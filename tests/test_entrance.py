import json
import os
import time
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

from character.entrance import Entrance


class Host(QWidget):
    def __init__(self):
        super().__init__()
        self.rig_view = None
        self.reactions = Mock()
        self.dialogue_system = Mock()
        self.animation_controller = Mock()
        self.is_dragging = False
        self.on_ground = False
        self.surfaces = [SimpleNamespace(name='ground', y_level=1080, x_min=0, x_max=1920)]
        self._scan_windows = Mock()
        self.update_render = Mock()

    def _get_screen_geometry(self):
        return QRect(0, 0, 1920, 1080)

    def _physics_body_rect(self):
        return QRect(20, 20, 120, 140)


def make(tmp_path, saved=None, seconds_away=0):
    app = QApplication.instance() or QApplication([])
    if saved is not None:
        state = {'position': saved}
        if seconds_away is not None:
            state['closed_at'] = time.time() - seconds_away
        (tmp_path / 'entrance.json').write_text(json.dumps(state), encoding='utf-8')
    host = Host()
    with patch('character.entrance.CONFIG_FILE', tmp_path / 'config.json'):
        entrance = Entrance(host)
    host.entrance = entrance
    entrance.start()
    entrance.timer.stop()
    entrance.waiting_for_renderer = False
    return app, host, entrance


def test_first_entrance_peeks_rises_and_finishes_grounded(tmp_path):
    app, host, entrance = make(tmp_path)
    with patch('character.entrance.time.monotonic', return_value=entrance.clock + .5):
        entrance.tick()
    peek = host.y()
    with patch('character.entrance.time.monotonic', return_value=entrance.clock + 1.5):
        entrance.tick()
    assert host.y() < peek
    entrance.finish()
    assert host.on_ground and not entrance.active
    assert host.y() + 160 == 1080
    assert host.velocity_y == 0
    host.dialogue_system.show_dialogue.assert_not_called()
    assert host.windowOpacity() == 1
    assert json.loads(entrance.path.read_text())['position'] == [host.x(), host.y()]


def test_restart_restores_position_without_first_greeting(tmp_path):
    app, host, entrance = make(tmp_path, [450, 920])
    assert (host.x(), host.y()) == (450, 920)
    assert not entrance.use_peek
    assert host.current_action == 'wave'
    assert host.windowOpacity() == 1
    entrance.finish()
    host.dialogue_system.show_dialogue.assert_not_called()
    host.move(600, 920)
    with patch('character.entrance.time.time', return_value=1234567890):
        entrance.close()
    assert json.loads(entrance.path.read_text())['position'] == [600, 920]
    assert json.loads(entrance.path.read_text())['closed_at'] == 1234567890


def test_missing_support_and_offscreen_position_recover_to_ground(tmp_path):
    app, host, entrance = make(tmp_path, [9000, -300])
    entrance.finish()
    assert host.x() + 140 <= 1920
    assert host.y() + 160 == 1080


def test_drag_interrupts_entrance_without_repositioning_or_greeting(tmp_path):
    app, host, entrance = make(tmp_path)
    host.move(300, 400)
    host.is_dragging = True
    entrance.tick()
    assert not entrance.active
    assert (host.x(), host.y()) == (300, 400)
    host.dialogue_system.show_dialogue.assert_not_called()


def test_native_entrance_poses_keep_emotion_and_have_authored_motion(tmp_path):
    from character.rig_planner import RigPlanner
    app = QApplication.instance() or QApplication([])
    planner = RigPlanner()
    wave = planner.sample({'action': 'wave', 'time': 1.2, 'emotion': 'sad'})['pose']
    rest = planner.sample({'action': 'idle', 'time': 1.2, 'emotion': 'sad'})['pose']
    assert wave['waveGesture'] > .9
    assert wave['exprSad'] == rest['exprSad']
    assert wave['exprHappy'] == rest['exprHappy']
    blink = planner.sample({'action': 'arrive', 'time': .15})['pose']
    assert blink['blink'] > .9


@pytest.mark.parametrize('seconds_away,peek', [(599, False), (600, True), (601, True), (None, True)])
def test_restart_selects_entrance_by_time_away(tmp_path, seconds_away, peek):
    app, host, entrance = make(tmp_path, [450, 500], seconds_away=seconds_away)
    assert entrance.use_peek == peek
    if peek:
        assert host.current_action == 'peek'
        assert host.y() == round(entrance.peek_y)
        with patch('character.entrance.time.monotonic', return_value=entrance.clock + 1.2):
            entrance.tick()
        assert host.current_action == 'arrive'
    with patch('character.entrance.time.monotonic', return_value=entrance.clock + 4):
        entrance.tick()
    host.dialogue_system.show_dialogue.assert_not_called()
    assert host.windowOpacity() == 1
    assert host.y() + 160 == 1080


def test_closing_during_peek_saves_safe_position_for_quick_restart(tmp_path):
    app, host, entrance = make(tmp_path)
    entrance.close()
    state = json.loads(entrance.path.read_text())
    assert state['position'] == [entrance.x, entrance.y]
    with patch('character.entrance.CONFIG_FILE', tmp_path / 'config.json'):
        restarted = Entrance(host)
    assert not restarted.use_peek


def test_wave_refreshes_rendered_emotion_without_pin(tmp_path):
    app, host, entrance = make(tmp_path, [450, 920])
    host.rig_view = Mock()
    host.sprite_animator = Mock()
    host.mood_system = Mock()
    host.mood_system.decide_emotion.return_value = {'emotion': 'sad'}
    entrance.pose('wave')
    host.sprite_animator.set_mood_emotion.assert_called_once_with('sad')
    host.sprite_animator.set_emotion_override.assert_not_called()
