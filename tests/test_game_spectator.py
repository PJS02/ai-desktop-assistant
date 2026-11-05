import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint, QRect
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
        self._rig_manual_action = None
        self._autonomous_behavior_active = False
        self._autonomous_behavior_generation = 0
        self.rig_view = Mock()
        self.sprite_animator = Mock(yaw=23, _emotion_override='happy')
        self.window_presence = SimpleNamespace(blocks_physics=False)
        self.animation_controller = Mock()
        self.mood_system = Mock()
        self.mood_system.decide_emotion.return_value = dict(emotion='neutral', intensity=.2)
        self.random_move = Mock()
        self.update_action = Mock()

    def _manual_control_active(self):
        return False

    def _dialogue_is_busy(self):
        return False

    def isVisible(self):
        return True


class GameSpectatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_original_generic_process_categories(self):
        for process in ('steam.exe', 'SomeGame.exe', r'C:\Tools\Unity.exe', 'STEAMWEBHELPER.EXE'):
            assert activity_category(process) == 'game'
        assert activity_category('chrome.exe') == 'web'
        assert activity_category('code.exe') == 'development'
        assert activity_category('discord.exe') == 'communication'
        # No per-title/executable allowlist, including the previous Rise special case.
        assert activity_category('MonsterHunterRise.exe') == 'work'

    def test_context_does_not_claim_a_known_game_or_visual_observation(self):
        text = game_context_instruction()
        assert '정확한 게임 이름과 플레이 상황은 확인하지 않았습니다' in text
        assert '몬스터헌터' not in text

    def test_detection_alone_leaves_normal_activity_untouched(self):
        h = Host()
        spectator = GameSpectator(h, Mock(return_value=GameActivity('steam.exe')))
        try:
            spectator.poll()
            assert spectator.activity and not spectator.is_active
            assert h.pos() == QPoint(100, 100) and h.on_ground
            assert not h._autonomous_behavior_active
            h.sprite_animator.play.assert_not_called()
            h.animation_controller.idle.stop.assert_not_called()
        finally:
            spectator.shutdown()
            h.deleteLater()

    def test_short_pose_returns_to_existing_movement_without_teleport(self):
        h = Host()
        original_surface = h.current_surface
        spectator = GameSpectator(h, Mock(return_value=GameActivity('SomeGame.exe')))
        try:
            with patch('character.game_spectator.time.monotonic', return_value=100) as clock, \
                    patch('character.game_spectator.random.random', return_value=0), \
                    patch('character.game_spectator.random.uniform', return_value=10):
                spectator.poll()
                assert spectator.try_activity('self_curiosity')
                assert spectator.is_active
                h.sprite_animator.play.assert_called_with('spectate', loop=True)
                assert h.pos() == QPoint(100, 100)
                clock.return_value = 111
                spectator.poll()
                assert not spectator.is_active
                assert h.pos() == QPoint(100, 100)
                assert h.on_ground and h.current_surface is original_surface
                h.random_move.assert_called_once()
                h.rig_view.set_decoration_painter.assert_called_with(None)
        finally:
            spectator.shutdown()
            h.deleteLater()

    def test_user_drag_interrupts_and_preserves_new_position(self):
        h = Host()
        spectator = GameSpectator(h, Mock(return_value=GameActivity('game.exe')))
        try:
            with patch('character.game_spectator.random.random', return_value=0):
                spectator.poll()
                assert spectator.try_activity('self_play')
                h.sprite_animator.play.assert_called_with('wave', loop=False)
                h.is_dragging = True
                h.move(250, 200)
                spectator.poll()
                assert not spectator.is_active and h.pos() == QPoint(250, 200)
                h.random_move.assert_not_called()
        finally:
            spectator.shutdown()
            h.deleteLater()

    def test_disabled_busy_or_resting_activity_stays_with_normal_behavior(self):
        h = Host()
        observer = Mock(return_value=GameActivity('game.exe'))
        spectator = GameSpectator(h, observer)
        try:
            h.game_spectator_enabled = False
            spectator.poll()
            observer.assert_not_called()
            assert not spectator.try_activity('self_play')
            h.game_spectator_enabled = True
            spectator.poll()
            assert not spectator.try_activity('self_rest')
            h.is_moving = True
            assert not spectator.try_activity('self_curiosity')
            h.sprite_animator.play.assert_not_called()
        finally:
            spectator.shutdown()
            h.deleteLater()

    def test_autonomous_selector_delegates_the_existing_need(self):
        tree = ast.parse(Path('character/character_widget.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CharacterWidget')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_run_autonomous_behavior')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<autonomy>', 'exec'), namespace)
        h = SimpleNamespace(game_spectator=Mock())
        h.game_spectator.try_activity.return_value = True
        assert namespace['_run_autonomous_behavior'](h, 'self_curiosity')
        h.game_spectator.try_activity.assert_called_once_with('self_curiosity')


if __name__ == '__main__':
    unittest.main()
