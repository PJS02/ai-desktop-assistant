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


def test_manual_worker_waits_for_external_window_before_capture(monkeypatch):
    from character import character_widget

    info = {'process': 'chrome.exe', 'title': 'recipe'}
    current_window = Mock(side_effect=[None, info])
    image = object()
    capture = Mock(return_value=image)
    send = Mock(return_value='{"dialogue":"맛있겠어요!"}')
    pause = Mock()
    character = SimpleNamespace(
        _character_closing=False, automatic_response_ready=Mock(),
        dialogue_system=SimpleNamespace(_process_gemini_response=lambda _: '맛있겠어요!'))
    monkeypatch.setattr(character_widget, 'get_active_window_info', current_window)
    monkeypatch.setattr(character_widget, 'capture_active_window_image', capture)
    monkeypatch.setattr(character_widget, 'request_gemini', send)
    monkeypatch.setattr(character_widget.time, 'sleep', pause)

    character_widget.CharacterWidget._check_active_window_async(
        character, 1, 2, {'api_key': 'test'}, 'calm', 'friendly',
        {'source': 'manual_generation', 'trace_id': 'window-selection-test'})

    assert current_window.call_count == 2
    pause.assert_called_once_with(0.1)
    capture.assert_called_once_with()
    assert send.call_args.kwargs['image'] is image
    result = character.automatic_response_ready.emit.call_args.args[0]
    assert result[2:4] == ('맛있겠어요!', info)
    assert result[5] is False


def test_manual_window_timeout_gives_selection_help_without_capture(monkeypatch):
    from character import character_widget

    character = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock())
    capture, send = Mock(), Mock()
    monkeypatch.setattr(character_widget, 'get_active_window_info', lambda: None)
    monkeypatch.setattr(character_widget, 'capture_active_window_image', capture)
    monkeypatch.setattr(character_widget, 'request_gemini', send)
    monkeypatch.setattr(character_widget.CharacterWidget, 'MANUAL_WINDOW_SELECTION_SECONDS', 0,
                        raising=False)

    character_widget.CharacterWidget._check_active_window_async(
        character, 1, 2, {'api_key': 'test'}, 'calm', 'friendly',
        {'source': 'manual_generation', 'trace_id': 'window-timeout-test'})

    capture.assert_not_called()
    send.assert_not_called()
    result = character.automatic_response_ready.emit.call_args.args[0]
    assert '다른 창' in result[2] and '대사 생성' in result[2]
    assert result[5] is True


def test_closing_while_waiting_for_window_cancels_capture(monkeypatch):
    from character import character_widget

    character = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock())
    capture, send = Mock(), Mock()
    pause = Mock(side_effect=lambda _: setattr(character, '_character_closing', True))
    monkeypatch.setattr(character_widget, 'get_active_window_info', lambda: None)
    monkeypatch.setattr(character_widget, 'capture_active_window_image', capture)
    monkeypatch.setattr(character_widget, 'request_gemini', send)
    monkeypatch.setattr(character_widget.time, 'sleep', pause)

    character_widget.CharacterWidget._check_active_window_async(
        character, 1, 2, {'api_key': 'test'}, 'calm', 'friendly',
        {'source': 'manual_generation', 'trace_id': 'window-close-test'})

    pause.assert_called_once_with(0.1)
    capture.assert_not_called()
    send.assert_not_called()
    character.automatic_response_ready.emit.assert_not_called()
