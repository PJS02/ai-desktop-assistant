"""High-five the hand drawn on the desktop, using its screen-space joints."""
from dataclasses import dataclass
import math

from app_logging import log_event
from .renderer import closest_hand_point


# The authored jump high-five's takeoff, apex and end in high-five.js.
TAKEOFF_TIME = .46
IMPACT_TIME = .76
CLIP_DURATION = 1.85


def upright_palm(points):
    wrist_x, wrist_y = points[0]
    knuckle_x = sum(points[i][0] for i in (5, 9, 13, 17)) / 4
    knuckle_y = sum(points[i][1] for i in (5, 9, 13, 17)) / 4
    dx, rise = knuckle_x - wrist_x, wrist_y - knuckle_y
    # Allow about 35 degrees of lean either way. Horizontal support poses and
    # hands pointing down have their own behavior.
    if rise < 8 or abs(dx) > .70 * rise:
        return None
    length = math.hypot(dx, rise)

    def along(a, b):
        return ((points[b][0] - points[a][0]) * dx
                - (points[b][1] - points[a][1]) * rise) / length

    # A partly occluded or relaxed finger can drop out. Three fingers need to
    # extend along the displayed palm, including past their middle joints.
    if sum(along(base, base + 3) > .32 * length
           and along(base + 1, base + 3) > .09 * length
           for base in (5, 9, 13, 17)) < 3:
        return None
    return wrist_x + .80 * dx, wrist_y - .80 * rise


@dataclass
class _Attempt:
    rig: object
    track: int
    side: int
    started: float
    last_tick: float
    target: tuple
    last_seen: float
    clip: float | None = None
    impact_wait: float | None = None
    recovering: bool = False
    withdrawing: bool = False


class DesktopHighFive:
    def __init__(self, actions):
        self.actions = actions
        self.character = actions.character
        self._candidate = None
        self._source = None
        self._latched = {}
        self._attempt = None

    def _origin(self, rig):
        return self.character.x() + rig.x(), self.character.y() + rig.y()

    def _stage(self, rig):
        return rig.stage_rect().translated(*self._origin(rig))

    @staticmethod
    def _rig_point(stage, point):
        return ((point[0] - stage.x()) * 360 / stage.width(),
                (point[1] - stage.y()) * 540 / stage.height())

    def _route(self, stage, hand, side=None):
        """Find a short approach to the hand's visible edge."""
        c = self.character
        points, palm = hand
        side = side or (-1 if palm[0] < stage.center().x() else 1)
        scale = stage.width() / 360
        reference_x = 202 if side < 0 else 158
        origin = (stage.x() + reference_x * scale, stage.y() + 268 * stage.height() / 540)
        contact = closest_hand_point(points, origin)
        x, y = self._rig_point(stage, contact)
        # The far shoulder moves forward and up at the apex. A low target
        # brings the torso down slightly while the feet still leave the floor.
        shoulder_x, shoulder_y = (145 if side < 0 else 216), 255
        height = y - shoulder_y + 10 - min(15., max(0., y - 300))
        if not 0 <= side * (x - reference_x) <= 325 or abs(height) > 72:
            return None
        reach = min(87., 15 + math.sqrt(76 ** 2 - height ** 2))
        outward = side * (x - shoulder_x)
        # Leave room for the rear arm to emerge past the torso at contact.
        distance = max(min(48., reach), min(outward, reach))
        target = c.x() + side * (outward - distance) * scale
        if abs(target - c.x()) <= 2:
            return side, c.x(), contact
        left, right = c._horizontal_limits()
        if c.current_surface is not None:
            feet = c._physics_body_rect().center().x()
            left = max(left, c.current_surface.x_min - feet + 5)
            right = min(right, c.current_surface.x_max - feet - 5)
        return (side, round(target), contact) if left <= target <= right else None

    def _available(self, rig):
        c = self.character
        spectator = getattr(c, 'game_spectator', None)
        return (rig is not None and c.on_ground and not c.is_jumping
                and self.actions.available() and self.actions.mode is None
                and c._rig_manual_action in (None, 'high_five')
                and not getattr(c, '_automatic_pose', None)
                and not getattr(c, '_autonomous_behavior_active', False)
                and not getattr(getattr(c, 'entrance', None), 'active', False)
                and not (getattr(spectator, 'is_game_mode', False) or getattr(spectator, 'is_active', False))
                and not (c.sprite_animator.current_action == 'land' and c.sprite_animator.is_playing))

    def interrupt_tracking(self):
        self._candidate = None

    def cancel(self):
        self._candidate = None
        attempt, self._attempt = self._attempt, None
        if attempt is None:
            return
        c = self.character
        if c.rig_view is attempt.rig:
            attempt.rig.set_high_five()
        if c._rig_manual_action != 'high_five':
            return
        c._rig_manual_action = None
        if c._character_closing or c.rig_view is not attempt.rig or not c.on_ground:
            return
        c.animation_controller.update_base_pos(c.pos())
        c.update_action(c.mood_system.decide_emotion())
        c.animation_controller.start_idle()

    def update(self, hands, now, source):
        if self._source is not None and source[0] != self._source[0]:
            self.cancel()
            self._latched.clear()
        fresh, self._source = source != self._source, source
        upright = {hand.track_id: (hand.points, palm) for hand in hands
                   if (palm := upright_palm(hand.points)) is not None}
        for track, lowered_at in tuple(self._latched.items()):
            if track in upright:
                self._latched[track] = None
            elif lowered_at is None:
                self._latched[track] = now
            elif now - lowered_at >= .28:
                del self._latched[track]

        c = self.character
        rig = getattr(c, 'rig_view', None)
        attempt = self._attempt
        if ((attempt is not None and (attempt.rig is not rig or c._rig_manual_action != 'high_five'))
                or (not upright and attempt is None) or not self._available(rig)):
            self.cancel()
            return False
        stage = self._stage(rig)
        if stage.isEmpty():
            self.cancel()
            return False
        if attempt is not None:
            self._advance(attempt, upright.get(attempt.track), stage, now)
            return self._attempt is not None

        nearby = []
        center = stage.center().x(), stage.center().y()
        for track, hand in upright.items():
            if track not in self._latched and (route := self._route(stage, hand)) is not None:
                side, _, contact = route
                nearby.append((math.dist(contact, center), track, side, contact))
        if not nearby:
            self._candidate = None
        elif fresh:
            _, track, side, contact = min(nearby)
            previous = self._candidate
            if previous is None or previous[:2] != (track, side) or now - previous[2] > .38:
                self._candidate = track, side, now
            elif now - previous[2] >= .075:
                self._start(rig, track, side, contact, now)
                self._advance(self._attempt, upright[track], stage, now)
        return self._attempt is not None

    def _start(self, rig, track, side, contact, now):
        c = self.character
        self._attempt = _Attempt(rig, track, side, now, now, contact, now)
        self._latched[track] = None
        self._candidate = None
        c._mark_character_interaction(wake=False)
        c._move_timer.stop()
        c.animation_controller.idle.stop()
        c.is_moving = c._ball_chasing = False
        c.velocity_x = 0.
        c._physics_position_x = None
        c._movement_x = float(c.x())
        c._rig_manual_action = 'high_five'
        c.is_flipped = side > 0
        c.sprite_animator.set_yaw(65 * side)

    def _advance(self, attempt, hand, stage, now):
        c = self.character
        dt = min(.12, now - attempt.last_tick)
        attempt.last_tick = now
        scale = stage.width() / 360
        route = None
        if not (attempt.recovering or attempt.withdrawing) and hand is not None:
            route = self._route(stage, hand, attempt.side)
            if attempt.clip is not None and route and abs(route[1] - c.x()) > 20 * scale:
                route = None  # The hand moved out of reach during the strike.
            if route:
                attempt.target, attempt.last_seen = route[2], now

        if attempt.clip is None:
            if now - attempt.started > 2.1 or now - attempt.last_seen > .20:
                self.cancel()
                return
            if not route:
                return
            if route[1] != c.x():
                if c.current_action != 'walk':
                    c.current_action = 'walk'
                    c.sprite_animator.play('walk')
                c._advance_horizontal(route[1], dt, speed_scale=max(1., 245 * scale / c.movement_speed))
                return
            c.current_action = 'idle'
            c.sprite_animator.play('idle')
            attempt.clip = 0.
        elif attempt.recovering:
            attempt.clip += dt
        elif attempt.withdrawing or now - attempt.last_seen > .20:
            if attempt.clip >= TAKEOFF_TIME:
                attempt.recovering = True
                attempt.clip += dt
            else:
                attempt.withdrawing = True
                attempt.clip -= 1.6 * dt
        else:
            attempt.clip = min(IMPACT_TIME, attempt.clip + dt)

        if attempt.clip >= CLIP_DURATION or (attempt.withdrawing and attempt.clip <= 0):
            self.cancel()
            return
        rig = attempt.rig
        rig.set_high_five(attempt.clip, side=attempt.side, target=self._rig_point(stage, attempt.target))
        if attempt.clip != IMPACT_TIME or attempt.recovering or attempt.withdrawing:
            return
        if attempt.impact_wait is None:
            attempt.impact_wait = now
        drawn = rig.high_five_contact(IMPACT_TIME)
        if route and drawn is not None:
            origin_x, origin_y = self._origin(rig)
            contact = drawn.x() + origin_x, drawn.y() + origin_y
            if math.dist(contact, attempt.target) <= max(5., 10 * scale):
                attempt.recovering = True
                self.actions.feedback.pulse('high_five', attempt.target)
                log_event('hand_interaction.high_five', '바탕화면 손과 하이파이브',
                          category='캐릭터 상태')
        if now - attempt.impact_wait >= .20:
            attempt.recovering = True
