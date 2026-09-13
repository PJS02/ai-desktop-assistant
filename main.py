import sys
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from dotenv import load_dotenv
from character.character_widget import CharacterWidget
from character.resolution_settings import ResolutionSettingsDialog
from character.config_manager import load_config, save_config


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
MEDIAPIPE_MAIN = PROJECT_ROOT / "medeapipe_capstone" / "main.py"


def start_mediapipe_process(script_path: Path = MEDIAPIPE_MAIN):
    """현재 Python 환경으로 MediaPipe GUI를 별도 프로세스에서 실행한다."""
    if not script_path.is_file():
        print(f"[MediaPipe 실행 실패] 파일을 찾을 수 없습니다: {script_path}")
        return None

    try:
        # PyQt와 Tkinter는 각각 이벤트 루프를 가지므로 같은 프로세스에서 함께 실행하지 않는다.
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT_ROOT),
        )
    except OSError as exc:
        print(f"[MediaPipe 실행 실패] {exc}")
        return None

    print(f"[MediaPipe 실행] PID={process.pid}")
    return process


def stop_mediapipe_process(process, wait_timeout: float = 3.0) -> None:
    """실행 중인 MediaPipe 자식 프로세스를 안전하게 종료한다."""
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=wait_timeout)
    except subprocess.TimeoutExpired:
        # 정상 종료 요청에 응답하지 않을 때만 강제 종료해 자식 프로세스가 남지 않게 한다.
        process.kill()
        process.wait(timeout=wait_timeout)
    print("[MediaPipe 종료]")


def main():
    app = QApplication(sys.argv)
    
    # 저장된 설정 불러오기
    saved_width, saved_height, saved_personality = load_config()
    print(f"[설정] 저장된 해상도: {saved_width} × {saved_height}px")
    print(f"[설정] 저장된 성격: {saved_personality}")
    
    # 설정 다이얼로그 띄우기 (저장된 값으로 초기화)
    settings_dialog = ResolutionSettingsDialog(saved_width, saved_height, saved_personality)
    if settings_dialog.exec() == ResolutionSettingsDialog.DialogCode.Accepted:
        width, height = settings_dialog.get_resolution()
        personality = settings_dialog.get_personality()
        print(f"[설정] 선택된 해상도: {width} × {height}px")
        print(f"[설정] 선택된 성격: {personality}")
        save_config(width, height, personality)  # 설정 저장
    else:
        # 취소 버튼 클릭 시 저장된 설정 사용
        width, height = saved_width, saved_height
        personality = saved_personality
        print(f"[설정] 저장된 해상도 사용: {width} × {height}px")
        print(f"[설정] 저장된 성격 사용: {personality}")
    
    # 캐릭터 위젯에 해상도 전달
    character = CharacterWidget(screen_width=width, screen_height=height, personality_preset=personality)
    character.show()

    # 캐릭터의 인식 수신기가 준비된 다음 MediaPipe GUI를 실행한다.
    mediapipe_process = start_mediapipe_process()
    app.aboutToQuit.connect(lambda: stop_mediapipe_process(mediapipe_process))

    try:
        return app.exec()
    finally:
        # 예외나 외부 종료로 aboutToQuit 신호가 누락되어도 자식 프로세스를 정리한다.
        stop_mediapipe_process(mediapipe_process)


if __name__ == "__main__":
    sys.exit(main())
