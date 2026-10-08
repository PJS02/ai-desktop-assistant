"""Logging contracts with fake audio/models; no camera, cloud or microphone."""
from pathlib import Path
import queue
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

import app_logging
from perception.controller import PerceptionController
from perception.receiver import JsonLineTcpReceiver
import json

CHILD_ROOT = Path(__file__).resolve().parents[1] / 'medeapipe_capstone'
if str(CHILD_ROOT) not in sys.path:
    sys.path.append(str(CHILD_ROOT))
from app.holistic_gui_app import HolisticGuiApp
from bridge.interaction_event_client import InteractionEventClient
from recognition import stt_engine


@pytest.fixture(autouse=True)
def fresh_logs():
    app_logging.clear_events()
    yield
    app_logging.clear_events()


def events(name):
    return [event for event in app_logging.get_events() if event.event == name]


def mood():
    return SimpleNamespace(on_external_emotion=Mock(return_value=True),
                           on_click=Mock(), on_idle=Mock())


def test_empty_observations_do_not_create_frame_logs():
    controller = PerceptionController(mood(), time_provider=lambda: 100)
    for _ in range(100):
        controller.handle_payload({'type': 'perception', 'timestamp': 100})
    assert app_logging.get_events() == []


def test_low_confidence_rejection_is_throttled_and_correlated():
    controller = PerceptionController(mood(), time_provider=lambda: 100)
    for _ in range(20):
        controller.handle_payload({'type': 'perception', 'timestamp': 100,
            'source': 'low-confidence-test', 'trace_id': 'observed-low',
            'emotion': {'label': 'happy', 'confidence': .1}})
    rejected = events('perception.rejected')
    assert len(rejected) == 1
    assert rejected[0].trace_id == 'observed-low'
    assert rejected[0].data['reason'] == 'low_confidence'


def test_speech_trace_context_reaches_callback_and_duplicate_is_rejected():
    callback = Mock()
    controller = PerceptionController(mood(), on_speech_with_context=callback,
                                      time_provider=lambda: 100)
    payload = {'type': 'perception', 'timestamp': 100, 'trace_id': 'frame',
               'speech': {'text': '테스트', 'session': 'session', 'sequence': 4,
                          'recognized_at': 100, 'trace_id': 'speech-4'}}
    controller.handle_payload(payload)
    controller.handle_payload(payload)
    assert callback.call_count == 1
    text, context = callback.call_args.args
    assert text == '테스트' and context['trace_id'] == 'speech-4'
    assert context['speech_session'] == 'session' and context['speech_sequence'] == 4
    assert events('perception.speech.accepted')[0].trace_id == 'speech-4'
    assert any(event.data['reason'] == 'duplicate' for event in events('perception.rejected'))


def test_attention_logs_away_return_and_disappearance():
    controller = PerceptionController(mood(), time_provider=lambda: 100)
    for attention in ('away', 'screen', None):
        controller.handle_payload({'type': 'perception', 'timestamp': 100,
                                   'attention': attention})
    assert [event.data['current'] for event in events('perception.attention.changed')] == ['away', 'screen', None]


def test_blocked_reaction_is_distinct_from_detection():
    callback = Mock(return_value=False)
    controller = PerceptionController(mood(), on_dialogue_with_context=callback,
                                      time_provider=lambda: 100)
    controller.handle_payload({'type': 'perception', 'timestamp': 100, 'trace_id': 'gesture-test',
        'motions': [{'kind': 'gesture', 'label': 'thumbs_up', 'side': 'left'}]})
    assert callback.call_args.args[1]['trace_id'] == 'gesture-test'
    result = events('perception.reaction.result')[0]
    assert result.trace_id == 'gesture-test' and result.data['outcome'] == 'blocked'


def test_queue_drop_has_identity_and_does_not_schedule_retry():
    client = InteractionEventClient()
    client.events = queue.Queue(maxsize=1)
    client.send({'type': 'recognition_state'})
    client.send({'type': 'recognition_state', 'trace_id': 'drop-id'})
    assert client.events.qsize() == 1
    dropped = events('transport.sender.dropped')[0]
    assert dropped.trace_id == 'drop-id'
    assert dropped.data['reason'] == 'queue_full' and dropped.data['retry_scheduled'] is False


def test_diagnostic_payload_shapes_cannot_break_queue_acceptance():
    client = InteractionEventClient()
    client.send({'type': 'recognition_state', 'always': None, 'mode': [], 'speech': 'plain text'})
    client.send({'type': 'recognition_state', 'always': {'emotion': None}, 'mode': None})
    assert client.events.qsize() == 2


def test_settings_timeout_reports_saved_but_runtime_unknown():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.settings_state = Mock(return_value={})
    app.emit_settings = Mock()
    app._settings_request_id = 'pending-request'
    app._settings_saved = True
    app.settings_result('pending-request', False, '확인 시간 초과', runtime_status='unknown')
    response = app.emit_settings.call_args.args[0]
    assert response['saved'] is True and response['runtime_applied'] is None
    assert response['runtime_status'] == 'unknown'


def test_other_request_does_not_inherit_previous_save_result():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.settings_state = Mock(return_value={})
    app.emit_settings = Mock()
    app._settings_request_id = 'previous-request'
    app._settings_saved = True
    app.settings_result('invalid-new-request', False, '잘못된 요청')
    assert app.emit_settings.call_args.args[0]['saved'] is False


def test_trace_metadata_does_not_bypass_semantic_dedup():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.last_sent_interaction_events = {}
    app.event_client = Mock()
    app.send_interaction_event_if_changed('state', {'type': 'recognition_state', 'trace_id': 'a',
                                                   'speech': {'sequence': 1, 'trace_id': 'speech-a'}})
    app.send_interaction_event_if_changed('state', {'type': 'recognition_state', 'trace_id': 'b',
                                                   'speech': {'sequence': 1, 'trace_id': 'speech-b'}})
    assert app.event_client.send.call_count == 1


def test_receiver_logs_new_speech_inside_repeat_window_without_mutating_payload():
    received = []
    receiver = JsonLineTcpReceiver(received.append)
    for sequence in (1, 1, 1, 2):
        payload = {'type': 'recognition_state', 'trace_id': f'packet-{sequence}',
                   'speech': {'session': 'test', 'sequence': sequence, 'latest_text': '같은 말'}}
        receiver._handle_line(json.dumps(payload).encode('utf-8'), 'fake-client')
        assert received[-1] == payload
    logged = events('transport.receiver.received')
    assert [event.trace_id for event in logged] == ['packet-1', 'packet-2']
    assert logged[-1].data['repeated_packets'] == 2


def test_per_frame_scores_ids_times_and_air_points_are_summarized():
    client = InteractionEventClient()
    receiver = JsonLineTcpReceiver(lambda _payload: None)
    for index in range(10):
        payload = {'type': 'recognition_state', 'trace_id': f'frame-{index}', 'timestamp': 100 + index,
                   'always': {'emotion': {'label': 'happy', 'confidence': .8 + index / 100}},
                   'mode': {'active': 'air', 'result': {'left_points': index}},
                   'rps_game': {'session': 'test', 'captured_at': 100 + index, 'hands': {'left': 'ROCK'}}}
        client.send(payload)
        receiver._handle_line(json.dumps(payload).encode('utf-8'), 'fake-client')
    assert len(events('transport.sender.queued')) == 1
    assert len(events('transport.receiver.received')) == 1


def test_failed_save_does_not_print_success(monkeypatch, capsys):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.device_settings = {}
    monkeypatch.setattr('app.holistic_gui_app.save_device_settings', Mock(side_effect=OSError('disk failed')))
    assert app.save_camera_device_settings({'index': 2, 'backend_label': 'test'}) == 'failed'
    assert '카메라 저장:' not in capsys.readouterr().out
    assert events('device.settings.failed')[0].data['outcome'] == 'failed'


def test_batch_save_is_deferred_without_false_success(monkeypatch, capsys):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.device_settings = {}
    app.settings_collecting = True
    save = Mock()
    monkeypatch.setattr('app.holistic_gui_app.save_device_settings', save)
    assert app.save_camera_device_settings({'index': 2, 'backend_label': 'test'}) == 'deferred'
    save.assert_not_called()
    assert capsys.readouterr().out == ''


def fake_stt(monkeypatch):
    stt = stt_engine.RealtimeSTT(time_provider=lambda: 100)
    stt.recognizer = Mock()
    stt.recognizer.recognize_google.return_value = '인식 결과'
    monkeypatch.setattr(stt, '_to_audio_data', lambda audio: audio)
    return stt


def test_google_request_result_and_speech_share_trace(monkeypatch):
    stt = fake_stt(monkeypatch)
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 0)
    request = events('stt.google.request')[0]
    result = events('stt.google.result')[0]
    speech = next(value for kind, value in stt.drain_events() if kind == 'speech')
    assert request.trace_id == result.trace_id == speech['trace_id']
    assert request.data['duration'] == .5
    assert result.data['text'] == speech['text'] == '인식 결과'


def test_unknown_speech_records_outcome_without_error_or_speech(monkeypatch):
    stt = fake_stt(monkeypatch)
    stt.recognizer.recognize_google.side_effect = stt_engine.sr.UnknownValueError()
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 0)
    assert events('stt.google.unrecognized')[0].level == 'INFO'
    assert not any(kind == 'speech' for kind, _value in stt.drain_events())


def test_audio_callback_defers_warning_logging_to_drain(monkeypatch):
    stt = fake_stt(monkeypatch)
    parameters = {}
    def stream_factory(**kwargs):
        parameters.update(kwargs)
        return Mock()
    monkeypatch.setattr(stt_engine, 'sd', SimpleNamespace(InputStream=stream_factory))
    stt._start_stream()
    app_logging.clear_events()
    parameters['callback'](np.full((320, 1), .02, dtype=np.float32), 320, None, 'overflow')
    assert events('stt.audio.warning') == []
    stt.drain_events()
    assert events('stt.audio.warning')[0].data['status'] == 'overflow'
    stt._stop_stream()


def test_inference_errors_throttle_and_recovery_is_recorded():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.emotion_recognizer = Mock()
    app.emotion_recognizer.predict.side_effect = [RuntimeError('bad model'), RuntimeError('bad model'),
                                                {'scores': {'happy': .9, 'neutral': .1}}]
    app.last_emotion_inference_ms = -150
    app.extract_face_crop = Mock(return_value=object())
    for stamp in (0, 150, 300):
        app.update_emotion_result(None, None, stamp)
    assert len(events('recognition.inference.failed')) == 1
    assert len(events('recognition.inference.recovered')) == 1
    assert app.emotion_result['label'] == 'happy'
