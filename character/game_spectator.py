"""Short game-aware gestures selected by the normal autonomous activity loop."""
import random
import time

from PyQt6.QtCore import QObject, QTimer

from .game_detection import active_game_activity
from .spectator_props import draw_spectator_props


class GameSpectator(QObject):
    def __init__(self, host, observer=active_game_activity):
        super().__init__(host)
        self.host, self.observer = host, observer
        self.activity = None
        self.is_active = False
        self._view = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def poll(self):
        h = self.host
        if h._character_closing:
            self.shutdown()
            return
        self.activity = self.observer() if h.game_spectator_enabled and h.isVisible() else None
        if not self.is_active:
            return
        if (not self.activity or h.rig_view is not self._view or h.is_dragging
                or h.is_moving or h.is_jumping or not h.on_ground
                or h._manual_control_active() or h._dialogue_is_busy()):
            self.stop()
        elif time.monotonic() >= self.until:
            self.stop()
            # Rejoin the existing movement policy, which already checks mood,
            # cursor proximity, surfaces and configured movement speed/range.
            if random.random() < .65:
                h.random_move()

    def try_activity(self, need):
        h = self.host
        if (not self.activity or not h.game_spectator_enabled or self.is_active
                or need not in ('self_curiosity', 'self_play')
                or h.rig_view is None or h._character_closing or not h.isVisible()
                or h.is_dragging or h.is_moving or h.is_jumping or not h.on_ground
                or h._manual_control_active() or h._dialogue_is_busy()
                or h._rig_manual_action is not None or getattr(h, '_automatic_pose', None)
                or getattr(h.window_presence, 'blocks_physics', False)):
            return False
        if random.random() >= .65:
            return False
        action = 'wave' if need == 'self_play' and random.random() < .6 else 'spectate'
        self._view = h.rig_view
        self.saved_yaw = h.sprite_animator.yaw
        self.saved_emotion = h.sprite_animator._emotion_override
        self.is_active = True
        self.until = time.monotonic() + (4.6 if action == 'wave' else random.uniform(9, 14))
        h.animation_controller.idle.stop()
        h._autonomous_behavior_active = True
        h._autonomous_behavior_generation += 1
        h._rig_manual_action = h.current_action = action
        h.sprite_animator.set_yaw(0)
        h.sprite_animator.set_emotion_override('happy' if action == 'wave' else 'neutral')
        h.sprite_animator.play(action, loop=action != 'wave')
        if action == 'spectate':
            self._view.set_decoration_painter(draw_spectator_props)
        self._view.failed.connect(self.stop)
        return True

    def stop(self):
        if not self.is_active:
            return
        self.is_active = False
        h = self.host
        if self._view:
            try:
                self._view.failed.disconnect(self.stop)
            except (RuntimeError, TypeError):
                pass
            self._view.set_decoration_painter(None)
        self._view = None
        h._rig_manual_action = None
        h._autonomous_behavior_active = False
        h._autonomous_behavior_generation += 1
        if h.rig_view is not None:
            h.sprite_animator.set_yaw(self.saved_yaw)
            h.sprite_animator.set_emotion_override(self.saved_emotion)
            h.sprite_animator.play('idle')
        h.animation_controller.update_base_pos(h.pos())
        if not h._character_closing:
            h.update_action(h.mood_system.decide_emotion())
            if not h._manual_control_active() and not h.is_dragging and h.on_ground:
                h.animation_controller.start_idle()

    def shutdown(self):
        self.timer.stop()
        self.activity = None
        self.stop()
