"""Owned Win32 layered window: replace the entire premultiplied frame atomically.

The Qt control/preview remain unchanged. No capture of other windows or desktop.
"""
import ctypes as c
from ctypes import wintypes as w

user = c.WinDLL("user32", use_last_error=True)
gdi = c.WinDLL("gdi32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
HANDLE = c.c_void_p
WNDPROC = c.WINFUNCTYPE(c.c_ssize_t, HANDLE, w.UINT, c.c_size_t, c.c_ssize_t)


class WindowClass(c.Structure):
    _fields_ = [("style", w.UINT), ("proc", WNDPROC), ("class_extra", c.c_int),
                ("window_extra", c.c_int), ("instance", HANDLE), ("icon", HANDLE),
                ("cursor", HANDLE), ("background", HANDLE), ("menu", w.LPCWSTR),
                ("name", w.LPCWSTR)]


class BitmapHeader(c.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                ("image_size", w.DWORD), ("xppm", w.LONG), ("yppm", w.LONG),
                ("colors", w.DWORD), ("important", w.DWORD)]


class BitmapInfo(c.Structure):
    _fields_ = [("header", BitmapHeader), ("colors", w.DWORD * 1)]


class Blend(c.Structure):
    _fields_ = [("operation", w.BYTE), ("flags", w.BYTE),
                ("constant_alpha", w.BYTE), ("alpha_format", w.BYTE)]


def signature(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


signature(kernel, "GetModuleHandleW", HANDLE, w.LPCWSTR)
signature(user, "DefWindowProcW", c.c_ssize_t, HANDLE, w.UINT, c.c_size_t, c.c_ssize_t)
signature(user, "RegisterClassW", w.WORD, c.POINTER(WindowClass))
signature(user, "CreateWindowExW", HANDLE, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
          c.c_int, c.c_int, c.c_int, c.c_int, HANDLE, HANDLE, HANDLE, HANDLE)
signature(user, "ValidateRect", w.BOOL, HANDLE, HANDLE)
signature(user, "ShowWindow", w.BOOL, HANDLE, c.c_int)
signature(user, "DestroyWindow", w.BOOL, HANDLE)
signature(user, "UpdateLayeredWindow", w.BOOL, HANDLE, HANDLE, c.POINTER(w.POINT),
          c.POINTER(w.SIZE), HANDLE, c.POINTER(w.POINT), w.DWORD, c.POINTER(Blend), w.DWORD)
signature(gdi, "CreateCompatibleDC", HANDLE, HANDLE)
signature(gdi, "CreateDIBSection", HANDLE, HANDLE, c.POINTER(BitmapInfo), w.UINT,
          c.POINTER(HANDLE), HANDLE, w.DWORD)
signature(gdi, "SelectObject", HANDLE, HANDLE, HANDLE)
signature(gdi, "DeleteObject", w.BOOL, HANDLE)
signature(gdi, "DeleteDC", w.BOOL, HANDLE)


@WNDPROC
def window_proc(hwnd, message, wp, lp):
    if message == 0x000F:  # WM_PAINT: only UpdateLayeredWindow supplies pixels.
        user.ValidateRect(hwnd, None)
        return 0
    if message == 0x0014:  # WM_ERASEBKGND
        return 1
    if message == 0x0084:  # WM_NCHITTEST
        return -1  # HTTRANSPARENT
    if message == 0x0021:  # WM_MOUSEACTIVATE
        return 3  # MA_NOACTIVATE
    return user.DefWindowProcW(hwnd, message, wp, lp)


_registered = False


class LayeredSurface:
    def __init__(self):
        global _registered
        instance = kernel.GetModuleHandleW(None)
        name = "CapstoneHandLandmarkSurface"
        if not _registered:
            klass = WindowClass(0, window_proc, 0, 0, instance, None, None, None, None, name)
            if not user.RegisterClassW(c.byref(klass)) and c.get_last_error() != 1410:
                raise c.WinError(c.get_last_error())
            _registered = True
        # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE.
        extended = 0x80000 | 0x20 | 0x8 | 0x80 | 0x8000000
        self.hwnd = user.CreateWindowExW(extended, name, "손 랜드마크 · 바탕화면 손",
                                         0x80000000, 0, 0, 1, 1, None, None, instance, None)
        if not self.hwnd:
            raise c.WinError(c.get_last_error())
        self.dc = gdi.CreateCompatibleDC(None)
        self.bitmap = None
        self.original = None
        self.buffer = HANDLE()
        self.size = (0, 0)
        self.visible = False

    def present(self, image, geometry, screen):
        size = (image.width(), image.height())
        if size != self.size:
            if self.bitmap:
                gdi.SelectObject(self.dc, self.original)
                gdi.DeleteObject(self.bitmap)
            info = BitmapInfo()
            info.header = BitmapHeader(c.sizeof(BitmapHeader), size[0], -size[1], 1, 32,
                                       0, size[0] * size[1] * 4, 0, 0, 0, 0)
            self.bitmap = gdi.CreateDIBSection(self.dc, c.byref(info), 0, c.byref(self.buffer), None, 0)
            if not self.bitmap:
                raise c.WinError(c.get_last_error())
            self.original = gdi.SelectObject(self.dc, self.bitmap)
            self.size = size
        # A top-down BGRA premultiplied bitmap, including ALL transparent pixels.
        c.memmove(self.buffer, image.constBits().asstring(image.sizeInBytes()), image.sizeInBytes())
        ratio = screen.devicePixelRatio()
        origin = screen.geometry()
        destination = w.POINT(round(origin.x() + (geometry.x() - origin.x()) * ratio),
                              round(origin.y() + (geometry.y() - origin.y()) * ratio))
        dimensions, source = w.SIZE(*size), w.POINT(0, 0)
        blend = Blend(0, 0, 255, 1)
        if not user.UpdateLayeredWindow(self.hwnd, None, c.byref(destination), c.byref(dimensions),
                                        self.dc, c.byref(source), 0, c.byref(blend), 2):
            raise c.WinError(c.get_last_error())
        if not self.visible:
            user.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
            self.visible = True

    def hide(self):
        user.ShowWindow(self.hwnd, 0)
        self.visible = False

    def close(self):
        if self.hwnd:
            user.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.bitmap:
            gdi.SelectObject(self.dc, self.original)
            gdi.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi.DeleteDC(self.dc)
            self.dc = None
        self.visible = False
