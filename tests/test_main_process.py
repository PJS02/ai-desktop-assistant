import subprocess
import sys
from unittest.mock import Mock, patch

import main as app_main


def test_start_mediapipe_process_uses_current_python(tmp_path):
    script_path = tmp_path / "main.py"
    script_path.touch()
    process = Mock(pid=1234)

    with patch.object(app_main.subprocess, "Popen", return_value=process) as popen:
        result = app_main.start_mediapipe_process(script_path)

    assert result is process
    popen.assert_called_once_with(
        [sys.executable, str(script_path)],
        cwd=str(app_main.PROJECT_ROOT),
    )


def test_start_mediapipe_process_skips_missing_script(tmp_path):
    missing_script = tmp_path / "missing.py"

    with patch.object(app_main.subprocess, "Popen") as popen:
        result = app_main.start_mediapipe_process(missing_script)

    assert result is None
    popen.assert_not_called()


def test_stop_mediapipe_process_terminates_running_process():
    process = Mock()
    process.poll.return_value = None

    app_main.stop_mediapipe_process(process)

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=3.0)
    process.kill.assert_not_called()


def test_stop_mediapipe_process_kills_unresponsive_process():
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("mediapipe", 3.0), None]

    app_main.stop_mediapipe_process(process)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
