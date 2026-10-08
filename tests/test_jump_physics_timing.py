"""Authored jump pose and elapsed-time physics across desktop scales."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect

from character import character_widget
from character.character_widget import CharacterWidget
from character.desktop_geometry import map_window_rectangle
from character.rig_planner import RigPlanner
from test_character_options import real_character
from test_surface_physics import SurfaceHost


@pytest.mark.parametrize('rate', [30, 60, 120])
@pytest.mark.parametrize('height', [20, 225, 450])
def test_exact_jump_height_and_landing_at_different_callback_rates(rate, height):
    host = SurfaceHost()
    host._y = 1240
    host.current_surface = host.surfaces[0]
    host.on_ground = True
    host.jump_height = height
    host.jump(force=True)
    origin, peak = 1240, host.y()
    for _ in range(rate * 4):
        host._apply_gravity(dt=1 / rate)
        peak = min(peak, host.y())
        if host.on_ground:
            break
    assert origin - peak == height
    assert host.on_ground and host.y() == origin


def flight_at_time(rate, *, jump=False):
    host = SurfaceHost()
    host._y = 500
    if jump:
        host.on_ground = True
        host.jump_height = 225
        host.jump(force=True)
    else:
        host.velocity_y = 4
    host.velocity_x = 8
    for _ in range(round(.4 * rate)):
        host._apply_gravity(dt=1 / rate)
    return host


@pytest.mark.parametrize('jump', [False, True])
def test_trajectory_matches_for_30_60_120_hz_and_delayed_callback(jump):
    hosts = [flight_at_time(rate, jump=jump) for rate in [30, 60, 120]]
    reference = hosts[0]
    for host in hosts[1:]:
        assert host.y() == reference.y()
        assert host.x() == reference.x()
        assert host.velocity_y == pytest.approx(reference.velocity_y)
        assert host.velocity_x == pytest.approx(reference.velocity_x)
    host = SurfaceHost()
    host._y = 500
    if jump:
        host.on_ground = True
        host.jump_height = 225
        host.jump(force=True)
    else:
        host.velocity_y = 4
    host.velocity_x = 8
    host._apply_gravity(dt=.4)
    assert (host.x(), host.y()) == (reference.x(), reference.y())


def test_delayed_fall_cannot_skip_thin_window_top():
    host = SurfaceHost()
    window = host.window()
    host._y, host.velocity_y = 300, 20
    host._apply_gravity(dt=.8)
    assert host.current_surface is window and host.y() == 600
    assert host.rig_view.actions.count(('land', False)) == 1


def test_live_timer_uses_elapsed_time_and_never_replays_dragged_time(monkeypatch):
    host = SurfaceHost()
    host._y, host.velocity_y = 500, 4
    clock = [100.0]
    host._gravity_last_time = clock[0]
    monkeypatch.setattr(character_widget.time, 'monotonic', lambda: clock[0])
    clock[0] += .4
    host._apply_gravity()
    reference = flight_at_time(60)
    # Reference includes horizontal throw; only vertical movement matters here.
    assert host.y() == reference.y()
    assert host.velocity_y == pytest.approx(reference.velocity_y)
    host.is_dragging = True
    clock[0] += .7
    host._apply_gravity()
    host.is_dragging = False
    before = host.y()
    clock[0] += .016
    host._apply_gravity()
    assert host.y() - before <= 1


def test_native_jump_phase_follows_velocity_and_landing():
    host = SurfaceHost()
    host._y, host.on_ground = 1240, True
    host.current_surface = host.surfaces[0]
    host.jump_height = 225
    phases = []
    host.rig_view.set_physics_jump_phase = lambda phase, **kwargs: phases.append((phase, kwargs))
    host.jump(force=True)
    for _ in range(150):
        host._apply_gravity(dt=1 / 60)
        if host.on_ground:
            break
    flight = [phase for phase, _ in phases if phase is not None]
    assert flight[0] == .15 and flight[-1] > .68
    assert all(later >= earlier for earlier, later in zip(flight, flight[1:]))
    assert phases[-1] == (None, {'landing': True})


def grounded_pose_host():
    host = SurfaceHost(QRect(20, 12, 110, 168))
    window = host.window()
    host.current_surface, host.on_ground = window, True
    host._y = 620
    host._grounded_body_bottom, host._grounded_surface_level = 180, 800
    host._physics_position_y = 620.0
    return host, window


def test_current_render_pose_aligns_feet_before_next_gravity_tick():
    host, window = grounded_pose_host()
    host.body = QRect(20, 12, 110, 188)
    CharacterWidget._align_grounded_pose(host)
    assert host.y() == 600
    assert host.y() + host.body.y() + host.body.height() == window.y_level
    assert host._physics_position_y == 600.0
    assert host._grounded_body_bottom == 200
    host._apply_gravity(dt=1 / 60)
    assert host.y() == 600 and host.current_surface is window
    assert ('land', False) not in host.rig_view.actions


@pytest.mark.parametrize('state', ['removed', 'moved_up', 'moved_down', 'side_exit',
                                 'rising', 'falling', 'dragging', 'closing', 'displaced'])
def test_render_pose_alignment_cannot_create_support_or_interrupt_flight(state):
    host, window = grounded_pose_host()
    host.body = QRect(20, 12, 110, 188)
    if state == 'removed':
        host.surfaces.remove(window)
    elif state == 'moved_up':
        window.y_level = 700
    elif state == 'moved_down':
        window.y_level = 900
    elif state == 'side_exit':
        host._x = 1100
    elif state == 'rising':
        host.is_jumping, host.velocity_y = True, -10
    elif state == 'falling':
        host.on_ground, host.velocity_y = False, 10
    elif state == 'dragging':
        host.is_dragging = True
    elif state == 'closing':
        host._character_closing = True
    else:
        host._y = 700
    before = (host.x(), host.y(), host._physics_position_y, host._grounded_body_bottom)
    CharacterWidget._align_grounded_pose(host)
    assert (host.x(), host.y(), host._physics_position_y, host._grounded_body_bottom) == before


def test_render_alignment_uses_existing_floor_when_new_window_appears_above():
    host, _window = grounded_pose_host()
    floor = host.surfaces[0]
    host.current_surface, host._y = floor, 1260
    host._grounded_surface_level = floor.y_level
    host.body = QRect(20, 12, 110, 188)
    host.window(1300)
    CharacterWidget._align_grounded_pose(host)
    assert host.y() == 1240 and host.current_surface is floor
    assert host.y() + 200 == floor.y_level


@pytest.mark.parametrize('scale', [1, 1.25, 1.5, 2])
def test_win32_windows_map_to_qt_coordinates_with_negative_monitor_origin(scale):
    physical_monitor = QRect(-2560, 0, 2560, 1440)
    logical_monitor = QRect(round(-2560 / scale), 0, round(2560 / scale), round(1440 / scale))
    raw_window = QRect(-2200, 180, 960, 600)
    rectangle = map_window_rectangle(raw_window, physical_monitor, logical_monitor)
    assert rectangle.x() == round(-2200 / scale)
    assert rectangle.y() == round(180 / scale)
    assert rectangle.width() == round(960 / scale)
    assert rectangle.height() == round(600 / scale)


@pytest.mark.parametrize('width,height', [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)])
def test_dynamic_full_screen_geometry_updates_ground(real_character, monkeypatch, width, height):
    host, _app = real_character
    geometry = QRect(-width, -100, width, height)
    screen = SimpleNamespace(geometry=lambda: geometry)
    monkeypatch.setattr(character_widget.QApplication, 'primaryScreen', lambda: screen)
    host._screen_auto_width = host._screen_auto_height = True
    assert host._get_screen_geometry() == geometry
    ground = next(surface for surface in host.surfaces if surface.name == 'ground')
    assert (ground.x_min, ground.x_max, ground.y_level) == (-width, 0, height - 100)
    host.move(-width - 300, height + 500)
    host._clamp_position_to_screen()
    body = host._physics_body_rect()
    assert host.x() + body.x() >= -width
    assert host.y() + body.y() + body.height() <= height - 100


@pytest.mark.parametrize('auto', [False, True])
def test_activity_range_recovers_after_display_shrinks_then_returns(real_character, monkeypatch, auto):
    host, _app = real_character
    geometry = [QRect(-2560, -100, 2560, 1440)]
    screen = SimpleNamespace(geometry=lambda: geometry[0])
    monkeypatch.setattr(character_widget.QApplication, 'primaryScreen', lambda: screen)
    host.custom_screen_width, host.custom_screen_height = 1920, 1080
    host._screen_auto_width = host._screen_auto_height = auto
    expected_large = (2560, 1440) if auto else (1920, 1080)
    assert host._get_screen_dimensions() == expected_large
    geometry[0] = QRect(-1280, -100, 1280, 720)
    assert host._get_screen_dimensions() == (1280, 720)
    assert (host.custom_screen_width, host.custom_screen_height) == (1920, 1080)
    geometry[0] = QRect(-2560, -100, 2560, 1440)
    assert host._get_screen_dimensions() == expected_large
    ground = next(surface for surface in host.surfaces if surface.name == 'ground')
    assert ground.y_level == expected_large[1] - 100


def test_applying_size_on_small_display_keeps_requested_activity_range(real_character, monkeypatch):
    host, _app = real_character
    geometry = [QRect(0, 0, 2560, 1440)]
    screen = SimpleNamespace(geometry=lambda: geometry[0])
    monkeypatch.setattr(character_widget.QApplication, 'primaryScreen', lambda: screen)
    host.custom_screen_width, host.custom_screen_height = 1920, 1080
    host._screen_auto_width = host._screen_auto_height = False
    geometry[0] = QRect(0, 0, 1280, 720)
    host.apply_character_settings(1920, 1080, 'Russell (기본)', size_percent=150)
    assert host._get_screen_dimensions() == (1280, 720)
    assert (host.custom_screen_width, host.custom_screen_height) == (1920, 1080)
    assert not host._screen_auto_width and not host._screen_auto_height
    geometry[0] = QRect(0, 0, 2560, 1440)
    assert host._get_screen_dimensions() == (1920, 1080)


def test_authored_jump_is_sampled_by_physics_and_removes_both_root_translations(real_character):
    _host, _app = real_character
    planner = RigPlanner()
    samples = []
    try:
        for phase in [.15, .30, .425, .55, .70]:
            state = {'action': 'fall', 'time': 123, 'externalPhysics': True,
                     'jumpActive': True, 'jumpPhase': phase, 'authoredJump': True,
                     'emotion': 'sad'}
            sample = planner.sample(state)
            raw = planner.sample({'action': 'jump', 'time': phase * 2.4, 'emotion': 'sad'})['pose']
            flight_height = 62 * raw['airborne']
            assert sample['pose']['bodyY'] == pytest.approx(raw['bodyY'] + flight_height)
            for foot in ['footNearY', 'footFarY']:
                assert sample['pose'][foot] == pytest.approx(raw[foot] + flight_height)
            for channel in ['armNear', 'armFar', 'elbowNear', 'elbowFar', 'lean', 'headAngle']:
                assert sample['pose'][channel] == raw[channel]
            assert sample['pose']['framingZoom'] == 1
            samples.append(sample['pose'])
        assert abs(samples[2]['armNear'] - samples[0]['armNear']) > 100
    finally:
        planner.engine.collectGarbage()
