"""Run: python preview_screen_privacy.py, then select a window within 3 seconds."""

import argparse
import re
import sys
import time

import cv2
import numpy as np

from context.active_window_classifier import capture_active_window_image
from context.screen_privacy import ScreenPrivacyError, redact_screen


def main(*, check_name=None):
    if check_name is not None and not check_name.strip():
        print("확인할 이름을 입력하세요.", file=sys.stderr)
        return 2
    print("3초 안에 캡처할 창을 선택하세요. 마스킹 결과에서 Esc 또는 Q를 누르면 종료합니다.", flush=True)
    time.sleep(3)
    try:
        image = capture_active_window_image()
        if image is None:
            print("활성 창을 캡처할 수 없습니다.", file=sys.stderr)
            return 1
        print("개인정보 마스킹 중입니다. 첫 실행은 OCR·한국어 이름 모델 다운로드로 시간이 걸릴 수 있습니다.", flush=True)
        diagnostics = {} if check_name is not None else None
        if diagnostics is None:
            masked, _, _ = redact_screen(image, "")
        else:
            masked, _, _ = redact_screen(image, "", diagnostics=diagnostics)
            text, spans = diagnostics["ocr_text"], diagnostics["pii_spans"]
            exact_count = len(list(re.finditer(re.escape(check_name), text)))
            pattern = r"\s*".join(re.escape(char) for char in check_name if not char.isspace())
            matches = list(re.finditer(pattern, text))
            detected_count = sum(all(any(start <= index < end for start, end in spans)
                                     for index in range(match.start(), match.end()) if not text[index].isspace())
                                 for match in matches)
            print(f"이름 OCR 일치: {exact_count}곳 / 공백 무시 일치: {len(matches)}곳", flush=True)
            print(f"이름 전체 개인정보 판정: {detected_count}곳", flush=True)
    except ScreenPrivacyError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ImportError, OSError, RuntimeError):
        print("화면 캡처에 실패했습니다. requirements.txt의 의존성과 Windows 환경을 확인하세요.", file=sys.stderr)
        return 1

    title = "Masked active window - Esc / Q to close"
    try:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        scale = min(1.0, 1280 / masked.width, 800 / masked.height)
        cv2.resizeWindow(title, max(1, int(masked.width * scale)), max(1, int(masked.height * scale)))
        cv2.imshow(title, cv2.cvtColor(np.array(masked), cv2.COLOR_RGB2BGR))
        while cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) >= 1:
            if (cv2.waitKey(100) & 0xFF) in (27, ord("q"), ord("Q")):
                break
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="현재 활성 창의 개인정보 마스킹 미리보기")
    parser.add_argument("--check-name", help="특정 이름의 OCR 일치·개인정보 판정 횟수만 출력")
    args = parser.parse_args()
    raise SystemExit(main(check_name=args.check_name))
