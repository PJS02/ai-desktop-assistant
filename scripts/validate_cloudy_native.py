"""Render the real native view, check bounded residency and saved WebGL frames.

Run with the project's .venv Python. This tool never starts a browser.
"""
import argparse
from array import array
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PIL import Image, ImageChops, ImageStat
import numpy as np
from character.cloudy_rig_view import CloudyRigView
from character.rig_state import RIG_ACTIONS, RIG_EMOTIONS


def compare_png(reference, current):
    a, b = Image.open(reference).convert("RGBA"), Image.open(current).convert("RGBA")
    if a.size != b.size:
        raise AssertionError(f"Canvas dimensions differ: {a.size}, {b.size}")
    # Transparent RGB has no visible meaning. Compare premultiplied pixels.
    def premultiplied(image):
        channels = image.split()
        return Image.merge("RGBA", tuple(ImageChops.multiply(c, channels[3])
                                         for c in channels[:3]) + (channels[3],))
    a, b = premultiplied(a), premultiplied(b)
    difference = ImageChops.difference(a, b)
    stats = ImageStat.Stat(difference)
    changed = int(np.count_nonzero(np.max(np.asarray(difference), axis=2) > 8))
    return {"mean_absolute_rgba": stats.mean,
            "pixels_difference_over_8": changed,
            "fraction_difference_over_8": changed / (a.width * a.height)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--output", default="integration-validation/native")
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    view = CloudyRigView()
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    view.resize(720, 1080)
    view.set_validation_state({"action": "idle", "time": 0, "companion": False})
    view.show()
    app.processEvents()
    source_hashes = dict(view.planner.source_hashes)
    report = {"source_hashes": source_hashes, "captures": [], "matrix_frames": 0,
              "errors": [], "matrix_plan_ms": []}
    reference = view.rig_root / "validation-left-elbow-v30/final-full"
    try:
        for side, yaw in (("left", -65), ("right", 65)):
            for moment in (0, .34, .38, .63, .76, .91, 1.25, 1.8, 3.5):
                state = {"action": "wave", "time": moment, "yaw": yaw, "companion": False}
                view.set_validation_state(state)
                image = view.grabFramebuffer()
                if view.stats()["error"]:
                    raise RuntimeError(view.stats()["error"])
                filename = f"{side}-{round(moment * 1000):04}.png"
                path = output / filename
                image.save(str(path))
                before = reference / side / filename
                record = {"state": state, "file": str(path), "reference": str(before)}
                if before.is_file():
                    record["comparison"] = compare_png(before, path)
                report["captures"].append(record)
        if args.matrix:
            for yaw, action, emotion, speaking in itertools.product(
                    (-65, 0, 65), sorted(RIG_ACTIONS), sorted(RIG_EMOTIONS), (False, True)):
                state = {"yaw": yaw, "action": action, "emotion": emotion,
                         "speaking": speaking, "speechTime": .91,
                         "time": .76, "companion": True}
                view.set_validation_state(state)
                view.grabFramebuffer()
                if view.stats()["error"]:
                    raise RuntimeError(f"{state}: {view.stats()['error']}")
                report["matrix_plan_ms"].append(view.stats()["plan_ms"])
                report["matrix_frames"] += 1
                if report["matrix_frames"] % 90 == 0:
                    print(f"Matrix {report['matrix_frames']}/810", flush=True)
            # Frame-bank churn: both sides of the full gesture, two passes.
            for _ in range(2):
                for yaw in (-65, 65):
                    for frame in range(93):
                        view.set_validation_state({"action": "wave", "time": frame / 20,
                                                   "yaw": yaw, "companion": False})
                        view.grabFramebuffer()
                        if view.stats()["error"]:
                            raise RuntimeError(view.stats()["error"])
        report["view_stats"] = view.stats()
        report["worker_memory"] = view.planner.stats()
        report["source_unchanged"] = all(
            hashlib.sha256((view.rig_root / file).read_bytes()).hexdigest() == digest
            for file, digest in source_hashes.items())
        if report["matrix_plan_ms"]:
            times = sorted(report["matrix_plan_ms"])
            report["matrix_plan_summary"] = {"median_ms": statistics.median(times),
                "p95_ms": times[int(len(times) * .95)], "max_ms": max(times)}
        print(json.dumps({k: v for k, v in report.items() if k in
              {"view_stats", "worker_memory", "source_unchanged", "matrix_frames", "matrix_plan_summary"}}, indent=2))
    except Exception as exc:
        report["errors"].append(str(exc))
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        view.release()
        view.close()


if __name__ == "__main__":
    main()
