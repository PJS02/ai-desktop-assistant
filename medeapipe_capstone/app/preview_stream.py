"""Opt-in, bounded preview delivery; camera images are never written to logs."""
import base64
import threading
import time

import cv2
from app_logging import write_protocol


class PreviewPublisher:
    INTERVAL = .2
    WIDTH = 640

    def __init__(self, publish=None):
        self._publish = publish or (lambda packet: write_protocol('APP_PREVIEW', packet))
        self._condition = threading.Condition()
        self._enabled = self._closed = False
        self._pending = None
        self._last = 0.
        self._thread = None

    def set_enabled(self, enabled):
        with self._condition:
            self._enabled = bool(enabled) and not self._closed
            self._pending = None
            self._last = 0.
            if self._enabled and self._thread is None:
                self._thread = threading.Thread(target=self._run, name='recognition-preview', daemon=True)
                self._thread.start()
            self._condition.notify_all()

    def ready(self):
        with self._condition:
            return self._enabled and not self._closed and time.monotonic() - self._last >= self.INTERVAL

    def offer(self, image, state):
        if not self.ready():
            return
        height, width = image.shape[:2]
        if width > self.WIDTH:
            image = cv2.resize(image, (self.WIDTH, round(height * self.WIDTH / width)), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok or encoded.nbytes > 200_000:
            return
        packet = {'jpeg': base64.b64encode(encoded).decode('ascii'), 'state': state}
        with self._condition:
            if self._enabled and not self._closed:
                self._last = time.monotonic()
                self._pending = packet
                self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(1)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                packet, self._pending = self._pending, None
                if not self._enabled:
                    continue
            self._publish(packet)
