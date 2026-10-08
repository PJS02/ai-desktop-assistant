"""No microphone or cloud endpoint is used: exercise captured audio and races."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import threading
import time

import numpy as np
import pytest
from PyQt6.QtMultimedia import QAudio
from PyQt6.QtWidgets import QApplication

from character.tts_service import SupertonicTTS

MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / 'medeapipe_capstone'
if str(MEDIAPIPE_ROOT) not in sys.path:
    sys.path.append(str(MEDIAPIPE_ROOT))
from recognition import stt_engine
from app.holistic_gui_app import HolisticGuiApp


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def process_until(app, condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(.005)
    assert condition()


def engine(monkeypatch):
    clock = [100.0]
    stt = stt_engine.RealtimeSTT(time_provider=lambda: clock[0])
    stt.recognizer = Mock()
    stt.recognizer.recognize_google.return_value = '같은 말'
    monkeypatch.setattr(stt, '_to_audio_data', lambda audio: audio)
    return stt, clock


def test_audio_callback_drops_playback_and_resumes_after_tail(monkeypatch):
    stt, clock = engine(monkeypatch)
    captured = {}

    def stream_factory(**kwargs):
        captured.update(kwargs)
        return Mock()

    monkeypatch.setattr(stt_engine, 'sd', SimpleNamespace(InputStream=stream_factory))
    stt._start_stream()
    callback = captured['callback']
    chunk = np.full((320, 1), .02, dtype=np.float32)
    callback(chunk, 320, None, None)
    assert not stt.audio_queue.empty()
    stt.set_character_speaking(True)
    assert stt.audio_queue.empty()
    callback(chunk, 320, None, None)
    assert stt.audio_queue.empty()
    stt.set_character_speaking(False)
    callback(chunk, 320, None, None)
    assert stt.audio_queue.empty()
    clock[0] += .9
    callback(chunk, 320, None, None)
    generation, resumed = stt.audio_queue.get_nowait()
    assert generation == 2 and np.array_equal(resumed, chunk[:, 0])
    stt._stop_stream()


def test_inflight_transcription_overlapping_playback_is_never_published(monkeypatch):
    stt, clock = engine(monkeypatch)

    def recognize(*_args, **_kwargs):
        stt.set_character_speaking(True)
        stt.set_character_speaking(False)
        clock[0] += 1
        return '캐릭터의 음성'

    stt.recognizer.recognize_google.side_effect = recognize
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 0)
    assert all(kind != 'speech' for kind, _value in stt.drain_events())


def test_two_completed_identical_utterances_both_survive(monkeypatch):
    stt, _clock = engine(monkeypatch)
    audio = np.full(8000, .02, dtype=np.float32)
    stt._transcribe_audio(audio, 0)
    stt._transcribe_audio(audio, 1)
    speeches = [value for kind, value in stt.drain_events() if kind == 'speech']
    assert len(speeches) == 2
    assert all(stt.accepts_speech_event(value) for value in speeches)
    assert [item['text'] for item in speeches] == ['같은 말', '같은 말']


def test_final_result_queued_before_tts_is_invalidated_before_tk_poll(monkeypatch):
    stt, clock = engine(monkeypatch)
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 0)
    speech = next(value for kind, value in stt.drain_events() if kind == 'speech')
    assert stt.accepts_speech_event(speech)
    stt.set_character_speaking(True)
    stt.set_character_speaking(False)
    clock[0] += 1
    assert not stt.accepts_speech_event(speech)


def test_worker_discards_partial_utterance_when_capture_generation_changes(monkeypatch):
    stt, clock = engine(monkeypatch)
    monkeypatch.setattr(stt, '_start_stream', lambda: None)
    captured = []

    def transcribe(audio, _offset, _generation):
        captured.append(audio.copy())
        stt.stop_event.set()

    monkeypatch.setattr(stt, '_transcribe_audio', transcribe)
    worker = threading.Thread(target=stt._run_stt, daemon=True)
    worker.start()
    try:
        stt.audio_queue.put((0, np.full(8000, .02, dtype=np.float32)))
        deadline = time.monotonic() + 2
        detected = False
        while not detected and time.monotonic() < deadline:
            detected = any(value == 'STT speech detected'
                           for _kind, value in stt.drain_events())
            time.sleep(.005)
        assert detected
        stt.set_character_speaking(True)
        stt.set_character_speaking(False)
        clock[0] += 1
        stt.audio_queue.put((2, np.full(8000, .04, dtype=np.float32)))
        stt.audio_queue.put((2, np.zeros(13000, dtype=np.float32)))
        worker.join(2)
        assert not worker.is_alive() and len(captured) == 1
        assert len(captured[0]) == 21000
        assert np.all(captured[0][:8000] == np.float32(.04))
    finally:
        stt.stop_event.set()
        worker.join(1)


def test_tk_poll_assigns_sequence_only_to_accepted_final_speech(monkeypatch):
    stt, clock = engine(monkeypatch)
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 0)
    stt.set_character_speaking(True)
    stt.set_character_speaking(False)
    clock[0] += 1
    stt._transcribe_audio(np.full(8000, .02, dtype=np.float32), 1)
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.root, app.stt, app.stt_status_var = Mock(), stt, Mock()
    app.append_stt_text = Mock()
    app.latest_speech_text, app.speech_sequence = '', 0
    app.send_recognition_state = Mock()
    app.poll_stt_events()
    assert app.latest_speech_text == '같은 말' and app.speech_sequence == 1
    app.send_recognition_state.assert_called_once_with()


class MemorySettings:
    def value(self, _key, default, type):
        return default

    def setValue(self, *_args):
        pass


def test_tts_busy_covers_cold_model_loading_and_model_failure(qt_app):
    release = threading.Event()

    def factory():
        release.wait(2)
        raise RuntimeError('model unavailable')

    tts = SupertonicTTS(MemorySettings(), model_factory=factory)
    busy = []
    tts.busy_changed.connect(busy.append)
    try:
        tts.speak('안녕하세요')
        assert tts.busy and busy == [True]
        release.set()
        process_until(qt_app, lambda: not tts.busy)
        assert busy == [True, False]
    finally:
        release.set()
        tts.close()


def test_tts_busy_finishes_on_audio_completion_and_disable(qt_app):
    tts = SupertonicTTS(MemorySettings())
    busy = []
    tts.busy_changed.connect(busy.append)
    sink = Mock()
    sink.error.return_value = QAudio.Error.NoError
    tts._audio_sink = sink
    tts._set_busy(True)
    tts._audio_state_changed(0, sink, QAudio.State.ActiveState)
    assert tts.busy
    tts._audio_state_changed(0, sink, QAudio.State.IdleState)
    assert not tts.busy
    tts._set_busy(True)
    tts.set_enabled(False)
    assert not tts.busy and busy == [True, False, True, False]
    tts.close()
