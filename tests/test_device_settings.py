from pathlib import Path
import sys
from types import SimpleNamespace


MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / "medeapipe_capstone"
if str(MEDIAPIPE_ROOT) not in sys.path:
    sys.path.append(str(MEDIAPIPE_ROOT))

from app.device_settings import (  # noqa: E402
    load_device_settings,
    merge_camera_candidates,
    save_device_settings,
    select_saved_camera,
    select_saved_microphone,
)
from recognition import holistic_tracker as tracker  # noqa: E402


def test_device_settings_round_trip(tmp_path):
    path = tmp_path / "config" / "device_settings.json"
    settings = {
        "camera": {"index": 1, "backend_label": "DirectShow"},
        "microphone": {"label": "index 2 / USB Mic", "name": "USB Mic"},
    }

    save_device_settings(settings, path)

    assert load_device_settings(path) == settings


def test_invalid_device_settings_fall_back_to_empty(tmp_path):
    path = tmp_path / "device_settings.json"
    path.write_text("not-json", encoding="utf-8")

    assert load_device_settings(path) == {}


def test_saved_camera_prefers_backend_then_index_then_first():
    cameras = [
        {"index": 0, "backend_label": "DirectShow"},
        {"index": 1, "backend_label": "Media Foundation"},
    ]

    assert select_saved_camera(
        cameras,
        {"index": 1, "backend_label": "Media Foundation"},
    ) == cameras[1]
    assert select_saved_camera(
        cameras,
        {"index": 1, "backend_label": "Unavailable"},
    ) == cameras[1]
    assert select_saved_camera(cameras, {"index": 9}) == cameras[0]


def test_active_camera_is_kept_when_full_scan_cannot_reopen_it():
    active_camera = {"index": 1, "backend_label": "DirectShow"}
    discovered = [{"index": 0, "backend_label": "DirectShow"}]

    merged = merge_camera_candidates(discovered, active_camera)

    assert merged == [active_camera, discovered[0]]


def test_active_camera_is_not_duplicated_in_full_camera_list():
    active_camera = {"index": 1, "backend_label": "DirectShow"}
    discovered = [active_camera, {"index": 0, "backend_label": "DirectShow"}]

    merged = merge_camera_candidates(discovered, active_camera)

    assert merged == discovered


def test_saved_microphone_survives_device_index_change():
    microphones = ["index 0 / Built-in Mic", "index 3 / USB Mic"]

    assert select_saved_microphone(
        microphones,
        {"label": "index 1 / USB Mic", "name": "USB Mic"},
    ) == "index 3 / USB Mic"
    assert select_saved_microphone(microphones, {}) == microphones[0]


def test_fast_camera_discovery_tries_saved_device_first(monkeypatch):
    attempts = []
    monkeypatch.setattr(
        tracker,
        "webcam_backends",
        lambda _name: [("DirectShow", 1), ("Media Foundation", 2)],
    )

    def fake_open(index, backend, backend_label, width, height):
        attempts.append((index, backend_label))
        if index != 2 or backend_label != "Media Foundation":
            return None
        cap = type("FakeCapture", (), {"release": lambda self: None})()
        return {
            "cap": cap,
            "frame": object(),
            "index": index,
            "backend": backend,
            "backend_label": backend_label,
        }

    monkeypatch.setattr(tracker, "try_open_webcam", fake_open)
    settings = SimpleNamespace(
        camera_backend="auto",
        camera_width=1280,
        camera_height=720,
    )

    result = tracker.discover_webcams(
        settings,
        stop_after_first=True,
        preferred_index=2,
        preferred_backend_label="Media Foundation",
    )

    assert attempts == [(2, "Media Foundation")]
    assert result[0]["index"] == 2
