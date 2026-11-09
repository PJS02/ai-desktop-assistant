"""Ignore application windows without excluding unrelated Python programs."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil
import pytest

from context import active_window_classifier as activity


@pytest.fixture
def window(monkeypatch):
    process = Mock(pid=os.getpid() + 1)
    process.name.return_value = 'python.exe'
    process.parents.return_value = []
    gui = SimpleNamespace(GetForegroundWindow=Mock(return_value=123),
                          GetWindowText=Mock(return_value='설정'),
                          GetWindowRect=Mock(return_value=(10, 20, 650, 500)))
    monkeypatch.setitem(sys.modules, 'win32gui', gui)
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(
        GetWindowThreadProcessId=lambda _: (7, process.pid)))
    monkeypatch.setattr(psutil, 'Process', Mock(return_value=process))
    grab = Mock(return_value=object())
    monkeypatch.setattr('PIL.ImageGrab.grab', grab)
    return SimpleNamespace(process=process, gui=gui, grab=grab)


@pytest.mark.parametrize('owner', ['self', 'child', 'grandchild'])
def test_own_windows_are_not_detected_or_captured(window, owner):
    if owner == 'self':
        window.process.pid = os.getpid()
    else:
        ancestors = [SimpleNamespace(pid=os.getpid())]
        if owner == 'grandchild':
            ancestors.insert(0, SimpleNamespace(pid=os.getpid() + 2))
        window.process.parents.return_value = ancestors
    assert activity.get_active_window_info() is None
    assert activity.capture_active_window_image() is None
    window.grab.assert_not_called()


def test_unrelated_python_window_with_same_title_is_still_detected(window):
    assert activity.get_active_window_info() == {'process': 'python.exe', 'title': '설정'}
    assert activity.capture_active_window_image() is window.grab.return_value
    window.grab.assert_called_once_with(bbox=(10, 20, 650, 500), all_screens=True)


def test_switching_to_own_window_before_capture_blocks_screenshot(window):
    assert activity.get_active_window_info() is not None
    window.process.pid = os.getpid()
    assert activity.capture_active_window_image() is None
    window.grab.assert_not_called()


def test_automatic_worker_does_not_send_when_own_window_is_active(window):
    from character.character_widget import CharacterWidget
    window.process.pid = os.getpid()
    character = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock(),
                                dialogue_system=Mock())
    send = Mock()
    with patch('character.character_widget.request_gemini', send):
        CharacterWidget._check_active_window_async(
            character, 1, 2, {'api_key': 'test'}, 'calm', 'friendly')
    send.assert_not_called()
    window.grab.assert_not_called()
    character.automatic_response_ready.emit.assert_called_once_with((1, 2, None, None, None, False))
