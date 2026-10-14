"""Classify unstructured diagnostics without confusing the stream with severity.

The domain identifies where a message belongs. Severity is determined separately
from explicit diagnostic markers; arbitrary stderr output remains a warning so
it stays visible without being presented as a confirmed failure.
"""
from __future__ import annotations

import re


_ERROR = re.compile(
    r'^(?:\s*(?:\[[^\]\n]*(?:오류|실패|error|fatal|critical)[^\]\n]*\]'
    r'|(?:ERROR|FATAL|CRITICAL)\b\s*[:\]\s]'
    r'|Traceback\s*\(most recent call last\)'
    r'|[\w.]+(?:Error|Exception)\s*:'
    r'|[EF]\d{4}\s)'
    r'|\d{4}-\d{2}-\d{2}[^\n]*?:\s*[EF]\s+)', re.I)
_WARNING = re.compile(
    r'^(?:\s*(?:\[[^\]\n]*(?:경고|warning|warn)[^\]\n]*\]'
    r'|(?:WARNING|WARN)\b\s*[:\]\s]'
    r'|[W]\d{4}\s)'
    r'|\d{4}-\d{2}-\d{2}[^\n]*?:\s*W\s+)', re.I)
_INFO = re.compile(
    r'^(?:\s*(?:\[(?:INFO|정보|DEBUG)\]'
    r'|(?:INFO|DEBUG)\b\s*[:\]\s]'
    r'|I\d{4}\s)'
    r'|\d{4}-\d{2}-\d{2}[^\n]*?:\s*I\s+)', re.I)

_RECOGNITION = (
    'mediapipe', 'tensorflow', 'xnnpack', '외부 감정', '외부 동작', '외부 음성',
    '사용자 인사', '외부 고개', '외부 상태', '인식 수신기', 'recognition',
    'speech', 'stt', '음성 인식', '카메라', '마이크', '사용자 인식',
    '감정 인식', '동작 인식', 'attention', '주의 인식', '고개 인식',
)
_DIALOGUE = (
    'gemini', 'api 요청', 'api 응답', 'api request', 'api response', '대사', '대화', 'dialogue', '말풍선',
    'tts', 'supertonic', '음성 출력', '음성 합성', '프롬프트', 'llm',
)
_CHARACTER = (
    '점프', '착지', '애니메이션', '감정 상태', '감정 변화', '현재 기분',
    'mood', 'russell', 'valence', 'arousal', 'idle', 'surface',
    'on_', 'random skip', '드래그', '자율 이벤트', 'self_play', 'self_rest',
    'self_curiosity', '쓰다듬기', '수동 제어', 'rps', '표정', '클릭 이벤트',
    'mousepressevent', 'mousemoveevent', 'mousereleaseevent', '아이템 획득',
    '아이템 반환', '공 놀이', '이동 시작', '이동 완료', '감정 좌표',
)


def _domain(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _RECOGNITION):
        return '사용자 인식'
    if any(marker in lowered for marker in _DIALOGUE):
        return '대화·AI'
    if any(marker in lowered for marker in _CHARACTER) or re.search(r'\bocc\b', lowered) or re.search(
        r'^\s*[\w]+\s*\|\s*[█░]+\s*\|', text, re.M
    ):
        return '캐릭터 상태'
    return '시스템'


def classify_output(message: str, *, is_error: bool = False) -> tuple[str, str]:
    """Return (source domain, level), preserving both even for failed operations."""
    text = str(message)
    # Recognized source labels outrank words in a quoted user/AI response.
    # For example, a Gemini answer mentioning a camera still belongs to AI.
    label = re.match(r'^\s*[^\w\[\n]{0,8}\[([^\]\n]+)\]', text)
    label_domain = _domain(label.group(1)) if label else '시스템'
    domain = label_domain if label_domain != '시스템' else _domain(text)

    lines = text.splitlines() or [text]
    if any(_ERROR.search(line) for line in lines):
        level = 'ERROR'
    elif any(_WARNING.search(line) for line in lines):
        level = 'WARNING'
    elif any(_INFO.search(line) for line in lines):
        level = 'INFO'
    else:
        level = 'WARNING' if is_error else 'INFO'
    return domain, level
