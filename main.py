import sys
import subprocess
import os
from pathlib import Path
import threading
import json
import atexit

from app_logging import (SESSION_ID, configure_logging, ingest_event, log_event,
                         new_trace_id, register_environment_secrets, shutdown_logging)
from log_classification import classify_output

_startup_capture = None
if __name__ == '__main__':
    # Capture native/library diagnostics before importing either GUI or models.
    from native_log_capture import StartupCapture
    register_environment_secrets()
    configure_logging(Path(__file__).resolve().parent / 'logs')
    _startup_capture = StartupCapture()
    def _close_startup_logging():
        _startup_capture.close()
        shutdown_logging()
    atexit.register(_close_startup_logging)
    log_event('application.bootstrap', '앱 시작', executable=sys.executable)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal
from dotenv import load_dotenv
from character.character_widget import CharacterWidget
from character.config_manager import load_config, load_character_options
from character.settings_controller import SettingsController
from character.log_console import AppLogManager, LogWindow


load_dotenv()
register_environment_secrets()

PROJECT_ROOT = Path(__file__).resolve().parent
MEDIAPIPE_MAIN = PROJECT_ROOT / "medeapipe_capstone" / "main.py"


class MediaPipeProcessManager(QObject):
    """숨겨진 MediaPipe GUI 프로세스의 실행, 표시, 종료를 관리한다."""

    settings_message = pyqtSignal(dict)

    def __init__(self, script_path: Path = MEDIAPIPE_MAIN) -> None:
        super().__init__()
        self.script_path = script_path
        self.process = None
        self._readers = []
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        if self.is_running:
            return True
        if not self.script_path.is_file():
            log_event('recognition.process_start_failed', '인식 프로세스 파일 없음', category='오류', level='ERROR', path=str(self.script_path))
            print(f"[MediaPipe 실행 실패] 파일을 찾을 수 없습니다: {self.script_path}")
            return False

        try:
            # PyQt와 Tkinter는 이벤트 루프가 다르므로 MediaPipe를 별도 프로세스로 실행한다.
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUNBUFFERED"] = "1"
            child_env['CAPSTONE_LOG_PROTOCOL'] = '1'
            child_env['CAPSTONE_LOG_SESSION'] = SESSION_ID
            self._stopping = False
            self.process = subprocess.Popen(
                [sys.executable, str(self.script_path), "--background"],
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=child_env,
            )
        except OSError as exc:
            self.process = None
            print(f"[MediaPipe 실행 실패] {exc}")
            log_event('recognition.process_start_failed', '인식 프로세스 실행 실패', category='오류', level='ERROR', error=str(exc))
            return False

        print(f"[MediaPipe 백그라운드 실행] PID={self.process.pid}")
        log_event('recognition.process_started', '인식 프로세스 실행', category='사용자 인식', pid=self.process.pid, script=str(self.script_path))
        self._start_output_reader()
        return True

    def _start_output_reader(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        reader = threading.Thread(
            target=self._forward_output,
            args=(self.process,),
            name="mediapipe-output-reader",
            daemon=True,
        )
        self._readers.append(reader)
        reader.start()
        stream = getattr(self.process, 'stderr', None)
        if stream is not None and hasattr(stream, '__iter__'):
            reader = threading.Thread(target=self._forward_stderr, args=(self.process,),
                                      name='mediapipe-stderr-reader', daemon=True)
            self._readers.append(reader)
            reader.start()
        if callable(getattr(self.process, 'wait', None)):
            watcher = threading.Thread(target=self._watch_exit, args=(self.process,),
                                       name='mediapipe-exit-watcher', daemon=True)
            self._readers.append(watcher)
            watcher.start()

    def _watch_exit(self, process):
        try:
            code = process.wait()
            log_event('recognition.process_exited', '인식 프로세스 최종 종료 상태',
                      category='사용자 인식', level='ERROR' if isinstance(code, int) and code != 0 and not self._stopping else 'INFO',
                      pid=getattr(process, 'pid', None), exit_code=code, shutdown_requested=self._stopping)
        except (OSError, ValueError) as exc:
            log_event('recognition.process_wait_failed', '인식 프로세스 종료 확인 실패', category='오류', level='ERROR', error=str(exc))

    def _forward_stderr(self, process):
        for line in process.stderr:
            if line.strip():
                message = line.rstrip('\r\n')
                category, level = classify_output(message, is_error=True)
                # The stream belongs to recognition even when an unlabelled
                # native diagnostic contains no domain-specific keyword.
                if category == '시스템':
                    category = '사용자 인식'
                log_event('recognition.process_stderr', message, category=category,
                          level=level, pid=getattr(process, 'pid', None), stream='stderr')

    def _forward_output(self, process) -> None:
        """자식 프로세스 출력을 메인 로그 수집기가 읽을 수 있도록 전달한다."""
        for line in process.stdout:
            message = line.rstrip("\r\n")
            if message.startswith('APP_LOG '):
                try:
                    ingest_event(json.loads(message[len('APP_LOG '):]))
                except (ValueError, TypeError, KeyError) as exc:
                    log_event('recognition.invalid_log', '인식 로그 형식 오류', category='오류', level='WARNING', error=str(exc), raw=message)
                continue
            if message.startswith('APP_SETTINGS '):
                try:
                    payload = json.loads(message[len('APP_SETTINGS '):])
                    if isinstance(payload, dict):
                        log_event('settings.remote_response', '인식 설정 응답 수신', trace_id=payload.get('request_id'), payload=payload,
                                  receiver_dialog_may_be_closed=True)
                        self.settings_message.emit(payload)
                except ValueError:
                    log_event('settings.invalid_response', '인식 기능 응답 형식 오류', category='오류', level='WARNING', raw=message)
                continue
            if message:
                log_event('recognition.process_stdout', message, category='사용자 인식', pid=process.pid, stream='stdout')
        log_event('recognition.process_output_closed', '인식 프로세스 출력 종료', category='사용자 인식',
                  pid=getattr(process, 'pid', None), exit_code=process.poll() if callable(getattr(process, 'poll', None)) else None, shutdown_requested=self._stopping)
        self.settings_message.emit({'kind': 'unavailable'})

    def _send_command(self, command: str) -> bool:
        trace_id = None
        if command.startswith('settings '):
            try:
                trace_id = json.loads(command[len('settings '):]).get('request_id')
            except (ValueError, AttributeError):
                pass
        if not self.is_running or self.process.stdin is None:
            log_event('recognition.command_rejected', '인식 명령 전송 불가', category='사용자 인식', level='WARNING', trace_id=trace_id, command=command, reason='process_unavailable')
            return False
        try:
            self.process.stdin.write(f"{command}\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            print(f"[MediaPipe 명령 전송 실패] {exc}")
            log_event('recognition.command_failed', '인식 명령 전송 실패', category='오류', level='ERROR', trace_id=trace_id, command=command, error=str(exc))
            return False
        log_event('recognition.command_sent', '인식 명령 전송', category='사용자 인식', trace_id=trace_id, command=command, pid=self.process.pid)
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

    def set_character_speaking(self, speaking: bool) -> bool:
        """Gate recognizer capture only while character audio actually plays."""
        return self._send_command('tts_speaking ' + ('1' if speaking else '0'))

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
        self._stopping = True
        log_event('recognition.process_stopping', '인식 프로세스 종료 요청', category='사용자 인식', pid=process.pid)
        self._send_command("shutdown")
        try:
            process.wait(timeout=wait_timeout)
        except subprocess.TimeoutExpired:
            # Tkinter가 정상 종료 명령에 응답하지 않을 때 단계적으로 프로세스를 정리한다.
            log_event('recognition.process_terminate', '정상 종료 대기 초과', category='사용자 인식', level='WARNING', pid=process.pid, timeout=wait_timeout)
            process.terminate()
            try:
                process.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                log_event('recognition.process_kill', '프로세스 강제 종료', category='사용자 인식', level='WARNING', pid=process.pid, timeout=wait_timeout)
                process.kill()
                process.wait(timeout=wait_timeout)
        print("[MediaPipe 종료]")
        for reader in self._readers:
            if reader is not threading.current_thread():
                reader.join(1)
        self._readers.clear()
        log_event('recognition.process_stopped', '인식 프로세스 종료 완료', category='사용자 인식', pid=process.pid, exit_code=process.poll())


def main():
    configure_logging(PROJECT_ROOT / 'logs')
    app = QApplication(sys.argv)
    if _startup_capture is not None:
        _startup_capture.handoff_python()
    log_manager = AppLogManager()
    log_manager.install_capture()
    log_event('application.qt_ready', 'Qt 앱 준비 완료')
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
    character.dialogue_system.tts.speaking_changed.connect(mediapipe_manager.set_character_speaking)
    app.aboutToQuit.connect(mediapipe_manager.stop)

    exit_code = None
    try:
        exit_code = app.exec()
        return exit_code
    finally:
        # 예외나 외부 종료로 aboutToQuit 신호가 누락되어도 자식 프로세스를 정리한다.
        mediapipe_manager.stop()
        log_window.shutdown()
        log_manager.restore_capture()
        log_event('application.shutdown', '앱 종료', exit_code=exit_code)
        if _startup_capture is not None:
            _startup_capture.close()
        shutdown_logging()


if __name__ == "__main__":
    sys.exit(main())
