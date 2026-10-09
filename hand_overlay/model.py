"""Camera-independent landmark values and display-only stability filtering."""
from dataclasses import dataclass
import itertools
import math
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
