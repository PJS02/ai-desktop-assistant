"""Stationary desktop activities and short reactions to the active game."""
import random
import time
from app_logging import log_event
from ai.gemini_client import is_screen_privacy_enabled

from PyQt6.QtCore import QObject, QPoint, QRectF, QTimer

from .desktop_activity import DesktopActivityObserver
from .game_detection import GameActivity
from .game_outcomes import GameOutcomeMonitor
from .spectator_props import draw_spectator_props
from .game_reactions import GAME_REACTIONS, GAME_RESPONSE_MAX_AGE
from .reactions import experience
from .rig_state import LANDING_ACTIONS


_SIDE_ACTIONS = {'writing', 'reading', 'documents', 'gaming', 'gaming-console'}
_ORDINARY_GAME_ACTIONS = ('gaming', 'gaming-console')
# Stage-space envelopes over a loop, including the hands and a small margin.
_ACTIVITY_BOUNDS = {
    'music': (20, 16, 344, 391),
    'writing': (66, 183, 222, 379),
    'reading': (94, 256, 233, 374),
    'documents': (85, 219, 233, 395),
    'gaming': (69, 265, 231, 381),
    'gaming-console': (68, 265, 231, 367),
    'gaming-racing': (90, 237, 273, 399),
    'gaming-rhythm': (92, 278, 268, 539),
    'spectate': (88, 169, 272, 408),
}
_REST_WINDOWS = {
    'spectate': (9, 4.4),
    'music': (0.6, 0.36),
    'writing': (5.6, 4.76),
    'reading': (4.8, 4.18),
    'documents': (5.6, 4.0),
    'gaming': (0.32, 0.16),
    'gaming-console': (4.8, 4.28),
    'gaming-racing': (4.4, 3.95),
    'gaming-rhythm': (4.8, 3.86),
}


class GameSpectator(QObject):
    MAX_RESPONSE_AGE = GAME_RESPONSE_MAX_AGE

    def __init__(self, host, observer=None, *, settle_seconds=2.0):
        super().__init__(host)
        self.host = host
        self._desktop = DesktopActivityObserver(host) if observer is None else None
        self.observer = observer if observer is not None else self._observe
        self.activity = None
        self._candidate = None
        self._stable_since = 0.0
        self._settle_seconds = settle_seconds
        self._game_entered = False
        self._game_motions = {}
        self._outcomes = GameOutcomeMonitor()
        self._last_side = -65
        self.is_game_mode = False
        self.is_active = False
        self.is_ai_reaction = False
        self._view = None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def _observe(self):
        h = self.host
        return self._desktop.observe(getattr(h, 'igdb_lookup', None), h.game_spectator_enabled,
                                     getattr(h, 'desk_activity_enabled', True))

    def poll(self):
        h = self.host
        if h._character_closing:
            self.shutdown()
            return
        observing = h.game_spectator_enabled or (self._desktop is not None and getattr(h, 'desk_activity_enabled', True))
        activity = self.observer() if observing and h.isVisible() else None
        if self._desktop is not None and (not observing or not h.isVisible()):
            self._desktop.clear()
        now = time.monotonic()
        accepted = self._accept_activity(activity, now)
        screen_game = (activity if accepted and self.is_game_mode and h.game_spectator_enabled
                       and activity.window_id and activity.process_instance
                       and getattr(h, 'auto_program_detection', False)
                       and is_screen_privacy_enabled(getattr(h, 'gemini_config', {})) else None)
        result = self._outcomes.poll(screen_game, now)
        if result is not None:
            outcome, quality = result
            experience(h, 'game_external_result', outcome=outcome, quality=quality)
        if not accepted:
            return
        if self.is_active and h.rig_view is not self._view:
            self.stop()
        if self._blocked():
            self.stop()
            return
        if self.is_game_mode and not self._game_entered:
            self._enter_mode()
        motion = self._motion_for(activity)
        if motion is None:
            if not (self.is_active and self._action == 'writing' and not self._at_rest(now)):
                self.stop()
            return
        placement = self._placement(motion)
        if placement is None:
            self.stop()
            return
        action, yaw = placement
        if not self.is_active:
            if (not h._dialogue_is_busy() and h._rig_manual_action is None
                    and not getattr(h, '_automatic_pose', None)
                    and not h._autonomous_behavior_active):
                self._start_activity(action, yaw)
        elif self._temporary:
            if now >= self.until:
                self._start_activity(action, yaw)
        elif not self._props_fit(self._action, self._yaw) or (self._at_rest(now) and (action, yaw) != (self._action, self._yaw)):
            self._start_activity(action, yaw)
        elif self.is_game_mode and now >= self.until and self._at_rest(now):
            reaction = random.choice(('game_cheer', 'game_oops'))
            self._begin(reaction, 3.2 if reaction == 'game_cheer' else 2.8, temporary=True)

    def _accept_activity(self, activity, now):
        key = activity.session_key if activity else None
        self.activity = activity
        if self._candidate != key:
            was_game = self.is_game_mode
            self._candidate, self._stable_since = key, now
            self.is_game_mode = self._game_entered = False
            self.stop()
            if was_game:
                log_event('game.mode_exited', '일반 캐릭터 행동으로 복귀', category='캐릭터 상태')
        if activity is None or now - self._stable_since < self._settle_seconds:
            return False
        presence = getattr(self.host, 'window_presence', None)
        self.is_game_mode = isinstance(activity, GameActivity) and not getattr(presence, 'is_active', False)
        return True

    def _blocked(self):
        h = self.host
        return (h.rig_view is None or h.is_dragging or h.is_jumping or not h.on_ground
                or (h.sprite_animator.current_action in LANDING_ACTIONS and h.sprite_animator.is_playing)
                or h._manual_control_active() or getattr(h, '_mouse_throw_active', False)
                or getattr(h, '_hand_throw_active', False)
                or (not self.is_active and h._rig_manual_action is not None
                    and not h._autonomous_behavior_active)
                or getattr(getattr(h, 'entrance', None), 'active', False)
                or getattr(getattr(h, 'window_presence', None), 'blocks_physics', False)
                or getattr(h.rig_view, 'high_five_pose_active', False) is True
                or any(getattr(getattr(h, name, None), 'is_active', False)
                       for name in ('cham_game', 'rps_game', 'hide_and_seek')))

    def _props_fit(self, action, yaw):
        view = self.host.rig_view
        stage = view.stage_rect()
        screen = self.host.screen()
        if not isinstance(stage, QRectF) or screen is None:
            return True
        origin = view.mapToGlobal(QPoint())
        stage.translate(origin.x(), origin.y())
        left, top, right, bottom = _ACTIVITY_BOUNDS[action]
        if yaw > 0:
            left, right = 360 - right, 360 - left
        sx, sy = stage.width() / 360, stage.height() / 540
        props = QRectF(stage.x() + left * sx, stage.y() + top * sy,
                       (right - left) * sx, (bottom - top) * sy)
        return QRectF(screen.geometry()).contains(props)

    def _placement(self, action):
        h = self.host
        if action in _SIDE_ACTIONS:
            yaw = h.sprite_animator.yaw
            side = (-65 if yaw < -21 else 65 if yaw > 21 else self._last_side)
            for candidate in (side, -side):
                if self._props_fit(action, candidate):
                    return action, candidate
        elif self._props_fit(action, 0):
            return action, 0
        return None

    def _motion_for(self, activity):
        if activity.motion is not None or not isinstance(activity, GameActivity):
            return activity.motion
        key = activity.run_key
        if key not in self._game_motions:
            self._game_motions[key] = random.choice(_ORDINARY_GAME_ACTIONS)
        return self._game_motions[key]

    def _at_rest(self, now):
        period, rest_start = _REST_WINDOWS[self._action]
        elapsed = now - self._started_at
        phase = elapsed % period
        if self._action == 'spectate' and phase <= 1.1:
            return True
        return phase >= rest_start

    def _start_activity(self, action, yaw):
        ordinary_game = self.is_game_mode and self.activity.motion is None
        duration = random.uniform(10, 16) if ordinary_game else float('inf')
        self._begin(action, duration, yaw=yaw)

    def _enter_mode(self):
        h = self.host
        self._game_entered = True
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
        landing = h.rig_view is not None and h.sprite_animator.current_action in LANDING_ACTIONS and h.sprite_animator.is_playing
        if (not h.is_dragging and not landing
                and not getattr(h, '_hand_throw_active', False) and not getattr(h, '_mouse_throw_active', False)):
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
        if not isinstance(current, GameActivity) or current.process.lower() != context.get('game_process'):
            return False
        if 'game_session' in context and current.session_key != context['game_session']:
            return False
        self.activity = current
        return True

    def play_ai_reaction(self, context):
        choice = context.get('game_reaction')
        reaction = GAME_REACTIONS.get(choice)
        h = self.host
        if ((reaction is None and choice != 'watch') or not h.isVisible() or h.is_moving or self._blocked()
                or not self.response_is_current(context)
                or not self._accept_activity(self.activity, time.monotonic())):
            return False
        if choice == 'watch':
            if not self.is_active and not getattr(h, '_automatic_pose', None):
                placement = self._placement(self._motion_for(self.activity))
                if placement is not None:
                    if not self._game_entered:
                        self._enter_mode()
                    self._start_activity(*placement)
            return True
        if not self.is_active and (h._rig_manual_action is not None or getattr(h, '_automatic_pose', None)):
            return False
        if not self._game_entered:
            self._enter_mode()
        self._begin(*reaction, ai=True, temporary=True)
        return True

    def _begin(self, action, duration, *, ai=False, temporary=False, yaw=0):
        h = self.host
        starting = not self.is_active
        if starting:
            self._view = h.rig_view
            self.saved_yaw = h.sprite_animator.yaw
            self.saved_emotion = h.sprite_animator._emotion_override
        same_pose = not starting and (self._action, self._yaw) == (action, yaw)
        self._hold_position()
        if not same_pose:
            self._started_at = time.monotonic()
            if not starting and self._yaw != yaw:
                self._view.set_decoration_painter(None)
                h.sprite_animator.play('idle')
        self.is_active = True
        self.is_ai_reaction = ai
        self._action, self._yaw = action, yaw
        self._temporary = temporary
        if yaw:
            self._last_side = yaw
        self._active_process = self.activity.process.lower()
        self.until = time.monotonic() + duration
        h.animation_controller.idle.stop()
        h._autonomous_behavior_active = True
        h._autonomous_behavior_generation += 1
        h._rig_manual_action = h.current_action = action
        h.sprite_animator.set_yaw(yaw)
        h.sprite_animator.set_mood_emotion(h.mood_system.decide_emotion()['emotion'])
        h.sprite_animator.play(action, loop=action != 'wave')
        log_event('game.reaction_started' if self.is_game_mode else 'desktop.activity_started',
                  '활동 모션 시작', category='캐릭터 상태', action=action, ai_selected=ai,
                  process=self._active_process, duration_seconds=None if duration == float('inf') else duration)
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
        if h._rig_manual_action != self._action:
            return
        h._rig_manual_action = None
        h._autonomous_behavior_active = False
        h._autonomous_behavior_generation += 1
        if h.rig_view is not None:
            h.sprite_animator.play('idle')
            h.sprite_animator.set_yaw(self.saved_yaw)
            h.sprite_animator.set_emotion_override(self.saved_emotion)
        h.animation_controller.update_base_pos(h.pos())
        if not h._character_closing:
            h.update_action(h.mood_system.decide_emotion())
            if not self.is_game_mode and not h._manual_control_active() and not h.is_dragging and h.on_ground:
                h.animation_controller.start_idle()

    def shutdown(self):
        self.timer.stop()
        self._outcomes.poll(None, time.monotonic())
        if self._desktop is not None:
            self._desktop.close()
        self.activity = None
        self.is_game_mode = False
        self.stop()
