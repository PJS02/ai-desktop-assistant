"""Camera-free UI check; previews use synthetic coordinates, never a real camera."""
import json
import math
import ctypes
from pathlib import Path

from PIL import Image, ImageDraw
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app import ControlWindow
from renderer import LandmarkWindow, palm_center
from tracker import Hand, Snapshot, demo_snapshot


def shifted_hand(x, y, label="Right"):
    base = demo_snapshot().hands[0]
    cx, cy = palm_center(base)
    points = tuple((px + x - cx, py + y - cy, z) for px, py, z in base.points)
    return Hand(label, points)


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    display = LandmarkWindow()
    control = ControlWindow(display, demo=True)
    control.camera.setValue(2)
    control.backend.setCurrentIndex(control.backend.findData("dshow"))
    output = Path(__file__).parent / "verification"
    output.mkdir(exist_ok=True)
    display.show()
    control.show()
    app.processEvents()
    assert display.grab().save(str(output / "demo.png"))
    geometry = display.geometry()
    control.overlay.setChecked(True)
    app.processEvents()
    assert display.overlay and not display.isVisible()
    visible = [w for w in display.desktop_windows if w.isVisible()]
    assert len(visible) == 1
    window = visible[0]
    assert window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    screen = control.screen().geometry()
    assert window.width() * window.height() < screen.width() * screen.height() / 10
    image = window.grab().toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.save(str(output / "desktop-hand.png"))
    assert control.grab().save(str(output / "controls.png"))

    # Render a different pose into the same retained surface, then check cleared alpha.
    previous_frame = window._image.copy()
    original = demo_snapshot().hands[0]
    curled = Hand(original.label, tuple((x, y + .3, z) if i in (6, 7, 8, 10, 11, 12, 14, 15, 16, 18, 19, 20)
                                       else (x, y, z) for i, (x, y, z) in enumerate(original.points)))
    display.set_snapshot(Snapshot(hands=(curled,)))
    window.advance(snap=True)
    current_frame = window._image
    cleared_pixel = any(previous_frame.pixelColor(x, y).alpha() > 160
                        and current_frame.pixelColor(x, y).alpha() == 0
                        for x in range(0, min(previous_frame.width(), current_frame.width()), 2)
                        for y in range(0, min(previous_frame.height(), current_frame.height()), 2))
    assert cleared_pixel
    if window._surface:
        actual = ctypes.string_at(window._surface.buffer, current_frame.sizeInBytes())
        assert actual == current_frame.constBits().asstring(current_frame.sizeInBytes())

    capacity = window.size()
    for i in range(20):
        display.set_snapshot(Snapshot(hands=(Hand(curled.label,
                             tuple((x + i * .001, y, z) for x, y, z in curled.points)),)))
        window.advance(snap=True)
        assert window.size() == capacity

    display.set_snapshot(Snapshot(hands=(shifted_hand(.1, .2),)))
    app.processEvents()
    first_position = window.pos()
    display.set_snapshot(Snapshot(hands=(shifted_hand(.9, .8),)))
    app.processEvents()
    assert window.x() > first_position.x() and window.y() > first_position.y()

    # Two hands get independent small windows and retain them when detection order changes.
    right, left = shifted_hand(.2, .5), shifted_hand(.8, .5, "Left")
    display.set_snapshot(Snapshot(hands=(right, left)))
    app.processEvents()
    assignments = {w.hand.label: w for w in display.desktop_windows}
    assert all(w.isVisible() for w in assignments.values())
    assert assignments["Right"].x() < assignments["Left"].x()
    display.set_snapshot(Snapshot(hands=(left, right)))
    app.processEvents()
    assert all(w.hand.label == label for label, w in assignments.items())

    # A simulated desktop illustration using rendered hand windows; not a screen capture.
    frames = []
    for i in range(36):
        phase = i / 36 * 2 * math.pi
        display.set_snapshot(Snapshot(hands=(shifted_hand(.5 + .38 * math.sin(phase),
                                                       .5 - .3 * math.cos(phase)),)))
        app.processEvents()
        active = next(w for w in display.desktop_windows if w.isVisible())
        pixels = active.grab().toImage().convertToFormat(image.Format.Format_RGBA8888)
        data = pixels.bits().asstring(pixels.sizeInBytes())
        cutout = Image.frombytes("RGBA", (pixels.width(), pixels.height()), data,
                                 "raw", "RGBA", pixels.bytesPerLine())
        canvas = Image.new("RGBA", (960, 540), "#101923")
        draw = ImageDraw.Draw(canvas)
        for x in range(0, 960, 80):
            draw.line((x, 0, x, 540), fill="#243342")
        for y in range(0, 540, 60):
            draw.line((0, y, 960, y), fill="#243342")
        draw.text((16, 14), "DESKTOP HAND - SYNTHETIC COORDINATES / NOT LIVE CAMERA", fill="#ccd9e6")
        ratio = min(960 / screen.width(), 540 / screen.height())
        cutout = cutout.resize((max(1, round(cutout.width * ratio)),
                               max(1, round(cutout.height * ratio))), Image.Resampling.LANCZOS)
        x = round((active.x() - screen.x()) * ratio)
        y = round((active.y() - screen.y()) * ratio)
        canvas.alpha_composite(cutout, (x, y))
        frames.append(canvas.convert("RGB"))
    frames[0].save(output / "movement-demo.gif", save_all=True, append_images=frames[1:],
                   duration=60, loop=0)

    display.set_snapshot(Snapshot())
    app.processEvents()
    assert all(not w.isVisible() for w in display.desktop_windows)
    control.overlay.setChecked(False)
    app.processEvents()
    assert display.isVisible() and display.geometry() == geometry
    control.overlay.setChecked(True)
    display.set_snapshot(demo_snapshot())
    app.processEvents()
    native_handles = [w._surface.hwnd for w in display.desktop_windows if w._surface]
    control.close()
    app.processEvents()
    assert not display.isVisible() and not control.isVisible()
    assert all(not w.isVisible() for w in display.desktop_windows)
    if native_handles:
        from native_surface import user, signature, HANDLE, w
        signature(user, "IsWindow", w.BOOL, HANDLE)
        assert all(not user.IsWindow(hwnd) for hwnd in native_handles)
    print(json.dumps({"small_hand_windows": "pass", "transparent_alpha": "pass",
                      "previous_pose_alpha_cleared": "pass", "native_frame_replaced": "pass",
                      "retained_window_dimensions": "pass", "native_windows_destroyed": "pass",
                      "click_through_flag": "pass", "full_screen_position_mapping": "pass",
                      "two_independent_hands": "pass", "lost_hand_hidden": "pass",
                      "preview_geometry_restored": "pass", "close_all_windows": "pass"}))


if __name__ == "__main__":
    main()
