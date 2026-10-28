"""Aggregate inference timings without writing per-frame logs or camera images."""
import time

from app_logging import log_event


class RecognitionPerformance:
    def __init__(self, interval=10.0):
        self.interval = interval
        self.started = time.perf_counter()
        self.frames = 0
        self.totals = [0.0, 0.0, 0.0]

    def record(self, holistic_ms, emotion_ms, postprocess_ms, *, preview_visible,
               camera, hands):
        self.frames += 1
        for index, value in enumerate((holistic_ms, emotion_ms, postprocess_ms)):
            self.totals[index] += value
        now = time.perf_counter()
        elapsed = now - self.started
        if elapsed < self.interval:
            return
        log_event('recognition.performance', '인식 처리 성능 요약', category='사용자 인식',
                  interval_seconds=round(elapsed, 2), processed_frames=self.frames,
                  recognition_fps=round(self.frames / elapsed, 2),
                  holistic_ms=round(self.totals[0] / self.frames, 2),
                  emotion_ms=round(self.totals[1] / self.frames, 2),
                  postprocess_ms=round(self.totals[2] / self.frames, 2),
                  preview_visible=preview_visible,
                  camera=camera.metrics(), hands=hands.metrics() if hands else None)
        self.started = now
        self.frames = 0
        self.totals = [0.0, 0.0, 0.0]
