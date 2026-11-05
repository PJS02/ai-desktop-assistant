import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
import ast
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import QPoint, QRect, QRectF
from PyQt6.QtWidgets import QApplication, QWidget

from character.cloudy_rig_view import CloudyRigView
from character.window_presence import WindowPresence, covered_fraction, occluding_window, foreground_window


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.move(200, 100)
        self.resize(120, 160)
        self._character_closing = False
        self.window_occlusion = True
        self.is_dragging = self.is_moving = False
        self.on_ground = True
        self.rig_view = Mock()
        self.sprite_animator = Mock(yaw=0, _emotion_override=None)
        self._move_timer = Mock()
        self.animation_controller = Mock()
        self.automatic_actions = Mock()
        self._cancel_autonomous_behavior = Mock()
        self.mood_system = Mock()
        self.update_action = Mock()
        self.current_surface = SimpleNamespace(name='ground', x_min=0, x_max=1000, y_level=700)

    def _physics_body_rect(self):
        return QRect(10, 0, 100, 100)

    def isVisible(self):
        return True

    def _manual_control_active(self):
        return False

    def _dialogue_is_busy(self):
        return False


class WindowPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def confirm(self, presence):
        presence.poll()
        presence._candidate_since -= 1
        presence.poll()

    def test_coverage_and_partial_input_follow_visual_clip(self):
        assert covered_fraction(QRect(0, 0, 100, 100), QRect(50, 0, 100, 100)) == .5
        scene = SimpleNamespace(_scene_layers={'hide': dict(offset=(0, 50),
                                 occlusions=(QRectF(0, 100, 200, 200),), reveal=None)})
        assert CloudyRigView.scene_contains(scene, QPoint(50, 80), QRect(0, 0, 100, 100))
        assert not CloudyRigView.scene_contains(scene, QPoint(50, 120), QRect(0, 0, 100, 100))
        assert not CloudyRigView.scene_contains(scene, QPoint(50, 20), QRect(0, 0, 100, 100))

    def test_delayed_escape_then_landing_and_walk(self):
        h = Host()
        observer = Mock(return_value=(1, QRect(100, 80, 600, 500)))
        presence = WindowPresence(h, observer)
        with patch('character.window_presence.time.monotonic', return_value=100) as clock, \
                patch('character.window_presence.TearOverlay') as overlay:
            overlay.return_value.geometry.return_value = QRect(180, 88, 160, 124)
            self.confirm(presence)
            assert presence.occluded and not presence.is_active
            clock.return_value = 107
            presence.poll()
            assert not presence.is_active
            clock.return_value = 109
            presence.poll()
            assert presence.is_active
            clock.return_value = 112
            presence.animate()
            assert not presence.is_active and not presence.occluded
            assert presence.front_of == 1
            assert not h.on_ground
            h.on_ground = True
            h.current_surface = SimpleNamespace(name='ground', x_min=0, x_max=1000, y_level=700)
            presence.poll()
            assert h.is_moving
            h.sprite_animator.play.assert_called_with('walk')
            h._move_timer.start.assert_called_with(16)
        presence.shutdown()
        h.deleteLater()

    def test_changed_window_resets_wait_and_setting_disables(self):
        h = Host()
        observer = Mock(return_value=(1, QRect(100, 80, 600, 500)))
        presence = WindowPresence(h, observer)
        with patch('character.window_presence.time.monotonic', return_value=100) as clock:
            self.confirm(presence)
            clock.return_value = 107
            observer.return_value = (2, QRect(100, 80, 600, 500))
            self.confirm(presence)
            assert presence.hidden_since == 107
            assert not presence.is_active
            h.window_occlusion = False
            presence.poll()
            assert not presence.blocks_physics
            h.rig_view.clear_scene_layer.assert_called_with('foreground')
        presence.shutdown()
        h.deleteLater()

    def test_background_platforms_inside_cover_are_rejected(self):
        h = Host()
        presence = WindowPresence(h, Mock(return_value=None))
        presence.cover = (1, QRect(100, 80, 600, 500))
        assert not presence.surface_visible(SimpleNamespace(name='window_back', y_level=200,
                                                           x_min=100, x_max=600), 210, 310)
        assert presence.surface_visible(SimpleNamespace(name='window_front', y_level=80,
                                                       x_min=100, x_max=600), 210, 310)
        presence.shutdown()
        h.deleteLater()

    def test_z_order_ignores_own_and_lower_windows(self):
        h = Host()
        h.current_surface.source_key = 'hWnd:5'
        gui, process = Mock(), Mock()
        gui.EnumWindows.side_effect = lambda callback, _: [callback(n, None) for n in (1, 2, 5, 6)]
        gui.IsWindowVisible.return_value = True
        gui.IsIconic.return_value = False
        gui.GetWindowText.return_value = 'Application'
        gui.GetClassName.return_value = 'ApplicationWindow'
        gui.GetWindowLong.return_value = 0
        gui.GetWindowRect.return_value = (100, 80, 700, 580)
        gui.error = OSError
        process.GetWindowThreadProcessId.side_effect = lambda n: (0, os.getpid() if n == 1 else -1)
        with patch.dict('sys.modules', {'win32gui': gui, 'win32process': process}), \
                patch('character.window_presence.foreground_window', return_value=(2, QRect(100, 80, 600, 500))) as foreground, \
                patch('character.window_presence.os.name', 'nt'):
            assert occluding_window(h)[0] == 2
            foreground.return_value = (6, QRect(100, 80, 600, 500))
            assert occluding_window(h) is None
            foreground.return_value = (2, QRect(800, 80, 200, 500))
            assert occluding_window(h) is None
        h.deleteLater()

    def test_background_overlap_on_ground_cannot_hide_character(self):
        h = Host()
        gui = Mock()
        gui.error = OSError
        with patch.dict('sys.modules', {'win32gui': gui}), \
                patch('character.window_presence.foreground_window', return_value=(2, QRect(800, 80, 200, 500))), \
                patch('character.window_presence.os.name', 'nt'):
            assert occluding_window(h) is None
            gui.EnumWindows.assert_not_called()
        h.deleteLater()

    def test_failed_z_order_query_leaves_character_visible(self):
        h = Host()
        h.current_surface.source_key = 'hWnd:5'
        gui = Mock()
        gui.error = OSError
        gui.EnumWindows.side_effect = OSError('window changed during query')
        with patch.dict('sys.modules', {'win32gui': gui}), \
                patch('character.window_presence.foreground_window', return_value=(2, QRect(100, 80, 600, 500))) as foreground, \
                patch('character.window_presence.os.name', 'nt'):
            assert occluding_window(h) is None
            foreground.assert_called_once()
        h.deleteLater()

    def test_transient_overlap_is_not_hidden(self):
        h = Host()
        observer = Mock(return_value=(1, QRect(100, 80, 600, 500)))
        presence = WindowPresence(h, observer)
        with patch('character.window_presence.time.monotonic', return_value=100) as clock:
            presence.poll()
            assert not presence.occluded and presence.hidden_since is None
            h.rig_view.set_scene_layer.assert_not_called()
            clock.return_value = 100.1
            observer.return_value = None
            presence.poll()
            assert not presence.occluded and presence.hidden_since is None
            observer.return_value = (1, QRect(100, 80, 600, 500))
            clock.return_value = 101
            presence.poll()
            clock.return_value = 101.4
            presence.poll()
            assert presence.occluded and presence.hidden_since == 101.4
        presence.shutdown()
        h.deleteLater()

    def test_escape_immunity_survives_walking_out_and_back(self):
        h = Host()
        observer = Mock(return_value=None)
        presence = WindowPresence(h, observer)
        presence.front_of = 1
        presence.poll()
        assert presence.front_of == 1
        observer.return_value = (1, QRect(100, 80, 600, 500))
        self.confirm(presence)
        assert not presence.occluded and not presence.is_active
        h.rig_view.set_scene_layer.assert_not_called()
        observer.return_value = (2, QRect(100, 80, 600, 500))
        self.confirm(presence)
        assert presence.front_of is None and presence.occluded
        presence.shutdown()
        h.deleteLater()

    def test_cloaked_and_translucent_foreground_are_not_opaque_covers(self):
        gui, process = Mock(), Mock()
        gui.error = OSError
        gui.GetForegroundWindow.return_value = 42
        gui.IsWindowVisible.return_value = True
        gui.IsIconic.return_value = False
        gui.GetClassName.return_value = 'Application'
        gui.GetWindowText.return_value = 'Application'
        gui.GetWindowLong.return_value = 0
        process.GetWindowThreadProcessId.return_value = (0, -1)
        with patch.dict('sys.modules', {'win32gui': gui, 'win32process': process}), \
                patch('character.window_presence._window_is_cloaked', return_value=True) as cloaked, \
                patch('character.window_presence.os.name', 'nt'):
            assert foreground_window() is None
            cloaked.return_value = False
            gui.GetWindowLong.return_value = 0x80000
            assert foreground_window() is None

    def test_hidden_character_does_not_fall_before_escape(self):
        tree = ast.parse(Path('character/character_widget.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CharacterWidget')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_apply_gravity')
        namespace = {'time': time}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<physics>', 'exec'), namespace)
        host = SimpleNamespace(window_presence=SimpleNamespace(blocks_physics=True))
        namespace['_apply_gravity'](host, .1)
        assert host._gravity_last_time > 0


if __name__ == '__main__':
    unittest.main()
