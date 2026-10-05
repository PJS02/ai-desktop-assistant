"""Interactive verification of the production host without external AI/camera work.

The CharacterWidget, renderer, input handlers, mood and gravity are unchanged.
Only automatic external-service/window monitoring is disabled for this session.
Manual thinking at startup holds the moving window still for UI inspection.
"""
from pathlib import Path
import json
import argparse
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from character.character_widget import CharacterWidget

app = QApplication([])
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--action", choices=("thinking", "sleep", "wave", "idle"), default="thinking")
parser.add_argument("--yaw", type=float, default=0)
args = parser.parse_args()
host = CharacterWidget()
for name in ("_activity_monitor_timer", "_window_scan_timer"):
    timer = getattr(host, name, None)
    if timer is not None:
        timer.stop()
host.perception_receiver.stop()
host.move(700, host.custom_screen_height - host.height())
host.on_ground = True
host.velocity_x = host.velocity_y = 0
host.show()
host._set_rig_direction(args.yaw)
host._play_rig_action(args.action)

report_path = Path(__file__).with_name("host-ui-observations.json")
start = time.monotonic()
samples = []
previous = None

def record():
    global previous
    state = {
        "seconds": round(time.monotonic() - start, 3),
        "action": host.current_action,
        "manual": host._rig_manual_action,
        "yaw": host._rig_preferred_yaw,
        "dragging": host.is_dragging,
        "on_ground": host.on_ground,
        "moving": host.is_moving,
        "x": host.x(), "y": host.y(),
        "native": host.rig_view is not None,
        "debug": host.show_debug,
    }
    samples.append(state)
    key = tuple(state[k] for k in state if k != "seconds")
    if key != previous:
        print(json.dumps(state), flush=True)
        previous = key
    report_path.write_text(json.dumps({"setup": __doc__, "samples": samples}, indent=2), encoding="utf-8")

timer = QTimer()
timer.timeout.connect(record)
timer.start(100)
app.aboutToQuit.connect(timer.stop)
app.exec()
