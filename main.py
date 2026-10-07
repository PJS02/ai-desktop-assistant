import sys
import subprocess
import os
from pathlib import Path
import threading
import json

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
from dotenv import load_dotenv
from character.character_widget import CharacterWidget
from character.config_manager import load_config, load_character_options
from character.settings_controller import SettingsController
from character.log_console import AppLogManager, LogWindow


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
MEDIAPIPE_MAIN = PROJECT_ROOT / "medeapipe_capstone" / "main.py"


class MediaPipeProcessManager(QObject):
    """숨겨진 MediaPipe GUI 프로세스의 실행, 표시, 종료를 관리한다."""

    settings_message = pyqtSignal(dict)

    def __init__(self, script_path: Path = MEDIAPIPE_MAIN) -> None:
        super().__init__()
        self.script_path = script_path
        self.process = None

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        if self.is_running:
            return True
        if not self.script_path.is_file():
            print(f"[MediaPipe 실행 실패] 파일을 찾을 수 없습니다: {self.script_path}")
            return False

        try:
            # PyQt와 Tkinter는 이벤트 루프가 다르므로 MediaPipe를 별도 프로세스로 실행한다.
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUNBUFFERED"] = "1"
            self.process = subprocess.Popen(
                [sys.executable, str(self.script_path), "--background"],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=child_env,
            )
        except OSError as exc:
            self.process = None
            print(f"[MediaPipe 실행 실패] {exc}")
            return False

        print(f"[MediaPipe 백그라운드 실행] PID={self.process.pid}")
        self._start_output_reader()
        return True

    def _start_output_reader(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        threading.Thread(
            target=self._forward_output,
            args=(self.process,),
            name="mediapipe-output-reader",
            daemon=True,
        ).start()

    def _forward_output(self, process) -> None:
        """자식 프로세스 출력을 메인 로그 수집기가 읽을 수 있도록 전달한다."""
        for line in process.stdout:
            message = line.rstrip("\r\n")
            if message.startswith('APP_SETTINGS '):
                try:
                    payload = json.loads(message[len('APP_SETTINGS '):])
                    if isinstance(payload, dict):
                        self.settings_message.emit(payload)
                except ValueError:
                    print('[통합 설정] 인식 기능 응답 형식 오류')
                continue
            if message:
                print(f"[MediaPipe] {message}")
        self.settings_message.emit({'kind': 'unavailable'})

    def _send_command(self, command: str) -> bool:
        if not self.is_running or self.process.stdin is None:
            return False
        try:
            self.process.stdin.write(f"{command}\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            print(f"[MediaPipe 명령 전송 실패] {exc}")
            return False
        return True

    def show_console(self) -> bool:
        """실행 중인 콘솔을 표시하고, 종료된 경우에는 다시 시작한다."""
        if not self.is_running and not self.start():
            return False
        return self._send_command("show")

    def send_game_command(self, command: str) -> bool:
        if command.startswith("rps_begin ") and not self.is_running:
            if not self.start():
                return False
        return self._send_command(command)

    def request_settings(self, refresh_devices=False):
        if not self.is_running and not self.start():
            return False
        return self._send_command('settings ' + json.dumps({'action': 'refresh' if refresh_devices else 'get'}))

    def apply_settings(self, request_id, values):
        return self._send_command('settings ' + json.dumps({'action': 'apply', 'request_id': request_id, 'values': values}, ensure_ascii=False))

    def stop(self, wait_timeout: float = 3.0) -> None:
        if not self.is_running:
            return

        process = self.process
        self._send_command("shutdown")
        try:
            process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            # Tkinter가 정상 종료 명령에 응답하지 않을 때 단계적으로 프로세스를 정리한다.
            process.terminate()
            try:
                process.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=wait_timeout)
        print("[MediaPipe 종료]")


def main():
    app = QApplication(sys.argv)
    log_manager = AppLogManager()
    log_manager.install_capture()
    log_window = LogWindow(log_manager)
    mediapipe_manager = MediaPipeProcessManager()
    
    # 저장된 설정 불러오기
    saved_width, saved_height, saved_personality = load_config()
    print(f"[설정] 저장된 해상도: {saved_width} × {saved_height}px")
    print(f"[설정] 저장된 성격: {saved_personality}")
    
    width, height, personality = saved_width, saved_height, saved_personality
    
    # 캐릭터 위젯에 해상도 전달
    character = CharacterWidget(
        screen_width=width,
        screen_height=height,
        personality_preset=personality,
        on_show_perception_console=mediapipe_manager.show_console,
        on_show_log_window=log_window.show_and_raise,
        on_close_log_window=log_window.shutdown,
        on_rps_command=mediapipe_manager.send_game_command,
        character_options=load_character_options(),
    )
    settings_controller = SettingsController(character, mediapipe_manager)
    character._show_settings_callback = settings_controller.show
    character.show()

    # 캐릭터의 인식 수신기가 준비된 다음 MediaPipe GUI를 실행한다.
    mediapipe_manager.start()
    app.aboutToQuit.connect(mediapipe_manager.stop)

    try:
        return app.exec()
    finally:
        # 예외나 외부 종료로 aboutToQuit 신호가 누락되어도 자식 프로세스를 정리한다.
        mediapipe_manager.stop()
        log_window.shutdown()
        log_manager.restore_capture()


if __name__ == "__main__":
    sys.exit(main())
