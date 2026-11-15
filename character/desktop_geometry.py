"""Win32 window geometry and visibility in Qt's desktop coordinates."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from types import SimpleNamespace

from app_logging import log_throttled

from PyQt6.QtCore import QRect, QRectF
from PyQt6.QtGui import QPainterPath, QRegion
from PyQt6.QtWidgets import QApplication

try:
    import win32con
    import win32gui
    import win32process
except ImportError:
    win32gui = None


WINDOW_SCAN_AVAILABLE = win32gui is not None
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
_DWMWA_CLOAKED = 14


class LogicalWindow:
    def __init__(self, window, rectangle, clip_rect=None):
        self._window = window
        self.left, self.top = rectangle.x(), rectangle.y()
        self.width, self.height = rectangle.width(), rectangle.height()
        self.clip_rect = QRectF(rectangle) if clip_rect is None else clip_rect

    def __getattr__(self, name):
        return getattr(self._window, name)


def map_window_rectangle(rectangle, physical_monitor, logical_monitor):
    """Map each edge separately, including monitors with a negative origin."""
    sx = logical_monitor.width() / physical_monitor.width()
    sy = logical_monitor.height() / physical_monitor.height()
    left = logical_monitor.x() + (rectangle.x() - physical_monitor.x()) * sx
    top = logical_monitor.y() + (rectangle.y() - physical_monitor.y()) * sy
    right = left + rectangle.width() * sx
    bottom = top + rectangle.height() * sy
    return QRect(round(left), round(top), round(right) - round(left), round(bottom) - round(top))


def _visible_frame(hwnd):
    try:
        query = ctypes.windll.dwmapi.DwmGetWindowAttribute
        query.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
        query.restype = ctypes.c_long
        bounds = wintypes.RECT()
        if query(hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(bounds), ctypes.sizeof(bounds)) == 0:
            rect = QRect(bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top)
            if not rect.isEmpty():
                return rect
    except (AttributeError, OSError):
        pass
    return None


def logical_window(window):
    """Convert the visible window frame to Qt coordinates on its own monitor."""
    if os.name != "nt" or QApplication.instance() is None or not getattr(window, "_hWnd", None):
        return window

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]

    try:
        user32 = ctypes.windll.user32
        monitor_from_window = user32.MonitorFromWindow
        monitor_from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
        monitor_from_window.restype = wintypes.HANDLE
        get_monitor_info = user32.GetMonitorInfoW
        get_monitor_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        monitor = monitor_from_window(window._hWnd, 2)
        if not monitor or not get_monitor_info(monitor, ctypes.byref(info)):
            log_throttled('desktop.dpi.fallback', 'Win32 모니터 정보를 읽지 못해 원래 창 좌표를 사용합니다.',
                          key=f'monitor:{window._hWnd}', interval=30, level='WARNING',
                          window_handle=window._hWnd, reason='monitor_lookup_failed')
            return window
        raw = info.rcMonitor
        physical = QRect(raw.left, raw.top, raw.right - raw.left, raw.bottom - raw.top)
        screens = QApplication.screens()
        screen = next((candidate for candidate in screens
                       if candidate.name().lower() == info.szDevice.lower()), None)
        if screen is None:
            # Qt may report a display's model name, but keeps its Windows origin.
            screen = next((candidate for candidate in screens
                           if candidate.geometry().topLeft() == physical.topLeft()), None)
        if screen is None:
            log_throttled('desktop.dpi.fallback', 'Qt 화면과 Win32 모니터가 일치하지 않아 원래 좌표를 사용합니다.',
                          key=f'screen:{info.szDevice}', interval=30, level='WARNING',
                          window_handle=window._hWnd, monitor=info.szDevice,
                          qt_screens=[candidate.name() for candidate in screens],
                          reason='screen_not_matched')
            return window
        # DWM gives physical pixels and excludes the invisible resize border.
        frame = _visible_frame(window._hWnd)
        rectangle = frame if frame is not None else QRect(window.left, window.top, window.width, window.height)
        geometry = screen.geometry()
        logical = map_window_rectangle(rectangle, physical, geometry)
        clip = None
        if frame is not None:
            # Keep fractional edges until the shader maps them back to desktop pixels.
            scale = screen.devicePixelRatio()
            clip = QRectF(geometry.x() + (frame.x() - physical.x()) / scale,
                          geometry.y() + (frame.y() - physical.y()) / scale,
                          frame.width() / scale, frame.height() / scale)
        return LogicalWindow(window, logical, clip)
    except (AttributeError, OSError, ValueError, ZeroDivisionError) as exc:
        log_throttled('desktop.dpi.fallback', '창의 DPI 좌표 변환에 실패해 원래 좌표를 사용합니다.',
                      key=f'conversion:{window._hWnd}', interval=30, level='WARNING',
                      window_handle=window._hWnd, reason='conversion_failed', error=str(exc))
        return window


def window_is_cloaked(hwnd):
    """Detect windows hidden by DWM, including on other virtual desktops."""
    try:
        query = ctypes.windll.dwmapi.DwmGetWindowAttribute
        query.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
        query.restype = ctypes.c_long
        value = wintypes.DWORD()
        return query(hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) == 0 and bool(value.value)
    except (AttributeError, OSError):
        return False


def desktop_windows():
    """Yield (window, opaque) from the top of the native window stack down."""
    handles = []
    seen = set()
    try:
        # Follow the native order explicitly; focus can sit below topmost windows.
        hwnd = win32gui.GetTopWindow(0)
        while hwnd:
            if hwnd in seen:
                raise OSError('Window order changed during the scan')
            seen.add(hwnd)
            handles.append(hwnd)
            hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
    except win32gui.error as exc:
        raise OSError('Could not read window order') from exc

    pid = os.getpid()
    for hwnd in handles:
        try:
            if (not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd)
                    or win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                    or win32gui.GetClassName(hwnd) in {'Progman', 'WorkerW'}
                    or window_is_cloaked(hwnd)):
                continue
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if style & win32con.WS_EX_TRANSPARENT:
                continue
            opacity = 255
            if style & win32con.WS_EX_LAYERED:
                # Per-pixel transparency cannot be represented by the frame rect.
                _, opacity, flags = win32gui.GetLayeredWindowAttributes(hwnd)
                if flags != win32con.LWA_ALPHA or not opacity:
                    continue
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            window = SimpleNamespace(_hWnd=hwnd, left=left, top=top, width=right-left,
                                     height=bottom-top, title=win32gui.GetWindowText(hwnd))
            yield logical_window(window), opacity == 255
        except (OSError, win32gui.error):
            # A window may disappear mid-scan or use per-pixel alpha.
            continue


def exposed_windows(windows, screen):
    """Subtract higher opaque windows, including ones ineligible for interaction."""
    covered = QRegion()
    for window, opaque in windows:
        frame = QRect(window.left, window.top, window.width, window.height)
        region = QRegion(frame.intersected(screen))
        exposed = region.subtracted(covered)
        if not exposed.isEmpty():
            if opaque:
                covered = covered.united(region)
            yield window, frame, exposed


def exposed_top_spans(frame, region):
    """Return the visible runs along the original top edge as half-open intervals."""
    path = QPainterPath()
    path.addRegion(region.intersected(QRect(frame.x(), frame.y(), frame.width(), 1)))
    runs = [polygon.boundingRect() for polygon in path.toSubpathPolygons()]
    return tuple(sorted((int(run.left()), int(run.right())) for run in runs))


def support_span(surface, left, right):
    """Find the continuous ledge under the center of the character's feet."""
    spans = getattr(surface, 'top_spans', None)
    if spans is None:
        if left < surface.x_max and right > surface.x_min:
            return surface.x_min, surface.x_max
        return None
    center = (left + right) / 2
    return next((span for span in spans if span[0] <= center < span[1]), None)


def surface_rect(surface):
    return QRect(round(surface.x_min), round(surface.y_level),
                 round(surface.x_max - surface.x_min), round(surface.height))
