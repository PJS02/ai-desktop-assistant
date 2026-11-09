"""Local OCR/PII filtering. Only the returned image may reach external APIs."""

from __future__ import annotations

import math
import re
import threading

from app_logging import log_event


class ScreenPrivacyError(RuntimeError):
    """A screenshot could not be checked safely; the request must be blocked."""


# Deliberately prefer masking too much to validating real identity/account numbers.
KOREAN_PATTERNS = {
    "KR_RRN": r"(?<!\d)\d{6}\s*[-‐–]?\s*[1-8]\d{6}(?!\d)",
    "KR_PHONE": r"(?<!\d)(?:(?:\+82\s*[-.]?\s*|0)(?:1[016789]|2|[3-6]\d|70))\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}(?!\d)",
    "KR_PASSPORT": r"(?<![A-Za-z0-9])[MSROD]\s*\d{3}\s*[A-Za-z0-9]\s*\d{4}(?![A-Za-z0-9])",
    "KR_DRIVER_LICENSE": r"(?<!\d)\d{2}\s*[-‐–]\s*\d{2}\s*[-‐–]\s*\d{6}\s*[-‐–]\s*\d{2}(?!\d)",
    "KR_ACCOUNT": r"(?<!\d)\d{2,6}\s*[-‐–]\s*\d{2,6}\s*[-‐–]\s*\d{2,8}(?:\s*[-‐–]\s*\d{1,6})?(?!\d)",
    "LONG_NUMBER": r"(?<!\d)\d{10,19}(?!\d)",
    "EMAIL_ADDRESS": r"[A-Za-z0-9._%+\-]+\s*@\s*[A-Za-z0-9.\-]+\s*\.\s*[A-Za-z]{2,}",
    "URL": r"(?:https?://|www\.)[^\s<>]+",
    "KR_PERSON": r"(?:성\s*명|이\s*름|예금주|수취인|받는\s*분|담당자|고객명|사용자명|name)\s*[:：=]\s*(?P<person>[가-힣]{2,5})(?![가-힣])",
    "KR_ADDRESS": r"(?:주\s*소|배송지|거주지|소재지)\s*[:：=]?\s*[^\n]{5,120}|(?:서울|부산|대구|인천|광주|대전|울산|세종|제주|경기|강원|충청|전라|경상)[가-힣]*(?:\s+[가-힣0-9]+){1,5}\s+[가-힣0-9]+(?:로|길|동|읍|면)\s*\d[^\n]{0,60}",
    "LABELED_PRIVATE": r"(?:계좌(?:번호)?|카드\s*번호|생년월일|생일|아이디|로그인\s*ID|비밀번호|password|api[_\s-]?key|access[_\s-]?token|인증\s*번호)\s*[:：=]?\s*[^\n]{2,100}",
}

_lock = threading.Lock()
_analyzer = None
_ocr = None
_models_prepared = False
_PRIVATE_MENU = re.compile(
    r"(?:비밀번호|password|아이디|로그인\s*ID|api[_\s-]?key|access[_\s-]?token)\s*"
    r"(?:변경|바꾸기|수정|설정|재설정|찾기|입력|검색|확인|복사)", re.I,
)


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        import spacy
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
        from presidio_analyzer.nlp_engine import SpacyNlpEngine
        from presidio_analyzer.predefined_recognizers import CreditCardRecognizer, IpRecognizer
        from .korean_ner import KoreanPersonRecognizer

        # shortcut: addresses use rules; add an address model for free-form addresses.
        nlp = SpacyNlpEngine()
        nlp.nlp = {"ko": spacy.blank("xx")}
        registry = RecognizerRegistry(supported_languages=["ko"])
        registry.add_recognizer(CreditCardRecognizer(supported_language="ko"))
        registry.add_recognizer(IpRecognizer(supported_language="ko"))
        registry.add_recognizer(KoreanPersonRecognizer())
        for entity, pattern in KOREAN_PATTERNS.items():
            registry.add_recognizer(PatternRecognizer(
                supported_entity=entity, supported_language="ko",
                patterns=[Pattern(name=entity, regex=pattern, score=0.85)],
            ))
        _analyzer = AnalyzerEngine(registry=registry, nlp_engine=nlp, supported_languages=["ko"])
    return _analyzer


def _find_spans(text):
    """Map normal and whitespace-joined detections back to original offsets."""
    if not text:
        return []
    analyzer = _get_analyzer()
    spans = [(item.start, item.end) for item in analyzer.analyze(text=text, language="ko")
             if not (item.entity_type == "LABELED_PRIVATE"
                     and _PRIVATE_MENU.fullmatch(text[item.start:item.end].strip()))]
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[index] for index in positions)
    if compact != text and compact:
        numeric_entities = ["KR_RRN", "KR_PHONE", "KR_PASSPORT", "KR_DRIVER_LICENSE",
                            "KR_ACCOUNT", "LONG_NUMBER", "CREDIT_CARD"]
        spans.extend((positions[item.start], positions[item.end - 1] + 1)
                     for item in analyzer.analyze(text=compact, language="ko", entities=numeric_entities))
    return spans


def _redact_text(text, known_values):
    spans = _find_spans(text)
    for value in known_values:
        spans.extend((match.start(), match.end()) for match in re.finditer(re.escape(value), text))
    # Merge before replacement so overlapping entities cannot leave fragments.
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        text = text[:start] + "[REDACTED]" + text[end:]
    return text


def prepare(*, cancelled=lambda: False) -> bool:
    """합성 입력으로 OCR·이름 인식을 차례로 준비한다. 화면 캡처나 API 호출은 없다."""
    global _ocr, _models_prepared
    with _lock:
        if cancelled():
            return False
        if _models_prepared:
            return True
        import cv2
        import numpy as np
        from .ocr_worker import OCRWorker

        if _ocr is None:
            _ocr = OCRWorker()
        pixels = np.full((64, 256, 3), 255, dtype=np.uint8)
        cv2.putText(pixels, "warmup", (8, 45), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 0), 2, cv2.LINE_AA)
        if len(list(_ocr.predict(pixels, return_word_box=True))) != 1:
            raise ScreenPrivacyError("화면 글자 인식 모델을 준비하지 못했어요")
        log_event('screen.models.progress', '글자 인식 준비 완료', category='대화·AI',
                  completed=1, total=2, detail='글자 인식 완료 · 개인정보 인식을 준비하는 중')
        if cancelled():
            return False
        _get_analyzer().analyze(text="모델준비확인", language="ko")
        _models_prepared = True
        return True


def redact_screen(image, prompt: str, system_instruction: str | None = None, *, diagnostics=None):
    """Return a masked RGB image and scrubbed request text, or raise safely.

    Models are initialized lazily and serialized across request threads. Paddle
    runs in a child process so CPU inference cannot hold the GUI's GIL.
    No images/text are saved.
    Optional preview diagnostics stay in caller-owned memory and are never logged.
    """
    global _ocr
    try:
        import cv2
        import numpy as np
        from PIL import Image

        with _lock:
            _get_analyzer()
            if _ocr is None:
                from .ocr_worker import OCRWorker

                _ocr = OCRWorker()
            pixels = np.array(image.convert("RGB"), copy=True)
            height, width = pixels.shape[:2]
            if not height or not width:
                raise ValueError("empty image")
            results = list(_ocr.predict(cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR), return_word_box=True))
            if len(results) != 1:
                raise ValueError("missing OCR page")
            result = results[0]
            texts, scores = result["rec_texts"], result["rec_scores"]
            polygons, detected = result["rec_polys"], result["dt_polys"]
            if not len(texts) == len(scores) == len(polygons):
                raise ValueError("incomplete OCR result")

            def rectangle(polygon):
                points = np.asarray(polygon, dtype=float)
                if points.shape != (4, 2) or not np.isfinite(points).all():
                    raise ValueError("invalid OCR coordinates")
                left, top = np.floor(points.min(axis=0)).astype(int)
                right, bottom = np.ceil(points.max(axis=0)).astype(int)
                if right <= left or bottom <= top or right <= 0 or bottom <= 0 or left >= width or top >= height:
                    raise ValueError("OCR coordinates outside image")
                margin = max(4, math.ceil((bottom - top) * 0.15))
                return (max(0, left - margin), max(0, top - margin),
                        min(width - 1, right + margin), min(height - 1, bottom + margin))

            boxes = [rectangle(polygon) for polygon in polygons]
            detected_boxes = [rectangle(polygon) for polygon in detected]
            if any(box not in detected_boxes for box in boxes):
                raise ValueError("unmatched OCR recognition")
            masked = set()
            lines = []
            words = result.get("text_word")
            word_polygons = result.get("text_word_region")
            if (words is None) != (word_polygons is None) or (
                words is not None and not len(words) == len(word_polygons) == len(texts)
            ):
                raise ValueError("incomplete OCR word result")
            for index, (text, score, box) in enumerate(zip(texts, scores, boxes)):
                if not isinstance(text, str) or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
                    raise ValueError("invalid OCR text or confidence")
                word_spans = []
                if words is not None:
                    if len(words[index]) != len(word_polygons[index]):
                        raise ValueError("incomplete OCR word coordinates")
                    cursor = 0
                    for word, poly in zip(words[index], word_polygons[index]):
                        if not isinstance(word, str) or not word:
                            raise ValueError("invalid OCR word")
                        start = text.find(word, cursor)
                        if start < 0:
                            raise ValueError("unaligned OCR word")
                        cursor = start + len(word)
                        word_box = rectangle(poly)
                        if not (box[0] <= word_box[0] < word_box[2] <= box[2]
                                and box[1] <= word_box[1] < word_box[3] <= box[3]):
                            raise ValueError("OCR word outside its line")
                        word_spans.append((start, cursor, word_box))
                lines.append((box, text, word_spans))
            lines.sort(key=lambda line: (line[0][1], line[0][0]))
            combined = "\n".join(text for _, text, _ in lines)
            spans = _find_spans(combined)
            if diagnostics is not None:
                diagnostics.update(ocr_text=combined, pii_spans=tuple(spans))
            known_values = set()
            for start, end in spans:
                value = combined[start:end].strip()
                if value:
                    known_values.add(value)
                    # Labeled Korean names can also occur without the label in titles.
                    name = re.match(KOREAN_PATTERNS["KR_PERSON"], value, re.I)
                    if name:
                        known_values.add(name.group("person"))
            offset = 0
            for box, text, word_spans in lines:
                for start, end in spans:
                    local_start, local_end = max(0, start - offset), min(len(text), end - offset)
                    if local_start >= local_end:
                        continue
                    covered = set()
                    selected = set()
                    for word_start, word_end, word_box in word_spans:
                        if word_start < local_end and word_end > local_start:
                            selected.add(word_box)
                            covered.update(range(word_start, word_end))
                    required = {i for i in range(local_start, local_end) if not text[i].isspace()}
                    # Fall back to the line if word boxes cannot cover the entire entity.
                    masked.update(selected if required <= covered else {box})
                offset += len(text) + 1
            for left, top, right, bottom in masked:
                cv2.rectangle(pixels, (left, top), (right, bottom), (0, 0, 0), thickness=-1)
            return (Image.fromarray(pixels), _redact_text(prompt, known_values),
                    _redact_text(system_instruction, known_values) if system_instruction else system_instruction)
    except Exception:
        # Exception messages from OCR can contain input data; never expose them.
        raise ScreenPrivacyError("화면 개인정보 보호 처리에 실패하여 전송을 차단했습니다.") from None
