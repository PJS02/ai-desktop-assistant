"""Screen-space hand interactions; no camera, inference, or Qt event synthesis."""
from dataclasses import dataclass
import math


PET_HEAD_HEIGHT_RATIO = .40


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
    label: str | None = None

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
    def grasp_pose(self):
        # Both thumb and index bend a little; a fully clenched fist or an open
        # hand is a different gesture. Joint angles are independent of rotation.
        return (not self.all_open and not self.open_for_grab
                and .20 <= self.finger_bend(1) <= 2.45
                and .25 <= self.finger_bend(5) <= 2.45)

    @property
    def petting_tips(self):
        wrist, knuckle = self.points[0], self.points[9]
        dx, dy = knuckle[0] - wrist[0], knuckle[1] - wrist[1]
        if abs(dx) < 8 or abs(dx) < abs(dy):
            return ()
        length_sq = dx * dx + dy * dy
        tips = []
        for base in (5, 9, 13, 17):
            x, y = self.points[base + 3]
            bx, by = self.points[base]
            if dx * (x - bx) + dy * (y - by) >= length_sq * .18:
                tips.append((x, y))
        # One finger can be hidden or flexed in the edge-on camera view.
        if len(tips) < 3:
            return ()
        across = tuple(dx * y - dy * x for x, y in tips)
        # A sideways hand shows the fingertips close together in projection.
        if max(across) - min(across) > length_sq * .55:
            return ()
        return tuple(tips)

    @property
    def all_open(self):
        return all(self.extended) and self.thumb_open and self.pinch_ratio > .55

    @property
    def open_for_grab(self):
        # A relaxed open hand can keep the thumb and index close together.
        return (all(self.extended) and self.pinch_ratio >= .40
                and self.finger_bend(1) < .55 and self.finger_bend(5) < .45)

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
        # Either side can support the feet with a relaxed thumb or one bent finger.
        return sum(self.extended) >= 3 and dx >= 8 and dx >= dy * .8


class HandInteractionEngine:
    """One held target, stable acquisition, release hysteresis and short dropouts.

    Actions are supplied by the character host. Holds require fresh camera
    samples, while strokes follow the displayed motion between samples.
    """
    HOLD_GRACE_SECONDS = .75
    GRAB_GRACE_SECONDS = 1.25
    OPEN_SECONDS = .18
    GRAB_OPEN_SECONDS = .30
    OPEN_SAMPLES = 4
    SWING_SPEED = 1050.  # Logical screen pixels per second.

    def __init__(self, actions):
        self.actions = actions
        self.active = None
        self._pinched = {}
        self._ball_grips = {}
        self._last = {}
        self._candidate = None
        self._candidate_at = 0.
        self._candidate_seen_at = 0.
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
        self._swing_sample = None

    def reset(self, reason='tracking_lost', now=0.):
        if self.active:
            self.actions.end_hold(reason, (0., 0.))
        self.active = None
        self._candidate = None
        self._missing_at = None
        self._pets.clear()
        self._last.clear()
        self._pinched.clear()
        self._ball_grips.clear()
        self._poke_candidates.clear()
        self._poke_latched.clear()
        self._token = None
        self._open_at = None
        self._open_samples = 0
        self._held_hand = None
        self._last_seen_at = None
        self._other_ids.clear()
        self._rebind = None
        self._swing_sample = None
        self._blocked_until = now + .35

    def _release(self, now, reason, velocity=(0., 0.)):
        self.actions.end_hold(reason, velocity)
        self.active = None
        self._ball_grips.clear()
        self._candidate = None
        self._missing_at = None
        self._open_at = None
        self._open_samples = 0
        self._held_hand = None
        self._last_seen_at = None
        self._other_ids.clear()
        self._rebind = None
        self._swing_sample = None
        self._blocked_until = now + .35

    def interrupt_tracking(self, now):
        """A stale drawing is hidden, but a short gap need not drop its target."""
        if self.active and self._missing_at is None:
            self._missing_at = self._last_seen_at if self._last_seen_at is not None else now
        self._open_at = None
        self._open_samples = 0
        self._swing_sample = None

    @staticmethod
    def _anchor(hand):
        return tuple(sum(hand.points[i][axis] for i in (0, 5, 9, 13, 17)) / 5
                     for axis in (0, 1))

    @staticmethod
    def _size(hand):
        return max(distance(hand.points[0], hand.points[9]),
                   distance(hand.points[5], hand.points[17]), 8.)

    def _swing_velocity(self, hand, now):
        # A moving palm distinguishes a swing from the fingers opening in place.
        center = self._anchor(hand)
        previous = self._swing_sample
        velocity = (0., 0.)
        swing = (0., 0.)
        if previous:
            elapsed = now - previous[0]
            if .01 <= elapsed <= .15:
                velocity = tuple((end - start) / elapsed for start, end in zip(previous[1], center))
                prior = previous[2]
                speed, prior_speed = math.hypot(*velocity), math.hypot(*prior)
                if (min(speed, prior_speed) >= self.SWING_SPEED
                        and sum(a * b for a, b in zip(prior, velocity)) >= .75 * speed * prior_speed):
                    swing = velocity
        self._swing_sample = now, center, velocity
        return swing

    def _near_held_hand(self, hand, now):
        old = self._held_hand
        if old is None:
            return False
        ratio = self._size(hand) / self._size(old)
        reach = max(90., self._size(old) * 2.)
        if self.active[0] == 'grab' and old.label is not None and hand.label == old.label:
            reach += min(180., (now - self._missing_at) * 450.)
        return .45 <= ratio <= 2.2 and distance(self._anchor(hand), self._anchor(old)) <= reach

    def _find_reappeared_hand(self, hands, now, fresh):
        # A hand already visible alongside the held hand cannot take its place.
        candidates = [h for h in hands if h.track_id not in self._other_ids
                      and self._near_held_hand(h, now)]
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

    def _ball_contact(self, hand, ball, now, fresh):
        """Confirm two fresh gripping poses and include motion between camera samples."""
        if ball is None:
            self._ball_grips.pop(hand.track_id, None)
            return False
        if not fresh:
            return False
        previous = self._ball_grips.pop(hand.track_id, None)
        if hand.open_for_grab or not (hand.pinch_ratio <= .45 or hand.grasp_pose):
            return False
        relative = tuple(a - b for a, b in zip(hand.pinch_point, ball.center))
        self._ball_grips[hand.track_id] = now, relative
        if previous is None or not 0 < now - previous[0] <= .20:
            return False
        radius = max(ball.width, ball.height) / 2 + max(24., min(40., self._size(hand) * .55))
        if math.hypot(*relative) <= radius:
            return True
        # Sweep relative hand/ball motion so a fast ball cannot skip the catch area.
        start = previous[1]
        delta = tuple(a - b for a, b in zip(relative, start))
        length_sq = sum(value * value for value in delta)
        if not length_sq:
            return False
        fraction = max(0., min(1., -sum(a * b for a, b in zip(start, delta)) / length_sq))
        return math.hypot(*(a + fraction * b for a, b in zip(start, delta))) <= radius

    def update(self, hands, now, source_token):
        if not self.actions.available():
            self.reset('character_busy', now)
            return
        fresh = source_token != self._token
        self._token = source_token
        present = {hand.track_id for hand in hands}
        self._pinched = {key: value for key, value in self._pinched.items() if key in present}
        self._ball_grips = {key: value for key, value in self._ball_grips.items() if key in present}
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
            grace = self.GRAB_GRACE_SECONDS if mode == 'grab' else self.HOLD_GRACE_SECONDS
            if not self.actions.hold_valid(mode):
                self._release(now, 'target_changed')
                return
            if (self._missing_at is not None
                    and now - self._missing_at >= grace):
                self._release(now, 'tracking_lost')
                return
            hand = next((h for h in hands if h.track_id == identity), None)
            if hand is not None and self._missing_at is not None and not self._near_held_hand(hand, now):
                hand = None
            if hand is None:
                self._candidate = None
                self._open_at = None
                self._open_samples = 0
                self._swing_sample = None
                if self._missing_at is None:
                    self._missing_at = self._last_seen_at if self._last_seen_at is not None else now
                if now - self._missing_at >= grace:
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
            if mode == 'ball' and fresh:
                swing = self._swing_velocity(hand, now)
                if any(swing):
                    self.actions.move_hold(mode, hand.pinch_point)
                    self._release(now, 'thrown', swing)
                    return
            if mode == 'palm' and not hand.supports:
                if self._open_at is None:
                    self._open_at, self._open_samples = now, 0
                self._open_samples += int(fresh)
                if (fresh and now - self._open_at >= self.OPEN_SECONDS
                        and self._open_samples >= 2):
                    self._release(now, 'palm_closed')
            else:
                opened = hand.open_for_grab if mode == 'grab' else hand.all_open
                if mode != 'palm' and opened:
                    open_seconds = self.GRAB_OPEN_SECONDS if mode == 'grab' else self.OPEN_SECONDS
                    if self._open_at is None:
                        self._open_at = now
                        self._open_samples = 0
                        if mode == 'grab':
                            self._release_velocity = self._swing_velocity(hand, now) if fresh else (0., 0.)
                            self._swing_sample = None
                        else:
                            self._release_velocity = release_velocities[identity]
                    self._open_samples += int(fresh)
                    if (fresh and now - self._open_at >= open_seconds
                            and self._open_samples >= self.OPEN_SAMPLES):
                        thrown = mode == 'grab' and any(self._release_velocity)
                        self._release(now, 'thrown' if thrown else 'released', self._release_velocity)
                    return
                self._open_at = None
                self._open_samples = 0
                point = (hand.palm if mode == 'palm' else
                         hand.grip_point if mode == 'grab' else hand.pinch_point)
                self.actions.move_hold(mode, point)
                if mode == 'grab' and fresh:
                    swing = self._swing_velocity(hand, now)
                    if any(swing):
                        self._release(now, 'thrown', swing)
            return

        body = self.actions.body_rect()
        candidate = None
        if now >= self._blocked_until:
            ball = self.actions.ball_rect()
            torso = Box(body.x + body.width * .09, body.y + body.height * .45,
                        body.width * .82, body.height * .37)
            for hand in hands:
                point = hand.pinch_point
                if self._ball_contact(hand, ball, now, fresh):
                    candidate = 'ball', hand.track_id, point
                    break
                if (hand.grasp_pose and torso.contains(hand.points[4])
                        and torso.contains(hand.points[8])
                        and (self._pinched[hand.track_id] or not hand.petting_tips)):
                    candidate = 'grab', hand.track_id, hand.grip_point
                    break
                if hand.supports:
                    px, py = hand.palm
                    left, right = hand.support_span
                    span = (right - left) / 2 + max(12., body.width * .20)
                    if (abs(body.center[0] - px) <= span
                            and -max(14., body.height * .30) <= py - body.bottom <= max(35., body.height * .16)):
                        candidate = 'palm', hand.track_id, hand.palm
                        break
        key = candidate[:2] if candidate else None
        if candidate:
            if key != self._candidate:
                self._candidate, self._candidate_at = key, now
                self._candidate_samples = 0
            self._candidate_seen_at = now
            self._candidate_samples += int(fresh)
            dwell = .055 if candidate[0] == 'grab' else .12
            # Ball contact already confirms two fresh poses; it needs no stationary dwell.
            if candidate[0] == 'ball' or (now - self._candidate_at >= dwell and self._candidate_samples >= 2):
                if self.actions.begin_hold(candidate[0], candidate[2]):
                    self.active = candidate[:2]
                    self._held_hand = next(h for h in hands if h.track_id == candidate[1])
                    self._last_seen_at = now
                    self._other_ids = {h.track_id for h in hands if h.track_id != candidate[1]}
                    self._rebind = None
                    if candidate[0] in ('grab', 'ball'):
                        self._swing_velocity(self._held_hand, now)
                    self._pets.clear()
                    return
        elif (self._candidate is not None
              and (self._candidate[0] not in ('grab', 'palm') or now - self._candidate_seen_at > .10
                   or self._candidate[1] not in present)):
            self._candidate = None
        if key is None:
            for hand in hands:
                self._touch(hand, body, now, fresh)

    def _touch(self, hand, body, now, fresh):
        margin = max(4, body.width * .10)
        head = Box(body.x - margin, body.y - margin,
                   body.width + margin * 2, body.height * PET_HEAD_HEIGHT_RATIO + margin)
        tips = hand.petting_tips
        contact = next((tip for tip in tips if head.contains(tip)), None)
        identity = hand.track_id
        if fresh:
            tip = hand.points[8]
            cheek = Box(body.x + body.width * .12, body.y + body.height * .27,
                        body.width * .76, body.height * .14)
            # Stay out of the middle of the face; cheek contact uses a pointed index.
            on_cheek = (not tips and cheek.contains(tip)
                        and abs(tip[0] - body.center[0]) > body.width * .12 and hand.extended[0])
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
        previous = self._pets.get(identity)
        if contact is None:
            if previous and now - previous[1] > .10:
                self._pets.pop(identity, None)
            return
        anchor = self._anchor(hand)
        if previous is None:
            self._pets[identity] = now, now, anchor, 0., None
            return
        started, last_time, last_point, traveled, feedback_at = previous
        dt = now - last_time
        movement = distance(anchor, last_point)
        if dt <= 0 or dt > .35 or movement / dt > 1600:
            self._pets[identity] = now, now, anchor, 0., None
            return
        traveled += abs(anchor[0] - last_point[0])
        elapsed = now - (feedback_at if feedback_at is not None else started)
        if (feedback_at is None or elapsed >= .15) and traveled >= 5:
            self.actions.pet(traveled / max(elapsed, .001), min(elapsed, .2), contact)
            feedback_at, traveled = now, 0.
        self._pets[identity] = started, now, anchor, traveled, feedback_at
