"""Stationary game mode, with continuous viewing and short local/AI gestures."""
import random
import time
from app_logging import log_event

from PyQt6.QtCore import QObject, QTimer

from .game_detection import active_game_activity
from .spectator_props import draw_spectator_props
from .game_reactions import GAME_REACTIONS, GAME_RESPONSE_MAX_AGE


class GameSpectator(QObject):
    MAX_RESPONSE_AGE = GAME_RESPONSE_MAX_AGE

    def __init__(self, host, observer=active_game_activity):
        super().__init__(host)
        self.host, self.observer = host, observer
        self.activity = None
        self.is_game_mode = False
        self.is_active = False
        self.is_ai_reaction = False
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
        previous = self.activity
        self.activity = self.observer() if h.game_spectator_enabled and h.isVisible() else None
        if self.activity is None:
            if self.is_game_mode:
                self.is_game_mode = False
                self.stop()
                log_event('game.mode_exited', '일반 캐릭터 행동으로 복귀', category='캐릭터 상태')
            return
        if (not self.is_game_mode or previous is None
                or previous.process.lower() != self.activity.process.lower()):
            self._enter_mode()
        self._hold_position()
        paused = (h.rig_view is None or h.is_dragging or h.is_jumping or not h.on_ground
                  or h._manual_control_active()
                  or getattr(getattr(h, 'entrance', None), 'active', False)
                  or any(getattr(getattr(h, name, None), 'is_active', False)
                         for name in ('cham_game', 'rps_game')))
        if self.is_active and h.rig_view is not self._view:
            self.stop()
        if paused:
            self.stop()
            return
        if not self.is_active:
            if (not h._dialogue_is_busy() and h._rig_manual_action is None
                    and not getattr(h, '_automatic_pose', None)):
                self._begin('spectate', random.uniform(10, 16))
        elif time.monotonic() >= self.until:
            if self._action == 'spectate':
                action = random.choice(('game_cheer', 'game_oops'))
                self._begin(action, 3.2 if action == 'game_cheer' else 2.8)
            else:
                self._begin('spectate', random.uniform(10, 16))

    def _enter_mode(self):
        h = self.host
        self.is_game_mode = True
        self.stop()
        h._cancel_autonomous_behavior()
        # A pre-existing ambient thinking/sleep pose must not block viewing.
        if not h._manual_control_active():
            h._automatic_pose = None
            h._rig_manual_action = None
        presence = getattr(h, 'window_presence', None)
        if presence is not None:
            presence.cancel()
            presence.walk_after_landing = False
        log_event('game.mode_entered', '게임 전용 모드: 배회 중단, 제자리 관람',
                  category='캐릭터 상태', process=self.activity.process.lower())

    def _hold_position(self):
        """Stop autonomous travel without freezing gravity or a user's drag/throw."""
        h = self.host
        if h._manual_control_active():
            return
        h._move_timer.stop()
        h.is_moving = h._ball_chasing = False
        h._chase_last_time = None
        h.animation_controller.idle.stop()
        h.animation_controller.update_base_pos(h.pos())
        if not h.is_dragging and not getattr(h, '_hand_throw_active', False):
            h.velocity_x = 0
            h._physics_position_x = float(h.x())

    def response_is_current(self, context):
        """Recheck foreground/rules and age at delivery, including delayed TTS."""
        h = self.host
        captured_at = context.get('game_observed_at')
        if (not h.game_spectator_enabled or h._character_closing
                or (context.get('source') != 'manual_generation'
                    and not getattr(h, 'auto_program_detection', True))
                or not isinstance(captured_at, (int, float))
                or not 0 <= time.monotonic() - captured_at <= self.MAX_RESPONSE_AGE):
            return False
        if ('input_epoch' in context
                and context['input_epoch'] != h.dialogue_system.user_input_epoch):
            return False
        current = self.observer()
        if not current or current.process.lower() != context.get('game_process'):
            return False
        self.activity = current
        return True

    def play_ai_reaction(self, context):
        reaction = GAME_REACTIONS.get(context.get('game_reaction'))
        h = self.host
        if (not reaction or not self.response_is_current(context)
                or h.rig_view is None or not h.isVisible()
                or h.is_dragging or h.is_moving or h.is_jumping or not h.on_ground
                or h._manual_control_active()
                or getattr(getattr(h, 'entrance', None), 'active', False)
                or getattr(h.window_presence, 'blocks_physics', False)):
            return False
        if not self.is_active and (h._rig_manual_action is not None or getattr(h, '_automatic_pose', None)):
            return False
        if not self.is_game_mode:
            self._enter_mode()
        self._hold_position()
        self._begin(*reaction, ai=True)
        return True

    def _begin(self, action, duration, *, ai=False):
        h = self.host
        starting = not self.is_active
        if starting:
            self._view = h.rig_view
            self.saved_yaw = h.sprite_animator.yaw
            self.saved_emotion = h.sprite_animator._emotion_override
        self.is_active = True
        self.is_ai_reaction = ai
        self._action = action
        self._active_process = self.activity.process.lower()
        self.until = time.monotonic() + duration
        h.animation_controller.idle.stop()
        h._autonomous_behavior_active = True
        h._autonomous_behavior_generation += 1
        h._rig_manual_action = h.current_action = action
        h.sprite_animator.set_yaw(0)
        h.sprite_animator.set_mood_emotion(h.mood_system.decide_emotion()['emotion'])
        h.sprite_animator.play(action, loop=action != 'wave')
        log_event('game.reaction_started', '게임 관람 동작 시작', category='캐릭터 상태',
                  action=action, ai_selected=ai, process=self._active_process, duration_seconds=duration)
        self._view.set_decoration_painter(draw_spectator_props if action == 'spectate' else None)
        if starting:
            self._view.failed.connect(self.stop)

    def stop(self):
        if not self.is_active:
            return
        self.is_active = False
        self.is_ai_reaction = False
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
            if not self.is_game_mode and not h._manual_control_active() and not h.is_dragging and h.on_ground:
                h.animation_controller.start_idle()

    def shutdown(self):
        self.timer.stop()
        self.activity = None
        self.is_game_mode = False
        self.stop()
