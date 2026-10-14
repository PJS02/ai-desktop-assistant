"""Camera -> normalized landmarks only. No dependency on the character app or Qt."""
from dataclasses import replace
import os
import threading
import time
from pathlib import Path
import sys

# Keep direct execution of the lab working without installing the project.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from hand_overlay.model import Hand, Snapshot, HandSmoother, palm


class HandTracker:
    """Single-slot mailbox: a slow renderer never queues old camera frames."""
    def __init__(self, camera: int = 0, mirror: bool = True, smooth: bool = True, backend: str = "auto",
                 max_hands: int = 1):
        self.camera = camera
        self.backend = backend
        self.max_hands = max_hands
        self._mirror = mirror
        self._smooth = smooth
        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._stop = threading.Event()
        self._thread = None

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def configure(self, mirror: bool, smooth: bool):
        with self._lock:
            self._mirror, self._smooth = mirror, smooth

    def publish(self, snapshot: Snapshot):
        with self._lock:
            self._snapshot = snapshot

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running():
            return
        self._stop.clear()
        self.publish(Snapshot(status="카메라 연결 중…"))
        self._thread = threading.Thread(target=self._run, name="hand-landmark-camera", daemon=True)
        self._thread.start()

    def stop(self):
        # Camera/model resources belong to the worker; never release during read/process.
        self._stop.set()

    def join(self, timeout: float = 2.0):
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        capture = None
        detector = None
        try:
            import cv2
            import mediapipe as mp

            # Use the API/model already bundled with this project's MediaPipe 0.10.9.
            if not hasattr(mp, "solutions"):
                raise RuntimeError("이 테스트는 mediapipe==0.10.9 환경이 필요합니다. README를 확인하세요.")
            if os.name == "nt":
                # Webcam indices can differ by backend. The project's saved camera uses MSMF.
                backends = {"auto": (cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY),
                            "msmf": (cv2.CAP_MSMF,), "dshow": (cv2.CAP_DSHOW,),
                            "any": (cv2.CAP_ANY,)}[self.backend]
            else:
                backends = (cv2.CAP_ANY,)
            frame = None
            for backend in backends:
                if self._stop.is_set():
                    return
                capture = cv2.VideoCapture(self.camera, backend)
                if capture.isOpened():
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    capture.set(cv2.CAP_PROP_FPS, 30)
                    ok, frame = capture.read()
                    if ok and frame is not None:
                        break
                capture.release()
                capture = None
            if capture is None:
                raise RuntimeError(f"카메라 {self.camera} 연결 실패. 다른 앱의 카메라 사용과 Windows 카메라 권한을 확인하세요.")

            detector = mp.solutions.hands.Hands(
                static_image_mode=False, max_num_hands=self.max_hands, model_complexity=1,
                min_detection_confidence=0.6, min_tracking_confidence=0.6,
            )
            smoother = HandSmoother()
            previous_settings = None
            count, bucket_count = 0, 0
            bucket_start = time.monotonic()
            fps = 0.0
            while not self._stop.is_set():
                started = time.monotonic()
                with self._lock:
                    mirror, smooth = self._mirror, self._smooth
                if previous_settings != (mirror, smooth):
                    smoother.reset()
                    previous_settings = (mirror, smooth)
                image = cv2.flip(frame, 1) if mirror else frame
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                inference_start = time.monotonic()
                result = detector.process(rgb)
                inference_ms = (time.monotonic() - inference_start) * 1000
                hands = []
                for landmarks, handedness in zip(result.multi_hand_landmarks or (),
                                                result.multi_handedness or ()):
                    label = handedness.classification[0].label
                    # MediaPipe assumes a mirrored selfie input for left/right labels.
                    if not mirror:
                        label = "Left" if label == "Right" else "Right"
                    hands.append(Hand(label, tuple((p.x, p.y, p.z) for p in landmarks.landmark)))
                filtered = smoother.apply(tuple(hands), timestamp=time.monotonic(), enabled=smooth)
                count += 1
                bucket_count += 1
                now = time.monotonic()
                if now - bucket_start >= 0.75:
                    fps = bucket_count / (now - bucket_start)
                    bucket_count, bucket_start = 0, now
                self.publish(Snapshot(filtered, frame.shape[1] / frame.shape[0], now,
                                      fps, inference_ms, count,
                                      "손 인식 중" if filtered else "손을 카메라에 보여주세요"))
                self._stop.wait(max(0, 1 / 30 - (time.monotonic() - started)))
                if self._stop.is_set():
                    break
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise RuntimeError("카메라 프레임을 읽지 못했습니다. 연결을 확인하고 다시 시작하세요.")
        except Exception as exc:
            self.publish(replace(self.snapshot(), hands=(), status="오류", error=str(exc)))
        finally:
            try:
                if detector is not None:
                    detector.close()
            finally:
                if capture is not None:
                    capture.release()
            last = self.snapshot()
            if not last.error:
                self.publish(replace(last, hands=(), status="카메라 중지됨"))


def demo_snapshot() -> Snapshot:
    """Synthetic open palm, exclusively for camera-free rendering checks."""
    points = (
        (.51, .84, 0), (.40, .73, 0), (.32, .64, 0), (.26, .53, 0), (.21, .43, 0),
        (.40, .53, 0), (.38, .36, 0), (.37, .24, 0), (.36, .13, 0),
        (.50, .50, 0), (.50, .31, 0), (.50, .18, 0), (.50, .07, 0),
        (.60, .53, 0), (.62, .36, 0), (.63, .24, 0), (.64, .15, 0),
        (.69, .59, 0), (.73, .47, 0), (.76, .39, 0), (.79, .32, 0),
    )
    return Snapshot((Hand("Right", points),), timestamp=time.monotonic(), status="데모 · 실제 카메라 인식 아님")
