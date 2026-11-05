"""Screen-space hand interactions; no camera, inference, or Qt event synthesis."""
from dataclasses import dataclass
import math


def distance(a, b):
    return math.dist(a, b)


def midpoint(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b))


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self):
        return self.x + self.width / 2, self.y + self.height / 2

    @property
    def bottom(self):
        return self.y + self.height

    def contains(self, point, margin=0):
        return (self.x - margin <= point[0] <= self.x + self.width + margin
                and self.y - margin <= point[1] <= self.bottom + margin)


@dataclass(frozen=True)
class DisplayedHand:
    track_id: int
    points: tuple  # The actual interpolated desktop positions, in logical pixels.
    landmarks: tuple  # Normalized 3D coordinates, for scale-independent gestures.

    @property
    def pinch_ratio(self):
        p = self.landmarks
        size = max(distance(p[5], p[17]), distance(p[0], p[9]), .001)
        return distance(p[4], p[8]) / size

    @property
    def pinch_point(self):
        return midpoint(self.points[4], self.points[8])

    @property
    def extended(self):
        p = self.landmarks
        return tuple(distance(p[tip], p[0]) > distance(p[pip], p[0]) * 1.12
                     for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20)))

    def _bend(self, a, b, c):
        p = self.landmarks
        first = tuple(y-x for x,y in zip(p[a], p[b]))
        second = tuple(y-x for x,y in zip(p[b], p[c]))
        length = math.sqrt(sum(x*x for x in first) * sum(x*x for x in second))
        if length < 1e-10:
            return 0.
        return math.acos(max(-1., min(1., sum(x*y for x,y in zip(first,second)) / length)))

    def finger_bend(self, base):
        return max(self._bend(base,base+1,base+2), self._bend(base+1,base+2,base+3))

    @property
    def thumb_open(self):
        p = self.landmarks
        size = max(distance(p[5], p[17]), distance(p[0], p[9]), .001)
        return (distance(p[4], p[17]) > distance(p[2], p[17]) * 1.10
                and distance(p[4], p[5]) > size * .35)

    @property
    def head_grasp(self):
        # Both thumb and index bend a little; a fully clenched fist or an open
        # hand is a different gesture. Joint angles are independent of rotation.
        return (not self.all_open and .20 <= self.finger_bend(1) <= 2.45
                and .25 <= self.finger_bend(5) <= 2.45)

    @property
    def pointing(self):
        return (self.extended[0] and self.finger_bend(5) < .45
                and not self.thumb_open and self.finger_bend(1) >= .65
                and all(not self.extended[i] and self.finger_bend(base) >= .65
                        for i,base in ((1,9),(2,13),(3,17))))

    @property
    def all_open(self):
        return all(self.extended) and self.thumb_open and self.pinch_ratio > .55

    @property
    def fingertips(self):
        return tuple(self.points[i] for i in (4, 8, 12, 16, 20))

    @property
    def grip_point(self):
        return self.pinch_point

    @property
    def support_span(self):
        points = tuple(self.points[i] for i in (0, 5, 9, 13, 17, 8, 12, 16, 20))
        return min(p[0] for p in points), max(p[0] for p in points)

    @property
    def palm(self):
        left, right = self.support_span
        top = min(self.points[i][1] for i in (0, 5, 9, 13, 17, 8, 12, 16, 20))
        return (left + right) / 2, top - 6

    @property
    def supports(self):
        wrist, knuckle = self.points[0], self.points[9]
        dx, dy = abs(knuckle[0] - wrist[0]), abs(knuckle[1] - wrist[1])
        return self.all_open and dx >= 8 and dx >= dy * 1.5


class HandInteractionEngine:
    """One held target, stable acquisition, release hysteresis and short dropouts.

    Actions are supplied by the character host. Only displayed hands may act;
    source tokens prevent frozen packets from starting new contacts.
    """
    HOLD_GRACE_SECONDS = .75
    OPEN_SECONDS = .18
    OPEN_SAMPLES = 4

    def __init__(self, actions):
        self.actions = actions
        self.active = None
        self._pinched = {}
        self._last = {}
        self._candidate = None
        self._candidate_at = 0.
        self._candidate_samples = 0
        self._missing_at = None
        self._blocked_until = 0.
        self._token = None
        self._pets = {}
        self._poke_latched = set()
        self._poke_at = -math.inf
        self._poke_candidates = {}
        self._open_at = None
        self._open_samples = 0
        self._held_hand = None
        self._last_seen_at = None
        self._other_ids = set()
        self._rebind = None

    def reset(self, reason='tracking_lost', now=0.):
        if self.active:
            self.actions.end_hold(reason, (0., 0.))
        self.active = None
        self._candidate = None
        self._missing_at = None
        self._pets.clear()
        self._last.clear()
        self._pinched.clear()
        self._poke_candidates.clear()
        self._poke_latched.clear()
        self._token = None
        self._open_at = None
        self._open_samples = 0
        self._held_hand = None
        self._last_seen_at = None
        self._other_ids.clear()
        self._rebind = None
        self._blocked_until = now + .35

    def _release(self, now, reason, velocity=(0., 0.)):
        self.actions.end_hold(reason, velocity)
        self.active = None
        self._candidate = None
        self._missing_at = None
        self._open_at = None
        self._open_samples = 0
        self._held_hand = None
        self._last_seen_at = None
        self._other_ids.clear()
        self._rebind = None
        self._blocked_until = now + .35

    def interrupt_tracking(self, now):
        """A stale drawing is hidden, but a short gap need not drop its target."""
        if self.active and self._missing_at is None:
            self._missing_at = self._last_seen_at if self._last_seen_at is not None else now
        self._open_at = None
        self._open_samples = 0

    @staticmethod
    def _anchor(hand):
        return tuple(sum(hand.points[i][axis] for i in (0, 5, 9, 13, 17)) / 5
                     for axis in (0, 1))

    @staticmethod
    def _size(hand):
        return max(distance(hand.points[0], hand.points[9]),
                   distance(hand.points[5], hand.points[17]), 8.)

    def _near_held_hand(self, hand):
        old = self._held_hand
        if old is None:
            return False
        ratio = self._size(hand) / self._size(old)
        return (.45 <= ratio <= 2.2 and distance(self._anchor(hand), self._anchor(old))
                <= max(90., self._size(old) * 2.))

    def _find_reappeared_hand(self, hands, now, fresh):
        # A hand already visible alongside the held hand cannot take its place.
        candidates = [h for h in hands if h.track_id not in self._other_ids
                      and self._near_held_hand(h)]
        if not candidates or not fresh:
            return None
        best = min(candidates, key=lambda h: distance(self._anchor(h), self._anchor(self._held_hand)))
        previous = self._rebind
        if (previous is None or previous[0] != best.track_id or now - previous[1] > .2
                or distance(previous[2], self._anchor(best)) > max(40., self._size(best))):
            self._rebind = best.track_id, now, self._anchor(best)
            return None
        self._rebind = None
        return best

    def update(self, hands, now, source_token):
        if not self.actions.available():
            self.reset('character_busy', now)
            return
        fresh = source_token != self._token
        self._token = source_token
        present = {hand.track_id for hand in hands}
        self._pinched = {key: value for key, value in self._pinched.items() if key in present}
        self._pets = {key: value for key, value in self._pets.items() if key in present}
        self._poke_latched.intersection_update(present)
        self._poke_candidates = {k: v for k, v in self._poke_candidates.items() if k in present}
        release_velocities = {}
        for hand in hands:
            previous = self._last.get(hand.track_id)
            release_velocities[hand.track_id] = (previous[2] if previous and now - previous[0] <= .12
                                                 else (0., 0.))
            velocity = (0., 0.)
            if previous and fresh:
                dt = now - previous[0]
                if .005 <= dt <= .2:
                    raw = tuple((a - b) / dt for a, b in zip(hand.pinch_point, previous[1]))
                    velocity = tuple(previous[2][i] * .5 + raw[i] * .5 for i in (0, 1))
            elif previous:
                velocity = previous[2]
            if fresh:
                self._last[hand.track_id] = now, hand.pinch_point, velocity
            was = self._pinched.get(hand.track_id, False)
            self._pinched[hand.track_id] = hand.pinch_ratio < (.40 if was else .25)
        self._last = {k: v for k, v in self._last.items() if k in present}

        if self.active:
            mode, identity = self.active
            if not self.actions.hold_valid(mode):
                self._release(now, 'target_changed')
                return
            if (self._missing_at is not None
                    and now - self._missing_at >= self.HOLD_GRACE_SECONDS):
                self._release(now, 'tracking_lost')
                return
            hand = next((h for h in hands if h.track_id == identity), None)
            if hand is not None and self._missing_at is not None and not self._near_held_hand(hand):
                hand = None
            if hand is None:
                self._candidate = None
                self._open_at = None
                self._open_samples = 0
                if self._missing_at is None:
                    self._missing_at = self._last_seen_at if self._last_seen_at is not None else now
                if now - self._missing_at >= self.HOLD_GRACE_SECONDS:
                    self._release(now, 'tracking_lost')
                    return
                hand = self._find_reappeared_hand(hands, now, fresh)
                if hand is None:
                    return
                identity = hand.track_id
                self.active = mode, identity
                # No throw speed may be carried across an identity interruption.
                release_velocities[identity] = (0., 0.)
                self._last.pop(identity, None)
            self._missing_at = None
            self._rebind = None
            self._held_hand = hand
            if fresh:
                self._last_seen_at = now
            self._other_ids.update(h.track_id for h in hands if h.track_id != identity)
            if mode == 'palm' and not hand.supports:
                self._release(now, 'palm_closed')
            else:
                if mode != 'palm' and hand.all_open:
                    if self._open_at is None:
                        self._open_at = now
                        self._open_samples = 0
                        self._release_velocity = release_velocities[identity]
                    self._open_samples += int(fresh)
                    if (now - self._open_at >= self.OPEN_SECONDS
                            and self._open_samples >= self.OPEN_SAMPLES):
                        self._release(now, 'released', self._release_velocity)
                    return
                self._open_at = None
                self._open_samples = 0
                point = (hand.palm if mode == 'palm' else
                         hand.grip_point if mode == 'grab' else hand.pinch_point)
                self.actions.move_hold(mode, point)
            return

        body = self.actions.body_rect()
        candidate = None
        if now >= self._blocked_until:
            ball = self.actions.ball_rect()
            for hand in hands:
                point = hand.pinch_point
                if self._pinched[hand.track_id]:
                    if ball and ball.contains(point, 9):
                        candidate = 'ball', hand.track_id, point
                        break
                head = Box(body.x, body.y, body.width, body.height * .40)
                if (hand.head_grasp and head.contains(hand.points[4], 4)
                        and head.contains(hand.points[8], 4)):
                    candidate = 'grab', hand.track_id, hand.grip_point
                    break
                if hand.supports:
                    px, py = hand.palm
                    left, right = hand.support_span
                    span = (right - left) / 2 + 8
                    if (abs(body.center[0] - px) <= span
                            and -max(14., body.height * .30) <= py - body.bottom <= 35):
                        candidate = 'palm', hand.track_id, hand.palm
                        break
        key = candidate[:2] if candidate else None
        if key != self._candidate:
            self._candidate, self._candidate_at = key, now
            self._candidate_samples = int(fresh)
        elif fresh:
            self._candidate_samples += 1
        if candidate:
            dwell = .18 if candidate[0] == 'palm' else .12
            if now - self._candidate_at >= dwell and self._candidate_samples >= 2:
                if self.actions.begin_hold(candidate[0], candidate[2]):
                    self.active = candidate[:2]
                    self._held_hand = next(h for h in hands if h.track_id == candidate[1])
                    self._last_seen_at = now
                    self._other_ids = {h.track_id for h in hands if h.track_id != candidate[1]}
                    self._rebind = None
                    self._pets.clear()
                    return
        if fresh:
            for hand in hands:
                if key is None:
                    self._touch(hand, body, now)

    def _touch(self, hand, body, now):
        tip = hand.points[8]
        head = Box(body.x, body.y + body.height * .04, body.width, body.height * .23)
        cheek = Box(body.x + body.width * .12, body.y + body.height * .27,
                    body.width * .76, body.height * .14)
        # Stay out of the middle of the face; cheek contact uses a pointed index.
        on_cheek = (cheek.contains(tip) and abs(tip[0] - body.center[0]) > body.width * .12
                    and hand.extended[0])
        identity = hand.track_id
        if on_cheek:
            entered = self._poke_candidates.setdefault(identity, now)
            if (identity not in self._poke_latched and now - entered >= .07
                    and now - self._poke_at >= 1.):
                self.actions.poke(tip)
                self._poke_latched.add(identity)
                self._poke_at = now
        else:
            self._poke_candidates.pop(identity, None)
            self._poke_latched.discard(identity)
        contact = tip if hand.pointing and head.contains(tip) else None
        if contact is None:
            self._pets.pop(identity, None)
            return
        previous = self._pets.get(identity)
        if previous is None:
            self._pets[identity] = now, now, contact, 0., None
            return
        started, last_time, last_point, traveled, feedback_at = previous
        dt = now - last_time
        movement = distance(contact, last_point)
        if dt <= 0 or dt > .2 or movement / dt > 650:
            self._pets.pop(identity, None)
            return
        traveled += movement
        elapsed = now - (feedback_at if feedback_at is not None else started)
        if ((feedback_at is None and now - started >= .08)
                or (feedback_at is not None and elapsed >= .15 and traveled >= 3)):
            self.actions.pet(traveled / max(elapsed, .001), min(elapsed, .2), contact)
            feedback_at, traveled = now, 0.
        self._pets[identity] = started, now, contact, traveled, feedback_at
