"""Supertonic 3로 AI 답변을 로컬 합성하고 Qt 오디오로 재생한다."""

import queue
import re
import threading
import time
import unicodedata
from dataclasses import dataclass

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QSettings, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
from app_logging import log_event, new_trace_id


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
    speaking_changed = pyqtSignal(bool)  # 실제 오디오 재생 상태 (합성 대기 제외)
    busy_changed = pyqtSignal(bool)  # synthesis or playback; ordered dialogue waits for both
    request_finished = pyqtSignal(int)

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
        self._speaking = False
        self._busy = False
        self._request_contexts = {}
        self._playback_generation = None
        self._last_audio_state = None
        self._playback_started_at = None
        self.audio_ready.connect(self._play_audio)
        self.request_finished.connect(self._finish_request, Qt.ConnectionType.QueuedConnection)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def voice_id(self) -> str:
        return self._voice_id

    @property
    def busy(self) -> bool:
        return self._busy

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._settings.setValue("tts/enabled", self._enabled)
        if not self._enabled:
            self._cancel_request(self._generation, 'disabled')
            self._generation += 1
            self._stop_playback(reason='disabled')
            self._set_busy(False)
            if self._thread is not None:
                self._enqueue("stop", self._generation, "", "")

    def set_voice(self, voice_id: str) -> None:
        if voice_id not in _VOICE_IDS:
            raise ValueError(f"Unknown Supertonic 3 voice: {voice_id}")
        self._voice_id = voice_id
        self._settings.setValue("tts/voice_id", voice_id)

    def sync_settings(self):
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            self._log_tts('tts.settings_save_failed', '음성 설정 저장 실패', level='ERROR',
                          status=str(self._settings.status()))
            raise OSError('음성 설정을 저장하지 못했습니다.')
        self._log_tts('tts.settings_saved', '음성 설정 저장 확인', enabled=self._enabled,
                      voice_id=self._voice_id)

    def speak(self, text: str) -> None:
        self.speak_with_context(text, {})

    def speak_with_context(self, text: str, context=None) -> None:
        """Keep speak(text) compatible while correlating actual synthesis and playback."""
        context = dict(context or {})
        context.setdefault('trace_id', new_trace_id('tts'))
        if self._closed or not self._enabled:
            self._log_tts('tts.skipped', '음성 출력 생략', context=context,
                          reason='shutdown' if self._closed else 'disabled', text=text)
            return
        prepared = _prepare_text(text)
        if not prepared:
            self._log_tts('tts.skipped', '발화할 문장 없음', context=context,
                          reason='empty_prepared_text', text=text, prepared_text=prepared)
            return
        self._cancel_request(self._generation, 'replaced')
        self._generation += 1
        self._request_contexts[self._generation] = context
        self._log_tts('tts.requested', '음성 합성 요청', generation=self._generation,
                      text=text, prepared_text=prepared, voice_id=self._voice_id,
                      language=_language_for(prepared))
        self._set_busy(True)
        self._stop_playback(reason='replaced')
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="supertonic-tts")
            self._thread.start()
        self._enqueue("speak", self._generation, prepared, self._voice_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_request(self._generation, 'shutdown')
        self._generation += 1
        self._stop_playback(reason='shutdown')
        self._set_busy(False)
        if self._thread is not None:
            self._enqueue("close", self._generation, "", "")
            self._thread.join(timeout=2.0)
            self._log_tts('tts.worker_shutdown', '음성 작업 종료 대기 결과',
                          stopped=not self._thread.is_alive(), timeout_seconds=2.0)

    def _enqueue(self, command: str, generation: int, text: str, voice_id: str) -> None:
        # 합성 대기 중인 옛 답변은 최신 말풍선에 맞춰 버린다.
        try:
            previous = self._commands.get_nowait()
            if previous[0] == 'speak':
                self._log_tts('tts.queued_discarded', '대기 중인 이전 발화 교체',
                              generation=previous[1], reason=command)
                self._request_contexts.pop(previous[1], None)
        except queue.Empty:
            pass
        self._commands.put_nowait((command, generation, text, voice_id))

    @staticmethod
    def _create_model():
        from supertonic import TTS

        print("[TTS] Supertonic 3 모델 로딩 중 (첫 실행 시 약 400MB 다운로드)")
        return TTS(model="supertonic-3", auto_download=True)

    def _run(self) -> None:
        started = time.monotonic()
        self._log_tts('tts.model_loading', 'Supertonic 3 모델 로딩 시작', model='supertonic-3')
        try:
            model = self._model_factory()
            self._log_tts('tts.model_ready', 'Supertonic 3 모델 준비 완료', model='supertonic-3',
                          elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                          sample_rate=model.sample_rate)
            styles = {}
            while True:
                command, generation, text, voice_id = self._commands.get()
                if command == "close":
                    return
                if command == "stop" or generation != self._generation or self._closed:
                    if command == 'speak':
                        self._log_tts('tts.synthesis_discarded', '만료된 합성 요청 생략',
                                      generation=generation, reason='shutdown' if self._closed else 'generation_mismatch')
                        self._request_contexts.pop(generation, None)
                    continue
                context = dict(self._request_contexts.get(generation, {}))
                synthesis_started = time.monotonic()
                try:
                    self._log_tts('tts.synthesis_started', '음성 합성 시작', generation=generation,
                                  context=context, text=text, voice_id=voice_id, language=_language_for(text))
                    if voice_id not in styles:
                        styles[voice_id] = model.get_voice_style(voice_id)
                    wav, _ = model.synthesize(
                        text,
                        voice_style=styles[voice_id],
                        lang=_language_for(text),
                    )
                    if generation != self._generation or self._closed or not self._enabled:
                        self._log_tts('tts.synthesis_discarded', '완료된 이전 음성 합성 폐기',
                                      generation=generation, context=context,
                                      reason='shutdown' if self._closed else 'disabled' if not self._enabled else 'generation_mismatch')
                        self._request_contexts.pop(generation, None)
                        continue
                    import numpy as np

                    samples = np.asarray(wav).reshape(-1)
                    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    self._log_tts('tts.synthesis_completed', '음성 합성 완료', generation=generation,
                                  context=context, elapsed_ms=round((time.monotonic() - synthesis_started) * 1000, 2),
                                  pcm_bytes=len(pcm), sample_rate=model.sample_rate,
                                  audio_seconds=len(samples) / model.sample_rate)
                    self.audio_ready.emit(generation, pcm, model.sample_rate)
                except Exception as exc:
                    self._log_tts('tts.synthesis_failed', '음성 합성 실패', generation=generation,
                                  context=context, level='ERROR', error=str(exc),
                                  elapsed_ms=round((time.monotonic() - synthesis_started) * 1000, 2))
                    self.request_finished.emit(generation)
        except Exception as exc:
            self._log_tts('tts.model_failed', 'Supertonic 3 모델 로딩 실패',
                          level='ERROR', error=str(exc), model='supertonic-3',
                          elapsed_ms=round((time.monotonic() - started) * 1000, 2))
            self.request_finished.emit(self._generation)

    def _play_audio(self, generation: int, pcm: bytes, sample_rate: int) -> None:
        if self._closed or not self._enabled or generation != self._generation:
            self._log_tts('tts.audio_discarded', '만료된 음성 재생 결과 폐기', generation=generation,
                          reason='shutdown' if self._closed else 'disabled' if not self._enabled else 'generation_mismatch')
            self._request_contexts.pop(generation, None)
            return
        context = self._request_contexts.get(generation) or {'trace_id': new_trace_id('tts')}
        self._stop_playback(reason='replaced')
        self._request_contexts[generation] = context
        if not pcm:
            self._log_tts('tts.skipped', '빈 오디오 재생 생략', generation=generation, reason='empty_audio')
            self._set_busy(False)
            self._request_contexts.pop(generation, None)
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(sample_rate)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull() or not device.isFormatSupported(audio_format):
            self._log_tts('tts.output_unavailable', '오디오 출력 사용 불가', generation=generation,
                          level='ERROR', reason='no_device' if device.isNull() else 'unsupported_format',
                          sample_rate=sample_rate, channels=1, sample_format='Int16')
            self._set_busy(False)
            self._request_contexts.pop(generation, None)
            return

        self._audio_buffer = QBuffer(self)
        self._audio_buffer.setData(QByteArray(pcm))
        self._audio_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        sink = QAudioSink(device, audio_format, self)
        self._audio_sink = sink
        self._playback_generation = generation
        self._last_audio_state = None
        self._playback_started_at = None
        self._log_tts('tts.playback_requested', '오디오 장치 재생 요청', generation=generation,
                      sample_rate=sample_rate, pcm_bytes=len(pcm), channels=1,
                      device=str(device.description()) if callable(getattr(device, 'description', None)) else None)
        sink.stateChanged.connect(
            lambda state: self._audio_state_changed(generation, sink, state)
        )
        try:
            sink.start(self._audio_buffer)
            # 일부 출력 장치는 start 안에서 이미 상태를 바꾼다. 현재 상태도
            # 확인하되, 중복 신호는 _set_speaking에서 제외한다.
            self._audio_state_changed(generation, sink, sink.state())
        except Exception as exc:
            self._log_tts('tts.playback_failed', '오디오 재생 시작 실패', generation=generation,
                          level='ERROR', error=str(exc))
            self._stop_playback(reason='start_exception')
            self._set_busy(False)

    def _audio_state_changed(self, generation: int, sink: QAudioSink, state) -> None:
        # 취소된 요청이나 교체/삭제된 출력 장치의 지연 콜백은 새 발화를
        # 켜거나 끄지 못한다. 합성/텍스트 요청만으로는 True를 내보내지 않는다.
        if generation != self._generation or sink is not self._audio_sink:
            return
        error = sink.error()
        signature = (generation, state, error)
        if signature != self._last_audio_state:
            self._last_audio_state = signature
            if error != QAudio.Error.NoError:
                self._log_tts('tts.playback_failed', '오디오 장치 재생 오류', generation=generation,
                              level='ERROR', state=getattr(state, 'name', str(state)),
                              error=getattr(error, 'name', str(error)))
            elif state == QAudio.State.ActiveState:
                self._playback_started_at = time.monotonic()
                self._log_tts('tts.playback_started', '오디오 장치 실제 재생 시작', generation=generation)
            elif state == QAudio.State.IdleState:
                self._log_tts('tts.playback_completed', '오디오 재생 완료', generation=generation,
                              elapsed_ms=round((time.monotonic() - self._playback_started_at) * 1000, 2)
                              if self._playback_started_at is not None else None)
            elif state == QAudio.State.StoppedState:
                self._log_tts('tts.playback_stopped', '오디오 장치 정지', generation=generation,
                              reason='device_stopped')
            elif state == QAudio.State.SuspendedState:
                self._log_tts('tts.playback_suspended', '오디오 재생 일시 정지', generation=generation)
        self._set_speaking(
            not self._closed
            and self._enabled
            and state == QAudio.State.ActiveState
            and sink.error() == QAudio.Error.NoError
        )
        if state in (QAudio.State.IdleState, QAudio.State.StoppedState):
            self._set_busy(False)

    def _finish_request(self, generation):
        if generation == self._generation:
            self._set_busy(False)
        self._request_contexts.pop(generation, None)

    def _set_busy(self, busy):
        busy = bool(busy)
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _set_speaking(self, speaking: bool) -> None:
        speaking = bool(speaking)
        if speaking != self._speaking:
            self._speaking = speaking
            self.speaking_changed.emit(speaking)

    def _stop_playback(self, reason='stopped') -> None:
        # 참조를 먼저 해제해 stop 중 발생하는 옛 stateChanged도 무시한다.
        sink, self._audio_sink = self._audio_sink, None
        buffer, self._audio_buffer = self._audio_buffer, None
        self._set_speaking(False)
        if sink is not None:
            if self._speaking or self._last_audio_state is None or self._last_audio_state[1] != QAudio.State.IdleState:
                self._log_tts('tts.playback_stopped', '음성 재생 중단 요청',
                              generation=self._playback_generation, reason=reason)
            sink.stop()
            sink.deleteLater()
            self._request_contexts.pop(self._playback_generation, None)
        if buffer is not None:
            buffer.close()
            buffer.deleteLater()
        self._playback_generation = None

    def _log_tts(self, event, message, *, generation=None, context=None, level='INFO', **data):
        context = context if context is not None else self._request_contexts.get(
            self._generation if generation is None else generation, {})
        log_event(event, message, category='대화·AI', level=level,
                  trace_id=context.get('trace_id'), generation=generation, component='TTS', **data)

    def _cancel_request(self, generation, reason):
        if generation in self._request_contexts and self._busy:
            self._log_tts('tts.request_cancelled', '이전 음성 요청 취소',
                          generation=generation, reason=reason)
