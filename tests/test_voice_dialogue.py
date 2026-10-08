"""Completed microphone events use the same ordered conversation as typed input."""
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from character.dialogue_system import DialogueSystem
from perception.controller import PerceptionController
from perception.events import parse_perception_event


class FakeTTS(QObject):
    speaking_changed = pyqtSignal(bool)
    busy_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.spoken = []
        self.closed = False

    def speak(self, text):
        self.spoken.append(text)

    def close(self):
        self.closed = True


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def process_until(app, condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    assert condition()


def make_dialogue(monkeypatch, provider):
    monkeypatch.setattr(DialogueSystem, '_load_gemini_config', lambda self: None)
    mood = SimpleNamespace(get_emotion_description_for_prompt=lambda: '기쁨',
                           get_emotion_tone_instructions=lambda: '밝게')
    personality = SimpleNamespace(get_personality_for_prompt=lambda: '친절',
                                  get_dialogue_tone_hints=lambda: '간결하게')
    host = SimpleNamespace(mood_system=mood, personality_system=personality)
    clock = [100.0]
    tts = FakeTTS()
    dialogue = DialogueSystem(host, tts=tts, response_provider=provider,
                              time_provider=lambda: clock[0])
    dialogue.gemini_config = {'model': 'test-model'}
    dialogue.shown = []
    dialogue.show_dialogue = lambda text, **_kwargs: dialogue.shown.append(
        (text, QThread.currentThread()))
    return dialogue, tts, clock


def speech(sequence=1, text='안녕', **metadata):
    return {'type': 'perception', 'source': 'microphone', 'timestamp': 100.0,
            'speech': {'text': text, 'sequence': sequence, 'session': 'session-a',
                       'recognized_at': 100.0, 'final': True, **metadata}}


def test_final_speech_to_ai_bubble_and_tts_uses_main_thread(qt_app, monkeypatch):
    worker_threads = []

    def provider(prompt, config):
        worker_threads.append(QThread.currentThread())
        assert '안녕' in prompt and '기쁨' in prompt
        assert config == {'model': 'test-model'}
        return '{"text": "안녕하세요!"}'

    dialogue, tts, _clock = make_dialogue(monkeypatch, provider)
    controller = PerceptionController(Mock(), on_speech=dialogue.submit_speech,
                                      time_provider=lambda: 100.0)
    try:
        controller.handle_payload(speech(final=False))
        assert dialogue.conversation_history == []
        controller.handle_payload(speech())
        controller.handle_payload(speech())
        process_until(qt_app, lambda: tts.spoken == ['안녕하세요!'])
        assert len(dialogue.conversation_history) == 2
        assert dialogue.conversation_history[0]['source'] == 'voice'
        assert dialogue.shown[0][0] == '[사용자]: 안녕'
        assert dialogue.shown[-1][0] == '안녕하세요!'
        assert all(thread is qt_app.thread() for _text, thread in dialogue.shown)
        assert worker_threads[0] is not qt_app.thread()
    finally:
        dialogue.shutdown()


def test_busy_cooldown_and_tts_synthesis_keep_inputs_in_order(qt_app, monkeypatch):
    release = threading.Event()
    prompts = []

    def provider(prompt, _config):
        prompts.append(prompt)
        release.wait(2)
        return f'답변 {len(prompts)}'

    dialogue, tts, clock = make_dialogue(monkeypatch, provider)
    try:
        dialogue.submit_speech('첫 번째')
        dialogue.ask_ai('두 번째')
        dialogue.submit_speech('세 번째')
        assert len(dialogue.pending_inputs) == 2
        release.set()
        process_until(qt_app, lambda: len(tts.spoken) == 1)
        assert len(prompts) == 1
        clock[0] = 111
        tts.busy_changed.emit(True)  # synthesis is pending; no actual playback yet
        dialogue._process_next_input()
        assert len(prompts) == 1
        tts.busy_changed.emit(False)
        process_until(qt_app, lambda: len(tts.spoken) == 2)
        assert '사용자 입력:\n두 번째' in prompts[1]
        assert '캐릭터: 답변 1' in prompts[1]
        clock[0] = 122
        dialogue._process_next_input()
        process_until(qt_app, lambda: len(tts.spoken) == 3)
        assert '사용자 입력:\n세 번째' in prompts[2]
        assert prompts[2].index('사용자: 첫 번째') < prompts[2].index('캐릭터: 답변 1')
        assert prompts[2].index('캐릭터: 답변 1') < prompts[2].index('사용자: 두 번째')
        assert prompts[2].index('사용자: 두 번째') < prompts[2].index('캐릭터: 답변 2')
        assert [item['source'] for item in dialogue.conversation_history
                if item['role'] == 'user'] == ['voice', 'text', 'voice']
    finally:
        release.set()
        dialogue.shutdown()


def test_fast_queued_response_preserves_previous_bubble_for_five_seconds(qt_app, monkeypatch):
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: '답변')
    dialogue.request_cooldown = 0
    try:
        dialogue.ask_ai('첫 번째')
        dialogue.ask_ai('두 번째')
        process_until(qt_app, lambda: len(tts.spoken) == 1)
        clock[0] = 104.9
        dialogue._process_next_input()
        assert len(dialogue.pending_inputs) == 1
        clock[0] = 105
        dialogue._process_next_input()
        process_until(qt_app, lambda: len(tts.spoken) == 2)
    finally:
        dialogue.shutdown()


def test_error_preserves_input_and_can_retry(qt_app, monkeypatch):
    responses = iter(['[Gemini error] unavailable', '복구됐어요'])
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: next(responses))
    try:
        dialogue.submit_speech('다시 도와줘')
        process_until(qt_app, lambda: len(tts.spoken) == 1)
        assert dialogue.conversation_history[0]['text'] == '다시 도와줘'
        assert dialogue.conversation_history[0]['state'] == 'failed'
        assert dialogue.retry_last_input()
        assert len(dialogue.pending_inputs) == 1
        clock[0] = 111
        dialogue._process_next_input()
        process_until(qt_app, lambda: tts.spoken[-1] == '복구됐어요')
        assert dialogue.conversation_history[-1]['state'] == 'completed'
        assert not dialogue.retry_last_input()
    finally:
        dialogue.shutdown()


def test_shutdown_ignores_late_response_and_cancels_queue(qt_app, monkeypatch):
    release = threading.Event()
    returned = threading.Event()

    def provider(*_args):
        release.wait(2)
        returned.set()
        return '늦게 도착한 응답'

    dialogue, tts, _clock = make_dialogue(monkeypatch, provider)
    dialogue.submit_speech('처음')
    dialogue.ask_ai('대기 중')
    dialogue.shutdown()
    release.set()
    process_until(qt_app, returned.is_set)
    qt_app.processEvents()
    assert tts.closed and tts.spoken == []
    assert not dialogue.pending_inputs and not dialogue.is_ai_responding
    assert all(item['state'] == 'cancelled' for item in dialogue.conversation_history)
    assert not dialogue.submit_speech('종료 후')


def test_repeated_text_is_new_turn_but_old_sequence_is_not_replayed():
    received = []
    controller = PerceptionController(Mock(), on_speech=received.append,
                                      time_provider=lambda: 100.0)
    for payload in [speech(1), speech(2), speech(1), speech(2),
                    speech(1, session='session-b')]:
        controller.handle_payload(payload)
    assert received == ['안녕', '안녕', '안녕']


def test_old_transcript_is_not_revived_by_fresh_camera_frame():
    received = []
    controller = PerceptionController(Mock(), on_speech=received.append,
                                      time_provider=lambda: 100.0)
    controller.handle_payload(speech(recognized_at=90.0))
    controller.handle_payload(speech(2, recognized_at=100.0))
    assert received == ['안녕']


def test_echo_ids_and_acoustic_tail_are_consumed_during_playback():
    clock = [100.0]
    received = []
    controller = PerceptionController(Mock(), on_speech=received.append,
                                      time_provider=lambda: clock[0])
    controller.set_speech_suppressed(True)
    controller.handle_payload(speech(1))
    clock[0] = 102
    controller.set_speech_suppressed(False)
    controller.handle_payload(speech(2, recognized_at=102.1))
    clock[0] = 103
    controller.handle_payload(speech(1))
    controller.handle_payload(speech(2, recognized_at=102.1))
    controller.handle_payload(speech(3, recognized_at=103))
    assert received == ['안녕']


def test_speech_metadata_supports_legacy_and_explicit_interim_results():
    event = parse_perception_event(speech(final=False, recognized_at='bad'))
    assert not event.speech_final and event.speech_recognized_at is None
    event = parse_perception_event({'type': 'recognition_state', 'speech': '안녕'})
    assert event.speech_final and event.speech == '안녕'


@pytest.mark.parametrize('response', ['500원이에요', '401호로 가세요',
                                      '{"text": "429는 숫자예요"}', 'Unauthorized라는 단어의 뜻은 권한 없음이에요'])
def test_normal_numeric_and_error_word_answers_are_not_http_failures(response):
    assert not DialogueSystem._is_error_response(response)
    dialogue = DialogueSystem.__new__(DialogueSystem)
    text = dialogue._process_gemini_response(response)
    assert text in response
