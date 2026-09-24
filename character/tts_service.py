"""Supertonic 3로 AI 답변을 로컬 합성하고 Qt 오디오로 재생한다."""

import queue
import re
import threading
import unicodedata
from dataclasses import dataclass

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QSettings, pyqtSignal
from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices


_VOICE_IDS = tuple(f"F{index}" for index in range(1, 6)) + tuple(
    f"M{index}" for index in range(1, 6)
)


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str


def available_voices() -> list[VoiceInfo]:
    """Supertonic 3 모델에 포함된 기본 목소리 목록."""
    return [VoiceInfo(voice_id, f"Supertonic 3 · {voice_id}") for voice_id in _VOICE_IDS]


def _prepare_text(text: str) -> str:
    """모델이 읽지 못하는 이모지와 제어 문자를 발화에서 제외한다."""
    return "".join(
        char
        for char in str(text)
        if char not in "\ufe0e\ufe0f"
        and unicodedata.category(char) not in {"So", "Cc", "Cs", "Cf", "Sk"}
        or char in "\n\t"
    ).strip()


def _language_for(text: str) -> str:
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "na"


class SupertonicTTS(QObject):
    """최신 AI 답변만 재생하고 합성 중에도 Qt 화면을 계속 반응하게 한다."""

    audio_ready = pyqtSignal(int, bytes, int)  # 요청 번호, 16비트 PCM, 샘플레이트

    def __init__(self, settings=None, model_factory=None):
        super().__init__()
        self._settings = settings if settings is not None else QSettings("PJS02", "AIDesktopAssistant")
        self._enabled = self._settings.value("tts/enabled", True, type=bool)
        saved_voice = self._settings.value("tts/voice_id", "F1", type=str)
        self._voice_id = saved_voice if saved_voice in _VOICE_IDS else "F1"
        self._model_factory = model_factory or self._create_model
        self._commands: queue.Queue[tuple[str, int, str, str]] = queue.Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._closed = False
        self._audio_sink: QAudioSink | None = None
        self._audio_buffer: QBuffer | None = None
        self.audio_ready.connect(self._play_audio)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._settings.setValue("tts/enabled", self._enabled)
        if not self._enabled:
            self._generation += 1
            self._stop_playback()
            if self._thread is not None:
                self._enqueue("stop", self._generation, "", "")

    def set_voice(self, voice_id: str) -> None:
        if voice_id not in _VOICE_IDS:
            raise ValueError(f"Unknown Supertonic 3 voice: {voice_id}")
        self._voice_id = voice_id
        self._settings.setValue("tts/voice_id", voice_id)

    def speak(self, text: str) -> None:
        if self._closed or not self._enabled:
            return
        prepared = _prepare_text(text)
        if not prepared:
            return
        self._generation += 1
        self._stop_playback()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="supertonic-tts")
            self._thread.start()
        self._enqueue("speak", self._generation, prepared, self._voice_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._stop_playback()
        if self._thread is not None:
            self._enqueue("close", self._generation, "", "")
            self._thread.join(timeout=2.0)

    def _enqueue(self, command: str, generation: int, text: str, voice_id: str) -> None:
        # 합성 대기 중인 옛 답변은 최신 말풍선에 맞춰 버린다.
        try:
            self._commands.get_nowait()
        except queue.Empty:
            pass
        self._commands.put_nowait((command, generation, text, voice_id))

    @staticmethod
    def _create_model():
        from supertonic import TTS

        print("[TTS] Supertonic 3 모델 로딩 중 (첫 실행 시 약 400MB 다운로드)")
        return TTS(model="supertonic-3", auto_download=True)

    def _run(self) -> None:
        try:
            model = self._model_factory()
            styles = {}
            while True:
                command, generation, text, voice_id = self._commands.get()
                if command == "close":
                    return
                if command == "stop" or generation != self._generation or self._closed:
                    continue
                try:
                    if voice_id not in styles:
                        styles[voice_id] = model.get_voice_style(voice_id)
                    wav, _ = model.synthesize(
                        text,
                        voice_style=styles[voice_id],
                        lang=_language_for(text),
                    )
                    if generation != self._generation or self._closed or not self._enabled:
                        continue
                    import numpy as np

                    samples = np.asarray(wav).reshape(-1)
                    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    self.audio_ready.emit(generation, pcm, model.sample_rate)
                except Exception as exc:
                    print(f"[TTS] 음성 합성 실패: {exc}")
        except Exception as exc:
            print(f"[TTS] Supertonic 3 모델을 시작하지 못했습니다: {exc}")

    def _play_audio(self, generation: int, pcm: bytes, sample_rate: int) -> None:
        if self._closed or not self._enabled or generation != self._generation:
            return
        self._stop_playback()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(sample_rate)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull() or not device.isFormatSupported(audio_format):
            print("[TTS] 44.1kHz 모노 오디오 출력을 사용할 수 없습니다.")
            return

        self._audio_buffer = QBuffer(self)
        self._audio_buffer.setData(QByteArray(pcm))
        self._audio_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._audio_sink = QAudioSink(device, audio_format, self)
        self._audio_sink.start(self._audio_buffer)

    def _stop_playback(self) -> None:
        if self._audio_sink is not None:
            self._audio_sink.stop()
            self._audio_sink.deleteLater()
            self._audio_sink = None
        if self._audio_buffer is not None:
            self._audio_buffer.close()
            self._audio_buffer.deleteLater()
            self._audio_buffer = None
