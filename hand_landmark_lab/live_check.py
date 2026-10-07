"""Optional verification of this app's live hand windows. Never saves camera video."""
import ctypes
import json
from pathlib import Path
import time

from PyQt6.QtCore import QTimer


def install(control, seconds: float):
    started = time.monotonic()
    report = {"configured_max_hands": control.max_hands.value(), "max_tracked_hands": 0,
              "max_visible_hand_windows": 0, "full_frame_matches_native_buffer": True,
              "samples": 0, "saved_landmark_frame": False}
    positions = set()
    output = Path(__file__).parent / "verification"
    output.mkdir(exist_ok=True)
    timer = QTimer(control)
    timer.setInterval(100)

    def check():
        snapshot = control.tracker.snapshot() if control.tracker else None
        windows = [window for window in control.display.desktop_windows if window.isVisible()]
        report["samples"] += 1
        report["max_visible_hand_windows"] = max(report["max_visible_hand_windows"], len(windows))
        if snapshot:
            report["max_tracked_hands"] = max(report["max_tracked_hands"], len(snapshot.hands))
            report.update(frames=snapshot.frames, fps=round(snapshot.fps, 1), error=snapshot.error)
        for window in windows:
            positions.add((window.x(), window.y()))
            image = window._image
            if image is not None and window._surface:
                actual = ctypes.string_at(window._surface.buffer, image.sizeInBytes())
                expected = image.constBits().asstring(image.sizeInBytes())
                report["full_frame_matches_native_buffer"] &= actual == expected
            if image is not None and snapshot and snapshot.frames >= 20 and not report["saved_landmark_frame"]:
                report["saved_landmark_frame"] = image.save(str(output / "live-hand.png"))
        if time.monotonic() - started >= seconds:
            timer.stop()
            report["distinct_window_positions"] = len(positions)
            report["hand_rendering_observed"] = report["max_visible_hand_windows"] > 0
            (output / "live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("LIVE_CHECK " + json.dumps(report), flush=True)

    timer.timeout.connect(check)
    timer.start()
    return timer
