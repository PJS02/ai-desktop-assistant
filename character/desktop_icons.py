"""Notify Explorer about moved items and position returned icons in its desktop view."""
import os
import time
from pathlib import Path
from threading import Thread

from PyQt6.QtCore import QStandardPaths, QTimer

from app_logging import log_throttled

try:
    import pythoncom
    import pywintypes
    import win32api
    import win32con
    import win32gui
    from win32com.shell import shell, shellcon
except ImportError:
    shell = None


def notify_item_moved(source, destination):
    if shell is None:
        return
    try:
        event = shellcon.SHCNE_RENAMEFOLDER if destination.is_dir() else shellcon.SHCNE_RENAMEITEM
        flags = shellcon.SHCNF_PATHW | shellcon.SHCNF_FLUSHNOWAIT
        shell.SHChangeNotify(event, flags, str(source.absolute()), str(destination.absolute()))
    except (OSError, pywintypes.error, pywintypes.com_error) as exc:
        log_throttled('desktop.icons.notify_failed', '탐색기에 파일 이동을 알리지 못했습니다.',
                      interval=30, category='캐릭터 상태', error=type(exc).__name__)


def refresh_desktop_after_drop(paths):
    if shell is None:
        return
    desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    if desktop and any(path.parent == Path(desktop) for path in paths):
        Thread(target=_refresh_desktop, name='desktop-icon-refresh', daemon=True).start()


def _refresh_desktop():
    pythoncom.CoInitialize()
    view = None
    try:
        _, view = _desktop_view()
        if view is not None:
            view.QueryInterface(shell.IID_IShellView).Refresh()
    except (OSError, pywintypes.error, pywintypes.com_error) as exc:
        log_throttled('desktop.icons.refresh_failed', '바탕화면 아이콘을 새로고침하지 못했습니다.',
                      interval=30, category='캐릭터 상태', error=type(exc).__name__)
    finally:
        view = None
        pythoncom.CoUninitialize()


def queue_returned_icon(widget, path):
    if shell is None:
        return
    try:
        body = widget._physics_body_rect()
        scale = widget.devicePixelRatioF()
        x, y = win32gui.ClientToScreen(int(widget.winId()), (0, 0))
        bounds = (x + round(body.left() * scale), y + round(body.top() * scale),
                  x + round((body.x() + body.width()) * scale),
                  y + round((body.y() + body.height()) * scale))
    except (OSError, pywintypes.error):
        return

    deadline = time.monotonic() + 5.

    def try_place():
        try:
            if not path.exists() or _position_icon(path, bounds):
                return
        except (OSError, pywintypes.error, pywintypes.com_error, AttributeError) as exc:
            log_throttled('desktop.icons.position_failed', '반환한 아이콘의 위치를 지정하지 못했습니다.',
                          interval=30, category='캐릭터 상태', error=type(exc).__name__)
            return
        # The file can exist before Explorer includes it in the view.
        if time.monotonic() < deadline:
            QTimer.singleShot(120, try_place)

    QTimer.singleShot(0, try_place)


def _desktop_view():
    from win32com.client import dynamic

    windows = dynamic.Dispatch('Shell.Application').Windows()
    desktop = windows.FindWindowSW(shellcon.CSIDL_DESKTOP, pythoncom.Empty, shellcon.SWC_DESKTOP,
                                   0, shellcon.SWFO_NEEDDISPATCH)
    if desktop is None:
        return None, None
    service = desktop._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
    top_level_browser = pywintypes.IID('{4C96BE40-915C-11CF-99D3-00AA004AE837}')
    browser = service.QueryService(top_level_browser, shell.IID_IShellBrowser)
    shell_view = browser.QueryActiveShellView()
    return shell_view.GetWindow(), shell_view.QueryInterface(shell.IID_IFolderView)


def _position_icon(path, body):
    """Return False when Explorer has yet to list the returned file."""
    hwnd, view = _desktop_view()
    if view is None or view.GetAutoArrange():
        return True

    folder = view.GetFolder(shell.IID_IShellFolder)
    expected = os.path.normcase(os.path.normpath(path))
    target, occupied = None, []
    for index in range(view.ItemCount(shellcon.SVGIO_ALLVIEW)):
        try:
            item = view.Item(index)
            if item is None:
                continue
            name = folder.GetDisplayNameOf([item], shellcon.SHGDN_FORPARSING)
            if os.path.normcase(os.path.normpath(name)) == expected:
                target = item
            else:
                occupied.append(view.GetItemPosition(item))
        except pywintypes.com_error:
            # Explorer's list can change as files are added or removed.
            continue
    if target is None:
        return False

    left, top, right, bottom = body
    monitor = win32api.MonitorFromPoint(((left + right) // 2, (top + bottom) // 2),
                                         win32con.MONITOR_DEFAULTTONEAREST)
    work = win32api.GetMonitorInfo(monitor)['Work']
    offset_x, offset_y = win32gui.ScreenToClient(hwnd, (0, 0))
    body_in_view = (left + offset_x, top + offset_y, right + offset_x, bottom + offset_y)
    work_in_view = (work[0] + offset_x, work[1] + offset_y, work[2] + offset_x, work[3] + offset_y)
    spacing = view.GetSpacing(0, 0)
    position = _nearest_open_position(body_in_view, work_in_view, spacing, occupied)
    if position is not None:
        view.SelectAndPositionItem(target, position, shellcon.SVSI_POSITIONITEM)
    return True


def _nearest_open_position(body, work, spacing, occupied):
    left, top, right, bottom = work
    width, height = spacing
    if width <= 0 or height <= 0 or right - left < width or bottom - top < height:
        return None

    body_left, body_top, body_right, body_bottom = body
    preferred_x = (body_left + body_right - width) // 2
    preferred_y = body_bottom
    candidates = [(x, y) for y in range(top, bottom - height + 1, height)
                  for x in range(left, right - width + 1, width)]
    candidates.append((min(max(preferred_x, left), right - width),
                       min(max(preferred_y, top), bottom - height)))
    candidates.sort(key=lambda point: (point[0] - preferred_x) ** 2 + (point[1] - preferred_y) ** 2)
    for x, y in candidates:
        if x < body_right and x + width > body_left and y < body_bottom and y + height > body_top:
            continue
        if not any(abs(x - used_x) < width and abs(y - used_y) < height for used_x, used_y in occupied):
            return x, y
    return None
