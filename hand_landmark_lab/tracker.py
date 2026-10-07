"""Camera -> normalized landmarks only. No dependency on the character app or Qt."""
from dataclasses import dataclass, replace
import itertools
import math
import os
import threading
import time


@dataclass(frozen=True)
class Hand:
    label: str
    points: tuple[tuple[float, float, float], ...]
    track_id: int = 0


@dataclass(frozen=True)
class Snapshot:
    hands: tuple[Hand, ...] = ()
    aspect: float = 4 / 3
    timestamp: float = 0.0
    fps: float = 0.0
    inference_ms: float = 0.0
    frames: int = 0
    status: str = "대기 중"
    error: str = ""


def palm(hand: Hand):
    return tuple(sum(hand.points[i][axis] for i in (0, 5, 9, 13, 17)) / 5 for axis in (0, 1))


@dataclass
class _Track:
    raw: Hand
    filtered: Hand
    seen: float
    updated: float
    pending: Hand | None = None
    accepted: float = 0.0


class HandSmoother:
    """Stable identities, brief dropout retention, spike rejection and adaptive filtering."""
    HOLD_SECONDS = 0.12

    def __init__(self):
        self.tracks = []
        self.next_id = 1
        self.new_candidate = None
        self.candidate_time = 0.0

    def reset(self):
        self.tracks.clear()
        self.new_candidate = None

    @staticmethod
    def size(hand: Hand) -> float:
        return max(math.dist(hand.points[0][:2], hand.points[9][:2]),
                   math.dist(hand.points[5][:2], hand.points[17][:2]), .03)

    @classmethod
    def duplicate(cls, first: Hand, second: Hand) -> bool:
        size = max(cls.size(first), cls.size(second))
        rms = math.sqrt(sum(math.dist(a[:2], b[:2]) ** 2 for a, b in
                            zip(first.points, second.points)) / 21)
        return cls.distance(first, second) < max(.018, size * .18) and rms < max(.025, size * .22)

    @staticmethod
    def shape_distance(first: Hand, second: Hand) -> float:
        a, b = palm(first), palm(second)
        return max(math.hypot((p[0] - a[0]) - (q[0] - b[0]),
                              (p[1] - a[1]) - (q[1] - b[1]))
                   for p, q in zip(first.points, second.points))

    def apply(self, hands: tuple[Hand, ...], timestamp: float | None = None,
              enabled: bool = True) -> tuple[Hand, ...]:
        now = time.monotonic() if timestamp is None else timestamp
        unique = []
        for hand in hands:
            if not any(self.duplicate(hand, other) for other in unique):
                unique.append(hand)
        hands = tuple(unique)
        if not enabled:
            self.reset()
            return hands
        self.tracks = [track for track in self.tracks if now - track.seen <= self.HOLD_SECONDS]
        available = list(range(len(self.tracks)))
        # Global nearest assignment for the two hands. A transient left/right label flip
        # must not discard a good history or move a window to the other hand.
        pairs = []
        if hands and available:
            count = min(len(hands), len(available))
            choices = ((sum(self.distance(self.tracks[t].raw, hands[h])
                           + (0.025 if self.tracks[t].raw.label != hands[h].label else 0)
                           for h, t in zip(h_indices, t_indices)), tuple(zip(h_indices, t_indices)))
                       for h_indices in itertools.permutations(range(len(hands)), count)
                       for t_indices in itertools.permutations(available, count))
            _, pairs = min(choices, key=lambda choice: choice[0])
        assigned = {h: t for h, t in pairs}
        candidate_seen = False
        for index, hand in enumerate(hands):
            if index not in assigned:
                if self.tracks:
                    candidate_seen = True
                    confirmed = self.new_candidate is not None and now - self.candidate_time <= .2 and (
                        self.distance(self.new_candidate, hand) < .08
                        and self.shape_distance(self.new_candidate, hand) < .065)
                    if not confirmed:
                        self.new_candidate, self.candidate_time = hand, now
                        continue
                self.new_candidate = None
                identified = Hand(hand.label, hand.points, self.next_id)
                self.next_id += 1
                self.tracks.append(_Track(identified, identified, now, now, accepted=now))
                continue
            track = self.tracks[assigned[index]]
            track.seen = now
            hand = Hand(track.filtered.label, hand.points, track.filtered.track_id)
            jump = self.distance(track.raw, hand)
            shape_jump = self.shape_distance(track.raw, hand)
            shape_limit = max(.045, self.size(track.raw) * .75)
            if jump > 0.16 or shape_jump > shape_limit:
                confirmed = track.pending is not None and (
                    (self.distance(track.pending, hand) < 0.12
                     and self.shape_distance(track.pending, hand) < max(.02, self.size(hand) * .25))
                    or (jump > .16 and shape_jump <= shape_limit
                        and self.same_direction(track.raw, track.pending, hand)))
                if not confirmed:
                    track.pending = hand
                    track.updated = now
                    continue
            track.pending = None
            dt = min(0.1, max(0.001, now - track.updated))
            old_center, new_center = palm(track.filtered), palm(hand)
            residual = math.dist(old_center, new_center)
            # Slow noise gets stronger filtering; intentional movement catches up faster.
            motion = min(1.0, max(0.0, (residual - 0.008) / 0.05))
            position_gain = 1 - math.exp(-dt / (0.11 - 0.08 * motion))
            shape_gain = 1 - math.exp(-dt / 0.055)
            center = tuple(a + position_gain * (b - a) for a, b in zip(old_center, new_center))
            points = []
            for previous, current in zip(track.filtered.points, hand.points):
                xy = tuple(center[i] + (previous[i] - old_center[i]) + shape_gain * (
                           (current[i] - new_center[i]) - (previous[i] - old_center[i])) for i in (0, 1))
                points.append((*xy, previous[2] + shape_gain * (current[2] - previous[2])))
            track.raw = hand
            track.filtered = Hand(hand.label, tuple(points), hand.track_id)
            track.updated = now
            track.accepted = now
        if not candidate_seen:
            self.new_candidate = None
        live = [track for track in self.tracks if track.seen == now]
        # When an overlapping track disappears but a live hand still occupies that
        # location, do not retain an extra ghost merely for the dropout grace period.
        self.tracks = [track for track in self.tracks if track.seen == now or not any(
            self.distance(track.filtered, current.filtered) < max(self.size(track.filtered),
                                                                  self.size(current.filtered)) * .8
            for current in live)]
        return tuple(track.filtered for track in self.tracks if now - track.accepted <= .18)

    @staticmethod
    def distance(a: Hand, b: Hand) -> float:
        return math.dist(palm(a), palm(b))

    @staticmethod
    def same_direction(origin: Hand, first: Hand, second: Hand) -> bool:
        a, b, c = palm(origin), palm(first), palm(second)
        u, v = tuple(y - x for x, y in zip(a, b)), tuple(y - x for x, y in zip(a, c))
        length = math.hypot(*u) * math.hypot(*v)
        return length > 0 and sum(x * y for x, y in zip(u, v)) / length > 0.85


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
