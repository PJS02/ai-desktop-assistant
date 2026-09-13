from io import StringIO
from pathlib import Path
import queue
import sys
from unittest.mock import Mock


MEDIAPIPE_ROOT = Path(__file__).resolve().parents[1] / "medeapipe_capstone"
sys.path.insert(0, str(MEDIAPIPE_ROOT))

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
