import subprocess
import sys
from unittest.mock import Mock, patch

import main as app_main


def test_mediapipe_manager_starts_hidden_with_current_python(tmp_path):
    script_path = tmp_path / "main.py"
    script_path.touch()
    process = Mock(pid=1234, stdin=Mock())
    process.poll.return_value = None
    manager = app_main.MediaPipeProcessManager(script_path)

    with patch.object(app_main.subprocess, "Popen", return_value=process) as popen:
        result = manager.start()

    assert result is True
    assert manager.process is process
    popen.assert_called_once_with(
        [sys.executable, str(script_path), "--background"],
        cwd=str(app_main.PROJECT_ROOT),
        stdin=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )


def test_mediapipe_manager_skips_missing_script(tmp_path):
    missing_script = tmp_path / "missing.py"
    manager = app_main.MediaPipeProcessManager(missing_script)

    with patch.object(app_main.subprocess, "Popen") as popen:
        result = manager.start()

    assert result is False
    popen.assert_not_called()


def test_show_console_sends_command_to_running_process(tmp_path):
    process = Mock(stdin=Mock())
    process.poll.return_value = None
    manager = app_main.MediaPipeProcessManager(tmp_path / "main.py")
    manager.process = process

    assert manager.show_console() is True

    process.stdin.write.assert_called_once_with("show\n")
    process.stdin.flush.assert_called_once_with()


def test_stop_requests_graceful_shutdown_first(tmp_path):
    process = Mock(stdin=Mock())
    process.poll.return_value = None
    manager = app_main.MediaPipeProcessManager(tmp_path / "main.py")
    manager.process = process

    manager.stop()

    process.stdin.write.assert_called_once_with("shutdown\n")
    process.wait.assert_called_once_with(timeout=3.0)
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_stop_kills_unresponsive_process(tmp_path):
    process = Mock(stdin=Mock())
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired("mediapipe", 3.0),
        subprocess.TimeoutExpired("mediapipe", 3.0),
        None,
    ]
    manager = app_main.MediaPipeProcessManager(tmp_path / "main.py")
    manager.process = process

    manager.stop()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 3
