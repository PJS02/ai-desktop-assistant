import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QWidget

from character.game_detection import activity_category, GameActivity, game_context_instruction
from character.game_spectator import GameSpectator


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(120, 200)
        self.move(100, 100)
        self._character_closing = False
        self.game_spectator_enabled = True
        self.is_dragging = self.is_moving = self.is_jumping = False
        self.on_ground = True
        self.current_surface = object()
        self._rig_manual_action = self._automatic_pose = None
        self._autonomous_behavior_active = False
        self._autonomous_behavior_generation = 0
        self.rig_view = Mock()
        self.sprite_animator = Mock(yaw=23, _emotion_override='sad')
        self.window_presence = SimpleNamespace(blocks_physics=False, cancel=Mock(), walk_after_landing=False)
        self.animation_controller = Mock()
        self._move_timer = Mock()
        self._cancel_autonomous_behavior = Mock()
        self.mood_system = Mock()
        self.mood_system.decide_emotion.return_value = dict(emotion='sad', intensity=.2)
        self.random_move = Mock()
        self.update_action = Mock()

    def _manual_control_active(self):
        return False

    def _dialogue_is_busy(self):
        return False

    def isVisible(self):
        return True


@pytest.fixture(scope='module', autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session():
    host = Host()
    observer = Mock(return_value=GameActivity('custom.exe'))
    spectator = GameSpectator(host, observer)
    host.game_spectator = spectator
    yield host, spectator, observer
    spectator.shutdown()
    host.deleteLater()


def test_original_generic_process_categories():
    for process in ('steam.exe', 'SomeGame.exe', r'C:\Tools\Unity.exe', 'STEAMWEBHELPER.EXE'):
        assert activity_category(process) == 'game'
    assert activity_category('chrome.exe') == 'web'
    assert activity_category('code.exe') == 'development'
    assert activity_category('discord.exe') == 'communication'
    assert activity_category('MonsterHunterRise.exe') == 'work'


def test_process_only_context_does_not_claim_visual_observation():
    assert '정확한 게임 이름과 플레이 상황은 확인하지 않았습니다' in game_context_instruction()


def test_detecting_game_stops_current_walk_and_immediately_starts_viewing(session):
    host, spectator, _ = session
    host.is_moving = host._ball_chasing = True
    host.velocity_x = 12
    spectator.poll()
    assert spectator.is_game_mode and spectator.is_active
    assert host.pos() == QPoint(100, 100)
    assert not host.is_moving and not host._ball_chasing
    assert host.velocity_x == 0
    host._move_timer.stop.assert_called()
    host.sprite_animator.play.assert_called_with('spectate', loop=True)
    host.window_presence.cancel.assert_called_once()


def test_continuous_game_only_motions_never_resume_walking(session):
    host, spectator, _ = session
    surface = host.current_surface
    with patch('character.game_spectator.time.monotonic', return_value=100) as clock, \
            patch('character.game_spectator.random.uniform', return_value=10):
        for second in range(120):
            clock.return_value = 100 + second
            spectator.poll()
            assert spectator.is_game_mode and spectator.is_active
            assert host.pos() == QPoint(100, 100)
        actions = {call.args[0] for call in host.sprite_animator.play.call_args_list}
        assert actions <= {'spectate', 'game_cheer', 'game_oops'}
        assert 'spectate' in actions and len(actions) > 1
        assert host.current_surface is surface and host.on_ground
        host.random_move.assert_not_called()
        host.animation_controller.start_idle.assert_not_called()


def test_leaving_game_restores_normal_behaviour(session):
    host, spectator, observer = session
    spectator.poll()
    observer.return_value = None
    spectator.poll()
    assert not spectator.is_game_mode and not spectator.is_active
    assert host.pos() == QPoint(100, 100)
    host.animation_controller.start_idle.assert_called_once()
    host.update_action.assert_called()
    host.rig_view.set_decoration_painter.assert_called_with(None)


def test_disabling_game_mode_releases_ownership(session):
    host, spectator, observer = session
    spectator.poll()
    observer.reset_mock()
    host.game_spectator_enabled = False
    spectator.poll()
    assert not spectator.is_game_mode and not spectator.is_active
    observer.assert_not_called()


def test_drag_interrupts_pose_but_keeps_game_mode_and_new_position(session):
    host, spectator, _ = session
    spectator.poll()
    host.is_dragging = True
    host.move(250, 200)
    spectator.poll()
    assert spectator.is_game_mode and not spectator.is_active
    host.animation_controller.start_idle.assert_not_called()
    host.is_dragging = False
    spectator.poll()
    assert spectator.is_active and host.pos() == QPoint(250, 200)
    host.sprite_animator.play.assert_called_with('spectate', loop=True)


def test_existing_jump_can_land_without_starting_another_jump(session):
    host, spectator, _ = session
    host.is_jumping, host.on_ground = True, False
    host.velocity_y = 5
    spectator.poll()
    assert spectator.is_game_mode and not spectator.is_active
    assert host.velocity_y == 5
    host.is_jumping, host.on_ground = False, True
    spectator.poll()
    assert spectator.is_active


def test_manual_control_is_preserved_until_released(session):
    host, spectator, _ = session
    host._manual_control_active = lambda: True
    host.is_moving = True
    spectator.poll()
    assert spectator.is_game_mode and not spectator.is_active
    assert host.is_moving
    host._move_timer.stop.assert_not_called()
    host._manual_control_active = lambda: False
    spectator.poll()
    assert spectator.is_active and not host.is_moving


def test_ai_reaction_returns_to_viewing_during_its_voice(session):
    host, spectator, _ = session
    context = {'game_process': 'custom.exe', 'game_observed_at': 100, 'game_reaction': 'cheer'}
    with patch('character.game_spectator.time.monotonic', return_value=101) as clock:
        spectator.poll()
        host._dialogue_is_busy = lambda: True
        assert spectator.play_ai_reaction(context)
        assert spectator.is_ai_reaction
        host.sprite_animator.play.assert_called_with('game_cheer', loop=True)
        host.sprite_animator.set_emotion_override.assert_not_called()
        clock.return_value = 105
        spectator.poll()
        assert spectator.is_game_mode and spectator.is_active
        host.sprite_animator.play.assert_called_with('spectate', loop=True)
        spectator.poll()
        assert spectator.is_active
        host.random_move.assert_not_called()


def test_old_disabled_or_switched_game_response_cannot_start_motion(session):
    host, spectator, observer = session
    context = {'game_process': 'custom.exe', 'game_observed_at': 100, 'game_reaction': 'oops'}
    with patch('character.game_spectator.time.monotonic', return_value=100 + spectator.MAX_RESPONSE_AGE + 1) as clock:
        assert not spectator.play_ai_reaction(context)
        clock.return_value = 101
        observer.return_value = GameActivity('other.exe')
        assert not spectator.play_ai_reaction(context)
        observer.return_value = GameActivity('custom.exe')
        host.game_spectator_enabled = False
        assert not spectator.play_ai_reaction(context)
        host.sprite_animator.play.assert_not_called()


def test_real_movement_callbacks_cannot_displace_a_paused_game_character(session):
    from character.character_widget import CharacterWidget
    host, spectator, _ = session
    spectator.poll()
    # Even while a direct interaction has paused the pose, game mode owns travel.
    spectator.stop()
    assert spectator.is_game_mode and not spectator.is_active
    initial = host.pos()
    CharacterWidget.random_move(host)
    CharacterWidget.jump(host)
    CharacterWidget.move_toward_ball(host, 900)
    CharacterWidget.on_animation_position_changed(host, QPoint(900, 600))
    assert not CharacterWidget._run_autonomous_behavior(host, 'self_play')
    CharacterWidget._maybe_run_autonomous_event(host, 120)
    host.is_moving = True
    CharacterWidget._smooth_moving(host)
    assert host.pos() == initial and not host.is_moving
    assert not host.is_jumping


def test_mood_refresh_cannot_replace_the_game_pose(session):
    from character.character_widget import CharacterWidget
    host, spectator, _ = session
    spectator.poll()
    CharacterWidget.update_action(host, {'emotion': 'happy'})
    assert host.current_action == 'spectate'
    host.sprite_animator.set_mood_emotion.assert_called_with('happy')


def test_game_mode_prevents_occlusion_escape_and_automatic_sleep(session):
    from character.window_presence import WindowPresence
    from character.automatic_actions import AutomaticActions
    host, spectator, _ = session
    spectator.poll()
    presence = SimpleNamespace(host=host, cancel=Mock(), walk_after_landing=True)
    WindowPresence.poll(presence)
    presence.cancel.assert_called_once()
    assert not presence.walk_after_landing
    WindowPresence.walk_on_support(presence)
    automatic = SimpleNamespace(host=host, _release=Mock())
    AutomaticActions.tick(automatic)
    automatic._release.assert_called_once()
    assert host.current_action == 'spectate'
