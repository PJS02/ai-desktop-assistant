import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
from unittest.mock import Mock, patch

import unittest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QRegion
from PyQt6.QtWidgets import QApplication, QWidget

from character.hide_and_seek import HideAndSeek, peek_depth, hiding_spots, side_vertical_alignment


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(120, 160)
        self.move(200, 100)
        self.surfaces = [SimpleNamespace(name='window_test', x_min=100, x_max=600,
                                        y_level=200, height=400, source_key='test')]
        self.rig_view = Mock()
        self.is_dragging = self.is_jumping = self.is_moving = False
        self.on_ground = True
        self._character_closing = False
        self._rig_manual_action = None
        self._autonomous_behavior_generation = 0
        self.sprite_animator = Mock(yaw=0, _emotion_override=None)
        self.animation_controller = Mock()
        self._move_timer = Mock()
        self.mood_system = Mock()
        self.autonomous_needs = Mock()
        self.dialogue_system = Mock()
        self.update_action = Mock()
        self._mark_character_interaction = Mock()

    def _physics_body_rect(self):
        return QRect(10, 0, 100, 100)

    def _get_screen_geometry(self):
        return QRect(0, 0, 1000, 800)

    def _manual_control_active(self):
        return False

    def _dialogue_is_busy(self):
        return False

    def isVisible(self):
        return True


class HideAndSeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_timeline_is_continuous_and_returns(self):
        values = [peek_depth(i / 1000) for i in range(13001)]
        assert values[0] == values[-1] == 0
        assert all(0 <= v <= .95 for v in values)
        assert max(abs(a - b) for a, b in zip(values, values[1:])) < .003
        assert peek_depth(1) > .9
        assert .5 < peek_depth(3) < .6


    def test_discovery_restores_position_mask_and_rewards_once(self):
        h = Host()
        game = HideAndSeek(h)
        with patch('character.hide_and_seek.time.monotonic', return_value=100) as clock:
            assert game.start()
            clock.return_value = 103
            game.tick()
            assert h.y() == 100
            assert h.mask().isEmpty()
            scene = h.rig_view.set_scene_layer.call_args.kwargs
            assert 50 < scene['offset'][1] < 60
            assert scene['animated']
            assert game.discover()
            assert game.discover()
            clock.return_value = 108
            game.tick()
            assert not game.is_active
            assert h.pos() == QPoint(200, 100)
            assert h.mask().isEmpty()
            assert not h._autonomous_behavior_active
            h.rig_view.clear_scene_layer.assert_called_with('hide_and_seek')
            h.mood_system.on_self_play.assert_called_once()
            game.cancel()
            h.mood_system.on_self_play.assert_called_once()
        h.deleteLater()


    def test_moved_or_closed_target_cancels_without_reward(self):
        for remove in (False, True):
            h = Host()
            game = HideAndSeek(h)
            assert game.start()
            game._last_target_check -= 1
            if remove:
                h.surfaces.clear()
            else:
                h.surfaces[0].y_level += 50
            game.tick()
            assert not game.is_active
            assert h.mask().isEmpty()
            assert h.pos() == QPoint(200, 100)
            h.mood_system.on_self_play.assert_not_called()
            h.deleteLater()


    def test_no_window_or_busy_character_does_not_start(self):
        h = Host()
        game = HideAndSeek(h)
        h.is_dragging = True
        assert not game.start()
        h.is_dragging = False
        h.surfaces.clear()
        assert not game.start()
        assert h.mask().isEmpty()
        h.deleteLater()

    def test_timeout_restores_original_mask_without_penalty(self):
        h = Host()
        original = QRegion(QRect(5, 0, 110, 150))
        h.setMask(original)
        game = HideAndSeek(h)
        with patch('character.hide_and_seek.time.monotonic', return_value=100) as clock:
            assert game.start()
            clock.return_value = 114
            game.tick()
        assert not game.is_active
        assert h.mask() == original
        assert h.pos() == QPoint(200, 100)
        h.mood_system.on_self_play.assert_not_called()
        h.deleteLater()

    def test_both_side_edges_peek_horizontally_without_moving_host(self):
        for side, left, right in (('right', 320, 620), ('left', 0, 200)):
            h = Host()
            h.surfaces = [SimpleNamespace(name='window_side', x_min=left, x_max=right,
                                         y_level=50, height=400, source_key='test')]
            game = HideAndSeek(h)
            with patch('character.hide_and_seek.time.monotonic', return_value=100) as clock:
                assert game.start()
                assert game.mode == side
                h.sprite_animator.play.assert_called_with('peek_'+side)
                clock.return_value = 103
                game.tick()
                scene = h.rig_view.set_scene_layer.call_args.kwargs
                dx, dy = scene['offset']
                assert (dx > 0) == (side == 'right')
                assert 50 < abs(dx) < 70 and abs(dy) < 2
                assert scene['input_margin'] > 0
                assert h.pos() == QPoint(200, 100)
                assert game.discover()
                clock.return_value = 108
                game.tick()
                assert not game.is_active and h.pos() == QPoint(200, 100)
                h.mood_system.on_self_play.assert_called_once()
            h.deleteLater()

    def test_distant_or_short_side_windows_do_not_qualify(self):
        body, screen = QRect(210, 100, 100, 100), QRect(0, 0, 1000, 800)
        for left, top, height in ((400, 50, 400), (320, 120, 400), (320, 50, 90)):
            surface = SimpleNamespace(name='window_side', x_min=left, x_max=left+300,
                                      y_level=top, height=height)
            assert not hiding_spots([surface], body, screen)

    def test_moved_side_window_cancels_without_reward(self):
        h = Host()
        h.surfaces = [SimpleNamespace(name='window_side', x_min=320, x_max=620,
                                     y_level=50, height=400, source_key='test')]
        game = HideAndSeek(h)
        assert game.start()
        h.surfaces[0].x_min += 40
        game._last_target_check -= 1
        game.tick()
        assert not game.is_active and h.pos() == QPoint(200, 100)
        h.mood_system.on_self_play.assert_not_called()
        h.deleteLater()

    def test_photo_layout_accepts_hair_overlap_and_slightly_clipped_feet(self):
        # A painted hair edge can overlap a native invisible frame, while the
        # torso stands beside it. A few shoe pixels can extend past the screen.
        body, screen = QRect(145, 90, 90, 248), QRect(0, 0, 640, 333)
        window = SimpleNamespace(name='window_photo', x_min=0, x_max=158,
                                 y_level=0, height=333)
        spots = hiding_spots([window], body, screen)
        assert len(spots) == 1 and spots[0][1] == 'left'
        mirror_body = QRect(405, 90, 90, 248)
        mirror_window = SimpleNamespace(name='window_photo_right', x_min=482, x_max=640,
                                        y_level=0, height=333)
        spots = hiding_spots([mirror_window], mirror_body, screen)
        assert len(spots) == 1 and spots[0][1] == 'right'
        assert not hiding_spots([window], QRect(80, 90, 90, 248), screen)

    def test_explicit_request_can_stop_normal_walking_without_teleport(self):
        h = Host()
        game = HideAndSeek(h)
        h.is_moving = True
        assert not game.start()
        assert game.start(manual=True)
        assert not h.is_moving and h.pos() == QPoint(200, 100)
        h._move_timer.stop.assert_called()
        game.cancel()
        h.deleteLater()

    def test_failure_reports_actual_busy_state_instead_of_wrong_location(self):
        h = Host()
        game = HideAndSeek(h)
        with patch.object(h, '_dialogue_is_busy', return_value=True):
            assert not game.start(manual=True)
            assert '대화' in game.failure_reason
            assert '가까이' not in game.failure_reason
        h.on_ground = False
        assert not game.start(manual=True)
        assert '착지' in game.failure_reason
        h.deleteLater()

    def test_second_photo_straddles_edge_with_feet_below_window(self):
        body = QRect(164, 171, 105, 240)
        screen = QRect(0, 0, 800, 600)
        window = SimpleNamespace(name='window_photo', x_min=212, x_max=800,
                                 y_level=0, height=380)
        spots = hiding_spots([window], body, screen)
        assert len(spots) == 1 and spots[0][1] == 'right'
        assert spots[0][2] == 48
        shift = side_vertical_alignment(QRect(212, 0, 588, 380), body)
        assert shift == -35
        assert body.translated(0, shift).bottom() <= 375

    def test_pull_up_is_smooth_and_returns_to_the_original_ground_position(self):
        h = Host()
        h.move(154, 171)
        h._physics_body_rect = lambda: QRect(10, 0, 105, 240)
        h.surfaces = [SimpleNamespace(name='window_photo', x_min=212, x_max=800,
                                     y_level=0, height=380, source_key='test')]
        game = HideAndSeek(h)
        with patch('character.hide_and_seek.time.monotonic', return_value=100) as clock:
            assert game.start(manual=True)
            assert game.side_shift_y == -35
            assert h.pos() == QPoint(154, 171)
            clock.return_value = 103
            game.tick()
            dx, dy = h.rig_view.set_scene_layer.call_args.kwargs['offset']
            assert 20 < dx < 30 and -36 < dy < -34
            assert h.pos() == QPoint(154, 171)
            assert game.discover()
            clock.return_value = 108
            game.tick()
            assert not game.is_active and h.pos() == QPoint(154, 171)
        h.deleteLater()

if __name__ == '__main__':
    unittest.main()
