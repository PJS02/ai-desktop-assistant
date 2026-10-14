import time
from unittest.mock import Mock

import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal
from PyQt6.QtMultimedia import QAudio

from character.dialogue_system import DialogueSystem
from character.tts_service import SupertonicTTS, _language_for, _prepare_text, available_voices
from character import tts_service


class MemorySettings:
    def __init__(self):
        self.data = {}

    def value(self, key, default, type):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value


class FakeModel:
    sample_rate = 44100

    def __init__(self):
        self.calls = []

    def get_voice_style(self, name):
        return name

    def synthesize(self, text, voice_style, lang):
        self.calls.append((text, voice_style, lang))
        return np.array([[0.0, 0.5, -0.5]], dtype=np.float32), np.array([0.1])


def _process_until(app, condition, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    assert condition()


def test_ai_response_is_shown_and_sent_to_tts():
    dialogue = DialogueSystem(Mock())
    dialogue.show_dialogue = Mock()
    dialogue.tts = Mock()

    dialogue.show_ai_response("안녕하세요")

    dialogue.show_dialogue.assert_called_once_with("안녕하세요", duration=5000)
    dialogue.tts.speak.assert_called_once_with("안녕하세요")


def test_supertonic_synthesizes_korean_with_selected_voice_and_pcm():
    app = QCoreApplication.instance() or QCoreApplication([])
    settings = MemorySettings()
    model = FakeModel()
    tts = SupertonicTTS(settings, model_factory=lambda: model)
    received = []
    speaking = []
    tts.speaking_changed.connect(speaking.append)
    tts.audio_ready.disconnect(tts._play_audio)
    tts.audio_ready.connect(lambda generation, pcm, rate: received.append((generation, pcm, rate)))
    try:
        tts.set_voice("M2")
        tts.speak("안녕하세요 😊")
        _process_until(app, lambda: len(received) == 1)

        assert model.calls == [("안녕하세요", "M2", "ko")]
        assert received[0][1] == np.array([0, 16383, -16383], dtype=np.int16).tobytes()
        assert received[0][2] == 44100
        assert settings.data["tts/voice_id"] == "M2"
        assert speaking == []  # 텍스트 요청과 합성 완료는 실제 재생이 아니다.

        tts.set_enabled(False)
        tts.speak("읽히면 안 됩니다")
        assert len(model.calls) == 1
        assert settings.data["tts/enabled"] is False
    finally:
        tts.close()


def test_voice_list_and_text_cleanup():
    assert [voice.id for voice in available_voices()] == [
        "F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"
    ]
    assert _prepare_text("반가워요 👩🏽‍💻!") == "반가워요 !"
    assert _language_for("Hello") == "en"


class FakeAudioSink(QObject):
    stateChanged = pyqtSignal(object)

    def __init__(self, start_state, start_error, fail_start, parent):
        super().__init__(parent)
        self.start_state = start_state
        self.start_error = start_error
        self.fail_start = fail_start
        self._state = QAudio.State.StoppedState
        self._error = QAudio.Error.NoError
        self.start_calls = 0
        self.stop_calls = 0

    def state(self):
        return self._state

    def error(self):
        return self._error

    def start(self, buffer):
        assert buffer.isOpen()
        self.start_calls += 1
        if self.fail_start:
            raise RuntimeError("audio device disappeared")
        self.transition(self.start_state, self.start_error)

    def stop(self):
        self.stop_calls += 1
        self.transition(QAudio.State.StoppedState)

    def transition(self, state, error=QAudio.Error.NoError):
        self._state, self._error = state, error
        self.stateChanged.emit(state)


@pytest.fixture
def audio_output(monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    device = Mock()
    device.isNull.return_value = False
    device.isFormatSupported.return_value = True
    config = {"sinks": [], "device": device,
              "start_state": QAudio.State.ActiveState,
              "start_error": QAudio.Error.NoError, "fail_start": False}

    def create_sink(device, audio_format, parent):
        sink = FakeAudioSink(config["start_state"], config["start_error"],
                             config["fail_start"], parent)
        config["sinks"].append(sink)
        return sink

    monkeypatch.setattr(tts_service, "QAudioSink", create_sink)
    monkeypatch.setattr(tts_service, "QMediaDevices", Mock(defaultAudioOutput=lambda: device))
    return config


def test_speaking_follows_actual_audio_states_without_duplicate_notifications(audio_output):
    tts = SupertonicTTS(MemorySettings())
    speaking = []
    tts.speaking_changed.connect(speaking.append)
    try:
        tts._play_audio(tts._generation, b"\0\0" * 4410, 44100)
        sink = audio_output["sinks"][-1]
        assert speaking == [True]
        sink.transition(QAudio.State.ActiveState)
        assert speaking == [True]
        sink.transition(QAudio.State.IdleState)
        assert speaking == [True, False]
        sink.transition(QAudio.State.ActiveState)
        sink.transition(QAudio.State.SuspendedState)
        assert speaking == [True, False, True, False]
        sink.transition(QAudio.State.ActiveState)
        sink.transition(QAudio.State.StoppedState, QAudio.Error.IOError)
        assert speaking == [True, False, True, False, True, False]
    finally:
        tts.close()


@pytest.mark.parametrize("cancel", ["disable", "close", "stop"])
def test_cancellation_clears_speaking_and_ignores_retired_sink_callbacks(audio_output, cancel):
    tts = SupertonicTTS(MemorySettings())
    speaking = []
    tts.speaking_changed.connect(speaking.append)
    try:
        tts._play_audio(tts._generation, b"\0\0" * 4410, 44100)
        sink = audio_output["sinks"][-1]
        if cancel == "disable":
            tts.set_enabled(False)
        elif cancel == "close":
            tts.close()
        else:
            tts._stop_playback()
        assert speaking == [True, False]
        assert sink.stop_calls == 1
        assert tts._audio_sink is None
        assert tts._audio_buffer is None
        sink.transition(QAudio.State.ActiveState)
        sink.transition(QAudio.State.IdleState)
        assert speaking == [True, False]
    finally:
        tts.close()


def test_old_sink_cannot_stop_new_playback_and_stale_generation_cannot_change_state(audio_output):
    tts = SupertonicTTS(MemorySettings())
    speaking = []
    tts.speaking_changed.connect(speaking.append)
    try:
        old_generation = tts._generation
        tts._play_audio(old_generation, b"\0\0" * 4410, 44100)
        old_sink = audio_output["sinks"][-1]
        tts._generation += 1
        tts._play_audio(tts._generation, b"\0\0" * 4410, 44100)
        new_sink = audio_output["sinks"][-1]
        assert speaking == [True, False, True]
        old_sink.transition(QAudio.State.StoppedState, QAudio.Error.FatalError)
        old_sink.transition(QAudio.State.ActiveState)
        tts._audio_state_changed(old_generation, new_sink, QAudio.State.IdleState)
        tts._play_audio(old_generation, b"\0\0" * 4410, 44100)
        assert speaking == [True, False, True]
        assert len(audio_output["sinks"]) == 2
        new_sink.transition(QAudio.State.IdleState)
        assert speaking == [True, False, True, False]
    finally:
        tts.close()


@pytest.mark.parametrize("unavailable", ["empty", "no_device", "unsupported", "start_error", "start_exception"])
def test_failed_or_empty_playback_never_announces_speaking(audio_output, unavailable):
    if unavailable == "no_device":
        audio_output["device"].isNull.return_value = True
    elif unavailable == "unsupported":
        audio_output["device"].isFormatSupported.return_value = False
    elif unavailable == "start_error":
        audio_output["start_state"] = QAudio.State.StoppedState
        audio_output["start_error"] = QAudio.Error.OpenError
    elif unavailable == "start_exception":
        audio_output["fail_start"] = True
    tts = SupertonicTTS(MemorySettings())
    speaking = []
    tts.speaking_changed.connect(speaking.append)
    try:
        pcm = b"" if unavailable == "empty" else b"\0\0" * 4410
        tts._play_audio(tts._generation, pcm, 44100)
        assert speaking == []
        if unavailable in {"empty", "no_device", "unsupported", "start_exception"}:
            assert tts._audio_sink is None
            assert tts._audio_buffer is None
    finally:
        tts.close()
