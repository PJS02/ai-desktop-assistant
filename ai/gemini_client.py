"""Gemini API request and configuration shared by all app features."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app_logging import log_event, new_trace_id, register_secret


AI_DIR = Path(__file__).resolve().parent
CONFIG_PATH = AI_DIR / "config" / "gemini_config.json"
LEGACY_CONFIG_PATHS = (
    AI_DIR.parent / "context" / "gemini_config.json",
    AI_DIR.parent / "context" / "config" / "gemini_config.json",
)


def _read_config():
    for path in (CONFIG_PATH, *LEGACY_CONFIG_PATHS):
        if path.exists():
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or any(
                not isinstance(config.get(field, ""), str) for field in ("api_key", "model")
            ):
                raise ValueError("AI 설정 파일 형식이 올바르지 않습니다.")
            register_secret(config.get("api_key", ""))
            return config, path
    return {}, None


def _write_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def load_gemini_config() -> dict:
    """Prefer central settings; migrate legacy settings without deleting the original."""
    config, path = _read_config()
    if path is not None and path != CONFIG_PATH:
        _write_config(config)
    log_event("settings.ai.loaded" if path else "settings.ai.fallback", "AI 설정 로드",
              path=str(path) if path else None, model=config.get("model", ""),
              api_key_present=bool(config.get("api_key")))
    return config


def save_gemini_config(api_key, model, *, trace_id=None):
    """Atomically update the one shared config, preserving unrelated settings."""
    register_secret(api_key)
    try:
        if not isinstance(api_key, str) or not isinstance(model, str):
            raise ValueError("API 키와 모델은 문자열이어야 합니다.")
        config, _ = _read_config()
        config.update(api_key=api_key, model=model)
        _write_config(config)
        log_event("settings.ai.saved", "AI 공통 설정 저장", trace_id=trace_id,
                  path=str(CONFIG_PATH), model=model, api_key_present=bool(api_key))
    except (OSError, ValueError) as error:
        log_event("settings.ai.save_failed", "AI 설정 저장 실패: 기존 파일 유지",
                  category="오류", level="ERROR", trace_id=trace_id, error=str(error))
        raise


def request_gemini(
    prompt: str,
    config: dict,
    *,
    image=None,
    response_schema: dict | None = None,
    system_instruction: str | None = None,
    log_context: dict | None = None,
) -> str:
    """Send one Gemini request with feature-specific output rules."""
    api_key = config.get("api_key", "")
    context = dict(log_context or {})
    trace_id = context.get("trace_id") or new_trace_id("gemini")
    register_secret(api_key)
    if not api_key:
        log_event("gemini.skipped", "Gemini 호출 생략", category="대화·AI",
                  level="WARNING", trace_id=trace_id, reason="missing_api_key")
        return ""

    model = config.get("model") or "gemma-3-4b-it"
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    parts = [{"text": prompt}]
    if image is not None:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buffer.getvalue()).decode("ascii")}})

    payload = {"contents": [{"parts": parts}]}
    if response_schema is not None:
        payload["generationConfig"] = {"responseMimeType": "application/json", "responseJsonSchema": response_schema}
    if system_instruction:
        payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

    log_event("gemini.request", "Gemini 실제 요청 본문", category="대화·AI",
              trace_id=trace_id, model=model, payload=payload,
              source=context.get("source"), timeout_seconds=30)
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    for attempt in range(3):
        started = time.monotonic()
        log_event("gemini.attempt_started", "Gemini HTTP 요청 시작", category="대화·AI",
                  trace_id=trace_id, attempt=attempt + 1, model=model)
        try:
            with urlopen(request, timeout=30) as response:
                raw_body = response.read().decode("utf-8")
                status = getattr(response, "status", None)
            log_event("gemini.http_response", "Gemini HTTP 응답 전체", category="대화·AI",
                      trace_id=trace_id, attempt=attempt + 1, status=status,
                      elapsed_ms=round((time.monotonic() - started) * 1000, 2), body=raw_body)
            data = json.loads(raw_body)
            break
        except HTTPError as error:
            try:
                error_body = error.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            log_event("gemini.http_failed", "Gemini HTTP 요청 실패", category="대화·AI",
                      level="ERROR", trace_id=trace_id, attempt=attempt + 1,
                      status=error.code, error=str(error), body=error_body,
                      elapsed_ms=round((time.monotonic() - started) * 1000, 2))
            if error.code == 500 and attempt < 2:
                log_event("gemini.retry_scheduled", "Gemini 서버 오류 재시도", category="대화·AI",
                          level="WARNING", trace_id=trace_id, attempt=attempt + 1,
                          next_attempt=attempt + 2, delay_seconds=1 + attempt)
                time.sleep(1 + attempt)
                continue
            return f"[gemini error] {error}"
        except URLError as error:
            log_event("gemini.connection_failed", "Gemini 연결 실패", category="대화·AI",
                      level="ERROR", trace_id=trace_id, attempt=attempt + 1, error=str(error),
                      elapsed_ms=round((time.monotonic() - started) * 1000, 2))
            return f"[gemini error] {error}"
        except Exception as error:
            log_event("gemini.failed", "Gemini 응답 처리 실패", category="대화·AI",
                      level="ERROR", trace_id=trace_id, attempt=attempt + 1, error=str(error),
                      elapsed_ms=round((time.monotonic() - started) * 1000, 2))
            return f"[gemini error] {error}"

    candidates = data.get("candidates", [])
    if not candidates:
        log_event("gemini.empty_response", "Gemini 응답 후보 없음", category="대화·AI",
                  level="ERROR", trace_id=trace_id, reason="no_candidates", response=data)
        return "[gemini error] no candidates"
    response_parts = candidates[0].get("content", {}).get("parts", [])
    if not response_parts:
        log_event("gemini.empty_response", "Gemini 응답 내용 없음", category="대화·AI",
                  level="ERROR", trace_id=trace_id, reason="empty_content", response=data)
        return "[gemini error] empty content"
    selected = response_parts[0].get("text", "").strip()
    log_event("gemini.text_extracted", "Gemini 첫 후보의 첫 텍스트 추출", category="대화·AI",
              level="INFO" if selected else "WARNING", trace_id=trace_id,
              candidate_index=0, part_index=0, text=selected,
              finish_reason=candidates[0].get("finishReason"),
              usage=data.get("usageMetadata"), prompt_feedback=data.get("promptFeedback"))
    return selected
