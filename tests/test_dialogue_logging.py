"""Conversation diagnostics preserve provider, output and device behaviour."""
import io
import json
import threading
from urllib.error import HTTPError, URLError

import pytest
from PyQt6.QtMultimedia import QAudio
from PyQt6.QtWidgets import QApplication

from app_logging import subscribe
from character.dialogue_system import DialogueSystem
from character.tts_service import SupertonicTTS
from context import active_window_classifier as api
from test_voice_dialogue import make_dialogue, process_until
from test_tts_service import MemorySettings, FakeModel, audio_output
from test_dialogue_styles import dialogue_ui


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def events():
    received = []
    unsubscribe = subscribe(lambda record: received.append(record))
    try:
        yield received
    finally:
        unsubscribe()


def event(records, name):
    return next(record for record in records if record.event == name)


class HTTPResponse:
    status = 200

    def __init__(self, body):
        self.body = body
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        self.reads += 1
        return self.body.encode('utf-8')


def test_http_logs_actual_payload_full_body_and_preserves_first_text(monkeypatch, events):
    text = '{"dialogue": "' + '전체 응답 ' * 40 + '"}'
    body = json.dumps({'candidates': [
        {'content': {'parts': [{'text': text}, {'text': 'second part'}]}, 'finishReason': 'STOP'},
        {'content': {'parts': [{'text': 'second candidate'}]}}],
        'usageMetadata': {'totalTokenCount': 123}}, ensure_ascii=False)
    response = HTTPResponse(body)
    sent = []

    def open_request(request, timeout):
        sent.append((request, timeout))
        return response

    monkeypatch.setattr(api, 'urlopen', open_request)
    result = api.call_gemini('실제 프롬프트\n감정 지침', {'api_key': 'secret-http-only', 'model': 'unchanged-model'},
                             log_context={'trace_id': 'trace-http', 'source': 'text'})
    assert result == text and response.reads == 1
    request_log = event(events, 'gemini.request')
    assert request_log.data['payload'] == json.loads(sent[0][0].data)
    assert request_log.data['payload']['contents'][0]['parts'][0]['text'] == '실제 프롬프트\n감정 지침'
    assert event(events, 'gemini.http_response').data['body'] == body
    assert event(events, 'gemini.text_extracted').data['text'] == text
    assert all(record.trace_id == 'trace-http' for record in events)
    assert 'secret-http-only' not in '\n'.join(record.details() for record in events)
    assert sent[0][1] == 30


def test_http_retry_logs_error_body_and_attempts_without_changing_policy(monkeypatch, events):
    count = [0]
    sleeps = []

    def open_request(request, timeout):
        count[0] += 1
        if count[0] < 3:
            raise HTTPError(request.full_url, 500, 'server error', {}, io.BytesIO(b'{"error":"unavailable"}'))
        return HTTPResponse('{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}')

    monkeypatch.setattr(api, 'urlopen', open_request)
    monkeypatch.setattr(api.time, 'sleep', sleeps.append)
    assert api.call_gemini('prompt', {'api_key': 'retry-secret'}, log_context={'trace_id': 'trace-retry'}) == 'ok'
    assert sleeps == [1, 2] and count == [3]
    assert [record.data['attempt'] for record in events if record.event == 'gemini.attempt_started'] == [1, 2, 3]
    failures = [record for record in events if record.event == 'gemini.http_failed']
    assert len(failures) == 2 and all(record.category == '오류' for record in failures)
    assert failures[0].data['body'] == '{"error":"unavailable"}'


@pytest.mark.parametrize('failure', ['http', 'url', 'json', 'no_candidates', 'empty_content', 'no_key'])
def test_gemini_failure_paths_are_visible_and_credentials_are_removed(monkeypatch, events, failure):
    secret = 'private-diagnostic-key'

    def open_request(request, timeout):
        if failure == 'http':
            raise HTTPError(request.full_url, 403, 'forbidden ' + secret, {}, io.BytesIO(b'blocked'))
        if failure == 'url':
            raise URLError('failed for key ' + secret)
        bodies = {'json': 'not-json ' + secret, 'no_candidates': '{}',
                  'empty_content': '{"candidates":[{"content":{}}]}'}
        return HTTPResponse(bodies[failure])

    monkeypatch.setattr(api, 'urlopen', open_request)
    result = api.call_gemini('prompt', {'api_key': '' if failure == 'no_key' else secret},
                             log_context={'trace_id': 'trace-failure'})
    assert result == '' if failure == 'no_key' else result.startswith('[gemini error]')
    assert any(record.level in {'ERROR', 'WARNING'} for record in events)
    assert secret not in '\n'.join(record.details() for record in events)
    assert all(record.trace_id == 'trace-failure' for record in events)


def test_voice_turn_prompt_normalization_and_legacy_provider_share_trace(qt_app, monkeypatch, events):
    calls = []

    def provider(prompt, config):
        calls.append((prompt, config))
        return '{"dialogue":"전체 최종 문장"}'

    dialogue, tts, _clock = make_dialogue(monkeypatch, provider)
    try:
        dialogue.submit_speech_with_context('  실제 음성 입력  ',
            {'trace_id': 'trace-voice', 'speech_session': 'session', 'speech_sequence': 7})
        process_until(qt_app, lambda: len(tts.spoken) == 1)
        assert len(calls) == 1 and calls[0][1] == {'model': 'test-model'}
        assert tts.spoken == ['전체 최종 문장']
        accepted = event(events, 'dialogue.input_accepted')
        assert accepted.data['raw_text'] == '  실제 음성 입력  '
        assert accepted.data['speech']['speech_sequence'] == 7
        assert event(events, 'dialogue.prompt_built').data['prompt'] == calls[0][0]
        assert event(events, 'dialogue.response_normalized').data['selected_field'] == 'dialogue'
        for name in ('dialogue.input_accepted', 'dialogue.processing_started', 'dialogue.prompt_built',
                     'dialogue.model_text_received', 'dialogue.response_normalized',
                     'dialogue.turn_completed', 'dialogue.tts_requested'):
            assert event(events, name).trace_id == 'trace-voice'
        assert all(turn['trace_id'] == 'trace-voice' for turn in dialogue.conversation_history)
    finally:
        dialogue.shutdown()


def test_wait_reason_changes_and_retry_parent_are_recorded(qt_app, monkeypatch, events):
    responses = iter(['[gemini error] unavailable', 'restored'])
    dialogue, tts, clock = make_dialogue(monkeypatch, lambda *_args: next(responses))
    try:
        dialogue.ask_ai('retry me')
        process_until(qt_app, lambda: len(tts.spoken) == 1)
        failed_trace = event(events, 'dialogue.turn_failed').trace_id
        assert dialogue.retry_last_input()
        waits = [record for record in events if record.event == 'dialogue.input_waiting']
        assert waits[-1].data['reason'] == 'cooldown'
        dialogue._process_next_input()
        assert len([record for record in events if record.event == 'dialogue.input_waiting']) == len(waits)
        tts.busy_changed.emit(True)
        dialogue._process_next_input()
        assert event(list(reversed(events)), 'dialogue.input_waiting').data['reason'] == 'tts_synthesis'
        clock[0] = 111
        tts.busy_changed.emit(False)
        process_until(qt_app, lambda: len(tts.spoken) == 2)
        retried = [record for record in events if record.event == 'dialogue.input_accepted'][-1]
        assert retried.data['retry_of'] == failed_trace and retried.trace_id != failed_trace
    finally:
        dialogue.shutdown()


def test_shutdown_logs_queued_cancellation_and_late_response_discard(qt_app, monkeypatch, events):
    release = threading.Event()
    returned = threading.Event()

    def provider(*_args):
        release.wait(2)
        returned.set()
        return 'late'

    dialogue, tts, _clock = make_dialogue(monkeypatch, provider)
    try:
        dialogue.ask_ai('first')
        dialogue.ask_ai('second')
        traces = [turn['trace_id'] for turn in dialogue.conversation_history]
        dialogue.shutdown()
        release.set()
        process_until(qt_app, returned.is_set)
        process_until(qt_app, lambda: any(record.event == 'dialogue.response_discarded' for record in events))
        assert {record.trace_id for record in events if record.event == 'dialogue.turn_cancelled'} == set(traces)
        assert event(events, 'dialogue.response_discarded').trace_id == traces[0]
        assert not tts.spoken
    finally:
        release.set()
        dialogue.shutdown()


def test_actual_audio_states_log_single_start_completion_and_trace(qt_app, audio_output, events):
    tts = SupertonicTTS(MemorySettings())
    tts._request_contexts[tts._generation] = {'trace_id': 'trace-audio'}
    try:
        tts._play_audio(tts._generation, b'\0\0' * 4410, 44100)
        sink = audio_output['sinks'][-1]
        sink.transition(QAudio.State.ActiveState)
        sink.transition(QAudio.State.IdleState)
        sink.transition(QAudio.State.IdleState)
        assert [record.event for record in events if record.event in
                {'tts.playback_started', 'tts.playback_completed'}] == ['tts.playback_started', 'tts.playback_completed']
        assert all(record.trace_id == 'trace-audio' for record in events)
        assert not any(record.event == 'tts.playback_failed' for record in events)
    finally:
        tts.close()


def test_tts_disabled_and_output_errors_are_explicit(qt_app, audio_output, events):
    tts = SupertonicTTS(MemorySettings())
    try:
        tts.set_enabled(False)
        tts.speak_with_context('disabled voice', {'trace_id': 'trace-disabled'})
        assert event(events, 'tts.skipped').data['reason'] == 'disabled'
        assert event(events, 'tts.skipped').trace_id == 'trace-disabled'
        assert tts._thread is None
        tts.set_enabled(True)
        tts._request_contexts[tts._generation] = {'trace_id': 'trace-error'}
        audio_output['start_state'] = QAudio.State.StoppedState
        audio_output['start_error'] = QAudio.Error.OpenError
        tts._play_audio(tts._generation, b'\0\0' * 4410, 44100)
        error = event(events, 'tts.playback_failed')
        assert error.trace_id == 'trace-error' and error.category == '오류'
        assert error.data['error'] == 'OpenError'
        assert not any(record.event == 'tts.playback_started' for record in events)
    finally:
        tts.close()


def test_synthesis_logs_actual_cleaned_text_and_completion(qt_app, events):
    model = FakeModel()
    tts = SupertonicTTS(MemorySettings(), model_factory=lambda: model)
    tts.audio_ready.disconnect(tts._play_audio)
    ready = []
    tts.audio_ready.connect(lambda *_args: ready.append(True))
    try:
        tts.speak_with_context('반가워요 😊', {'trace_id': 'trace-synthesis'})
        process_until(qt_app, lambda: bool(ready))
        assert event(events, 'tts.requested').data['text'] == '반가워요 😊'
        assert event(events, 'tts.synthesis_started').data['text'] == '반가워요'
        complete = event(events, 'tts.synthesis_completed')
        assert complete.trace_id == 'trace-synthesis' and complete.data['pcm_bytes'] == 6
        assert not any(record.event == 'tts.playback_started' for record in events)
    finally:
        tts.close()


def test_real_bubbles_log_shown_replacement_and_timeout_once(dialogue_ui, events):
    dialogue, _tts = dialogue_ui
    dialogue.show_dialogue('old text', duration=0, log_context={'trace_id': 'trace-old'})
    previous = dialogue.current_dialogue
    dialogue.show_dialogue('new text', duration=0, log_context={'trace_id': 'trace-new'})
    current = dialogue.current_dialogue
    previous.dialogue_closed.emit()  # duplicate old notification does not duplicate the close log
    current._auto_close()
    shown = [record for record in events if record.event == 'dialogue.widget_shown']
    closed = [record for record in events if record.event == 'dialogue.widget_closed']
    replaced = event(events, 'dialogue.widget_replaced')
    assert [record.trace_id for record in shown] == ['trace-old', 'trace-new']
    assert [record.data['reason'] for record in closed] == ['replaced', 'duration_elapsed']
    assert replaced.trace_id == 'trace-old'
    assert replaced.data['replacement_trace_id'] == 'trace-new'
