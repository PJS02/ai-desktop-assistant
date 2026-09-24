import time
from unittest.mock import Mock

import numpy as np
from PyQt6.QtCore import QCoreApplication

from character.dialogue_system import DialogueSystem
from character.tts_service import SupertonicTTS, _language_for, _prepare_text, available_voices


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
