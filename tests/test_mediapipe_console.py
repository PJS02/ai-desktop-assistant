from io import StringIO
from pathlib import Path
import queue
import sys
from unittest.mock import Mock


MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / "medeapipe_capstone"
if str(MEDIAPIPE_ROOT) not in sys.path:
    sys.path.append(str(MEDIAPIPE_ROOT))

from app.holistic_gui_app import HolisticGuiApp  # noqa: E402


def make_console_app():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.root = Mock()
    app.control_commands = queue.Queue()
    app.is_shutting_down = False
    return app


def test_show_and_hide_console_only_change_window_state():
    app = make_console_app()

    app.show_console()
    app.hide_console()

    app.root.deiconify.assert_called_once_with()
    app.root.state.assert_called_once_with("normal")
    app.root.lift.assert_called_once_with()
    app.root.focus_force.assert_called_once_with()
    app.root.withdraw.assert_called_once_with()


def test_command_reader_forwards_commands_and_shutdown():
    app = make_console_app()
    app.command_stream = StringIO("show\nhide\n")

    app.read_control_commands()

    assert app.control_commands.get_nowait() == "show"
    assert app.control_commands.get_nowait() == "hide"
    assert app.control_commands.get_nowait() == "shutdown"


def test_shutdown_command_closes_without_scheduling_another_poll():
    app = make_console_app()
    app.on_close = Mock()
    app.control_commands.put("shutdown")

    app.poll_control_commands()

    app.on_close.assert_called_once_with()
    app.root.after.assert_not_called()


def test_stt_speech_event_updates_text_and_sequence():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.root = Mock()
    app.stt = Mock()
    app.stt.drain_events.return_value = [("speech", "테스트 음성")]
    app.latest_speech_text = ""
    app.speech_sequence = 0
    app.send_recognition_state = Mock()

    app.poll_stt_events()

    assert app.latest_speech_text == "테스트 음성"
    assert app.speech_sequence == 1
    app.send_recognition_state.assert_called_once_with()
    app.root.after.assert_called_once_with(100, app.poll_stt_events)


def test_camera_refresh_releases_active_camera_before_full_discovery(monkeypatch):
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.camera_discovery_thread = None
    app.status_var = Mock()
    app.cap = Mock()
    app.release_camera = Mock()

    thread = Mock()
    monkeypatch.setattr(
        "app.holistic_gui_app.threading.Thread",
        Mock(return_value=thread),
    )

    app.start_full_camera_discovery()

    assert app.restart_camera_after_discovery is True
    app.release_camera.assert_called_once_with()
    thread.start.assert_called_once_with()


def test_saved_bool_accepts_only_json_boolean_values():
    assert HolisticGuiApp.saved_bool({"enabled": False}, "enabled", True) is False
    assert HolisticGuiApp.saved_bool({"enabled": "false"}, "enabled", True) is True
    assert HolisticGuiApp.saved_bool({}, "enabled", False) is False


def test_recognition_mode_and_tools_are_saved_together():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.device_settings = {}
    app.active_mode = "air"
    app.tracking_var = Mock(**{"get.return_value": True})
    app.marker_only_var = Mock(**{"get.return_value": False})
    app.mirror_var = Mock(**{"get.return_value": True})
    app.info_overlay_var = Mock(**{"get.return_value": False})
    app.emotion_var = Mock(**{"get.return_value": True})
    app.always_recognition_var = Mock(**{"get.return_value": True})
    app.save_device_settings_safely = Mock()

    app.save_recognition_settings()

    assert app.device_settings["recognition"] == {
        "mode": "air",
        "tracking": True,
        "marker_only": False,
        "mirror": True,
        "info_overlay": False,
        "emotion": True,
        "always_recognition": True,
    }
    app.save_device_settings_safely.assert_called_once_with()
