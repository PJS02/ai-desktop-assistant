"""Regressions for downward-only window landings and full-screen body bounds."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect

from character import character_widget
from character.character_widget import CharacterWidget, Surface
from test_character_rig_host import HostHarness
from test_character_options import real_character


class SurfaceHost(HostHarness):
    get_landing_surface = CharacterWidget.get_landing_surface
    _clamp_position_to_screen = CharacterWidget._clamp_position_to_screen

    def __init__(self, body=None):
        super().__init__()
        self.body = body or QRect(0, 0, 150, 200)
        self.surfaces = [Surface('ground', 1440, 0, 2560)]
        self.current_surface = None
        self.on_ground = False

    def _character_visual_rect(self):
        return self.body

    def _get_screen_dimensions(self):
        return 2560, 1440

    def window(self, y=800, left=100, right=1000):
        window = Surface('window_test', y, left, right)
        self.surfaces.append(window)
        return window


def fall_until_grounded(host, ticks=200):
    for _ in range(ticks):
        host._apply_gravity()
        if host.on_ground:
            return
    pytest.fail('Character did not land')


def test_downward_crossing_lands_once_and_chooses_first_surface():
    host = SurfaceHost()
    first = host.window()
    host.window(810)
    host._y, host.velocity_y = 599, 20
    host._apply_gravity()
    assert host.on_ground and host.current_surface is first
    assert host.y() == 600
    for _ in range(5):
        host._apply_gravity()
    assert host.rig_view.actions.count(('land', False)) == 1


@pytest.mark.parametrize('motion', ['fall_below_top', 'side_entry', 'jump_upwards'])
def test_no_snap_from_below_or_side_or_while_rising(motion):
    host = SurfaceHost()
    window = host.window(left=500)
    host._x, host._y = 550, 650
    host.velocity_y = 4
    if motion == 'side_entry':
        host._x, host.velocity_x = 340, 20
    elif motion == 'jump_upwards':
        host._y = 610
        host.is_jumping = True
        host.velocity_y = -12
        host._jump_physics_y, host._jump_apex_y = 610.0, 300.0
    before_y = host.y()
    host._apply_gravity()
    assert not host.on_ground and host.current_surface is not window
    assert host.y() != 600
    if motion == 'jump_upwards':
        assert host.y() < before_y and host.is_jumping
    else:
        assert host.y() >= before_y


def test_new_window_above_feet_cannot_lift_grounded_character():
    host = SurfaceHost()
    host._y = 1240
    fall_until_grounded(host)
    host.window(1200)
    host._apply_gravity()
    assert host.y() == 1240
    assert host.current_surface.name == 'ground'


@pytest.mark.parametrize('change', ['removed', 'moved_up', 'walked_off'])
def test_lost_support_starts_falling_without_teleport(change):
    host = SurfaceHost()
    window = host.window()
    host._y, host.velocity_y = 599, 2
    fall_until_grounded(host)
    if change == 'removed':
        host.surfaces.remove(window)
    elif change == 'moved_up':
        window.y_level = 700
    else:
        host._x = 1100
    before_y = host.y()
    host._apply_gravity()
    assert not host.on_ground and host.current_surface is None
    assert host.y() >= before_y and host.velocity_y > 0
    fall_until_grounded(host)
    assert host.current_surface.name == 'ground'


def test_touching_horizontal_edge_without_overlap_is_not_a_landing():
    host = SurfaceHost()
    host.window(left=500)
    host._x, host._y, host.velocity_y = 350, 599, 10
    host._apply_gravity()
    assert not host.on_ground


def test_window_moved_down_is_reached_by_falling_instead_of_following():
    host = SurfaceHost()
    window = host.window()
    host._y, host.velocity_y = 599, 2
    fall_until_grounded(host)
    window.y_level = 900
    host._apply_gravity()
    assert not host.on_ground and host.y() < 700
    fall_until_grounded(host)
    assert host.current_surface is window and host.y() == 700


def test_window_landing_uses_painted_feet_with_transparent_padding():
    host = SurfaceHost(QRect(20, 12, 110, 168))
    window = host.window()
    host._y, host.velocity_y = 619, 8
    host._apply_gravity()
    assert host.on_ground and host.current_surface is window
    assert host.y() == 620
    assert host.y() + host.body.y() + host.body.height() == 800


def test_body_feet_reach_qhd_bottom_despite_transparent_padding():
    host = SurfaceHost(QRect(20, 12, 110, 168))
    host._y = 1200
    fall_until_grounded(host)
    assert host.y() + host.body.y() + host.body.height() == 1440
    assert host.y() + host.height() > 1440
    host._clamp_position_to_screen()
    assert host.y() == 1260
    # A pose changing the foot offset keeps the standing body on the floor.
    host.body = QRect(20, 12, 110, 163)
    host._apply_gravity()
    assert host.on_ground and host.y() == 1265


@pytest.mark.parametrize('x,y,expected', [
    (-100, -100, (-20, -12)), (2600, 1500, (2430, 1260)),
])
def test_screen_clamp_uses_body_instead_of_transparent_window(x, y, expected):
    host = SurfaceHost(QRect(20, 12, 110, 168))
    host._x, host._y = x, y
    host._clamp_position_to_screen()
    assert (host.x(), host.y()) == expected


def test_settings_use_full_qhd_geometry_not_taskbar_work_area(real_character, monkeypatch):
    host, _app = real_character
    screen = SimpleNamespace(geometry=lambda: QRect(0, 0, 2560, 1440),
                             availableGeometry=lambda: QRect(0, 0, 2560, 1392))
    monkeypatch.setattr(character_widget.QApplication, 'primaryScreen', lambda: screen)
    host.apply_character_settings(2560, 1440, 'Russell (기본)')
    assert host._get_screen_dimensions() == (2560, 1440)
    assert next(s for s in host.surfaces if s.name == 'ground').y_level == 1440
    restarted = CharacterWidget(screen_width=2560, screen_height=1440)
    try:
        assert restarted._get_screen_dimensions() == (2560, 1440)
        assert next(s for s in restarted.surfaces if s.name == 'ground').y_level == 1440
    finally:
        restarted.close()
