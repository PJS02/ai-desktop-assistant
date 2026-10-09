"""Restore a character obscured by the Windows taskbar without taking focus."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import os


_TASKBAR_CLASSES = frozenset({'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'})
_GW_HWNDPREV = 3
_RESTORE_FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0200
_MAX_WINDOWS = 512


class _WindowsApi:
    def __init__(self, user32=None):
        self.user32 = user32 if user32 is not None else ctypes.WinDLL('user32', use_last_error=True)
        signatures = {
            'IsWindow': ([wintypes.HWND], wintypes.BOOL),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'GetWindow': ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'GetClassNameW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'SetWindowPos': ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes, function.restype = arguments, result

    def is_window(self, hwnd):
        return bool(self.user32.IsWindow(hwnd))

    def is_visible(self, hwnd):
        return bool(self.user32.IsWindowVisible(hwnd))

    def is_own_window(self, hwnd):
        process_id = wintypes.DWORD()
        thread_id = self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return bool(thread_id) and process_id.value == os.getpid()

    def window_rect(self, hwnd):
        rectangle = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            return None
        return rectangle.left, rectangle.top, rectangle.right, rectangle.bottom

    def taskbars_above(self, hwnd):
        """Read only visible taskbars ahead of this HWND in the native Z order."""
        taskbars, seen = [], {hwnd}
        current = hwnd
        for _ in range(_MAX_WINDOWS):
            ctypes.set_last_error(0)
            current = self.user32.GetWindow(current, _GW_HWNDPREV)
            if not current:
                return None if ctypes.get_last_error() else tuple(taskbars)
            if current in seen or not self.is_window(current):
                return None
            seen.add(current)
            if not self.is_visible(current):
                continue
            class_name = ctypes.create_unicode_buffer(256)
            if not self.user32.GetClassNameW(current, class_name, len(class_name)):
                return None
            if class_name.value in _TASKBAR_CLASSES:
                taskbars.append(current)
        return None

    def restore(self, hwnd):
        return bool(self.user32.SetWindowPos(
            hwnd, wintypes.HWND(-1), 0, 0, 0, 0, _RESTORE_FLAGS))


def _load_windows_api():
    if os.name != 'nt':
        return None
    try:
        return _WindowsApi()
    except (AttributeError, OSError):
        return None


def _rectangle(values):
    rectangle = tuple(float(value) for value in values)
    if (len(rectangle) != 4 or not all(math.isfinite(value) for value in rectangle)
            or rectangle[2] <= rectangle[0] or rectangle[3] <= rectangle[1]):
        return None
    return rectangle


def _intersection(first, second):
    return _rectangle((max(first[0], second[0]), max(first[1], second[1]),
                       min(first[2], second[2]), min(first[3], second[3])))


class TaskbarVisibilityGuard:
    """Lazily use Win32; unsupported platforms and failed native queries are no-ops."""

    def __init__(self, api=None):
        self._api = api
        self._api_loaded = api is not None

    def ensure_visible(self, hwnd, *, body_rect=None, body_offset=None, widget_size=None):
        """Return True only when this process's character was successfully raised.

        body_rect is an optional native desktop (left, top, right, bottom) tuple.
        Prefer body_offset=(x, y, width, height) plus widget_size=(width, height)
        for a frameless Qt host: its local logical bounds are mapped through the
        current native window rectangle, including monitor DPI and origin.
        Supplying neither uses the full native host rectangle.
        """
        try:
            hwnd = int(hwnd)
            if hwnd <= 0 or hwnd >= 2 ** (ctypes.sizeof(wintypes.HWND) * 8):
                return False
            if not self._api_loaded:
                self._api = _load_windows_api()
                self._api_loaded = True
            api = self._api
            if (api is None or not api.is_window(hwnd) or not api.is_visible(hwnd)
                    or not api.is_own_window(hwnd)):
                return False
            host_rect = api.window_rect(hwnd)
            host_rect = _rectangle(host_rect) if host_rect is not None else None
            if host_rect is None:
                return False
            if body_rect is not None and body_offset is not None:
                return False
            if body_offset is not None:
                x, y, width, height = (float(value) for value in body_offset)
                widget_width, widget_height = (float(value) for value in widget_size)
                if not all(math.isfinite(value) for value in
                           (x, y, width, height, widget_width, widget_height)):
                    return False
                if min(width, height, widget_width, widget_height) <= 0:
                    return False
                scale_x = (host_rect[2] - host_rect[0]) / widget_width
                scale_y = (host_rect[3] - host_rect[1]) / widget_height
                body_rect = (host_rect[0] + x * scale_x, host_rect[1] + y * scale_y,
                             host_rect[0] + (x + width) * scale_x,
                             host_rect[1] + (y + height) * scale_y)
            painted_rect = _rectangle(body_rect) if body_rect is not None else host_rect
            painted_rect = _intersection(painted_rect, host_rect) if painted_rect else None
            if painted_rect is None:
                return False
            taskbars = api.taskbars_above(hwnd)
            if taskbars is None:
                return False
            for taskbar in taskbars:
                if not api.is_window(taskbar) or not api.is_visible(taskbar):
                    continue
                rectangle = api.window_rect(taskbar)
                rectangle = _rectangle(rectangle) if rectangle is not None else None
                if rectangle is not None and _intersection(painted_rect, rectangle):
                    if api.is_window(hwnd) and api.is_visible(hwnd) and api.is_own_window(hwnd):
                        return api.restore(hwnd)
                    return False
            return False
        except (AttributeError, OSError, TypeError, ValueError, OverflowError):
            return False
