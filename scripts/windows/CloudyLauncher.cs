using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;

internal static class CloudyLauncher
{
    [STAThread]
    private static int Main()
    {
        try
        {
            bool firstInstance;
            using (var applicationLock = new Mutex(true, @"Local\CloudyDesktopAssistant", out firstInstance))
            {
                if (!firstInstance)
                    return 0;

                string folder = AppDomain.CurrentDomain.BaseDirectory;
                string appFolder = Path.Combine(folder, "app");
                var start = new ProcessStartInfo
                {
                    FileName = Path.Combine(folder, @"runtime\python\python.exe"),
                    Arguments = "-B -X utf8 -u \"" + Path.Combine(appFolder, "main.py") + "\"",
                    WorkingDirectory = appFolder,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };

                using (var process = Process.Start(start))
                {
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    process.WaitForExit();
                    if (process.ExitCode != 0)
                        ShowError("종료 코드 " + process.ExitCode);
                    return process.ExitCode;
                }
            }
        }
        catch (Exception error)
        {
            ShowError(error.Message);
            return 1;
        }
    }

    private static void ShowError(string detail)
    {
        MessageBox.Show("클라우디를 실행하는 중 문제가 발생했습니다.\n" + detail +
            "\n\n로그는 %LOCALAPPDATA%\\Cloudy\\logs에 저장됩니다.", "클라우디", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
