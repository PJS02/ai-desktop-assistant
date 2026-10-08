import argparse
import sys
from pathlib import Path

# The child process runs from its own directory; share the host's logging API.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_logging import log_event

from app.holistic_gui_app import main


def parse_args():
    parser = argparse.ArgumentParser(description="MediaPipe 사용자 인식 GUI")
    parser.add_argument(
        "--background",
        action="store_true",
        help="인식은 자동으로 시작하고 GUI 창은 숨긴 상태로 실행합니다.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    log_event('recognition.process.started', '사용자 인식 프로세스 시작',
              category='사용자 인식', background=args.background)
    try:
        main(background_mode=args.background,
             command_stream=sys.stdin if args.background else None)
    except BaseException as exc:
        log_event('recognition.process.failed', '사용자 인식 프로세스 종료 오류',
                  category='오류', level='ERROR', error=str(exc), exception=type(exc).__name__)
        raise
    finally:
        log_event('recognition.process.finished', '사용자 인식 프로세스 종료', category='사용자 인식')
