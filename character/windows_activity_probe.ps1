$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, WindowsBase
$automationAssemblies = @([Windows.Automation.AutomationElement].Assembly.Location,
    [Windows.Automation.ControlType].Assembly.Location, [System.Windows.Rect].Assembly.Location)
Add-Type -ReferencedAssemblies $automationAssemblies -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows.Automation;

public sealed class CloudyDocumentActivity {
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    private static extern bool GetGUIThreadInfo(uint thread, ref GuiThread info);
    [DllImport("user32.dll")]
    private static extern bool IsChild(IntPtr parent, IntPtr child);
    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr handle, out Rect bounds);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    private struct GuiThread {
        public uint Size, Flags;
        public IntPtr Active, Focus, Capture, Menu, Move, Caret;
        public Rect CaretRect;
    }

    private readonly object gate = new object();
    private readonly Stopwatch clock = Stopwatch.StartNew();
    private AutomationElement root;
    private IntPtr window;
    private bool allowEditControl;
    private long lastChange = -10000;
    private long lastEditing = -10000;

    public bool Observe(long handle, bool allowEdit) {
        var nextWindow = new IntPtr(handle);
        if (nextWindow != window || allowEdit != allowEditControl) {
            if (root != null) Automation.RemoveAutomationEventHandler(TextPattern.TextChangedEvent, root, Edited);
            root = null;
            lock (gate) {
                window = nextWindow;
                allowEditControl = allowEdit;
                lastChange = lastEditing = -10000;
            }
        }
        if (root == null && nextWindow != IntPtr.Zero && nextWindow == GetForegroundWindow()) {
            var element = AutomationElement.FromHandle(nextWindow);
            Automation.AddAutomationEventHandler(TextPattern.TextChangedEvent, element, TreeScope.Subtree, Edited);
            root = element;
        }
        lock (gate) {
            return root != null && window == GetForegroundWindow() && clock.ElapsedMilliseconds - lastEditing < 8000;
        }
    }

    private void Edited(object sender, AutomationEventArgs args) {
        var element = sender as AutomationElement;
        IntPtr watched;
        bool allowEdit;
        lock (gate) { watched = window; allowEdit = allowEditControl; }
        if (element == null || watched == IntPtr.Zero || watched != GetForegroundWindow()) return;
        try {
            if (!EditableDocument(element, allowEdit)) return;
            var focused = AutomationElement.FocusedElement;
            for (int depth = 0; focused != null && depth < 16; depth++) {
                if (Automation.Compare(focused, element)) {
                    lock (gate) {
                        if (window != watched || GetForegroundWindow() != watched) return;
                        long now = clock.ElapsedMilliseconds;
                        if (now - lastChange < 3500 || now - lastEditing < 8000) lastEditing = now;
                        lastChange = now;
                    }
                    return;
                }
                focused = TreeWalker.RawViewWalker.GetParent(focused);
            }
        } catch (ElementNotAvailableException) {
        } catch (InvalidOperationException) {
        } catch (UnauthorizedAccessException) {
        } catch (System.Runtime.InteropServices.COMException) {
        }
    }

    private static bool ReadOnly(AutomationElement element) {
        object pattern;
        return (element.TryGetCurrentPattern(ValuePattern.Pattern, out pattern) &&
                ((ValuePattern)pattern).Current.IsReadOnly) ||
               (element.TryGetCurrentPattern(TextPattern.Pattern, out pattern) &&
                Equals(((TextPattern)pattern).DocumentRange.GetAttributeValue(TextPattern.IsReadOnlyAttribute), true));
    }

    private static bool EditableDocument(AutomationElement element, bool allowEdit) {
        var control = element.Current;
        return !control.IsPassword && control.IsEnabled && !ReadOnly(element) &&
               (control.ControlType == ControlType.Document ||
                (allowEdit && control.ControlType == ControlType.Edit && control.BoundingRectangle.Height >= 44));
    }

    public long EditFocus(long handle) {
        var top = new IntPtr(handle);
        var gui = new GuiThread { Size = (uint)Marshal.SizeOf(typeof(GuiThread)) };
        if (top != GetForegroundWindow() || !GetGUIThreadInfo(0, ref gui) || gui.Focus == IntPtr.Zero ||
            (gui.Flags & 0x1e) != 0 || (gui.Focus != top && !IsChild(top, gui.Focus))) return 0;
        try {
            var focused = AutomationElement.FocusedElement;
            if (focused != null && (focused.Current.IsPassword || !focused.Current.IsEnabled || ReadOnly(focused)))
                return 0;
            for (int depth = 0; focused != null && depth < 16; depth++) {
                if (EditableDocument(focused, false)) return gui.Focus.ToInt64();
                if (focused.Current.NativeWindowHandle == handle) break;
                focused = TreeWalker.RawViewWalker.GetParent(focused);
            }
        } catch (ElementNotAvailableException) {
        } catch (InvalidOperationException) {
        } catch (System.Runtime.InteropServices.COMException) {
        }

        // Custom document canvases can expose a caret through Win32 even without TextPattern.
        Rect focus, window;
        if (gui.Focus == top || gui.Caret == IntPtr.Zero || (gui.Caret != gui.Focus && !IsChild(gui.Focus, gui.Caret)) ||
            !GetWindowRect(gui.Focus, out focus) || !GetWindowRect(top, out window)) return 0;
        return focus.Right - focus.Left >= Math.Max(160, (window.Right - window.Left) / 3) &&
               focus.Bottom - focus.Top >= Math.Max(100, (window.Bottom - window.Top) / 3)
               ? gui.Focus.ToInt64() : 0;
    }
}
'@

$document = New-Object CloudyDocumentActivity
$media = $null
$retryMedia = [DateTime]::MinValue
function Get-SessionManager {
    if ($null -eq $script:media) {
        if ([DateTime]::UtcNow -lt $script:retryMedia) { return $null }
        $script:retryMedia = [DateTime]::UtcNow.AddSeconds(30)
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $managerType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
        $script:asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Length -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
        $request = $script:asTask.MakeGenericMethod($managerType).Invoke($null, @($managerType::RequestAsync()))
        if (!$request.Wait(1500)) { return $null }
        $script:media = $request.GetAwaiter().GetResult()
    }
    return $script:media
}

function Test-Source($source, $aliases) {
    foreach ($alias in $aliases) {
        if ($source -eq $alias -or $source.EndsWith('\' + $alias) -or
            ($alias.EndsWith('_') -and $source.StartsWith($alias))) { return $true }
    }
    return $false
}

function Get-MediaActivity($query, $result) {
    $manager = Get-SessionManager
    if ($null -eq $manager) { return }
    foreach ($session in $manager.GetSessions()) {
        $source = $session.SourceAppUserModelId.ToLowerInvariant()
        $musicSource = Test-Source $source $query.music
        $videoSource = Test-Source $source $query.video
        if (!$musicSource -and !$videoSource) { continue }
        $info = $session.GetPlaybackInfo()
        $type = $info.PlaybackType
        if ($videoSource -and ($null -eq $type -or $query.video_title)) {
            $metadataType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
            $task = $script:asTask.MakeGenericMethod($metadataType).Invoke($null, @($session.TryGetMediaPropertiesAsync()))
            if ($task.Wait(500)) {
                $metadata = $task.GetAwaiter().GetResult()
                if ($null -eq $type) { $type = $metadata.PlaybackType }
                if ($query.video_title) {
                    $tab = $query.video_title -replace '^\(\d+\)\s+', '' -replace ' - YouTube$', ''
                    $videoSource = $metadata.Title -and ($metadata.Title.Trim() -eq $tab.Trim())
                }
            } elseif ($query.video_title) {
                $videoSource = $false
            }
        }
        if ($musicSource -and $type -ne 'Video' -and $info.PlaybackStatus -eq 'Playing') { $result.music = $true }
        if ($videoSource -and $type -eq 'Video') {
            if ($info.PlaybackStatus -eq 'Playing') { $result.video = 'playing' }
            elseif ($info.PlaybackStatus -eq 'Changing' -and !$result.video) { $result.video = 'buffering' }
            elseif ($info.PlaybackStatus -eq 'Paused' -and !$result.video) { $result.video = 'paused' }
        }
    }
}

while ($null -ne ($line = [Console]::ReadLine())) {
    $query = ConvertFrom-Json $line
    $result = @{ editing = $false; edit_focus = 0; music = $false; video = '' }
    try { $result.editing = $document.Observe([long]$query.editor, [bool]$query.allow_edit) } catch {}
    if ($query.office -and $query.editor) {
        try { $result.edit_focus = $document.EditFocus([long]$query.editor) } catch {}
    }
    if ($query.music -or $query.video) {
        try { Get-MediaActivity $query $result } catch { $media = $null }
    }
    [Console]::WriteLine((ConvertTo-Json -Compress $result))
}
