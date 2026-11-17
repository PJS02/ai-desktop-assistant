"""Synchronize file handoffs with the Windows desktop view."""
import errno
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread

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


def wait_for_desktop_removal(sources):
    """Wait for the moved icons to leave the desktop view before showing receipt."""
    if shell is None:
        return
    pythoncom.CoInitialize()
    view = folder = None
    try:
        desktops = {os.path.normcase(shell.SHGetFolderPath(0, location, None, 0))
                    for location in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_COMMON_DESKTOPDIRECTORY)}
        paths = {os.path.normcase(str(path)) for path in sources
                 if os.path.normcase(str(path.parent)) in desktops}
        if not paths:
            return
        _, view = _desktop_view()
        if view is None:
            return
        folder = view.GetFolder(shell.IID_IShellFolder)
        pending = set()
        for item in _view_items(view):
            try:
                path = folder.GetDisplayNameOf([item], shellcon.SHGDN_FORPARSING)
                if os.path.normcase(path) in paths:
                    pending.add(item)
            except pywintypes.com_error:
                continue

        deadline = time.monotonic() + 3.
        while pending and time.monotonic() < deadline:
            for item in tuple(pending):
                try:
                    view.GetItemPosition(item)
                except pywintypes.com_error:
                    pending.remove(item)
            if pending:
                time.sleep(.025)
    except (OSError, pywintypes.error, pywintypes.com_error, AttributeError) as exc:
        log_throttled('desktop.icons.receipt_failed', '바탕화면에서 원본 아이콘이 사라졌는지 확인하지 못했습니다.',
                      interval=30, category='캐릭터 상태', error=type(exc).__name__)
    finally:
        folder = view = None
        pythoncom.CoUninitialize()


def desktop_body_bounds(widget):
    if shell is None:
        return None
    try:
        body = widget._physics_body_rect()
        scale = widget.devicePixelRatioF()
        x, y = win32gui.ClientToScreen(int(widget.winId()), (0, 0))
        return (x + round(body.x() * scale), y + round(body.y() * scale),
                x + round((body.x() + body.width()) * scale),
                y + round((body.y() + body.height()) * scale))
    except (OSError, pywintypes.error):
        return None


def return_desktop_item(source, destination, body):
    """Move the file and place its desktop icon from the return worker."""
    if shell is None or body is None:
        return _move_and_notify(source, destination)
    pythoncom.CoInitialize()
    view = None
    try:
        try:
            hwnd, view = _desktop_view()
            position = _return_position(hwnd, view, body)
        except (OSError, pywintypes.error, pywintypes.com_error, AttributeError) as exc:
            _log_position_failure(exc)
            position = None
        if position is None:
            return _move_and_notify(source, destination)

        with _hold_desktop_paint(hwnd):
            try:
                source.rename(destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
                    raise
            else:
                notify_item_moved(source, destination)
                _place_returned_icon(view, destination, position)
                return destination

        # A copy to another drive can take a long time. Allow the view to paint during the transfer.
        destination = _move_and_notify(source, destination)
        _place_returned_icon(view, destination, position)
        return destination
    finally:
        view = None
        pythoncom.CoUninitialize()


def _move_and_notify(source, destination):
    target = Path(shutil.move(source, destination))
    notify_item_moved(source, target)
    return target


@contextmanager
def _hold_desktop_paint(hwnd):
    """Preserve the last painted icons while Explorer registers the returned file."""
    from ctypes import WinDLL, wintypes

    lock_window = WinDLL('user32').LockWindowUpdate
    lock_window.argtypes = [wintypes.HWND]
    lock_window.restype = wintypes.BOOL
    ready, placed = Event(), Event()

    def hold():
        try:
            locked = lock_window(hwnd)
        finally:
            ready.set()
        if locked:
            try:
                # Release independently if Explorer takes too long to answer a COM call.
                placed.wait(3)
            finally:
                lock_window(None)

    guard = Thread(target=hold, name='desktop-file-return-paint', daemon=True)
    guard.start()
    ready.wait()
    try:
        yield
    finally:
        placed.set()
        guard.join()


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


def _view_items(view):
    for index in range(view.ItemCount(shellcon.SVGIO_ALLVIEW)):
        try:
            item = view.Item(index)
            if item is not None:
                yield item
        except pywintypes.com_error:
            # The view can change while it is being read.
            continue


def _return_position(hwnd, view, body):
    if view is None or view.GetAutoArrange():
        return None

    occupied = []
    for item in _view_items(view):
        try:
            occupied.append(view.GetItemPosition(item))
        except pywintypes.com_error:
            continue

    left, top, right, bottom = body
    monitor = win32api.MonitorFromPoint(((left + right) // 2, (top + bottom) // 2),
                                         win32con.MONITOR_DEFAULTTONEAREST)
    work = win32api.GetMonitorInfo(monitor)['Work']
    offset_x, offset_y = win32gui.ScreenToClient(hwnd, (0, 0))
    body_in_view = (left + offset_x, top + offset_y, right + offset_x, bottom + offset_y)
    work_in_view = (work[0] + offset_x, work[1] + offset_y, work[2] + offset_x, work[3] + offset_y)
    spacing = view.GetSpacing(0, 0)
    return _nearest_open_position(body_in_view, work_in_view, spacing, occupied)


def _place_returned_icon(view, path, position):
    try:
        item_ids, _ = shell.SHParseDisplayName(str(path), 0)
        if not item_ids:
            return
        target = item_ids[-1]
        folder = view.GetFolder(shell.IID_IShellFolder)
        name = folder.GetDisplayNameOf([target], shellcon.SHGDN_FORPARSING)
        if os.path.normcase(os.path.normpath(name)) != os.path.normcase(os.path.normpath(path)):
            return

        deadline = time.monotonic() + 3.
        while time.monotonic() < deadline and path.exists():
            try:
                view.GetItemPosition(target)
            except pywintypes.com_error:
                time.sleep(.025)
                continue
            view.SelectAndPositionItem(target, position, shellcon.SVSI_POSITIONITEM)
            return
    except (OSError, pywintypes.error, pywintypes.com_error, AttributeError) as exc:
        _log_position_failure(exc)


def _log_position_failure(exc):
    log_throttled('desktop.icons.position_failed', '반환한 아이콘의 위치를 지정하지 못했습니다.',
                  interval=30, category='캐릭터 상태', error=type(exc).__name__)


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
