import json
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from character import ai_settings, character_widget, config_manager, dialogue_system
from character.character_widget import CharacterWidget, Surface
from character.motion_options import DEFAULT_CHARACTER_OPTIONS
from character.settings_dialog import SettingsDialog
from character.tts_service import SupertonicTTS
from test_character_rig_host import HostHarness
from test_settings import local_settings


def moving_host(speed=80):
    host = HostHarness()
    host.movement_speed = speed
    host.current_pixmap = None
    host.custom_screen_width, host.custom_screen_height = 1920, 1000
    host._move_timer = Mock()
    host.update = lambda: None
    return host


@pytest.mark.parametrize('distance', [7, 25, 100, -7, -25, -100])
@pytest.mark.parametrize('speed', [20, 80, 200])
def test_wandering_duration_depends_on_distance_not_speed(distance, speed, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(character_widget.random, 'random', lambda: .5)
    monkeypatch.setattr(character_widget.random, 'randint', lambda low, high: distance)
    host = moving_host(speed)
    host.random_move()
    assert host.is_moving
    ticks = 0
    while host.is_moving and ticks < 1000:
        clock[0] += .016
        host._smooth_moving()
        ticks += 1
    assert not host.is_moving
    assert host.x() == 200 + distance
    assert abs(ticks * .016 - abs(distance) / speed) <= .017


@pytest.mark.parametrize('direction', [-1, 1])
def test_fractional_motion_has_no_left_right_rounding_bias(direction):
    host = moving_host(20)
    for _ in range(100):
        host._advance_horizontal(200 + direction * 300, .016)
    assert host.x() == 200 + direction * 32


@pytest.mark.parametrize('emotion,base_speed', [
    ('neutral', 4.0), ('calm', 3.0), ('peaceful', 2.5), ('contentment', 3.5),
    ('sadness', 2.5), ('melancholy', 2.0), ('despair', 1.5), ('anxiety', 6.0),
    ('fear', 7.0), ('interest', 8.0), ('joy', 10.0), ('delight', 9.0),
    ('excitement', 12.0), ('anger', 10.0), ('disgust', 8.0), ('unknown', 4.0),
])
def test_ball_chase_preserves_pjs02_emotion_speed_ratios(emotion, base_speed, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    host = moving_host(80)
    host.mood_system.emotion = emotion
    for _ in range(50):
        host.move_toward_ball(1500)
        clock[0] += .016
    assert host.x() == round(200 + 80 * .8 * base_speed / 4 * .7)


@pytest.mark.parametrize('speed', [20, 80, 200])
@pytest.mark.parametrize('intensity', [-.5, 0, .5, 1, 1.5])
def test_ball_chase_scales_configured_speed_and_clamps_intensity(speed, intensity, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    host = moving_host(speed)
    host.mood_system.decide_emotion = lambda: {'emotion': 'joy', 'intensity': intensity}
    for _ in range(50):
        host.move_toward_ball(1500)
        clock[0] += .016
    intensity_scale = .7 + max(0, min(1, intensity)) * .3
    assert host.x() == round(200 + speed * .8 * 2.5 * intensity_scale)


@pytest.mark.parametrize('direction', [-1, 1])
@pytest.mark.parametrize('interval', [.008, .016, .04])
def test_ball_chase_speed_is_independent_of_direction_and_tick_rate(direction, interval, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    host = moving_host(80)
    host._x = 1000
    host._movement_x = 1000.0
    host._ball_chasing = True
    host._chase_last_time = clock[0]
    host.mood_system.decide_emotion = lambda: {'emotion': 'excitement', 'intensity': 1.0}
    for _ in range(round(.8 / interval)):
        clock[0] += interval
        host.move_toward_ball(1000 + direction * 600)
    assert host.x() == round(1000 + direction * 80 * .8 * 3)


@pytest.mark.parametrize('height', [20, 60, 225, 450])
def test_configured_jump_reaches_exact_apex_and_lands(height):
    host = moving_host()
    host.jump_height = height
    origin = host.y()
    host.jump()
    peak = host.y()
    for _ in range(200):
        host._apply_gravity()
        peak = min(peak, host.y())
        if host.on_ground:
            break
    assert origin - peak == height
    assert host.on_ground
    assert host.y() + host.height() == host.surface.y_level
    assert not host.is_jumping


def test_dragging_interrupts_the_saved_jump_trajectory():
    host = moving_host()
    host.jump()
    for _ in range(4):
        host._apply_gravity()
    host._y = 400
    host.mouseReleaseEvent(None)
    assert host.y() == 400
    assert not host.is_jumping
    assert host._jump_physics_y is None


def test_jump_height_is_limited_by_available_screen_space():
    host = moving_host()
    host._y = 100
    host.jump_height = 500
    host.jump()
    peak = host.y()
    for _ in range(200):
        host._apply_gravity()
        peak = min(peak, host.y())
        if host.on_ground:
            break
    assert peak == 0
    assert host.on_ground


def test_character_option_storage_migrates_and_preserves_extra_keys(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    path.write_text('{"width":1280,"height":720,"extra":42}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    assert config_manager.load_character_options() == DEFAULT_CHARACTER_OPTIONS
    options = {'size_percent': 160, 'movement_speed': 125, 'jump_height': 300, 'show_hitboxes': False,
               'movement_range_extra_percent': 50}
    config_manager.save_config(1280, 720, character_options=options)
    assert config_manager.load_character_options() == options
    assert json.loads(path.read_text(encoding='utf-8'))['extra'] == 42
    config_manager.save_config(1920, 1080)
    assert config_manager.load_character_options() == options
    with pytest.raises(ValueError):
        config_manager.save_config(1920, 1080, character_options={'movement_speed': float('inf')})
    assert config_manager.load_character_options() == options


@pytest.fixture
def real_character(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('CLOUDY_RENDERER', 'sprite')
    monkeypatch.setattr(character_widget, 'HAS_PYGETWINDOW', False)
    monkeypatch.setattr(character_widget.QtPerceptionReceiver, 'start', lambda self: False)
    path = tmp_path / 'ai.json'
    path.write_text('{"api_key":"","model":"test"}', encoding='utf-8')
    monkeypatch.setattr(ai_settings, 'GEMINI_PATHS', (path,))
    settings = QSettings(str(tmp_path / 'voice.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(dialogue_system, 'SupertonicTTS', lambda: SupertonicTTS(settings=settings))
    host = CharacterWidget(screen_width=1920, screen_height=1080)
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    host.show_debug = False
    for name in ('timer', 'emotion_timer', 'move_timer', 'drag_timer', '_move_timer', '_gravity_timer', '_activity_monitor_timer'):
        getattr(host, name).stop()
    host.animation_controller.stop()
    ground = next(surface for surface in host.surfaces if surface.name == 'ground')
    host.move(400, ground.y_level - host.height())
    host.on_ground = True
    host.current_surface = ground
    yield host, app
    host.close()


@pytest.mark.parametrize('scale', [50, 150, 200])
def test_scaled_size_preserves_feet_hit_region_and_sprite_frames(real_character, scale):
    host, app = real_character
    feet = host.current_surface.y_level
    center = host.x() + host.width() / 2
    host.apply_character_settings(*host._get_screen_dimensions(), 'Russell (기본)', size_percent=scale)
    assert (host.width(), host.height()) == (round(150 * scale / 100), round(200 * scale / 100))
    body = host._character_visual_rect()
    assert host.y() + body.y() + body.height() == feet
    assert abs(host.x() + host.width() / 2 - center) <= .5
    assert host.on_ground
    host.on_sprite_frame_changed(host.current_pixmap)
    assert host.width() == round(150 * scale / 100)
    assert host.pixmap().size() == host.size()
    host.show()
    app.processEvents()
    QTest.mousePress(host, Qt.MouseButton.LeftButton, pos=host.rect().bottomRight())
    assert host.is_dragging
    QTest.mouseRelease(host, Qt.MouseButton.LeftButton)


def test_settings_slider_numeric_input_apply_and_cancel(real_character):
    _, _app = real_character
    dialog = SettingsDialog(local_settings())
    dialog.character_sliders['size_percent'].setValue(150)
    dialog.character_inputs['movement_speed'].setValue(125)
    dialog.character_sliders['jump_height'].setValue(300)
    dialog.character_inputs['movement_range_extra_percent'].setValue(50)
    assert dialog.character_inputs['size_percent'].value() == 150
    assert dialog.character_sliders['movement_speed'].value() == 125
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.submit(False)
    values = emitted[0]['local']['character']
    assert (values['size_percent'], values['movement_speed'], values['jump_height']) == (150, 125, 300)
    assert values['movement_range_extra_percent'] == 50
    assert '200%' in dialog.movement_range_preview.text()
    dialog.complete('saved', local={'character': values})
    assert dialog.changes()['local'] == {}
    dialog.character_inputs['movement_speed'].setValue(300)
    dialog.character_inputs['movement_range_extra_percent'].setValue(-50)
    dialog.reject()
    assert dialog.local_baseline['character']['movement_speed'] == 125
    assert dialog.local_baseline['character']['movement_range_extra_percent'] == 50


def test_saved_character_options_apply_at_startup(real_character, tmp_path, monkeypatch):
    path = tmp_path / 'character.json'
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    options = {'size_percent': 200, 'movement_speed': 125, 'jump_height': 300,
               'movement_range_extra_percent': 50}
    config_manager.save_config(1920, 1080, character_options=options)
    restarted = CharacterWidget(character_options=config_manager.load_character_options())
    try:
        assert (restarted.width(), restarted.height()) == (300, 400)
        assert restarted.movement_speed == 125 and restarted.jump_height == 300
        assert restarted.movement_range_extra_percent == 50
    finally:
        restarted.close()


def test_hitbox_checkbox_apply_cancel_and_reload(real_character, tmp_path, monkeypatch):
    host, _app = real_character
    path = tmp_path / 'character.json'
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    dialog = SettingsDialog(local_settings())
    assert dialog.show_hitboxes.isChecked()
    dialog.show_hitboxes.setChecked(False)
    changes = dialog.changes()['local']['character']
    assert changes['show_hitboxes'] is False
    config_manager.save_config(changes.pop('width'), changes.pop('height'),
                               changes.pop('personality'), character_options=changes)
    host.is_moving = True
    before = host.pos()
    host.apply_character_settings(*host._get_screen_dimensions(), 'Russell (기본)', **changes)
    assert host.pos() == before and host.is_moving
    assert not host.show_debug
    assert config_manager.load_character_options()['show_hitboxes'] is False
    reopened = CharacterWidget(character_options=config_manager.load_character_options())
    try:
        assert not reopened.show_debug
    finally:
        reopened.close()
    dialog.reject()
    assert dialog.local_baseline['character']['show_hitboxes'] is True


def test_diagnostics_use_host_coordinates_and_toggle_removes_all_pixels(real_character):
    host, _app = real_character
    host.add_surface(Surface('window_test', host.y() + 20, host.x() + 10,
                             host.x() + 100, 120, window_title='검증 창'))
    def paint():
        image = QImage(host.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        host._paint_debug(painter)
        painter.end()
        return image
    host.set_show_hitboxes(True)
    image = paint()
    # The yellow window is inside the host; the red border follows the painted
    # character rather than transparent host padding.
    assert image.pixelColor(30, 125).alpha() > 0
    rect = host._character_visual_rect()
    assert image.pixelColor(rect.right() - 1, rect.center().y()).red() > 200
    host.set_show_hitboxes(False)
    assert not any(paint().pixelColor(x, y).alpha() for x, y in [(30, 125), (148, 150), (10, 10)])


@pytest.mark.parametrize('size,extra,emotion,limit', [
    (100, 0, 'neutral', 200), (50, 0, 'neutral', 100),
    (200, 0, 'neutral', 400), (200, 50, 'neutral', 500),
    (100, -50, 'neutral', 100), (200, 50, 'joy', 250),
    (200, 50, 'sadness', 100),
])
@pytest.mark.parametrize('direction', [-1, 1])
def test_random_route_scales_with_size_plus_extra_and_keeps_emotion_difference(
        size, extra, emotion, limit, direction, monkeypatch):
    host = moving_host()
    host._x = 700
    host.size_percent = size
    host.movement_range_extra_percent = extra
    host.mood_system.emotion = emotion
    monkeypatch.setattr(character_widget.random, 'random', lambda: .5)
    sampled = []
    def choose(low, high):
        sampled.append((low, high))
        return direction * high
    monkeypatch.setattr(character_widget.random, 'randint', choose)
    host.random_move()
    assert sampled == [(-limit, limit)]
    assert host._target_x == 700 + direction * limit
    assert host.movement_speed == 80


@pytest.mark.parametrize('extra', [-50, -200])
def test_zero_or_negative_total_range_does_not_start_walking(extra, monkeypatch):
    host = moving_host()
    host.size_percent = 50
    host.movement_range_extra_percent = extra
    monkeypatch.setattr(character_widget.random, 'random', lambda: .5)
    host.random_move()
    assert not host.is_moving and host.x() == 200
    assert not host._move_timer.start.called


@pytest.mark.parametrize('direction', [-1, 1])
def test_expanded_random_range_still_respects_screen_edges(direction, monkeypatch):
    host = moving_host()
    host.size_percent = 200
    host.movement_range_extra_percent = 200
    host.mood_system.emotion = 'neutral'
    host._x = 10 if direction < 0 else 1760
    monkeypatch.setattr(character_widget.random, 'random', lambda: .5)
    monkeypatch.setattr(character_widget.random, 'randint', lambda low, high: direction * high)
    host.random_move()
    assert host._target_x == (0 if direction < 0 else 1770)


def test_extra_range_apply_does_not_interrupt_current_motion(real_character):
    host, _app = real_character
    host.is_moving = True
    before = host.pos()
    host.apply_character_settings(*host._get_screen_dimensions(), 'Russell (기본)',
                                  movement_range_extra_percent=50)
    assert host.movement_range_extra_percent == 50
    assert host.is_moving and host.pos() == before


def test_legacy_options_keep_size_and_default_to_no_extra_range(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps({'character_options': {'size_percent': 150, 'movement_speed': 125,
                                                      'jump_height': 300, 'show_hitboxes': False}}))
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    saved = config_manager.load_character_options()
    assert saved['movement_range_extra_percent'] == 0
    assert saved['size_percent'] == 150 and saved['movement_speed'] == 125


@pytest.mark.parametrize('invalid', [-201, 201, float('nan')])
def test_invalid_extra_range_does_not_overwrite_saved_options(tmp_path, monkeypatch, invalid):
    path = tmp_path / 'range.json'
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    config_manager.save_config(1920, 1080, character_options={'movement_range_extra_percent': 50})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        config_manager.save_config(1920, 1080, character_options={'movement_range_extra_percent': invalid})
    assert path.read_bytes() == before
