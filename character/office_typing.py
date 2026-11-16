"""Detect typing timing in a confirmed foreground Word or Hangul document."""
import ctypes
from ctypes import wintypes as wt
import time

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication


class _RawDevice(ctypes.Structure):
    _fields_ = [('page', wt.USHORT), ('usage', wt.USHORT), ('flags', wt.DWORD), ('target', wt.HWND)]


class _RawKeyboard(ctypes.Structure):
    _fields_ = [('kind', wt.DWORD), ('size', wt.DWORD), ('device', wt.HANDLE), ('param', wt.WPARAM),
                ('scan', wt.USHORT), ('flags', wt.USHORT), ('reserved', wt.USHORT), ('key', wt.USHORT),
                ('message', wt.UINT), ('extra', wt.ULONG)]


class _GuiThread(ctypes.Structure):
    _fields_ = [('size', wt.DWORD), ('flags', wt.DWORD),
                *[(name, wt.HWND) for name in ('active', 'focus', 'capture', 'menu', 'move', 'caret')],
                ('caret_rect', wt.RECT)]


def _editing_key(key):
    return (key in (0x08, 0x0D, 0x20, 0x2E, 0xE2, 0xE5, 0xE7)
            or 0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A or 0x60 <= key <= 0x6F
            or 0xBA <= key <= 0xC0 or 0xDB <= key <= 0xDF)


class OfficeTyping(QAbstractNativeEventFilter):
    def __init__(self, host):
        super().__init__()
        self._host = host
        self._app = QCoreApplication.instance()
        self._registered = False
        self._target = (0, 0)
        self._last_press = self._last_edit = float('-inf')
        self._user32 = ctypes.WinDLL('user32', use_last_error=True)
        self._user32.GetForegroundWindow.restype = wt.HWND
        self._user32.GetGUIThreadInfo.argtypes = (wt.DWORD, ctypes.POINTER(_GuiThread))
        self._user32.GetAsyncKeyState.restype = wt.SHORT
        self._user32.RegisterRawInputDevices.argtypes = (ctypes.POINTER(_RawDevice), wt.UINT, wt.UINT)
        self._user32.GetRawInputData.argtypes = (wt.HANDLE, wt.UINT, wt.LPVOID, ctypes.POINTER(wt.UINT), wt.UINT)
        self._user32.GetRawInputData.restype = wt.UINT

    def sample(self, window, focus):
        target = (window, focus) if window and focus else (0, 0)
        if self._target != target:
            self._target = target
            self._last_press = self._last_edit = float('-inf')
        if target == (0, 0):
            self.close()
        elif not self._registered:
            device = _RawDevice(1, 6, 0x100, int(self._host.winId()))  # Keyboard, RIDEV_INPUTSINK
            if self._user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
                self._app.installNativeEventFilter(self)
                self._registered = True
        return time.monotonic() - self._last_edit < 8

    def _observe_press(self, now):
        if now - self._last_press < 3.5 or now - self._last_edit < 8:
            self._last_edit = now
        self._last_press = now

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b'windows_generic_MSG', b'windows_dispatcher_MSG') or not self._registered:
            return False, 0
        msg = wt.MSG.from_address(int(message))
        window, focus = self._target
        if msg.message != 0x00FF or self._user32.GetForegroundWindow() != window:  # WM_INPUT
            return False, 0
        gui = _GuiThread(size=ctypes.sizeof(_GuiThread))
        if not self._user32.GetGUIThreadInfo(0, ctypes.byref(gui)) or gui.focus != focus:
            return False, 0
        data = _RawKeyboard()
        size = wt.UINT(ctypes.sizeof(data))
        header_size = _RawKeyboard.scan.offset
        count = self._user32.GetRawInputData(msg.lParam, 0x10000003, ctypes.byref(data), ctypes.byref(size), header_size)
        if (count == ctypes.sizeof(data) and data.kind == 1 and not (data.flags & 1)
                and _editing_key(data.key)
                and not any(self._user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))):
            self._observe_press(time.monotonic())
        return False, 0

    def close(self):
        if self._registered:
            self._app.removeNativeEventFilter(self)
            device = _RawDevice(1, 6, 1, None)  # RIDEV_REMOVE
            self._user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device))
            self._registered = False
        self._target = (0, 0)
        self._last_press = self._last_edit = float('-inf')
