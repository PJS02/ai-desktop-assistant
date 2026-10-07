from copy import deepcopy

import pytest
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from character.manual_control import COMMAND_LABELS, DISPLAY_EMOTIONS, ManualControl
from character.mood_system import MoodSystem
from character.character_widget import CharacterWidget
from character.settings_dialog import SettingsDialog
from test_character_rig_host import HostHarness
from test_settings import local_settings
from test_character_options import real_character
from character import config_manager, settings_controller


@pytest.fixture
def manual_host():
    app = QApplication.instance() or QApplication([])
    host = HostHarness()
    host.current_pixmap = None
    host.surfaces = [host.surface]
    host.movement_speed = 80
    host.custom_screen_width, host.custom_screen_height = 1920, 1000
    host.manual_control = ManualControl(host)
    yield host, app
    host.manual_control.shutdown()


@pytest.mark.parametrize('command,yaw', [('look_left', -65), ('look_front', 0), ('look_right', 65)])
def test_look_changes_direction_without_position_or_animation(manual_host, command, yaw):
    host, _ = manual_host
    original = (host.pos(), list(host.rig_view.actions))
    host.manual_control.execute(command)
    assert host.manual_control.active
    assert host.sprite_animator.yaw == yaw and host._rig_preferred_yaw == yaw
    assert (host.pos(), host.rig_view.actions) == original


def test_look_stops_an_existing_automatic_walk_without_changing_position(manual_host):
    host, _ = manual_host
    host.is_moving = True
    host._move_timer.start(16)
    host.current_action = 'walk'
    original = host.pos()
    host.manual_control.execute('look_front')
    assert host.pos() == original and not host.is_moving
    assert host._move_timer.stopped and host.current_action == 'idle'
    assert host.manual_control.active and host.sprite_animator.yaw == 0


def test_look_preserves_an_existing_manual_walk(manual_host):
    host, _ = manual_host
    host.manual_control.execute('walk_right')
    original = host.pos()
    host.manual_control.execute('look_left')
    assert host.pos() == original and host.is_moving
    assert host.manual_control.motion == 'walk' and host.manual_control.direction == 1
    assert host.manual_control.timer.isActive() and host.sprite_animator.yaw == -65


@pytest.mark.parametrize('direction', [-1, 1])
def test_walk_uses_configured_speed_stops_at_edge_and_remains_manual(manual_host, direction, monkeypatch):
    host, _ = manual_host
    clock = [100.0]
    monkeypatch.setattr('character.manual_control.time.monotonic', lambda: clock[0])
    host.manual_control.execute('walk_left' if direction < 0 else 'walk_right')
    origin = host.x()
    for _ in range(100):
        clock[0] += .016
        host.manual_control.tick()
    assert host.x() == origin + direction * 128
    assert host.current_action == 'walk'
    host._x = 1 if direction < 0 else 1769
    clock[0] += .1
    host.manual_control.tick()
    assert host.x() == (0 if direction < 0 else 1770)
    assert not host.is_moving and host.current_action == 'idle'
    assert host.manual_control.active and not host.manual_control.timer.isActive()


@pytest.mark.parametrize('command,direction', [('jump_left', -1), ('jump', 0), ('jump_right', 1)])
def test_manual_jump_preserves_height_and_direction_stops_after_landing(manual_host, command, direction, monkeypatch):
    host, _ = manual_host
    clock = [100.0]
    monkeypatch.setattr('character.manual_control.time.monotonic', lambda: clock[0])
    host._cursor_over_character = True  # Explicit commands bypass automatic interaction suppression.
    host._last_pet_time = clock[0]
    host.jump_height = 100
    origin_x, origin_y = host.x(), host.y()
    host.manual_control.execute(command)
    assert host.is_jumping and not host.on_ground
    peak = host.y()
    for _ in range(200):
        clock[0] += .016
        host.manual_control.tick()
        host._apply_gravity()
        peak = min(peak, host.y())
        if host.on_ground:
            break
    host.manual_control.tick()
    assert origin_y - peak == 100
    assert host.on_ground and not host.is_moving
    assert (host.x() - origin_x) * direction > 0 if direction else host.x() == origin_x
    landing_x = host.x()
    clock[0] += .1
    host.manual_control.tick()
    assert host.x() == landing_x
    host.rig_view.animation_finished.emit()
    assert host.current_action == 'idle'


def test_stop_in_air_preserves_vertical_physics_and_lands(manual_host):
    host, _ = manual_host
    host.manual_control.execute('jump_right')
    original = (host.y(), host.velocity_y, host._jump_physics_y, host.is_jumping)
    host.manual_control.execute('stop')
    assert (host.y(), host.velocity_y, host._jump_physics_y, host.is_jumping) == original
    x = host.x()
    for _ in range(100):
        host._apply_gravity()
        if host.on_ground:
            break
    assert host.on_ground and host.x() == x


@pytest.mark.parametrize('pose', ['wave', 'thinking', 'sleep'])
def test_pose_waits_until_landing_and_keeps_chosen_direction(manual_host, pose):
    host, _ = manual_host
    host.manual_control.execute('look_left')
    host.manual_control.execute('jump')
    host.manual_control.execute(pose)
    assert host.manual_control.pending_pose == pose and host.current_action == 'jump'
    for _ in range(100):
        host._apply_gravity()
        if host.on_ground:
            break
    host.manual_control.tick()
    assert host.manual_control.pending_pose == pose and host.current_action == 'land'
    host.rig_view.animation_finished.emit()
    host.manual_control.tick()
    assert host.current_action == pose and host.sprite_animator.yaw == -65
    host.update_mood()
    host.advance_emotion()
    assert host.current_action == pose
    if pose == 'wave':
        host.dialogue_system.show_dialogue.assert_called_once()
        host.rig_view.animation_finished.emit()
        assert host.current_action == 'idle' and host.manual_control.active


def test_manual_blocks_automatic_movement_jump_greeting_and_idle_offsets_then_resumes(manual_host, monkeypatch):
    host, _ = manual_host
    host.manual_control.execute('stop')
    original = host.pos()
    host.random_move()
    host.move_toward_ball(900)
    host.jump()
    host._request_user_greeting()
    CharacterWidget.on_animation_position_changed(host, QPoint(999, 800))
    assert host.pos() == original and host.on_ground
    assert host.current_action == 'idle' and not host.is_moving
    assert host._pending_user_greeting_until is None
    host.manual_control.execute('resume')
    assert not host.manual_control.active
    monkeypatch.setattr('character.character_widget.random.random', lambda: .5)
    monkeypatch.setattr('character.character_widget.random.randint', lambda low, high: 50)
    host.random_move()
    assert host.is_moving


def test_home_clamps_original_x_uses_floor_and_clears_jump(manual_host):
    host, _ = manual_host
    home = host.x()
    host.manual_control.execute('jump_right')
    host._x = 800
    host.manual_control.execute('home')
    assert host.x() == home and host.y() + host.height() == 1000
    assert host.on_ground and not host.is_jumping and host.velocity_y == 0
    assert host.current_action == 'idle' and not host.rig_view.jump_active


def test_grabbing_interrupts_manual_move_and_shutdown_stops_timer(manual_host):
    host, _ = manual_host
    host.manual_control.execute('walk_right')
    host.is_dragging = True
    host.manual_control.tick()
    assert host.manual_control.active and not host.manual_control.timer.isActive()
    assert not host.is_moving
    host.is_dragging = False
    host.manual_control.execute('walk_right')
    host._shutdown_character_renderer()
    assert not host.manual_control.timer.isActive()


def test_manual_buttons_emit_immediately_without_applying_settings(manual_host):
    _, app = manual_host
    dialog = SettingsDialog(local_settings())
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.show()
    dialog.tabs.setCurrentIndex(4)
    commands, applies = [], []
    dialog.character_command_requested.connect(commands.append)
    dialog.apply_requested.connect(applies.append)
    assert set(dialog.command_buttons) == set(COMMAND_LABELS)
    for command, button in dialog.command_buttons.items():
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert commands[-1] == command
    assert applies == [] and dialog.changes() == {'local': {}, 'remote': {}}
    dialog.set_manual_status('직접 조작 중 · 왼쪽 이동')
    assert '왼쪽 이동' in dialog.manual_status.text()
    dialog.reject()


def test_settings_controller_dispatch_and_reopen_keep_manual_mode_without_saving_drafts(real_character, tmp_path, monkeypatch):
    host, app = real_character
    class Manager(QObject):
        settings_message = pyqtSignal(dict)
        def request_settings(self, refresh=False):
            return False
    class HiddenSettings(SettingsDialog):
        def __init__(self, *args):
            super().__init__(*args)
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    monkeypatch.setattr(settings_controller, 'SettingsDialog', HiddenSettings)
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', tmp_path / 'config.json')
    controller = settings_controller.SettingsController(host, Manager())
    controller.show()
    dialog = controller.dialog
    dialog.tabs.setCurrentIndex(4)
    dialog.character_inputs['movement_speed'].setValue(300)
    QTest.mouseClick(dialog.command_buttons['stop'], Qt.MouseButton.LeftButton)
    assert host.manual_control.active and host.movement_speed == 80
    assert '직접 조작 중' in dialog.manual_status.text()
    assert not config_manager.CONFIG_FILE.exists()
    dialog.reject()
    assert host.manual_control.active
    controller.show()
    assert '직접 조작 중' in controller.dialog.manual_status.text()
    controller.dialog.tabs.setCurrentIndex(4)
    QTest.mouseClick(controller.dialog.command_buttons['resume'], Qt.MouseButton.LeftButton)
    assert not host.manual_control.active and controller.dialog.manual_status.text() == '자동 행동 중'
    controller.dialog.reject()


def test_png_renderer_rejects_missing_pose_instead_of_replacing_current_action(real_character):
    host, _ = real_character
    host.manual_control.execute('wave')
    assert not host.manual_control.active
    assert '동작 이미지가 없습니다' in host.manual_control.status


@pytest.mark.parametrize('face', [name for name, _ in DISPLAY_EMOTIONS])
def test_display_face_leaves_real_mood_history_and_movement_mode_untouched(manual_host, face):
    host, _ = manual_host
    host.mood_system = MoodSystem()
    before = deepcopy(vars(host.mood_system))
    host.manual_control.set_display_emotion(face)
    assert vars(host.mood_system) == before
    assert host.sprite_animator.current_emotion == face
    assert not host.manual_control.active
    assert host.mood_system.decide_emotion()['emotion'] == 'neutral'
    host.manual_control.set_display_emotion('')
    assert vars(host.mood_system) == before
    assert host.sprite_animator.current_emotion == 'neutral'


@pytest.mark.parametrize('command', ['walk_right', 'jump_right', 'wave', 'sleep'])
def test_display_face_survives_actions_and_returns_to_latest_real_emotion(manual_host, command):
    host, _ = manual_host
    host.manual_control.set_display_emotion('sad')
    host.manual_control.execute(command)
    action, position = host.current_action, host.pos()
    host.mood_system.emotion = 'anger'
    host.update_mood()
    assert host.sprite_animator.current_emotion == 'sad'
    host.manual_control.set_display_emotion('')
    assert host.sprite_animator.current_emotion == 'angry'
    assert host.current_action == action and host.pos() == position
    assert host.manual_control.active


def test_display_controls_apply_immediately_reopen_and_reset_independent_of_motion(real_character, tmp_path, monkeypatch):
    host, _ = real_character
    class Manager(QObject):
        settings_message = pyqtSignal(dict)
        def request_settings(self, refresh=False):
            return False
    class HiddenSettings(SettingsDialog):
        def __init__(self, *args):
            super().__init__(*args)
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    monkeypatch.setattr(settings_controller, 'SettingsDialog', HiddenSettings)
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', tmp_path / 'config.json')
    controller = settings_controller.SettingsController(host, Manager())
    controller.show()
    dialog = controller.dialog
    dialog.tabs.setCurrentIndex(4)
    dialog.display_emotion.setCurrentIndex(dialog.display_emotion.findData('sad'))
    before = deepcopy(host.mood_system.get_emotion_explanation())
    QTest.mouseClick(dialog.display_emotion_apply, Qt.MouseButton.LeftButton)
    assert host.mood_system.get_emotion_explanation() == before and not host.manual_control.active
    assert host.current_action == 'sad'
    assert '슬픔' in dialog.display_emotion_status.text()
    assert dialog.changes() == {'local': {}, 'remote': {}}
    assert not config_manager.CONFIG_FILE.exists()
    dialog.reject()
    controller.show()
    dialog = controller.dialog
    assert dialog.display_emotion.currentData() == 'sad'
    dialog.tabs.setCurrentIndex(4)
    QTest.mouseClick(dialog.display_emotion_reset, Qt.MouseButton.LeftButton)
    assert host.manual_control.display_emotion is None
    assert dialog.display_emotion.currentData() == '' and host.current_action == 'idle'
    assert host.mood_system.get_emotion_explanation() == before
    dialog.reject()


def test_sprite_display_mapping_does_not_change_behavior_profile(manual_host, tmp_path):
    host, _ = manual_host
    host.rig_view = None
    host.assets_path = tmp_path
    (tmp_path / 'walk_angry').mkdir()
    host.manual_control.set_display_emotion('displeased')
    assert host.current_action == 'angry'
    assert host._get_walk_animation('joy') == 'walk_angry'
    assert host._get_falling_action('joy') == 'angry'
    assert host._get_emotion_response_profile('joy')['move_range'] == 100
    host.manual_control.set_display_emotion('')
    assert host.current_action == 'happy'
