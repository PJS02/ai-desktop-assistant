"""Native ordering, focus preservation and DPI overlap checks for taskbar recovery."""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from character import taskbar_visibility
from character.taskbar_visibility import TaskbarVisibilityGuard, _WindowsApi


CHARACTER = 0x1_0000_0011
PRIMARY_TRAY = 0x2_0000_0022
SECONDARY_TRAY = 0x3_0000_0033


class FakeApi:
    def __init__(self):
        self.rectangles = {CHARACTER: (200, 1200, 400, 1450),
                           PRIMARY_TRAY: (0, 1392, 2560, 1440),
                           SECONDARY_TRAY: (-2560, 1392, 0, 1440)}
        self.hidden = set()
        self.foreign = set()
        self.above = (PRIMARY_TRAY,)
        self.restored = []
        self.restore_result = True

    def is_window(self, hwnd):
        return hwnd in self.rectangles

    def is_visible(self, hwnd):
        return hwnd not in self.hidden

    def is_own_window(self, hwnd):
        return hwnd not in self.foreign

    def window_rect(self, hwnd):
        return self.rectangles[hwnd]

    def taskbars_above(self, hwnd):
        return self.above

    def restore(self, hwnd):
        self.restored.append(hwnd)
        return self.restore_result


def test_restore_only_character_when_visible_overlapping_taskbar_is_ahead():
    api = FakeApi()
    assert TaskbarVisibilityGuard(api).ensure_visible(CHARACTER)
    assert api.restored == [CHARACTER]
    assert api.rectangles[CHARACTER] == (200, 1200, 400, 1450)


@pytest.mark.parametrize('case', ['already_ahead', 'hidden_tray', 'hidden_character',
                                  'missing_character', 'foreign_character', 'no_overlap'])
def test_no_restore_when_taskbar_does_not_obscure_our_visible_character(case):
    api = FakeApi()
    if case == 'already_ahead':
        api.above = ()
    elif case == 'hidden_tray':
        api.hidden.add(PRIMARY_TRAY)
    elif case == 'hidden_character':
        api.hidden.add(CHARACTER)
    elif case == 'missing_character':
        del api.rectangles[CHARACTER]
    elif case == 'foreign_character':
        api.foreign.add(CHARACTER)
    else:
        api.rectangles[CHARACTER] = (200, 1100, 400, 1350)
    assert not TaskbarVisibilityGuard(api).ensure_visible(CHARACTER)
    assert api.restored == []


def test_transparent_host_padding_does_not_trigger_recovery():
    api = FakeApi()
    guard = TaskbarVisibilityGuard(api)
    assert not guard.ensure_visible(CHARACTER, body_offset=(20, 12, 110, 168),
                                    widget_size=(200, 250))
    assert api.restored == []
    assert guard.ensure_visible(CHARACTER, body_offset=(20, 12, 110, 220),
                                widget_size=(200, 250))


def test_local_logical_body_maps_to_native_dpi_and_negative_monitor_origin():
    api = FakeApi()
    api.rectangles[CHARACTER] = (-400, 1200, -100, 1575)
    api.above = (SECONDARY_TRAY,)
    guard = TaskbarVisibilityGuard(api)
    assert not guard.ensure_visible(CHARACTER, body_offset=(20, 12, 110, 100),
                                    widget_size=(200, 250))
    assert guard.ensure_visible(CHARACTER, body_offset=(20, 12, 110, 168),
                                widget_size=(200, 250))
    assert api.restored == [CHARACTER]


def test_painted_rect_is_clipped_to_actual_window_and_edges_are_exclusive():
    api = FakeApi()
    api.rectangles[CHARACTER] = (200, 1200, 400, 1392)
    guard = TaskbarVisibilityGuard(api)
    assert not guard.ensure_visible(CHARACTER, body_rect=(220, 1300, 350, 1500))
    api.rectangles[CHARACTER] = (200, 1200, 400, 1450)
    assert guard.ensure_visible(CHARACTER, body_rect=(220, 1391, 350, 1393))


@pytest.mark.parametrize('arguments', [
    {'body_rect': (0, 0, 0, 0)},
    {'body_rect': (0, 0, float('nan'), 1400)},
    {'body_offset': (20, 12, 110, 168)},
    {'body_offset': (20, 12, 110, 168), 'widget_size': (0, 250)},
    {'body_offset': (20, 12, -110, 168), 'widget_size': (200, 250)},
    {'body_rect': (220, 1300, 350, 1500), 'body_offset': (20, 12, 110, 168)},
])
def test_invalid_or_ambiguous_body_bounds_are_noops(arguments):
    api = FakeApi()
    assert not TaskbarVisibilityGuard(api).ensure_visible(CHARACTER, **arguments)
    assert api.restored == []


@pytest.mark.parametrize('failure', ['enumeration', 'query', 'restore'])
def test_native_errors_fail_without_raising(failure):
    api = FakeApi()
    if failure == 'enumeration':
        api.above = None
    elif failure == 'query':
        api.window_rect = lambda hwnd: (_ for _ in ()).throw(OSError('window destroyed'))
    else:
        api.restore_result = False
    assert not TaskbarVisibilityGuard(api).ensure_visible(CHARACTER)


def test_api_initialization_is_lazy_and_unavailable_backend_is_cached(monkeypatch):
    loads = []
    monkeypatch.setattr(taskbar_visibility, '_load_windows_api', lambda: loads.append(True))
    guard = TaskbarVisibilityGuard()
    assert loads == []
    assert not guard.ensure_visible(0)
    assert loads == []
    assert not guard.ensure_visible(CHARACTER)
    assert not guard.ensure_visible(CHARACTER)
    assert loads == [True]


def test_out_of_range_native_handle_cannot_wrap_to_another_window():
    api = FakeApi()
    oversized_handle = CHARACTER + 2 ** (ctypes.sizeof(wintypes.HWND) * 8)
    assert not TaskbarVisibilityGuard(api).ensure_visible(oversized_handle)
    assert api.restored == []


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def native_api(order, classes=None, hidden=()):
    classes = classes or {PRIMARY_TRAY: 'Shell_TrayWnd', SECONDARY_TRAY: 'Shell_SecondaryTrayWnd'}

    def previous(hwnd, command):
        assert command == 3
        index = order.index(hwnd)
        return order[index - 1] if index else 0

    def get_class(hwnd, buffer, size):
        buffer.value = classes.get(hwnd, 'OtherApp')
        return len(buffer.value)

    def process(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = taskbar_visibility.os.getpid()
        return 123

    user32 = SimpleNamespace(
        IsWindow=NativeFunction(lambda hwnd: hwnd in order),
        IsWindowVisible=NativeFunction(lambda hwnd: hwnd not in hidden),
        GetWindow=NativeFunction(previous),
        GetWindowRect=NativeFunction(lambda hwnd, pointer: 0),
        GetClassNameW=NativeFunction(get_class),
        GetWindowThreadProcessId=NativeFunction(process),
        SetWindowPos=NativeFunction(lambda *args: True))
    return _WindowsApi(user32), user32


def test_native_scan_selects_only_visible_taskbar_classes_ahead(monkeypatch):
    monkeypatch.setattr(taskbar_visibility.ctypes, 'set_last_error', lambda code: None, raising=False)
    monkeypatch.setattr(taskbar_visibility.ctypes, 'get_last_error', lambda: 0, raising=False)
    api, user32 = native_api([SECONDARY_TRAY, PRIMARY_TRAY, 55, CHARACTER, 66],
                             hidden=(PRIMARY_TRAY,))
    assert api.taskbars_above(CHARACTER) == (SECONDARY_TRAY,)
    assert all(call[0] != 66 for call in user32.GetClassNameW.calls)
    assert all(call[0] != PRIMARY_TRAY for call in user32.GetClassNameW.calls)


def test_native_scan_rejects_query_errors_and_z_order_cycles(monkeypatch):
    last_error = [0]
    monkeypatch.setattr(taskbar_visibility.ctypes, 'set_last_error', lambda code: last_error.__setitem__(0, code), raising=False)
    monkeypatch.setattr(taskbar_visibility.ctypes, 'get_last_error', lambda: last_error[0], raising=False)
    api, user32 = native_api([PRIMARY_TRAY, CHARACTER])
    user32.GetWindow.callback = lambda hwnd, command: hwnd
    assert api.taskbars_above(CHARACTER) is None

    def fail(hwnd, command):
        last_error[0] = 5
        return 0

    user32.GetWindow.callback = fail
    assert api.taskbars_above(CHARACTER) is None


def test_native_scan_has_a_bounded_walk_and_rejects_partial_snapshots(monkeypatch):
    monkeypatch.setattr(taskbar_visibility.ctypes, 'set_last_error', lambda code: None, raising=False)
    monkeypatch.setattr(taskbar_visibility.ctypes, 'get_last_error', lambda: 0, raising=False)
    monkeypatch.setattr(taskbar_visibility, '_MAX_WINDOWS', 1)
    api, _user32 = native_api([55, PRIMARY_TRAY, CHARACTER])
    assert api.taskbars_above(CHARACTER) is None


def test_native_signatures_and_restore_preserve_pointer_width_size_position_and_focus():
    api, user32 = native_api([PRIMARY_TRAY, CHARACTER])
    assert user32.GetWindow.restype is wintypes.HWND
    assert user32.GetWindow.argtypes[0] is wintypes.HWND
    assert user32.SetWindowPos.argtypes[:2] == [wintypes.HWND, wintypes.HWND]
    assert api.is_own_window(CHARACTER)
    assert api.restore(CHARACTER)
    hwnd, insert_after, x, y, width, height, flags = user32.SetWindowPos.calls[0]
    assert hwnd == CHARACTER
    assert insert_after.value == 2 ** (ctypes.sizeof(ctypes.c_void_p) * 8) - 1
    assert (x, y, width, height) == (0, 0, 0, 0)
    assert flags == 0x0213
