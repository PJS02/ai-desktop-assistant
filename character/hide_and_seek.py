"""Short, interruptible peeks over a window or around a nearby side edge."""
import math
import random
import time

from PyQt6.QtCore import QObject, QPoint, QRect, QTimer, Qt
from app_logging import log_event


def smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def peek_depth(seconds):
    """Fraction of body submerged: dip, hesitate, peek twice, then return."""
    if seconds < .85:
        return .94 * smooth(seconds / .85)
    if seconds < 1.25:
        return .94
    if seconds < 2.1:
        return .94 - .37 * smooth((seconds - 1.25) / .85)
    if seconds < 6.0:
        return .57 + .012 * math.sin((seconds - 2.1) * 2.3) * math.sin(math.pi * (seconds - 2.1) / 3.9) ** 2
    if seconds < 6.6:
        return .57 + .37 * smooth((seconds - 6) / .6)
    if seconds < 7.0:
        return .94
    if seconds < 7.8:
        return .94 - .41 * smooth((seconds - 7) / .8)
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


def hiding_spots(surfaces, body, screen):
    """Only nearby edges qualify; the character never teleports to a window."""
    spots = []
    for surface in surfaces:
        if not surface.name.startswith('window_') or not surface.height:
            continue
        rect = QRect(round(surface.x_min), round(surface.y_level),
                     round(surface.x_max-surface.x_min), round(surface.height))
        if (abs(body.bottom()+1-rect.top()) <= 24
                and rect.left()+body.width()*.6 < body.center().x() < rect.right()-body.width()*.6
                and rect.top()-screen.top() > body.height()*.7
                and rect.height() >= body.height()*1.1):
            spots.append((surface, 'top', body.height()))
        if (side_vertical_alignment(rect, body) is None or rect.width() < body.width()*1.1
                or not screen.adjusted(-2, -2, 2, 8).contains(body)):
            continue
        max_gap = min(28, body.width()*.35)
        # A broad head can straddle the edge while the torso is next to it.
        # The edge may pass slightly beyond the bounding-box center, but an
        # avatar almost entirely inside a window isn't a side-edge candidate.
        max_overlap = body.width()*.65
        gap_right = rect.left()-body.right()-1
        gap_left = body.left()-rect.right()-1
        if -max_overlap <= gap_right <= max_gap:
            spots.append((surface, 'right', rect.left()-body.left()))
        if -max_overlap <= gap_left <= max_gap:
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
        return random.choice(spots) if spots else None

    def start(self, manual=False):
        h = self.host
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
        elif getattr(getattr(h, 'window_presence', None), 'blocks_physics', False):
            self.failure_reason = '가려진 창에서 나온 뒤에 숨바꼭질할게!'
        elif (h._rig_manual_action is not None or getattr(h, '_automatic_pose', None)
              or getattr(h, '_ball_session_active', False)
              or any(getattr(getattr(h, n, None), 'is_active', False)
                     or (getattr(h, n, None) is not None and getattr(h, n).isVisible())
                     for n in ('cham_game', 'rps_game'))):
            self.failure_reason = '지금 하는 동작을 마치면 숨바꼭질할게!'
        if self.failure_reason:
            return False
        if manual:
            # Explicit menu requests can interrupt an ordinary stroll in place.
            h._move_timer.stop()
            h.is_moving = False
            h._ball_chasing = False
            h.animation_controller.idle.stop()
            h.animation_controller.update_base_pos(h.pos())
            scan = getattr(h, '_scan_windows', None)
            if scan is not None:
                scan()
        elif h.is_moving:
            self.failure_reason = '걷기를 마치면 숨바꼭질할게!'
            return False
        spot = self.candidate()
        if spot is None:
            windows = self.last_geometry['windows']
            self.failure_reason = ('숨을 수 있는 창이 아직 인식되지 않았어. 창을 열고 다시 시도해 줘!'
                                   if not windows else '창 가장자리와 몸이 조금 더 가까워야 해. 창이 몸보다 작지 않은지도 확인해 줘!')
            if manual:
                log_event('character.hide_and_seek.unavailable', '숨바꼭질 가장자리 판정 실패',
                          category='캐릭터 상태', reason='no_nearby_edge', **self.last_geometry)
                h.update_action(h.mood_system.decide_emotion())
                h.animation_controller.start_idle()
            return False
        self.surface, self.mode, self.hide_distance = spot
        self.original_position = QPoint(h.pos())
        self.original_yaw = h.sprite_animator.yaw
        self.original_override = h.sprite_animator._emotion_override
        self.original_manual_action = h._rig_manual_action
        self.body_height = h._physics_body_rect().height()
        self.window_rect = self._surface_rect()
        self.side_shift_y = (side_vertical_alignment(self.window_rect, h._physics_body_rect().translated(h.pos()))
                             if self.mode != 'top' else 0)
        self.found_at = None
        self.started = time.monotonic()
        self._last_target_check = self.started
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
        h.sprite_animator.set_yaw(0)
        h.sprite_animator.set_emotion_override('neutral')
        h.sprite_animator.play(action)
        self._frame_view = h.rig_view
        self._frame_view.frame_requested.connect(self.tick)
        self._frame_view.failed.connect(self.cancel)
        self.tick()
        return True

    def _surface_rect(self):
        s = self.surface
        return QRect(round(s.x_min), round(s.y_level),
                     round(s.x_max - s.x_min), round(s.height))

    def _target_unchanged(self):
        if self.surface not in self.host.surfaces or self._surface_rect() != self.window_rect:
            return False
        # Surface scans are slower than animation; catch close/move immediately.
        key = str(self.surface.source_key)
        if key.startswith('hWnd:'):
            import win32gui
            hwnd = int(key.split(':', 1)[1])
            try:
                if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                    return False
                from types import SimpleNamespace
                from .desktop_geometry import logical_window
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                window = logical_window(SimpleNamespace(_hWnd=hwnd, left=left, top=top,
                                                       width=right-left, height=bottom-top))
                return (abs(window.left - self.window_rect.left()) <= 2
                        and abs(window.top - self.window_rect.top()) <= 2
                        and abs(window.width - self.window_rect.width()) <= 2
                        and window.height >= self.window_rect.height()-2)
            except win32gui.error:
                return False
        return True

    def discover(self):
        if not self.is_active:
            return False
        if self.found_at is None:
            self.found_at = time.monotonic()
            self.found_depth = peek_depth(self.found_at - self.started)
            self.host.sprite_animator.set_emotion_override('excited')
            # The authored wave lifts gradually rather than snapping to a pose.
            self.host.sprite_animator.play('wave', loop=False)
        return True

    def tick(self):
        if not self.is_active:
            return
        h = self.host
        now = time.monotonic()
        target_ok = True
        if now - self._last_target_check >= .15:
            self._last_target_check = now
            target_ok = self._target_unchanged()
        if (h._character_closing or not h.isVisible() or h.is_dragging
                or h._manual_control_active() or h._dialogue_is_busy()
                or h.rig_view is None or not target_ok):
            self.cancel()
            return
        elapsed = now - self.started
        if self.found_at is not None:
            t = now - self.found_at
            depth = self.found_depth * (1 - smooth(t / .65))
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
        occluded = self.window_rect.translated(-h.pos())
        h.rig_view.set_scene_layer('hide_and_seek', offset=offset,
                                   occlusions=(occluded,), animated=True,
                                   input_margin=h._physics_body_rect().width()*.25 if self.mode != 'top' else 0.)
        h.sprite_animator.set_yaw(8 * math.sin(elapsed * .85))

    def cancel(self):
        self.finish()

    def finish(self, found=False):
        if not self.is_active:
            return
        self.is_active = False
        self.timer.stop()
        if self._frame_view is not None:
            try:
                self._frame_view.frame_requested.disconnect(self.tick)
                self._frame_view.failed.disconnect(self.cancel)
            except (TypeError, RuntimeError):
                pass
            self._frame_view.clear_scene_layer('hide_and_seek')
            self._frame_view = None
        h = self.host
        h.move(self.original_position)
        h._physics_position_y = h._physics_position_x = None
        h._gravity_last_time = time.monotonic()
        h.velocity_x = h.velocity_y = 0
        h._autonomous_behavior_active = False
        h._autonomous_behavior_generation += 1
        h._rig_manual_action = self.original_manual_action
        if h.rig_view is not None:
            h.sprite_animator.set_yaw(self.original_yaw)
            h.sprite_animator.set_emotion_override(self.original_override)
            h.sprite_animator.play('idle')
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
            h.dialogue_system.show_dialogue('앗, 들켰다! 한 번 더 할까?', duration=2500)
