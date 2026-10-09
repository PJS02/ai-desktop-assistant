"""Camera-safe movement ranges must not resize or distort the displayed hand."""
import math
import sys

import pytest
from PyQt6.QtCore import QRect

from hand_overlay.model import Hand
from hand_overlay.renderer import desktop_geometry, palm_center


def centered_hand(x, y, *, shaped=False):
    if not shaped:
        return Hand("Right", tuple((x, y, 0.0) for _ in range(21)))
    points = tuple(((i % 3 - 1) * .025, (i // 3 - 3) * .015, 0.0)
                   for i in range(21))
    cx, cy = palm_center(Hand("Right", points))
    return Hand("Right", tuple((px - cx + x, py - cy + y, z) for px, py, z in points))


@pytest.mark.parametrize("x,y,corner", [
    (.15, .15, "topLeft"), (.85, .15, "topRight"),
    (.15, .85, "bottomLeft"), (.85, .85, "bottomRight"),
])
def test_seventy_percent_camera_boundaries_reach_all_desktop_corners(x, y, corner):
    screen = QRect(0, 0, 1920, 1080)
    geometry, _ = desktop_geometry(centered_hand(x, y), screen, 4 / 3, range_percent=70)
    assert screen.contains(geometry)
    assert getattr(geometry, corner)() == getattr(screen, corner)()


@pytest.mark.parametrize("boundary,outside", [(.15, -.2), (.85, 1.2)])
def test_movement_outside_safe_camera_range_stays_at_edge(boundary, outside):
    screen = QRect(0, 0, 1920, 1080)
    edge, _ = desktop_geometry(centered_hand(boundary, boundary), screen, 4 / 3,
                               range_percent=70)
    beyond, _ = desktop_geometry(centered_hand(outside, outside), screen, 4 / 3,
                                 range_percent=70)
    assert beyond == edge


def test_full_range_default_preserves_existing_mapping():
    screen = QRect(0, 0, 1920, 1080)
    original, _ = desktop_geometry(centered_hand(.25, .7), screen, 4 / 3)
    explicit, _ = desktop_geometry(centered_hand(.25, .7), screen, 4 / 3,
                                   range_percent=100)
    assert original == explicit == QRect(448, 724, 64, 64)


def test_range_changes_position_without_changing_hand_shape_or_size():
    screen = QRect(0, 0, 1920, 1080)
    hand = centered_hand(.3, .4, shaped=True)
    full, full_points = desktop_geometry(hand, screen, 4 / 3, range_percent=100)
    safe, safe_points = desktop_geometry(hand, screen, 4 / 3, range_percent=70)
    assert full.topLeft() != safe.topLeft()
    assert full.size() == safe.size()
    for i, j in ((0, 4), (4, 8), (8, 12), (12, 20)):
        a, b = full_points[i] - full_points[j], safe_points[i] - safe_points[j]
        assert a.x() == pytest.approx(b.x())
        assert a.y() == pytest.approx(b.y())


def test_hand_size_setting_remains_independent_of_camera_range():
    screen = QRect(0, 0, 1920, 1080)
    hand = centered_hand(.5, .5, shaped=True)
    _, small = desktop_geometry(hand, screen, 4 / 3, scale=.5, range_percent=70)
    _, large = desktop_geometry(hand, screen, 4 / 3, scale=1, range_percent=70)
    small_distance = math.hypot((small[4] - small[8]).x(), (small[4] - small[8]).y())
    large_distance = math.hypot((large[4] - large[8]).x(), (large[4] - large[8]).y())
    assert large_distance == pytest.approx(small_distance * 2)


def test_safe_range_uses_logical_monitor_coordinates_with_negative_origin():
    # QRect is in Qt logical pixels. Raster DPI scaling happens after this mapping.
    screen = QRect(-1280, -160, 1280, 720)
    low, _ = desktop_geometry(centered_hand(.15, .15), screen, 4 / 3,
                              range_percent=70)
    high, _ = desktop_geometry(centered_hand(.85, .85), screen, 4 / 3,
                               range_percent=70)
    middle, points = desktop_geometry(centered_hand(.5, .5), screen, 4 / 3,
                                      range_percent=70)
    assert low.topLeft() == screen.topLeft()
    assert high.bottomRight() == screen.bottomRight()
    assert points[0].x() + middle.x() == screen.x() + screen.width() / 2
    assert points[0].y() + middle.y() == screen.y() + screen.height() / 2


@pytest.mark.parametrize("value", [0, -1, 101, float("nan"), float("inf")])
def test_invalid_camera_range_is_rejected(value):
    with pytest.raises(ValueError):
        desktop_geometry(centered_hand(.5, .5), QRect(0, 0, 1920, 1080), 4 / 3,
                         range_percent=value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native hand rasterization")
@pytest.mark.parametrize("ratio", [1.0, 1.25, 2.0])
def test_dpi_changes_raster_resolution_without_changing_logical_hand_position(monkeypatch, ratio):
    from PyQt6.QtWidgets import QApplication
    from hand_overlay import native_surface
    from hand_overlay.renderer import DesktopHandWindow

    app = QApplication.instance() or QApplication([])

    class Surface:
        hwnd = 17
        visible = False

        def present(self, image, geometry, screen):
            self.image = image
            self.geometry = geometry
            self.visible = True

        def hide(self):
            self.visible = False

        def close(self):
            self.hwnd = None
            self.visible = False

    class Screen:
        def geometry(self):
            return QRect(-1280, -160, 1280, 720)

        def devicePixelRatio(self):
            return ratio

    monkeypatch.setattr(native_surface, "LayeredSurface", Surface)
    window = DesktopHandWindow()
    try:
        window.show_hand(centered_hand(.5, .5, shaped=True), Screen(), 4 / 3, 1.0,
                         False, smooth_motion=False, range_percent=70)
        assert window.handles == (17,)
        image = window._surface.image
        assert image.width() == round(window.width() * ratio)
        assert image.height() == round(window.height() * ratio)
        assert image.devicePixelRatio() == ratio
        global_x = sum(window.points[i].x() + window.x() for i in (0, 5, 9, 13, 17)) / 5
        global_y = sum(window.points[i].y() + window.y() for i in (0, 5, 9, 13, 17)) / 5
        assert global_x == pytest.approx(-640, abs=1)
        assert global_y == pytest.approx(200, abs=1)
    finally:
        window.close()
        app.processEvents()
    assert window.handles == ()
