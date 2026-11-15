"""Short, interruptible peeks over a window or around a nearby side edge."""
import math
import random
import time

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, QTimer, Qt
from PyQt6.QtGui import QRegion
from app_logging import log_event

from .desktop_geometry import support_span, surface_rect


_FIRST_HIDE_END = .85
_FIRST_HOLD_END = 1.25
_FIRST_PEEK_END = 2.1
_FIRST_PEEK_DEPTH = .57
_HIDDEN_DEPTH = .94
_REVEAL_SECONDS = .65


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def peek_depth(seconds):
    """Fraction of body submerged: dip, hesitate, peek twice, then return."""
    if seconds < _FIRST_HIDE_END:
        return _HIDDEN_DEPTH * smooth(seconds / _FIRST_HIDE_END)
    if seconds < _FIRST_HOLD_END:
        return _HIDDEN_DEPTH
    if seconds < _FIRST_PEEK_END:
        progress = smooth((seconds - _FIRST_HOLD_END) / (_FIRST_PEEK_END - _FIRST_HOLD_END))
        return _HIDDEN_DEPTH + (_FIRST_PEEK_DEPTH - _HIDDEN_DEPTH) * progress
    if seconds < 6.0:
        t = seconds - _FIRST_PEEK_END
        return _FIRST_PEEK_DEPTH + .012 * math.sin(t * 2.3) * math.sin(math.pi * t / 3.9) ** 2
    if seconds < 6.6:
        return _FIRST_PEEK_DEPTH + (_HIDDEN_DEPTH - _FIRST_PEEK_DEPTH) * smooth((seconds - 6) / .6)
    if seconds < 7.0:
        return _HIDDEN_DEPTH
    if seconds < 7.8:
        return _HIDDEN_DEPTH - .41 * smooth((seconds - 7) / .8)
    if seconds < 12:
        return .53 + .012 * math.sin((seconds - 7.8) * 2.0) * math.sin(math.pi * (seconds - 7.8) / 4.2) ** 2
    return .53 * (1 - smooth((seconds - 12) / 1.0))


def side_vertical_alignment(rect, body):
    """Allow shoes below a window by gently pulling up during the hide."""
    minimum = rect.top()+4-body.top()
    maximum = rect.bottom()-4-body.bottom()
    if minimum > 10 or minimum > maximum:
        return None
    shift = max(minimum, min(0, maximum))
    return shift if abs(shift) <= body.height()*.35 else None


def _edge_visible(surface, frame, body, mode):
    region = getattr(surface, 'visible_region', None)
    if region is None:
        return True
    # Check the original edge across the character's full contact span.
    if mode == 'top':
        edge = QRect(body.left(), frame.top(), body.width(), 1)
    else:
        x = frame.left() if mode == 'right' else frame.right()
        edge = QRect(x, body.top(), 1, body.height())
    return QRegion(edge).subtracted(region).isEmpty()


def hiding_spots(surfaces, body, screen):
    """Only nearby edges qualify; the character never teleports to a window."""
    spots = []
    for surface in surfaces:
        if not surface.name.startswith('window_') or not surface.height:
            continue
        rect = surface_rect(surface)
        if (abs(body.bottom()+1-rect.top()) <= 24
                and rect.left()+body.width()*.6 < body.center().x() < rect.right()-body.width()*.6
                and rect.top()-screen.top() > body.height()*.7
                and rect.height() >= body.height()*1.1
                and _edge_visible(surface, rect, body, 'top')):
            spots.append((surface, 'top', body.height()))
        shift = side_vertical_alignment(rect, body)
        if (shift is None or rect.width() < body.width()*1.1
                or not screen.adjusted(-2, -2, 2, 8).contains(body)):
            continue
        aligned_body = body.translated(0, shift)
        max_gap = min(28, body.width()*.35)
        # A broad head can straddle the edge while the torso is next to it.
        # The edge may pass slightly beyond the bounding-box center, but an
        # avatar almost entirely inside a window isn't a side-edge candidate.
        max_overlap = body.width()*.65
        gap_right = rect.left()-body.right()-1
        gap_left = body.left()-rect.right()-1
        if -max_overlap <= gap_right <= max_gap and _edge_visible(surface, rect, aligned_body, 'right'):
            spots.append((surface, 'right', rect.left()-body.left()))
        if -max_overlap <= gap_left <= max_gap and _edge_visible(surface, rect, aligned_body, 'left'):
            spots.append((surface, 'left', body.right()-rect.right()))
    return spots


class HideAndSeek(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.is_active = False
        self.found_at = None
        self.failure_reason = ''
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self._frame_view = None

    def candidate(self):
        h = self.host
        body = h._physics_body_rect().translated(h.pos())
        screen = h._get_screen_geometry()
        spots = hiding_spots(h.surfaces, body, screen)
        self.last_geometry = {
            'body': body.getRect(), 'screen': screen.getRect(),
            'windows': [(s.x_min, s.y_level, s.x_max-s.x_min, s.height)
                        for s in h.surfaces if s.name.startswith('window_')],
        }
        candidates = []
        for spot in spots:
            surface, mode, _ = spot
            # 'right' describes the direction into the window, from its left side.
            wave_x = self._left_wave_position(surface, body, screen) if mode == 'right' else None
            if mode != 'right' or wave_x is not None:
                candidates.append((spot, wave_x))
        if candidates:
            spot, self.left_wave_x = random.choice(candidates)
            return spot
        if spots:
            self.failure_reason = '창 옆에 나와서 손을 흔들 공간이 필요해!'
        return None

    def _left_wave_position(self, surface, body, screen):
        h = self.host
        # Reserve the width of the rig stage so the reaching hand clears the window too.
        stage = h.rig_view.stage_rect()
        first = math.ceil(screen.left() + 2 - stage.left())
        last = math.floor(surface.x_min - 2 - stage.right())
        standing = getattr(h, 'current_surface', None)
        if standing is not None:
            span = support_span(standing, body.left(), body.right() + 1)
            if span is None:
                return None
            feet = body.x() + body.width() / 2 - h.x()
            first = max(first, math.ceil(span[0] - feet))
            last = min(last, math.ceil(span[1] - feet) - 1)
        return max(first, min(h.x(), last)) if first <= last else None

    def start(self, manual=False):
        h = self.host
        presence = getattr(h, 'window_presence', None)
        self.failure_reason = ''
        if self.is_active or h._character_closing:
            return False
        if h.rig_view is None:
            self.failure_reason = '이 숨바꼭질은 리그 캐릭터에서 할 수 있어.'
        elif h.is_dragging or h.is_jumping or not h.on_ground:
            self.failure_reason = '놓아주고 착지하면 숨바꼭질할게!'
        elif h._manual_control_active():
            self.failure_reason = '직접 조작을 끝내고 자동 행동으로 돌려줘!'
        elif h._dialogue_is_busy():
            self.failure_reason = '지금 대화가 끝나면 숨바꼭질할게!'
        elif presence is not None and presence.blocks_physics:
            self.failure_reason = '가려진 창에서 나온 뒤에 숨바꼭질할게!'
        elif (h._rig_manual_action is not None or getattr(h, '_automatic_pose', None)
              or getattr(h, '_ball_session_active', False)
              or any(getattr(getattr(h, n, None), 'is_active', False)
                     or (getattr(h, n, None) is not None and getattr(h, n).isVisible())
                     for n in ('cham_game', 'rps_game'))):
            self.failure_reason = '지금 하는 동작을 마치면 숨바꼭질할게!'
        if self.failure_reason:
            return False
        if not manual and h.is_moving:
            self.failure_reason = '걷기를 마치면 숨바꼭질할게!'
            return False
        scan = getattr(h, '_scan_windows', None)
        if scan is not None:
            scan()
        standing = getattr(h, 'current_surface', None)
        body = h._physics_body_rect().translated(h.pos())
        if standing is not None and (standing not in h.surfaces
                                     or support_span(standing, body.left(), body.right()+1) is None):
            self.failure_reason = '놓아주고 착지하면 숨바꼭질할게!'
            return False
        if manual:
            # Explicit menu requests can interrupt an ordinary stroll in place.
            h._move_timer.stop()
            h.is_moving = False
            h._ball_chasing = False
            h.animation_controller.idle.stop()
            h.animation_controller.update_base_pos(h.pos())
        spot = self.candidate()
        if spot is None:
            if not self.failure_reason:
                self.failure_reason = (
                    '숨을 수 있는 창이 아직 인식되지 않았어. 창을 열고 다시 시도해 줘!'
                    if not self.last_geometry['windows']
                    else '창 가장자리와 몸이 조금 더 가까워야 해. 창이 몸보다 작지 않은지도 확인해 줘!'
                )
            if manual:
                log_event('character.hide_and_seek.unavailable', '숨바꼭질 가장자리 판정 실패',
                          category='캐릭터 상태', reason='no_nearby_edge', **self.last_geometry)
                h.update_action(h.mood_system.decide_emotion())
                h.animation_controller.start_idle()
            return False
        self.surface, self.mode, self.hide_distance = spot
        self.original_position = QPoint(h.pos())
        self.wave_offset = None if self.left_wave_x is None else self.left_wave_x - h.x()
        self.original_yaw = h.sprite_animator.yaw
        self.original_override = h.sprite_animator._emotion_override
        self.original_manual_action = h._rig_manual_action
        self.original_body = body
        self.standing = standing
        self.standing_level = standing.y_level if standing is not None else None
        self.body_height = body.height()
        self.window_rect = surface_rect(self.surface)
        self.turn_offset = self._covered_turn_offset() if abs(self.original_yaw) > 21 else None
        self.side_shift_y = side_vertical_alignment(self.window_rect, body) if self.mode != 'top' else 0
        self.edge_body = body.translated(0, self.side_shift_y)
        self.found_at = None
        self.peek_offset = (0., 0.)
        self.wave_started = False
        self.wave_ended_at = None
        self.started = time.monotonic()
        h._move_timer.stop()
        h.animation_controller.idle.stop()
        hand = getattr(h, 'hand_interactions', None)
        if hand:
            hand.cancel('hide_and_seek')
        h.velocity_x = h.velocity_y = 0
        self.is_active = True
        h._autonomous_behavior_active = True
        h._autonomous_behavior_generation += 1
        action = 'peek' if self.mode == 'top' else 'peek_'+self.mode
        h._rig_manual_action = h.current_action = action
        h.sprite_animator.set_emotion_override('neutral')
        self._frame_view = h.rig_view
        if self.wave_offset:
            self._frame_view.set_peek_padding(abs(self.wave_offset))
        h.sprite_animator.play(action)
        self._frame_view.frame_requested.connect(self.tick)
        self._frame_view.failed.connect(self.cancel)
        if self.left_wave_x is not None:
            self._frame_view.animation_finished.connect(self._end_left_wave)
        self.tick()
        # Hand off the mask after the first peek frame is ready.
        if self.is_active and presence is not None:
            presence.clear_cover()
        return self.is_active

    def _covered_turn_offset(self):
        """Hide the whole stage while changing from the side artwork to the front."""
        h = self.host
        stage = h.rig_view.stage_rect().translated(h.x(), h.y())
        inside = QRectF(self.window_rect).adjusted(2, 2, -2, -2)
        if stage.width() > inside.width() or stage.height() > inside.height():
            return None
        dx = max(inside.left() - stage.left(), min(0., inside.right() - stage.right()))
        dy = max(inside.top() - stage.top(), min(0., inside.bottom() - stage.bottom()))
        return dx, dy

    def _target_unchanged(self):
        # The window scan updates visibility even when neither rectangle moves.
        standing = self.standing
        body = self.original_body
        if standing is not None:
            span = support_span(standing, body.left(), body.right()+1)
            if standing not in self.host.surfaces or standing.y_level != self.standing_level or span is None:
                return False
            if self.left_wave_x is not None:
                feet = body.x() + body.width() / 2 + self.wave_offset
                if not span[0] <= feet < span[1]:
                    return False
        return (self.surface in self.host.surfaces
                and surface_rect(self.surface) == self.window_rect
                and _edge_visible(self.surface, self.window_rect, self.edge_body, self.mode))

    def discover(self):
        if not self.is_active:
            return False
        if self.found_at is None:
            self.found_at = time.monotonic()
            if self.left_wave_x is not None:
                self.exit_yaw = self.host.sprite_animator.yaw
            else:
                self.found_depth = peek_depth(self.found_at - self.started)
                self._play_found_wave()
        return True

    def _play_found_wave(self):
        animator = self.host.sprite_animator
        animator.set_yaw(0)
        animator.set_emotion_override('excited')
        animator.play('wave', loop=False)

    def _tick_left_discovery(self, now):
        if self.wave_ended_at is not None:
            progress = smooth((now - self.wave_ended_at) / .4)
            if progress == 1.:
                self.finish(found=True)
                return
            self._set_offset((self.wave_offset * (1 - progress), 0.))
            return
        if self.wave_started:
            return
        progress = smooth((now - self.found_at) / _REVEAL_SECONDS)
        dx, dy = self.peek_offset
        self.host.sprite_animator.set_yaw(self.exit_yaw * (1 - progress))
        self._set_offset((dx * (1 - progress) + self.wave_offset * progress,
                          dy * (1 - progress)))
        if progress == 1.:
            self.wave_started = True
            self._play_found_wave()

    def _end_left_wave(self):
        if self.is_active and self.wave_started and self.wave_ended_at is None:
            self.wave_ended_at = time.monotonic()
            self.host._rig_manual_action = 'peek_' + self.mode
            self.host.sprite_animator.play('idle')

    def _set_offset(self, offset):
        h = self.host
        clip_rect = getattr(self.surface, 'clip_rect', None)
        h.rig_view.set_scene_layer('hide_and_seek', offset=offset,
                                   occlusions=(clip_rect if clip_rect is not None else self.window_rect,), animated=True,
                                   input_margin=h._physics_body_rect().width()*.25 if self.mode != 'top' else 0.)

    def tick(self):
        if not self.is_active:
            return
        h = self.host
        now = time.monotonic()
        if (h._character_closing or not h.isVisible() or h.is_dragging
                or h._manual_control_active() or h._dialogue_is_busy()
                or h.rig_view is None or not self._target_unchanged()):
            self.cancel()
            return
        if self.found_at is not None and self.left_wave_x is not None:
            self._tick_left_discovery(now)
            return
        elapsed = now - self.started
        peek_elapsed = elapsed if self.found_at is None else self.found_at - self.started
        if self.found_at is not None:
            t = now - self.found_at
            depth = self.found_depth * (1 - smooth(t / _REVEAL_SECONDS))
            # A small buoyant hop settles exactly back on the original ledge.
            headroom = max(0, h._physics_body_rect().top() - 2)
            hop = -min(self.body_height * .09, headroom) * math.sin(math.pi * min(1, t / .9))
            if t >= 4.6:
                self.finish(found=True)
                return
        else:
            depth, hop = peek_depth(elapsed), 0
            if elapsed >= 13:
                self.finish()
                return
        sway = math.sin(elapsed * 1.8) * 2 * min(1, depth * 3)
        if self.mode == 'top':
            offset = (sway, depth*self.hide_distance+hop)
        else:
            direction = -1 if self.mode == 'left' else 1
            # Lean the head out while the torso remains behind the vertical edge.
            lift = self.side_shift_y*smooth(depth/.53)
            offset = (direction*depth*self.hide_distance, lift+sway*.35+hop)
        if self.turn_offset is not None and peek_elapsed < _FIRST_PEEK_END:
            blend = smooth((depth - _FIRST_PEEK_DEPTH) / (_HIDDEN_DEPTH - _FIRST_PEEK_DEPTH))
            dx, dy = offset
            turn_x, turn_y = self.turn_offset
            offset = (dx + (turn_x - dx) * blend, dy + (turn_y - dy) * blend)
        self.peek_offset = offset
        self._set_offset(offset)
        # Turn toward the viewer once the character is behind the window.
        if self.turn_offset is None or elapsed >= _FIRST_HIDE_END or self.found_at is not None:
            h.sprite_animator.set_yaw(8 * math.sin(elapsed * .85))

    def cancel(self):
        self.finish()

    def finish(self, found=False):
        if not self.is_active:
            return
        self.timer.stop()
        h = self.host
        h._physics_position_y = h._physics_position_x = None
        h._gravity_last_time = time.monotonic()
        h.velocity_x = h.velocity_y = 0
        view = self._frame_view
        if view is not None:
            try:
                view.frame_requested.disconnect(self.tick)
                view.failed.disconnect(self.cancel)
                if self.left_wave_x is not None:
                    view.animation_finished.disconnect(self._end_left_wave)
            except (TypeError, RuntimeError):
                pass
            # Restore the foreground clip before the peek layer is removed.
            if not h._character_closing and (presence := getattr(h, 'window_presence', None)) is not None:
                presence.poll(resume_from_peek=True)
            view.clear_scene_layer('hide_and_seek')
            self._frame_view = None
        if h.rig_view is not None:
            h.sprite_animator.set_yaw(self.original_yaw)
            h.sprite_animator.set_emotion_override(self.original_override)
            h.sprite_animator.play('idle')
        if view is not None and self.wave_offset:
            view.set_peek_padding(0)
        if h.pos() != self.original_position:
            h.move(self.original_position)
        self.is_active = False
        h._autonomous_behavior_active = False
        h._autonomous_behavior_generation += 1
        h._rig_manual_action = self.original_manual_action
        h.current_action = 'idle'
        h.animation_controller.update_base_pos(h.pos())
        if not h._character_closing:
            h.update_action(h.mood_system.decide_emotion())
            if not h._manual_control_active() and not h.is_dragging:
                h.animation_controller.start_idle()
        if found:
            h._mark_character_interaction()
            h.mood_system.on_self_play()
            h.autonomous_needs.satisfy('self_play')
