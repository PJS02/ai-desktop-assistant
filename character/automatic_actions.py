"""Grounded thinking/sleep poses driven by dialogue and actual user inactivity."""
import time

from PyQt6.QtCore import QObject, QTimer


class AutomaticActions(QObject):
    SLEEP_SECONDS = 120
    THINK_DELAY = .5
    ERROR_SECONDS = 2

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        host._automatic_pose = None
        self.waiting_since = None
        self.error_until = 0.0
        self.sleep_after = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def set_ai_state(self, state):
        now = time.monotonic()
        self.waiting_since = now if state == 'waiting' else None
        self.error_until = now + self.ERROR_SECONDS if state == 'error' else 0.0
        self.wake()
        self.tick()

    def wake(self):
        self.sleep_after = time.monotonic() + self.SLEEP_SECONDS
        if self.host._automatic_pose == 'sleep':
            self._release()

    def _release(self):
        host = self.host
        previous, host._automatic_pose = host._automatic_pose, None
        if (previous and host.current_action == previous
                and not host._manual_control_active() and host._rig_manual_action is None
                and not host.is_dragging and host.on_ground and not host.is_jumping):
            host.update_action(host.mood_system.decide_emotion())
            if host.current_action == 'idle':
                host.animation_controller.start_idle()

    def tick(self):
        host = self.host
        if host._character_closing:
            self.timer.stop()
            return
        blocked = (host.rig_view is None or host._manual_control_active()
                   or host._rig_manual_action is not None or host.is_dragging
                   or host.is_jumping or not host.on_ground
                   or (host.sprite_animator.current_action == 'land' and host.sprite_animator.is_playing)
                   or any(getattr(getattr(host, name, None), 'is_active', False)
                          for name in ('cham_game', 'rps_game')))
        if blocked:
            self._release()
            return
        now = time.monotonic()
        action = None
        if (now < self.error_until or (self.waiting_since is not None
                                      and now - self.waiting_since >= self.THINK_DELAY)):
            action = 'thinking'
        elif (self.waiting_since is None and now >= self.sleep_after
              and host.get_system_idle_time() >= self.SLEEP_SECONDS
              and not host._dialogue_is_busy()
              and not getattr(host, '_automatic_request_active', False)
              and not getattr(host, '_ball_session_active', False)
              and not getattr(host.dialogue_system, 'current_dialogue', None)):
            action = 'sleep'
        if host._automatic_pose == action and (action is None or host.current_action == action):
            return
        self._release()
        if action:
            host._move_timer.stop()
            host.is_moving = host._ball_chasing = False
            host._chase_last_time = None
            host.animation_controller.idle.stop()
            host.animation_controller.update_base_pos(host.pos())
            host._automatic_pose = host.current_action = action
            host.sprite_animator.set_yaw(host._idle_rig_yaw())
            host.sprite_animator.set_emotion(host.mood_system.decide_emotion()['emotion'])
            host.update_render(action)

    def shutdown(self):
        self.timer.stop()
        self.host._automatic_pose = None
