"""Convert Win32 window pixels to Qt's device independent desktop coordinates."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from app_logging import log_throttled

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication


_DWMWA_EXTENDED_FRAME_BOUNDS = 9


class LogicalWindow:
    def __init__(self, window, rectangle):
        self._window = window
        self.left, self.top = rectangle.x(), rectangle.y()
        self.width, self.height = rectangle.width(), rectangle.height()

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
        rectangle = _visible_frame(window._hWnd)
        if rectangle is None:
            rectangle = QRect(window.left, window.top, window.width, window.height)
        return LogicalWindow(window, map_window_rectangle(rectangle, physical, screen.geometry()))
    except (AttributeError, OSError, ValueError, ZeroDivisionError) as exc:
        log_throttled('desktop.dpi.fallback', '창의 DPI 좌표 변환에 실패해 원래 좌표를 사용합니다.',
                      key=f'conversion:{window._hWnd}', interval=30, level='WARNING',
                      window_handle=window._hWnd, reason='conversion_failed', error=str(exc))
        return window
