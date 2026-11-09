"""Exercise production physics without starting the desktop application."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QRect


tree = ast.parse(Path('character/character_widget.py').read_text(encoding='utf-8'))
widget = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CharacterWidget')
names = {'get_landing_surface', '_gravity_step', '_get_screen_geometry', '_clamp_position_to_screen'}
namespace = {'QRect': QRect, 'math': math, 'Surface': object}
exec(compile(ast.Module(body=[node for node in widget.body
                             if isinstance(node, ast.FunctionDef) and node.name in names],
                        type_ignores=[]), '<character physics>', 'exec'), namespace)


class Host:
    rig_view = None
    gravity = .6
    is_moving = False
    is_jumping = False

    def __init__(self, feet):
        self.px, self.py = 100, feet - 200
        self.velocity_y, self.velocity_x = 5, 0
        self.on_ground, self.current_surface = False, None
        self.surfaces = [SimpleNamespace(name='ground', y_level=1040, x_min=0, x_max=1920)]
        self._rig_landed = Mock()

    def x(self): return self.px
    def y(self): return self.py
    def move(self, x, y): self.px, self.py = x, y
    def _physics_body_rect(self): return QRect(10, 20, 100, 180)
    def _get_screen_dimensions(self): return 1920, 1080


for name in names:
    setattr(Host, name, namespace[name])
namespace['CharacterWidget'] = Host


@pytest.mark.parametrize('feet', [1041, 1060, 1080])
def test_release_inside_taskbar_recovers_once_and_remains_grounded(feet):
    host = Host(feet)
    for _ in range(240):
        host._gravity_step(.5)
    assert host.y() + 200 == 1040
    assert host.on_ground
    assert host.velocity_y == 0
    assert host.current_surface is host.surfaces[0]
    host._rig_landed.assert_called_once()


def test_side_entry_below_window_top_does_not_lift_character():
    host = Host(1000)
    host.surfaces.insert(0, SimpleNamespace(name='window', y_level=990, x_min=0, x_max=1920))
    assert host.get_landing_surface(host.y()).name == 'ground'


def test_upward_jump_below_ground_is_not_prematurely_landed():
    host = Host(1080)
    host.velocity_y = -8
    host._gravity_step(.5)
    assert not host.on_ground
    host._rig_landed.assert_not_called()
