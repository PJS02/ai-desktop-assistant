from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

try:
    import numpy as np
except ImportError as exc:
    np = None
    NUMPY_IMPORT_ERROR = exc
else:
    NUMPY_IMPORT_ERROR = None

try:
    import sounddevice as sd
except ImportError as exc:
    sd = None
    SOUNDDEVICE_IMPORT_ERROR = exc
else:
    SOUNDDEVICE_IMPORT_ERROR = None

try:
    import speech_recognition as sr
except ImportError as exc:
    sr = None
    SPEECH_RECOGNITION_IMPORT_ERROR = exc
else:
    SPEECH_RECOGNITION_IMPORT_ERROR = None


SAMPLE_RATE = 16_000
CHANNELS = 1

PROVIDER_OPTIONS = ("google",)
SILENCE_OPTIONS = ("0.6 sec", "0.8 sec", "1.0 sec", "1.2 sec")
SENSITIVITY_OPTIONS = ("high", "medium", "low")
LANGUAGE_OPTIONS = ("ko-KR", "en-US", "ja-JP", "zh-CN")
SILENCE_SECONDS_BY_LABEL = {
    "0.6 sec": 0.6,
    "0.8 sec": 0.8,
    "1.0 sec": 1.0,
    "1.2 sec": 1.2,
}
START_RMS_BY_SENSITIVITY = {
    "high": 0.008,
    "medium": 0.015,
    "low": 0.025,
}
PRE_ROLL_SECONDS = 0.25
MIN_UTTERANCE_SECONDS = 0.35


@dataclass
class AudioDevice:
    index: int | None
    label: str


class RealtimeSTT:
    def __init__(self, time_provider=time.monotonic):
        self.audio_devices: list[AudioDevice] = []
        self.audio_queue: queue.Queue = queue.Queue()
        self.ui_queue: queue.Queue[tuple[str, str | dict]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.stream = None
        self.is_running = False
        self._time_provider = time_provider
        self._capture_lock = threading.Lock()
        self._capture_generation = 0
        self._character_speaking = False
        self._suppressed_until = 0.0

        self.active_provider = "google"
        self.active_silence_label = "0.8 sec"
        self.active_sensitivity = "medium"
        self.active_mic_label = ""
        self.active_language = "ko-KR"
        self.active_timestamps = True
        self.recognizer = sr.Recognizer() if sr is not None else None

    @property
    def input_suppressed(self):
        return self._character_speaking or self._time_provider() < self._suppressed_until

    def set_character_speaking(self, speaking: bool):
        """Drop playback audio, buffered fragments and overlapping network results."""
        with self._capture_lock:
            speaking = bool(speaking)
            if speaking == self._character_speaking:
                return
            self._character_speaking = speaking
            self._suppressed_until = self._time_provider() + 0.8
            self._capture_generation += 1
            while True:
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

    def accepts_speech_event(self, value):
        return (not self.input_suppressed and isinstance(value, dict)
                and value.get('generation') == self._capture_generation)

    def dependency_error(self) -> str | None:
        missing = []
        if NUMPY_IMPORT_ERROR is not None:
            missing.append("numpy")
        if SOUNDDEVICE_IMPORT_ERROR is not None:
            missing.append("sounddevice")
        if SPEECH_RECOGNITION_IMPORT_ERROR is not None:
            missing.append("SpeechRecognition")
        if not missing:
            return None
        return "STT dependency missing: " + ", ".join(missing)

    def refresh_microphones(self) -> list[str]:
        dependency_error = self.dependency_error()
        if dependency_error is not None:
            raise RuntimeError(dependency_error)

        devices = sd.query_devices()
        self.audio_devices = []
        labels: list[str] = []
        for index, device in enumerate(devices):
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
            label = f"index {index} / {device['name']}"
            self.audio_devices.append(AudioDevice(index=index, label=label))
            labels.append(label)
        return labels

    def start(
        self,
        mic_label: str,
        provider: str,
        silence_label: str,
        sensitivity: str,
        language: str,
        timestamps: bool,
    ) -> None:
        if self.is_running:
            return

        dependency_error = self.dependency_error()
        if dependency_error is not None:
            raise RuntimeError(dependency_error)
        if not mic_label:
            raise RuntimeError("No microphone selected.")
        if provider != "google":
            raise RuntimeError(f"Unsupported STT provider: {provider}")

        self.active_mic_label = mic_label
        self.active_provider = provider
        self.active_silence_label = silence_label
        self.active_sensitivity = sensitivity
        self.active_language = language
        self.active_timestamps = timestamps

        self.stop_event.clear()
        self.audio_queue = queue.Queue()
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._run_stt, daemon=True)
        self.worker_thread.start()

    def stop(self) -> None:
        if not self.is_running:
            return
        self.stop_event.set()
        self._stop_stream()
        self.ui_queue.put(("status", "STT stopping..."))

    def drain_events(self) -> list[tuple[str, str | dict]]:
        events: list[tuple[str, str | dict]] = []
        while True:
            try:
                events.append(self.ui_queue.get_nowait())
            except queue.Empty:
                return events

    def _run_stt(self) -> None:
        try:
            self.ui_queue.put(("status", "STT recording with Google Web Speech"))
            self.ui_queue.put(("text", "\n[STT started]\n"))
            self._start_stream()

            pre_roll = deque()
            pre_roll_samples = 0
            pre_roll_limit = int(SAMPLE_RATE * PRE_ROLL_SECONDS)
            silence_limit = int(
                SAMPLE_RATE * SILENCE_SECONDS_BY_LABEL.get(
                    self.active_silence_label,
                    0.8,
                )
            )
            start_threshold = START_RMS_BY_SENSITIVITY.get(self.active_sensitivity, 0.015)
            end_threshold = start_threshold * 0.55
            min_utterance_samples = int(SAMPLE_RATE * MIN_UTTERANCE_SECONDS)

            in_speech = False
            speech_chunks = []
            speech_samples = 0
            silence_samples = 0
            audio_offset = 0.0
            utterance_start = 0.0
            buffer_generation = self._capture_generation

            while not self.stop_event.is_set():
                try:
                    generation, chunk = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if generation != self._capture_generation or self.input_suppressed:
                    continue
                if generation != buffer_generation:
                    # Playback may have begun while transcription blocked the
                    # worker. Never join its old fragment to a new user utterance.
                    pre_roll.clear()
                    pre_roll_samples = 0
                    in_speech = False
                    speech_chunks = []
                    speech_samples = silence_samples = 0
                    buffer_generation = generation

                chunk_start = audio_offset
                audio_offset += len(chunk) / SAMPLE_RATE
                chunk_rms = self._rms(chunk)

                if not in_speech:
                    if chunk_rms >= start_threshold:
                        in_speech = True
                        utterance_start = max(0.0, chunk_start - (pre_roll_samples / SAMPLE_RATE))
                        speech_chunks = list(pre_roll) + [chunk]
                        speech_samples = pre_roll_samples + len(chunk)
                        silence_samples = 0
                        pre_roll.clear()
                        pre_roll_samples = 0
                        self.ui_queue.put(("status", "STT speech detected"))
                    else:
                        pre_roll.append(chunk)
                        pre_roll_samples += len(chunk)
                        while pre_roll_samples > pre_roll_limit and pre_roll:
                            removed = pre_roll.popleft()
                            pre_roll_samples -= len(removed)
                    continue

                speech_chunks.append(chunk)
                speech_samples += len(chunk)
                if chunk_rms <= end_threshold:
                    silence_samples += len(chunk)
                else:
                    silence_samples = 0

                if silence_samples >= silence_limit:
                    audio = np.concatenate(speech_chunks)
                    if speech_samples >= min_utterance_samples:
                        self._transcribe_audio(audio, utterance_start, buffer_generation)
                    in_speech = False
                    speech_chunks = []
                    speech_samples = 0
                    silence_samples = 0
                    self.ui_queue.put(("status", "STT listening"))

            if (speech_chunks and speech_samples >= min_utterance_samples
                    and buffer_generation == self._capture_generation and not self.input_suppressed):
                audio = np.concatenate(speech_chunks)
                self._transcribe_audio(audio, utterance_start, buffer_generation)

        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))
        finally:
            self._stop_stream()
            self.is_running = False
            self.ui_queue.put(("status", "STT stopped"))
            self.ui_queue.put(("running", "false"))
            self.ui_queue.put(("text", "[STT stopped]\n"))

    def _start_stream(self) -> None:
        selected = self.active_mic_label
        device_index = next(
            (item.index for item in self.audio_devices if item.label == selected),
            None,
        )

        def callback(indata, frames, time_info, status) -> None:
            if status:
                self.ui_queue.put(("status", f"Audio warning: {status}"))
            with self._capture_lock:
                if self.input_suppressed:
                    return
                mono = indata[:, 0].astype(np.float32, copy=True)
                self.audio_queue.put((self._capture_generation, mono))

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            device=device_index,
            callback=callback,
        )
        self.stream.start()

    def _stop_stream(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self.stream = None

    def _transcribe_audio(self, audio, offset: float, generation=None) -> None:
        generation = self._capture_generation if generation is None else generation
        if audio.size == 0 or self.input_suppressed or generation != self._capture_generation:
            return

        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms < 0.003:
            self.ui_queue.put(("status", "STT silence detected"))
            return

        self.ui_queue.put(("status", "STT sending audio to Google Web Speech"))
        audio_data = self._to_audio_data(audio)
        try:
            text = self.recognizer.recognize_google(
                audio_data,
                language=self.active_language,
            ).strip()
        except sr.UnknownValueError:
            self.ui_queue.put(("status", "STT could not understand speech"))
            return
        except sr.RequestError as exc:
            self.ui_queue.put(("error", f"Google Web Speech request failed: {exc}"))
            return

        if not text:
            self.ui_queue.put(("status", "STT no speech"))
            return

        if self.active_timestamps:
            duration = len(audio) / SAMPLE_RATE
            line = f"[{offset:05.2f} - {offset + duration:05.2f}] {text}"
        else:
            line = text
        with self._capture_lock:
            if self.input_suppressed or generation != self._capture_generation:
                return
            self.ui_queue.put(("text", line + "\n"))
            self.ui_queue.put(("speech", {'text': text, 'generation': generation}))
            self.ui_queue.put(("status", "STT transcribed with Google Web Speech"))

    def _to_audio_data(self, audio):
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        return sr.AudioData(pcm.tobytes(), SAMPLE_RATE, 2)

    def _rms(self, audio) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio))))
