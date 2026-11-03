"""One camera reader and independent consumers of its newest frame.

The capture belongs to the reader after start(). Consumers must copy an image
before drawing on it; no consumer can build up a queue of old camera frames.
"""
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class CameraFrame:
    image: object
    captured_at: float
    sequence: int


class LatestCameraStream:
    def __init__(self, capture, first_frame):
        self._capture = capture
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._latest = CameraFrame(first_frame, time.time(), 1)
        self._error = None
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name='shared-camera', daemon=True)

    @property
    def error(self):
        with self._condition:
            return self._error

    def start(self):
        self._thread.start()

    def latest(self, after_sequence=0, timeout=0):
        with self._condition:
            self._condition.wait_for(
                lambda: self._latest.sequence > after_sequence or self._stop.is_set(),
                timeout=timeout,
            )
            if self._stop.is_set() or self._latest.sequence <= after_sequence:
                return None
            return self._latest

    def metrics(self):
        with self._condition:
            elapsed = max(time.monotonic() - self._started_at, .001)
            return {'frames': self._latest.sequence, 'fps': (self._latest.sequence - 1) / elapsed,
                    'error': self._error}

    def stop(self):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()

    def join(self, timeout=2):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        try:
            while not self._stop.is_set():
                ok, image = self._capture.read()
                if not ok or image is None:
                    raise RuntimeError('Camera frame read failed')
                captured_at = time.time()
                with self._condition:
                    if self._stop.is_set():
                        break
                    self._latest = CameraFrame(image, captured_at, self._latest.sequence + 1)
                    self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                self._error = str(exc)
        finally:
            # Never release from the UI while read() is still using the capture.
            try:
                self._capture.release()
            finally:
                self.stop()
