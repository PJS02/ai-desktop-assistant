import argparse
import sys

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
    main(
        background_mode=args.background,
        command_stream=sys.stdin if args.background else None,
    )
