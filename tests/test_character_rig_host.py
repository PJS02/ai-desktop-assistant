"""Exercise real host state methods with a windowless physics harness."""
from pathlib import Path
from types import SimpleNamespace
import time
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QContextMenuEvent

from character.character_widget import CharacterWidget, Surface
from character.rig_state import RigAnimator
from test_rig_state import FakeRigView


class Timer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def start(self):
        self.stopped = False


class Mood:
    def __init__(self):
        self.emotion = "joy"

    def decide_emotion(self):
        return {"emotion": self.emotion}

    def decay(self):
        pass

    def update_idle_pressure(self, seconds):
        self.idle_seconds = seconds

    def advance_emotion(self, seconds):
        self.advance_seconds = seconds

    def has_emotion_changed(self):
        return False, self.emotion, self.emotion


class LegacyAnimator:
    def __init__(self):
        self.actions = []
        self.current_action = "idle"
        self.is_playing = True

    def play(self, action, **kwargs):
        self.actions.append(action)
        self.current_action = action

    def stop(self):
        self.is_playing = False


class HostHarness:
    EMOTION_RESPONSE_PROFILES = CharacterWidget.EMOTION_RESPONSE_PROFILES
    _get_emotion_response_profile = classmethod(CharacterWidget._get_emotion_response_profile.__func__)
    _animation_for_emotion = staticmethod(CharacterWidget._animation_for_emotion)
    # Bind actual production transitions, while substituting only drawing/UI.
    for _name in ("update_action", "update_mood", "_play_rig_action",
                  "_set_rig_direction", "_rig_landed", "on_animation_finished",
                  "_get_walk_animation", "_get_falling_action", "_get_emotion_animation",
                  "_apply_gravity", "random_move", "move_toward_ball", "_smooth_moving", "_advance_horizontal",
                  "mouseReleaseEvent", "_queue_sprite_fallback", "_use_sprite_renderer",
                  "_on_speaking_changed", "_shutdown_character_renderer", "jump",
                  "get_character_idle_time", "_mark_character_interaction",
                  "_maybe_run_autonomous_event", "advance_emotion",
                  "_request_user_greeting", "_try_user_greeting", "_show_perception_dialogue"):
        locals()[_name] = getattr(CharacterWidget, _name)

    def __init__(self, native=True):
        self.rig_view = FakeRigView() if native else None
        self.sprite_animator = RigAnimator(self.rig_view) if native else LegacyAnimator()
        if native:
            self.sprite_animator.animation_finished.connect(self.on_animation_finished)
        self._rig_manual_action = None
        self._rig_preferred_yaw = 0
        self._rig_fallback_pending = False
        self._character_closing = False
        self._pending_user_greeting_until = None
        self._greeting_retry_timer = Timer()
        self.rps_game = None
        self._ball_chasing = False
        self._ball_session_active = False
        self.is_dragging = self.is_moving = self.is_jumping = False
        self.on_ground = True
        self.can_jump = True
        self.current_action = "idle"
        self.is_flipped = False
        self.assets_path = Path("unused-test-assets")
        self.mood_system = Mood()
        self.idle_counter = 1
        self._last_character_interaction_time = time.monotonic()
        self._last_autonomous_event_time = time.monotonic()
        self._autonomous_event_cooldown = 60
        self._cursor_over_character = False
        self._last_pet_time = float('-inf')
        self._move_timer = Timer()
        self._remaining_steps = 0
        self.animation_controller = SimpleNamespace(
            idle=Timer(), update_base_pos=lambda pos: None, start_idle=lambda: None,
            stop=self._move_timer.stop)
        self.dialogue_system = SimpleNamespace(update_dialogue_position=lambda: None, show_dialogue=Mock())
        self._x, self._y = 200, 800
        self.surface = Surface("ground", 1000)
        self.current_surface = self.surface
        self.velocity_x = self.velocity_y = 0
        self.gravity, self.friction, self.bounce_damping = .5, .98, .6
        self.jump_force = 15
        self.overlay_updates = 0

    def update_render(self, action):
        if self.rig_view is not None:
            CharacterWidget.update_render(self, action)
        else:
            self.sprite_animator.play(action)

    def render(self):
        self.update_render(self.current_action)

    def _refresh_rig_overlay(self):
        self.overlay_updates += 1

    def _install_sprite_animator(self):
        self.sprite_animator = LegacyAnimator()

    def get_system_idle_time(self):
        return 0

    def _get_screen_dimensions(self):
        return 1920, 1000

    def get_landing_surface(self, y, x):
        return self.surface

    def _clamp_position_to_screen(self):
        pass

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return 150

    def height(self):
        return 200

    def move(self, x, y):
        self._x, self._y = int(x), int(y)

    def pos(self):
        return QPoint(self._x, self._y)

    def repaint(self):
        pass


@pytest.mark.parametrize("action", ["wave", "thinking", "sleep"])
def test_manual_pose_survives_wandering_chase_and_mood_poll(action):
    host = HostHarness()
    host.is_moving = True
    host._play_rig_action(action)
    assert not host.is_moving and host._move_timer.stopped
    original = list(host.rig_view.actions)
    host.mood_system.emotion = "anxiety"
    host.update_mood()
    host.random_move()
    host.move_toward_ball(700)
    assert host.current_action == action
    assert host.rig_view.actions == original
    assert host.sprite_animator.current_emotion == "anxious"


def test_wave_completion_returns_to_preferred_direction_idle_once():
    host = HostHarness()
    host._set_rig_direction(-65)
    host._play_rig_action("wave")
    host.rig_view.animation_finished.emit()
    host.rig_view.animation_finished.emit()
    assert host.current_action == "idle"
    assert host._rig_manual_action is None
    assert host.rig_view.actions == [("wave", False), ("idle", True)]
    assert host.sprite_animator.yaw == -65


def test_user_greeting_stops_walk_and_plays_wave_once_with_bubble():
    host = HostHarness()
    host.is_moving = True
    host._request_user_greeting()
    assert host.rig_view.actions == [('wave', False)]
    assert not host.is_moving and host._move_timer.stopped
    assert host._pending_user_greeting_until is None and host._greeting_retry_timer.stopped
    host.dialogue_system.show_dialogue.assert_called_once_with('안녕! 👋', duration=3000, use_narration=False)
    assert not host._try_user_greeting()
    host.rig_view.animation_finished.emit()
    assert host.current_action == 'idle'


@pytest.mark.parametrize('activity', ['drag', 'jump', 'fall', 'land', 'ball', 'rps'])
def test_greeting_waits_for_safe_state(activity):
    host = HostHarness()
    if activity == 'drag':
        host.is_dragging = True
    elif activity == 'jump':
        host.jump()
    elif activity == 'fall':
        host.on_ground = False
    elif activity == 'land':
        host.update_render('land')
    elif activity == 'ball':
        host._ball_session_active = True
    else:
        host.rps_game = SimpleNamespace(isVisible=lambda: True)
    original = (host.x(), host.y(), host.velocity_y, host.current_action, list(host.rig_view.actions))
    host._request_user_greeting()
    assert (host.x(), host.y(), host.velocity_y, host.current_action, host.rig_view.actions) == original
    host.dialogue_system.show_dialogue.assert_not_called()
    assert host._pending_user_greeting_until is not None and not host._greeting_retry_timer.stopped
    host.is_dragging = host.is_jumping = host._ball_session_active = False
    host.on_ground, host.rps_game = True, None
    if activity == 'land':
        host.rig_view.animation_finished.emit()
    assert host._try_user_greeting()
    assert host.current_action == 'wave'
    assert host._greeting_retry_timer.stopped


def test_delayed_greeting_expires_and_shutdown_cancels_it(monkeypatch):
    host = HostHarness()
    host.is_dragging = True
    monkeypatch.setattr('character.character_widget.time.monotonic', lambda: 100.0)
    host._request_user_greeting()
    monkeypatch.setattr('character.character_widget.time.monotonic', lambda: 111.0)
    host.is_dragging = False
    assert not host._try_user_greeting()
    assert host._pending_user_greeting_until is None and host._greeting_retry_timer.stopped
    host.dialogue_system.show_dialogue.assert_not_called()
    host.is_dragging = True
    host._request_user_greeting()
    host._shutdown_character_renderer()
    assert host._pending_user_greeting_until is None and host._greeting_retry_timer.stopped
    host._request_user_greeting()
    assert host._pending_user_greeting_until is None


def test_greeting_on_png_renderer_without_wave_assets_still_shows_bubble():
    host = HostHarness(native=False)
    host._request_user_greeting()
    host.dialogue_system.show_dialogue.assert_called_once()
    assert host._greeting_retry_timer.stopped


@pytest.mark.parametrize("flipped,yaw", [(False, -65), (True, 65)])
def test_walk_uses_real_direction_and_poll_changes_only_face(flipped, yaw):
    host = HostHarness()
    host.is_moving = True
    host.is_flipped = flipped
    host.current_action = host._get_walk_animation("joy")
    host.update_render(host.current_action)
    host.mood_system.emotion = "sadness"
    host.update_mood()
    assert host.rig_view.actions == [("walk", True)]
    assert host.sprite_animator.yaw == yaw
    assert host.sprite_animator.current_emotion == "sad"


def test_drag_release_falls_lands_once_then_idle_without_changing_physics():
    native, legacy = HostHarness(), HostHarness(native=False)
    for host in (native, legacy):
        host._y = 700
        host.is_dragging = True
        host._rig_manual_action = "sleep"
        host._drag_velocity_x, host._drag_velocity_y = 6, 4
        host.current_action = "hovering"
        host.update_render("hovering")
        host.mouseReleaseEvent(None)
    assert native.sprite_animator.current_action == "fall"
    assert not native.rig_view.jump_active
    assert native._rig_manual_action is None
    for _ in range(40):
        native._apply_gravity()
        legacy._apply_gravity()
        assert (native.x(), native.y(), native.velocity_x, native.velocity_y,
                native.on_ground) == (legacy.x(), legacy.y(), legacy.velocity_x,
                                     legacy.velocity_y, legacy.on_ground)
    assert native.rig_view.actions.count(("land", False)) == 1
    native.update_mood()
    native.random_move()
    assert native.current_action == "land"
    native.rig_view.animation_finished.emit()
    assert native.current_action == "idle"


def test_jump_fall_land_keeps_legacy_trajectory():
    native, legacy = HostHarness(), HostHarness(native=False)
    native.jump()
    legacy.jump()
    assert native.rig_view.actions == [("jump", True)]
    assert native.rig_view.jump_active
    for _ in range(70):
        native._apply_gravity()
        legacy._apply_gravity()
        assert native.rig_view.jump_active == native.is_jumping
        assert (native.x(), native.y(), native.velocity_x, native.velocity_y,
                native.on_ground) == (legacy.x(), legacy.y(), legacy.velocity_x,
                                     legacy.velocity_y, legacy.on_ground)
    assert native.rig_view.actions == [("jump", True), ("fall", True), ("land", False)]
    assert not native.rig_view.jump_active


def test_finishing_horizontal_motion_does_not_pause_falling_or_landing():
    for action in ("fall", "land"):
        host = HostHarness()
        host.is_moving = True
        host.on_ground = action == "land"
        host.current_action = action
        host.update_render(action)
        host._smooth_moving()
        assert host.rig_view.pauses == 0
        assert host.sprite_animator.is_playing


def test_landing_during_horizontal_motion_plays_once_then_resumes_walk():
    host = HostHarness()
    host.is_moving = True
    host._rig_landed()
    host.update_action({"emotion": "calm"})
    assert host.rig_view.actions == [("land", False)]
    host.rig_view.animation_finished.emit()
    assert host.rig_view.actions == [("land", False), ("walk", True)]


def test_host_forwards_actual_audio_channel_without_interrupting_wave():
    host = HostHarness()
    host._play_rig_action("wave")
    host._on_speaking_changed(True)
    host._on_speaking_changed(False)
    assert host.rig_view.speaking == [True, False]
    assert host.rig_view.actions == [("wave", False)]


@pytest.mark.parametrize("activity,expected", [("drag", "hovering"), ("walk", "walk"), ("idle", "happy")])
def test_runtime_fallback_releases_native_resources_and_preserves_activity(activity, expected):
    host = HostHarness()
    view = host.rig_view
    host.is_dragging = activity == "drag"
    host.is_moving = activity == "walk"
    host._use_sprite_renderer("test context failure")
    assert host.rig_view is None and view.releases == 1 and view.hidden
    assert host.current_action == expected
    assert host.sprite_animator.actions == [expected]
    host._on_speaking_changed(True)
    host._use_sprite_renderer("late duplicate failure")
    assert view.releases == 1


def test_closing_ignores_queued_fallback_and_late_audio():
    host = HostHarness()
    host.timer = Timer()
    host.emotion_timer = Timer()
    host._gravity_timer = Timer()
    host._shutdown_character_renderer()
    host._shutdown_character_renderer()
    host._queue_sprite_fallback("late failure")
    host._use_sprite_renderer("previously queued failure")
    host._on_speaking_changed(True)
    assert host.rig_view.releases == 1
    assert not host._rig_fallback_pending and not host.rig_view.speaking
    assert host.timer.stopped and host._gravity_timer.stopped and host._move_timer.stopped
    assert host.emotion_timer.stopped


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("interaction", ["cursor", "pet"])
def test_interacting_prevents_jump_without_changing_position_or_animation(native, interaction):
    host = HostHarness(native)
    host._cursor_over_character = interaction == "cursor"
    host._last_pet_time = time.monotonic() if interaction == "pet" else float('-inf')
    original = (host.x(), host.y(), host.velocity_y, host.current_action, host.on_ground)
    host.jump()
    assert (host.x(), host.y(), host.velocity_y, host.current_action, host.on_ground) == original
    assert host.sprite_animator.current_action == "idle"


def test_smooth_emotion_refresh_keeps_wave_while_updating_face():
    host = HostHarness()
    host._play_rig_action("wave")
    host.mood_system.emotion = "sadness"
    host.advance_emotion()
    assert host.rig_view.actions == [("wave", False)]
    assert host.sprite_animator.current_emotion == "sad"
    assert host.mood_system.advance_seconds == .1


def test_emotion_refresh_during_jump_does_not_replace_jump_pose():
    host = HostHarness()
    host.jump()
    host.mood_system.emotion = "anger"
    host.advance_emotion()
    assert host.rig_view.actions == [("jump", True)]
    assert host.sprite_animator.current_emotion == "angry"


def test_keyboard_context_menu_anchors_to_character_and_mouse_menu_is_not_duplicated():
    calls = []
    host = SimpleNamespace(
        rect=lambda: QRect(0, 0, 150, 200),
        mapToGlobal=lambda point: point + QPoint(400, 500),
        _show_context_menu=lambda point, **kwargs: calls.append((point, kwargs)),
    )
    keyboard_event = QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(0, 0), QPoint(-1, -1))
    CharacterWidget.contextMenuEvent(host, keyboard_event)
    assert calls == [(QPoint(474, 599), {"include_dialogue": True})]
    assert keyboard_event.isAccepted()
    host._context_menu = SimpleNamespace(isVisible=lambda: True)
    mouse_event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(405, 505))
    CharacterWidget.contextMenuEvent(host, mouse_event)
    assert len(calls) == 1 and mouse_event.isAccepted()
