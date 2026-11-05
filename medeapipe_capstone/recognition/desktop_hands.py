"""Low-latency desktop hands, independent of Holistic and the Tk event loop."""
import threading
import time
import uuid

import cv2

from app_logging import log_event


def create_detector():
    import mediapipe as mp

    return mp.solutions.hands.Hands(
        static_image_mode=False, max_num_hands=2, model_complexity=1,
        min_detection_confidence=.6, min_tracking_confidence=.6,
    )


class DesktopHandTracker:
    MAX_FRAME_AGE = .30
    MAX_INPUT_WIDTH = 640

    def __init__(self, camera, publish, *, detector_factory=create_detector):
        self.camera = camera
        self._publish = publish
        self._detector_factory = detector_factory
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._enabled = False
        self._mirror = False
        self._session = uuid.uuid4().hex
        self._sequence = 0
        self._size = (1, 1)
        self._frames = self._hand_frames = 0
        self._inference_ms = 0.
        self._error = None
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name='desktop-hands', daemon=True)

    def start(self):
        self._thread.start()

    def configure(self, enabled, mirror):
        # Only plain values cross this boundary: Tk variables stay on the UI thread.
        with self._lock:
            if self._stop.is_set() or (self._enabled, self._mirror) == (enabled, mirror):
                return
            self._send_locked([], time.time(), clear=True)
            self._enabled, self._mirror = bool(enabled), bool(mirror)
            self._session = uuid.uuid4().hex
            self._sequence = 0
            self._error = None
            self._wake.set()

    def stop(self):
        with self._lock:
            self._stop.set()
            self._enabled = False
            self._send_locked([], time.time(), clear=True)
            self._wake.set()

    def join(self, timeout=2):
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def metrics(self):
        with self._lock:
            elapsed = max(time.monotonic() - self._started_at, .001)
            return {'frames': self._frames, 'hand_frames': self._hand_frames,
                    'fps': self._frames / elapsed, 'inference_ms': self._inference_ms,
                    'error': self._error}

    def _send_locked(self, hands, captured_at, *, clear=False):
        self._sequence += 1
        width, height = self._size
        packet = {'type': 'hand_landmarks', 'version': 1, 'session_id': self._session,
                  'sequence': self._sequence, 'captured_at': captured_at,
                  'image_size': {'width': width, 'height': height},
                  'mirror': self._mirror, 'hands': hands}
        if clear:
            packet['clear'] = True
        self._publish(packet)

    @staticmethod
    def _hands(results, mirror):
        hands = []
        for landmarks, handedness in zip(results.multi_hand_landmarks or (),
                                        results.multi_handedness or ()):
            label = handedness.classification[0].label
            # Hands assumes mirrored selfie input for anatomical left/right labels.
            if not mirror:
                label = 'Left' if label == 'Right' else 'Right'
            hands.append({'label': label,
                          'points': [[p.x, p.y, p.z] for p in landmarks.landmark]})
        return hands

    def _run(self):
        detector = None
        detector_session = None
        failed_session = None
        last_sequence = 0
        try:
            while not self._stop.is_set():
                with self._lock:
                    enabled, mirror, session = self._enabled, self._mirror, self._session
                    self._wake.clear()
                if detector is not None and (not enabled or session != detector_session
                                             or session == failed_session):
                    detector.close()
                    detector = None
                if not enabled or session == failed_session:
                    self._wake.wait(.1)
                    continue
                frame = self.camera.latest(last_sequence, timeout=.05)
                if frame is None:
                    if self.camera.error:
                        with self._lock:
                            self._send_locked([], time.time(), clear=True)
                        break
                    continue
                with self._lock:
                    # A setting may change while waiting for the camera. Let the
                    # new session consume this frame instead of losing its first pose.
                    if self._stop.is_set() or not self._enabled or session != self._session:
                        continue
                last_sequence = frame.sequence
                if time.time() - frame.captured_at > self.MAX_FRAME_AGE:
                    continue
                try:
                    if detector is None:
                        log_event('hand_overlay.model.loading', '손 추적 모델 불러오기 시작', category='사용자 인식')
                        detector = self._detector_factory()
                        detector_session = session
                        log_event('hand_overlay.model.ready', '손 추적 모델 준비 완료', category='사용자 인식')
                    image = frame.image
                    height, width = image.shape[:2]
                    if width > self.MAX_INPUT_WIDTH:
                        image = cv2.resize(image, (self.MAX_INPUT_WIDTH,
                                           max(1, round(height * self.MAX_INPUT_WIDTH / width))),
                                           interpolation=cv2.INTER_AREA)
                    if mirror:
                        image = cv2.flip(image, 1)
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    rgb.flags.writeable = False
                    started = time.monotonic()
                    result = detector.process(rgb)
                    inference_ms = (time.monotonic() - started) * 1000
                    hands = self._hands(result, mirror)
                    with self._lock:
                        if (self._stop.is_set() or not self._enabled or self._session != session
                                or time.time() - frame.captured_at > self.MAX_FRAME_AGE):
                            continue
                        self._size = (width, height)
                        self._frames += 1
                        self._hand_frames += bool(hands)
                        self._inference_ms = inference_ms
                        self._send_locked(hands, frame.captured_at)
                except Exception as exc:
                    failed_session = session
                    with self._lock:
                        if self._session == session:
                            self._error = str(exc)
                            self._send_locked([], time.time(), clear=True)
                    log_event('hand_overlay.tracking.failed', '바탕화면 손 추적 실패',
                              category='오류', level='ERROR', error=str(exc))
        finally:
            if detector is not None:
                detector.close()
