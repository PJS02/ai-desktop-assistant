"""Ambient responses and random actions cannot replace admitted user turns."""
import threading
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication

from character.dialogue_system import DialogueSystem
from character.character_widget import CharacterWidget
from character import character_widget
from test_voice_dialogue import make_dialogue, process_until
from test_character_rig_host import HostHarness


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


class ActivityHost(QObject):
    show_ai_response = pyqtSignal(str)
    automatic_response_ready = pyqtSignal(object)
    _on_activity_monitor = CharacterWidget._on_activity_monitor
    _check_active_window_async = CharacterWidget._check_active_window_async
    _finish_automatic_response = CharacterWidget._finish_automatic_response
    _show_automatic_ai_response = CharacterWidget._show_automatic_ai_response

    def __init__(self, dialogue):
        super().__init__()
        self.dialogue_system = dialogue
        self.gemini_config = {'api_key': 'test-only', 'model': 'test-model'}
        self.mood_system = dialogue.character_widget.mood_system
        self.last_auto_dialogue_time = 0
        self.auto_dialogue_cooldown = 120
        self._automatic_request_generation = 0
        self._automatic_request_active = False
        self._character_closing = False
        self.show_ai_response.connect(self._show_automatic_ai_response)
        self.automatic_response_ready.connect(
            self._finish_automatic_response, Qt.ConnectionType.QueuedConnection)


@pytest.mark.parametrize('phase', ['ai', 'queued', 'synthesis', 'playback', 'hold'])
def test_automatic_signal_and_idle_behaviour_wait_for_every_conversation_phase(
        qt_app, monkeypatch, phase):
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    activity = ActivityHost(dialogue)
    host = HostHarness()
    host.dialogue_system = dialogue
    host._last_autonomous_event_time = host._autonomous_event_cooldown = 0
    host.mood_system.on_self_play = Mock()
    random = Mock(return_value=0)
    monkeypatch.setattr(character_widget.random, 'random', random)
    if phase == 'ai':
        dialogue.is_ai_responding = True
    elif phase == 'queued':
        dialogue.pending_inputs.append({'state': 'queued'})
    elif phase == 'synthesis':
        tts.busy_changed.emit(True)
    elif phase == 'playback':
        tts.speaking_changed.emit(True)
    else:
        dialogue._response_hold_until = clock[0] + 5
    try:
        assert dialogue.is_conversation_busy()
        activity.show_ai_response.emit('자동 대사')
        activity._on_activity_monitor()
        host._maybe_run_autonomous_event(30)
        host.random_move()
        host._show_perception_dialogue('제스처 반응')
        assert dialogue.shown == [] and tts.spoken == []
        assert not activity._automatic_request_active
        random.assert_not_called()
        host.mood_system.on_self_play.assert_not_called()
    finally:
        dialogue.shutdown()


def test_idle_automatic_signal_still_displays_through_selected_bubble(qt_app, monkeypatch):
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    host = ActivityHost(dialogue)
    try:
        host.show_ai_response.emit('자동 대사')
        assert dialogue.shown[-1][0] == '자동 대사'
        assert tts.spoken == ['자동 대사']
        assert dialogue.is_conversation_busy()
        clock[0] += 5
        assert not dialogue.is_conversation_busy()
    finally:
        dialogue.shutdown()


def test_late_automatic_result_is_discarded_even_after_user_reply_finished(qt_app, monkeypatch):
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    host = ActivityHost(dialogue)
    started = threading.Event()
    release = threading.Event()
    calls = []
    monkeypatch.setattr(character_widget, 'HAS_CONTEXT', True)
    monkeypatch.setattr(character_widget, 'get_active_window_info', lambda: {
        'process': 'code.exe', 'title': 'test editor'})

    def automatic_provider(_prompt, config):
        calls.append(config)
        started.set()
        release.wait(3)
        return '{"dialogue": "늦은 자동 대사"}'

    monkeypatch.setattr(character_widget, 'call_gemini', automatic_provider)
    try:
        host._on_activity_monitor()
        assert started.wait(1)
        host._on_activity_monitor()
        assert len(calls) == 1  # one activity request can be in flight
        dialogue.ask_ai('사용자 질문')
        process_until(qt_app, lambda: tts.spoken == ['사용자 답변'])
        clock[0] += 6
        assert not dialogue.is_conversation_busy()
        release.set()
        process_until(qt_app, lambda: not host._automatic_request_active)
        assert tts.spoken == ['사용자 답변']
        assert all(text != '늦은 자동 대사' for text, _thread in dialogue.shown)
        assert host.last_detected_activity['process'] == 'code.exe'
        assert host.last_auto_dialogue_time > 0
    finally:
        release.set()
        dialogue.shutdown()


def test_worker_without_active_window_releases_busy_flag(qt_app, monkeypatch):
    dialogue, _tts, _clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    host = ActivityHost(dialogue)
    monkeypatch.setattr(character_widget, 'HAS_CONTEXT', True)
    monkeypatch.setattr(character_widget, 'get_active_window_info', lambda: None)
    try:
        host._on_activity_monitor()
        process_until(qt_app, lambda: not host._automatic_request_active)
        assert host.last_auto_dialogue_time == 0 and dialogue.shown == []
    finally:
        dialogue.shutdown()


def test_completed_request_cannot_display_after_shutdown(qt_app, monkeypatch):
    dialogue, tts, _clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    host = ActivityHost(dialogue)
    host._automatic_request_generation = 1
    host._automatic_request_active = True
    host._character_closing = True
    dialogue.shutdown()
    host._finish_automatic_response((1, 0, '닫힌 뒤 응답', None, 100))
    host.show_ai_response.emit('닫힌 뒤 응답')
    assert tts.spoken == [] and dialogue.shown == []


def test_user_input_cancels_pending_ambient_script(qt_app, monkeypatch):
    dialogue, _tts, _clock = make_dialogue(monkeypatch, lambda *_args: '사용자 답변')
    try:
        dialogue.queue_dialogue('지연된 자동 대사', delay_ms=1000)
        assert dialogue._pending_dialogue is not None
        dialogue.ask_ai('사용자 질문')
        assert dialogue._pending_dialogue is None and not dialogue.queue_timer.isActive()
        dialogue._show_pending_dialogue()
        assert all(text != '지연된 자동 대사' for text, _thread in dialogue.shown)
    finally:
        dialogue.shutdown()


@pytest.mark.parametrize('wrapped', [
    '```json\n{"dialogue": "정상 답변"}\n```',
    '```\n{"dialogue": "정상 답변"}\n```',
    '```json\n{"dialogue": "정상 답변"}',
    '{"dialogue": "정상 답변"}\n```',
    '  {\n "dialogue": "정상 답변"\n}\n```  ',
])
def test_json_output_with_both_or_one_fence_is_plain_dialogue(wrapped):
    dialogue = DialogueSystem.__new__(DialogueSystem)
    assert dialogue._process_gemini_response(wrapped) == '정상 답변'


@pytest.mark.parametrize('prose', ['가격은 500원이에요', '본문의 ``` 표시는 그대로예요',
                                  '코드 예시:\n```python\nprint(1)\n```',
                                  '```json\nJSON을 설명하는 일반 문장\n```'])
def test_plain_prose_and_literal_backticks_are_preserved(prose):
    dialogue = DialogueSystem.__new__(DialogueSystem)
    assert dialogue._process_gemini_response(prose) == prose
