import argparse
import sys
from pathlib import Path

# The child process runs from its own directory; share the host's logging API.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_logging import log_event


def parse_args():
    parser = argparse.ArgumentParser(description="MediaPipe 사용자 인식 작업")
    parser.add_argument(
        "--background",
        action="store_true",
        help="창 없이 백그라운드 인식을 실행합니다.",
    )
    parser.add_argument('--diagnostic-gui', action='store_true', help='개발용 기존 진단 창을 실행합니다.')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    log_event('recognition.process.started', '사용자 인식 프로세스 시작',
              category='사용자 인식', background=not args.diagnostic_gui or args.background)
    try:
        if args.diagnostic_gui:
            from app.holistic_gui_app import main
            main(background_mode=args.background, command_stream=sys.stdin if args.background else None)
        else:
            from app.recognition_engine import RecognitionEngine
            from app.worker_loop import WorkerLoop
            loop = WorkerLoop()
            engine = None
            try:
                engine = RecognitionEngine(loop, background_mode=True, command_stream=sys.stdin)
                log_event('recognition.engine.ready', '창 없는 사용자 인식 작업 준비 완료',
                          category='사용자 인식', tkinter_loaded='tkinter' in sys.modules)
                loop.run()
            finally:
                if engine is not None:
                    engine.on_close()
    except BaseException as exc:
        log_event('recognition.process.failed', '사용자 인식 프로세스 종료 오류',
                  category='오류', level='ERROR', error=str(exc), exception=type(exc).__name__)
        raise
    finally:
        log_event('recognition.process.finished', '사용자 인식 프로세스 종료', category='사용자 인식')
