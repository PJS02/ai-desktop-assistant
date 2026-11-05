"""Real Presidio/OpenCV checks; OCR coordinates are deterministic fixtures."""

import base64
import io
import json
import os
import re
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ai import gemini_client
from app_logging import clear_events, get_events
from context import screen_privacy
from context import korean_ner


@pytest.fixture(autouse=True)
def ner_predictions(monkeypatch, request):
    if request.node.name.startswith("test_real_korean_ner"):
        return None
    def predict(text):
        return [{"entity_group": "PS", "start": match.start(), "end": match.end(), "score": 0.96}
                for match in re.finditer("홍길동|김민수|박지민", text)]
    predictor = Mock(side_effect=predict)
    monkeypatch.setattr(korean_ner, "_get_pipeline", lambda: predictor)
    return predictor


def polygon(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def ocr_result(texts, scores=None, polygons=None, detected=None):
    polygons = polygons if polygons is not None else [
        polygon(15, 15 + index * 30, 250, 30 + index * 30) for index in range(len(texts))]
    return dict(rec_texts=texts, rec_scores=scores if scores is not None else [0.99] * len(texts),
                rec_polys=polygons, dt_polys=detected if detected is not None else polygons)


@pytest.fixture
def screenshot():
    return Image.new("RGB", (640, 480), "white")


@pytest.fixture
def use_ocr(monkeypatch):
    def install(result):
        engine = Mock()
        engine.predict.return_value = [result]
        monkeypatch.setattr(screen_privacy, "_ocr", engine)
        return engine
    return install


@pytest.mark.parametrize("text", [
    "주민등록번호: 900101-1234567", "외국인등록번호 900101-5234567",
    "전화 010-1234-5678", "연락처 +82 10 1234 5678", "전화 02-123-4567",
    "메일 alice@example.com", "메일 alice @ example . com", "카드 4111 1111 1111 1111",
    "계좌번호 123456789012", "110-123-456789", "여권 M123A4567", "12-34-567890-12",
    "성명: 홍길동", "성명홍길동", "이 름 : 김민수", "예금주 박지민", "주소: 서울특별시 강남구 테헤란로 123",
    "서울특별시 강남구 테헤란로 123", "생년월일 1990.01.01", "아이디 private_user",
    "비밀번호 secret123!", "API key secret123", "https://example.com/private?token=abc",
    "IP 192.168.1.10",
])
def test_korean_and_common_pii_is_masked(text, screenshot, use_ocr):
    use_ocr(ocr_result([text, "프로젝트 작업 중"]))
    masked, prompt, _ = screen_privacy.redact_screen(screenshot, text)
    assert masked.getpixel((50, 20)) == (0, 0, 0)
    assert masked.getpixel((50, 50)) == (255, 255, 255)
    assert "[REDACTED]" in prompt
    assert screenshot.getpixel((50, 20)) == (255, 255, 255)


@pytest.mark.parametrize("texts", [
    ["연락처", "010", "1234", "5678"],
    ["주민등록번호", "900101", "1234567"],
    ["성명", "홍길동"],
])
def test_pii_split_across_boxes_is_masked(texts, screenshot, use_ocr):
    use_ocr(ocr_result(texts))
    masked, _, _ = screen_privacy.redact_screen(screenshot, "작업 설명")
    for index in range(1, len(texts)):
        assert masked.getpixel((50, 20 + index * 30)) == (0, 0, 0)


def test_name_found_in_image_is_removed_from_title_and_instruction(screenshot, use_ocr):
    use_ocr(ocr_result(["성명: 홍길동"]))
    _, prompt, instruction = screen_privacy.redact_screen(
        screenshot, "창 제목: 홍길동의 작업", "사용자 홍길동의 활동을 설명하세요")
    assert "홍길동" not in prompt + instruction


def test_uncertain_icons_and_unrecognized_regions_are_preserved(screenshot, use_ocr):
    use_ocr(ocr_result(["읽기 어려움", "", "일반 작업"], scores=[0.4, 0.9, 0.99], detected=[
        polygon(15, 15, 250, 30), polygon(15, 45, 250, 60),
        polygon(15, 75, 250, 90), polygon(15, 105, 250, 120)]))
    masked, _, _ = screen_privacy.redact_screen(screenshot, "설명")
    for y in (20, 50, 110):
        assert masked.getpixel((50, y)) == (255, 255, 255)
    assert masked.getpixel((50, 80)) == (255, 255, 255)


def test_low_confidence_phone_is_still_masked(screenshot, use_ocr):
    use_ocr(ocr_result(["010-1234-5678"], scores=[0.2]))
    masked, _, _ = screen_privacy.redact_screen(screenshot, "")
    assert masked.getpixel((50, 20)) == (0, 0, 0)


def test_unlabeled_name_is_masked_and_removed_from_prompt(screenshot, use_ocr, ner_predictions):
    def predict(text):
        start = text.find("김민수")
        return [] if start < 0 else [{"entity_group": "PS", "start": start, "end": start + 3, "score": 0.96}]
    ner_predictions.side_effect = predict
    use_ocr(ocr_result(["김민수", "설정", "홈"]))
    masked, prompt, _ = screen_privacy.redact_screen(screenshot, "김민수의 작업")
    assert masked.getpixel((50, 20)) == (0, 0, 0)
    assert masked.getpixel((50, 50)) == (255, 255, 255)
    assert masked.getpixel((50, 80)) == (255, 255, 255)
    assert "김민수" not in prompt


def test_ner_ignores_artifacts_locations_organizations_and_uncertain_names(ner_predictions):
    ner_predictions.side_effect = None
    ner_predictions.return_value = [
        {"entity_group": label, "start": 0, "end": 3, "score": score}
        for label, score in [("AF", 0.99), ("LC", 0.99), ("OG", 0.99), ("PS", 0.3)]]
    assert korean_ner.KoreanPersonRecognizer().analyze("테스트", ["PERSON"]) == []


def test_word_boxes_preserve_icon_and_menu_next_to_name(screenshot, use_ocr, ner_predictions):
    result = ocr_result(["● 김민수 설정"])
    result.update(text_word=[["● ", "김민수", " 설정"]], text_word_region=[[
        polygon(15, 15, 30, 30), polygon(60, 15, 110, 30), polygon(140, 15, 240, 30)]])
    use_ocr(result)
    ner_predictions.side_effect = None
    ner_predictions.return_value = [{"entity_group": "PS", "start": 2, "end": 5, "score": 0.95}]
    masked, _, _ = screen_privacy.redact_screen(screenshot, "")
    assert masked.getpixel((20, 20)) == (255, 255, 255)
    assert masked.getpixel((80, 20)) == (0, 0, 0)
    assert masked.getpixel((180, 20)) == (255, 255, 255)


def test_incomplete_word_coverage_falls_back_to_entire_sensitive_line(screenshot, use_ocr):
    result = ocr_result(["010-1234-5678"])
    result.update(text_word=[["010"]], text_word_region=[[polygon(15, 15, 45, 30)]])
    use_ocr(result)
    masked, _, _ = screen_privacy.redact_screen(screenshot, "")
    assert masked.getpixel((200, 20)) == (0, 0, 0)


@pytest.mark.parametrize("word_data", [
    {"text_word": [["010"]]},
    {"text_word": [["010"]], "text_word_region": [[]]},
    {"text_word": [["missing"]], "text_word_region": [[polygon(15, 15, 45, 30)]]},
    {"text_word": [["010"]], "text_word_region": [[polygon(300, 200, 330, 215)]]},
])
def test_malformed_word_alignment_blocks_request(word_data, screenshot, use_ocr):
    result = ocr_result(["010-1234-5678"])
    result.update(word_data)
    use_ocr(result)
    with pytest.raises(screen_privacy.ScreenPrivacyError):
        screen_privacy.redact_screen(screenshot, "")


def test_ner_failure_blocks_request(screenshot, use_ocr, ner_predictions):
    use_ocr(ocr_result(["김민수"]))
    ner_predictions.side_effect = RuntimeError("private name")
    with pytest.raises(screen_privacy.ScreenPrivacyError) as error:
        screen_privacy.redact_screen(screenshot, "")
    assert "private name" not in str(error.value)


@pytest.mark.parametrize("start,end,score", [(-1, 2, 0.9), (0, 99, 0.9), (0, 2, float("nan"))])
def test_invalid_ner_offsets_or_score_block_request(start, end, score, screenshot, use_ocr, ner_predictions):
    use_ocr(ocr_result(["김민수"]))
    ner_predictions.side_effect = None
    ner_predictions.return_value = [{"entity_group": "PS", "start": start, "end": end, "score": score}]
    with pytest.raises(screen_privacy.ScreenPrivacyError):
        screen_privacy.redact_screen(screenshot, "")


@pytest.mark.parametrize("text", ["이름 변경", "이름 바꾸기", "비밀번호 변경", "아이디 찾기"])
def test_ui_actions_are_not_private_field_values(text, screenshot, use_ocr):
    use_ocr(ocr_result([text]))
    masked, prompt, _ = screen_privacy.redact_screen(screenshot, text)
    assert np.array_equal(np.array(masked), np.array(screenshot))
    assert prompt == text


def test_rgb_and_edge_padding_are_preserved(use_ocr):
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    use_ocr(ocr_result(["01012345678"], polygons=[polygon(0, 0, 35, 15)]))
    masked, _, _ = screen_privacy.redact_screen(image, "설명")
    assert masked.mode == "RGB"
    assert masked.getpixel((39, 19)) == (0, 0, 0)
    assert masked.getpixel((90, 90)) == (255, 0, 0)


def test_valid_page_without_text_is_allowed(screenshot, use_ocr):
    use_ocr(ocr_result([]))
    masked, prompt, _ = screen_privacy.redact_screen(screenshot, "작업 설명")
    assert np.array_equal(np.array(masked), np.array(screenshot))
    assert prompt == "작업 설명"


@pytest.mark.parametrize("result", [
    {}, ocr_result(["text"], scores=[]), ocr_result(["text"], scores=[float("nan")]),
    ocr_result(["text"], polygons=[[[0, 0]]]),
    ocr_result(["text"], polygons=[polygon(1000, 1000, 1200, 1200)]),
    ocr_result(["text"], polygons=[polygon(15, 15, 250, 30)], detected=[]),
])
def test_malformed_ocr_blocks_transmission(result, screenshot, use_ocr):
    use_ocr(result)
    with pytest.raises(screen_privacy.ScreenPrivacyError):
        screen_privacy.redact_screen(screenshot, "설명")


def test_no_page_and_ocr_exceptions_block_transmission(screenshot, use_ocr):
    engine = use_ocr(ocr_result([]))
    engine.predict.return_value = []
    with pytest.raises(screen_privacy.ScreenPrivacyError):
        screen_privacy.redact_screen(screenshot, "설명")
    engine.predict.side_effect = RuntimeError("sensitive OCR text")
    with pytest.raises(screen_privacy.ScreenPrivacyError) as error:
        screen_privacy.redact_screen(screenshot, "설명")
    assert "sensitive" not in str(error.value)


def test_transport_sends_masked_pixels_and_text_and_omits_image_from_logs(screenshot, use_ocr):
    clear_events()
    use_ocr(ocr_result(["010-1234-5678", "프로젝트 작업 중"]))
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'
    with patch.object(gemini_client, "urlopen", return_value=response) as send:
        assert gemini_client.request_gemini("전화 010-1234-5678", {"api_key": "fake"},
                                          image=screenshot) == "ok"
    payload = json.loads(send.call_args.args[0].data)
    parts = payload["contents"][0]["parts"]
    encoded = parts[1]["inlineData"]["data"]
    sent = Image.open(io.BytesIO(base64.b64decode(encoded)))
    assert sent.getpixel((50, 20)) == (0, 0, 0)
    assert sent.getpixel((50, 50)) == (255, 255, 255)
    assert "010-1234-5678" not in json.dumps(payload)
    logs = "\n".join(event.details() for event in get_events())
    assert "010-1234-5678" not in logs
    assert encoded not in logs
    assert "[IMAGE OMITTED]" in logs


def test_transport_never_sends_if_privacy_filter_fails(screenshot):
    clear_events()
    with patch.object(gemini_client, "redact_screen", side_effect=screen_privacy.ScreenPrivacyError), patch.object(
            gemini_client, "urlopen") as send:
        result = gemini_client.request_gemini("private text", {"api_key": "fake"}, image=screenshot)
    send.assert_not_called()
    assert result.startswith("[gemini error]")
    assert any(event.event == "gemini.privacy_blocked" for event in get_events())
    assert "private text" not in "\n".join(event.details() for event in get_events())


def test_analyzer_failure_blocks_transmission_without_sensitive_error(screenshot, use_ocr):
    use_ocr(ocr_result(["연락처 010-1234-5678"]))
    with patch.object(screen_privacy, "_get_analyzer", side_effect=RuntimeError("private input")), patch.object(
            gemini_client, "urlopen") as send:
        result = gemini_client.request_gemini("private input", {"api_key": "fake"}, image=screenshot)
    send.assert_not_called()
    assert "private input" not in result


def test_text_only_request_does_not_load_privacy_models():
    with patch.object(gemini_client, "redact_screen") as redact, patch.object(gemini_client, "urlopen") as send:
        send.side_effect = OSError("offline")
        gemini_client.request_gemini("hello", {"api_key": "fake"})
    redact.assert_not_called()
    send.assert_called_once()


def test_capture_supports_active_window_on_negative_monitor(monkeypatch, screenshot):
    from context.active_window_classifier import capture_active_window_image
    win32gui = SimpleNamespace(GetForegroundWindow=lambda: 123,
                               GetWindowRect=lambda _: (-900, 20, -260, 500))
    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    with patch("PIL.ImageGrab.grab", return_value=screenshot) as grab:
        assert capture_active_window_image() is screenshot
    grab.assert_called_once_with(bbox=(-900, 20, -260, 500), all_screens=True)


def test_one_shot_activity_blocks_when_capture_is_unavailable(monkeypatch):
    from context import active_window_classifier as activity
    monkeypatch.setattr(activity.Path, "mkdir", Mock())
    monkeypatch.setattr(activity, "load_gemini_config", lambda: {"api_key": "fake"})
    monkeypatch.setattr(activity, "load_json_file", lambda *_: {})
    monkeypatch.setattr(activity, "get_rules", lambda: {"browsers": []})
    monkeypatch.setattr(activity, "get_active_window_info", lambda: {"process": "code.exe", "title": "work"})
    monkeypatch.setattr(activity, "classify_activity", lambda *_: "DEVELOP")
    monkeypatch.setattr(activity, "capture_active_window_image", lambda: None)
    with patch.object(activity, "request_gemini") as send:
        result = activity.generate_dialogue_json()
    send.assert_not_called()
    assert result == {"dialogue": "", "error": "screen_capture_unavailable", "category": "DEVELOP",
                      "process": "code.exe", "title": "work", "url": ""}


def test_activity_worker_sends_capture_without_logging_raw_title(screenshot):
    pytest.importorskip("PyQt6")
    from character.character_widget import CharacterWidget
    fake = SimpleNamespace(_character_closing=False,
                           dialogue_system=SimpleNamespace(_process_gemini_response=lambda _: "reply"),
                           automatic_response_ready=Mock())
    clear_events()
    with patch("character.character_widget.get_active_window_info", return_value={
        "process": "code.exe", "title": "private 010-1234-5678"}), patch(
            "character.character_widget.capture_active_window_image", return_value=screenshot), patch(
                "character.character_widget.request_gemini", return_value='{"dialogue":"reply"}') as send:
        CharacterWidget._check_active_window_async(fake, 1, 2, {"api_key": "fake"}, "calm", "friendly")
    assert send.call_args.kwargs["image"] is screenshot
    fake.automatic_response_ready.emit.assert_called_once()
    assert "010-1234-5678" not in "\n".join(event.details() for event in get_events())


def test_activity_worker_blocks_request_if_capture_is_unavailable():
    pytest.importorskip("PyQt6")
    from character.character_widget import CharacterWidget
    fake = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock())
    with patch("character.character_widget.get_active_window_info", return_value={
        "process": "code.exe", "title": "private"}), patch(
            "character.character_widget.capture_active_window_image", return_value=None), patch(
                "character.character_widget.request_gemini") as send:
        CharacterWidget._check_active_window_async(fake, 1, 2, {"api_key": "fake"}, "calm", "friendly")
    send.assert_not_called()
    fake.automatic_response_ready.emit.assert_called_once()


def test_preview_displays_only_masked_pixels(monkeypatch, screenshot, use_ocr):
    import preview_screen_privacy as preview
    use_ocr(ocr_result(["010-1234-5678", "프로젝트 작업 중"]))
    monkeypatch.setattr(preview, "capture_active_window_image", lambda: screenshot)
    monkeypatch.setattr(preview.time, "sleep", Mock())
    with patch.multiple(preview.cv2, namedWindow=Mock(), resizeWindow=Mock(), imshow=Mock(),
                        getWindowProperty=Mock(return_value=1), waitKey=Mock(return_value=27),
                        destroyAllWindows=Mock()), patch.object(gemini_client, "urlopen") as send:
        assert preview.main() == 0
        shown = preview.cv2.imshow.call_args.args[1]
        assert (shown[20, 50] == 0).all()
        assert (shown[50, 50] == 255).all()
        preview.cv2.destroyAllWindows.assert_called_once()
    send.assert_not_called()
    assert screenshot.getpixel((50, 20)) == (255, 255, 255)


@pytest.mark.parametrize("text,detect_name,exact,joined,detected", [
    ("김민수", True, 1, 1, 1),
    ("김민수", False, 1, 1, 0),
    ("김 민 수", False, 0, 1, 0),
    ("검민수", False, 0, 0, 0),
])
def test_preview_name_check_reports_only_counts(text, detect_name, exact, joined, detected,
                                               monkeypatch, screenshot, use_ocr, ner_predictions, capsys):
    import preview_screen_privacy as preview
    if not detect_name:
        ner_predictions.side_effect = None
        ner_predictions.return_value = []
    use_ocr(ocr_result([text]))
    monkeypatch.setattr(preview, "capture_active_window_image", lambda: screenshot)
    monkeypatch.setattr(preview.time, "sleep", Mock())
    with patch.multiple(preview.cv2, namedWindow=Mock(), resizeWindow=Mock(), imshow=Mock(),
                        getWindowProperty=Mock(return_value=1), waitKey=Mock(return_value=27),
                        destroyAllWindows=Mock()), patch.object(gemini_client, "urlopen") as send:
        assert preview.main(check_name="김민수") == 0
    output = capsys.readouterr().out
    assert f"이름 OCR 일치: {exact}곳 / 공백 무시 일치: {joined}곳" in output
    assert f"이름 전체 개인정보 판정: {detected}곳" in output
    assert "김민수" not in output
    assert text not in output
    send.assert_not_called()


def test_preview_rejects_blank_check_name(monkeypatch):
    import preview_screen_privacy as preview
    capture = Mock()
    monkeypatch.setattr(preview, "capture_active_window_image", capture)
    assert preview.main(check_name="  ") == 2
    capture.assert_not_called()


@pytest.mark.parametrize("capture_missing", [True, False])
def test_preview_does_not_display_on_capture_or_privacy_failure(monkeypatch, screenshot, capture_missing):
    import preview_screen_privacy as preview
    monkeypatch.setattr(preview.time, "sleep", Mock())
    monkeypatch.setattr(preview, "capture_active_window_image", lambda: None if capture_missing else screenshot)
    with patch.object(preview, "redact_screen", side_effect=screen_privacy.ScreenPrivacyError("blocked")), patch.object(
            preview.cv2, "imshow") as show:
        assert preview.main() == 1
    show.assert_not_called()


@pytest.mark.skipif(os.environ.get("RUN_PADDLE_OCR_TEST") != "1", reason="requires local OCR models")
def test_real_paddleocr_masks_synthetic_korean_screen(monkeypatch):
    monkeypatch.setattr(screen_privacy, "_ocr", None)
    image = Image.new("RGB", (1000, 280), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 32)
    draw.text((30, 30), "연락처: 010-1234-5678", font=font, fill="black")
    draw.text((30, 150), "프로젝트 작업 중", font=font, fill="black")
    masked, prompt, _ = screen_privacy.redact_screen(image, "연락처: 010-1234-5678")
    assert "010-1234-5678" not in prompt
    pixels = np.array(masked)
    number_left = 30 + draw.textlength("연락처: ", font=font)
    left, top, right, bottom = draw.textbbox((number_left, 30), "010-1234-5678", font=font)
    assert (pixels[int(top):int(bottom), int(left):int(right)] == 0).all()
    assert np.array_equal(pixels[40:60, 35:85], np.array(image)[40:60, 35:85])
    assert np.array_equal(pixels[140:220], np.array(image)[140:220])


@pytest.mark.skipif(os.environ.get("RUN_KOREAN_NER_TEST") != "1", reason="requires local Korean NER model")
def test_real_korean_ner_names_and_menu_labels():
    recognizer = korean_ner.KoreanPersonRecognizer()
    for text, name in [("홍길동", "홍길동"), ("김민수", "김민수"), ("이서연", "이서연"),
                       ("박지민", "박지민"), ("김민수님에게 메시지를 보냈습니다.", "김민수"),
                       ("오늘 이서연과 회의합니다.", "이서연")]:
        results = recognizer.analyze(text, ["PERSON"])
        assert name in [text[result.start:result.end] for result in results]
    for text in ["설정", "홈", "프로젝트 작업 중", "다운로드"]:
        assert recognizer.analyze(text, ["PERSON"]) == []
    for text in ["이름 변경", "이름 바꾸기", "비밀번호 변경", "아이디 찾기"]:
        assert screen_privacy._find_spans(text) == []
    long_text = "설정 메뉴 " * 400 + "\n김민수님에게 메시지를 보냈습니다."
    results = recognizer.analyze(long_text, ["PERSON"])
    assert "김민수" in [long_text[result.start:result.end] for result in results]


@pytest.mark.skipif(os.environ.get("RUN_PADDLE_OCR_TEST") != "1" or os.environ.get("RUN_KOREAN_NER_TEST") != "1",
                    reason="requires local OCR and Korean NER models")
def test_real_korean_ner_with_ocr_preserves_icon_and_menu(monkeypatch):
    monkeypatch.setattr(screen_privacy, "_ocr", None)
    image = Image.new("RGB", (1000, 280), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 32)
    draw.rectangle((30, 30, 55, 55), fill="blue")
    draw.text((130, 30), "김민수", font=font, fill="black")
    draw.text((30, 150), "설정 메뉴", font=font, fill="black")
    masked, prompt, _ = screen_privacy.redact_screen(image, "김민수의 작업")
    pixels = np.array(masked)
    assert "김민수" not in prompt
    assert np.array_equal(pixels[30:56, 30:56], np.array(image)[30:56, 30:56])
    assert (pixels[40:60, 135:210] == 0).all()
    assert np.array_equal(pixels[140:220], np.array(image)[140:220])


@pytest.mark.skipif(os.environ.get("RUN_PADDLE_OCR_TEST") != "1" or os.environ.get("RUN_KOREAN_NER_TEST") != "1",
                    reason="requires local OCR and Korean NER models")
@pytest.mark.parametrize("font_size", [12, 14, 16])
def test_real_korean_ner_small_messenger_name(font_size, monkeypatch):
    monkeypatch.setattr(screen_privacy, "_ocr", None)
    image = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", font_size)
    draw.text((20, 15), "채팅  친구  설정", font=font, fill="black")
    draw.ellipse((20, 80, 48, 108), fill="blue")
    draw.text((70, 80), "김민수", font=font, fill="black")
    draw.text((70, 106), "안녕하세요. 확인했어요.", font=font, fill="gray")
    draw.text((300, 80), "15:30", font=font, fill="gray")
    diagnostics = {}
    masked, _, _ = screen_privacy.redact_screen(image, "", diagnostics=diagnostics)
    assert "김민수" in diagnostics["ocr_text"]
    pixels = np.array(masked)
    left, top, right, bottom = draw.textbbox((70, 80), "김민수", font=font)
    original_name = np.array(image)[top:bottom, left:right]
    masked_name = pixels[top:bottom, left:right]
    glyphs = np.any(original_name < 255, axis=2)
    assert (masked_name[glyphs] == 0).all()
    assert np.all(masked_name == 0, axis=2).mean() >= 0.9
    assert np.array_equal(pixels[80:109, 20:49], np.array(image)[80:109, 20:49])
