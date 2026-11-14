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
from context.screen_privacy import ScreenPrivacyError, redact_screen


AI_DIR = Path(__file__).resolve().parent
REQUEST_TIMEOUT_SECONDS = 120
DAILY_REQUEST_QUOTA_EXHAUSTED = "[gemini error] HTTP 429: daily model request quota exhausted"
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


def is_screen_privacy_enabled(config):
    return config.get("screen_privacy_enabled") is not False


def _allows_unmasked_screen():
    try:
        config, _ = _read_config()
    except (OSError, ValueError):
        return False
    return not is_screen_privacy_enabled(config)


def save_gemini_config(api_key, model, *, screen_privacy_enabled=None, trace_id=None):
    """Atomically update the one shared config, preserving unrelated settings."""
    register_secret(api_key)
    try:
        if not isinstance(api_key, str) or not isinstance(model, str):
            raise ValueError("API 키와 모델은 문자열이어야 합니다.")
        config, _ = _read_config()
        config.update(api_key=api_key, model=model)
        if screen_privacy_enabled is not None:
            if not isinstance(screen_privacy_enabled, bool):
                raise ValueError("화면 개인정보 마스킹 설정은 켬 또는 끔이어야 합니다.")
            config["screen_privacy_enabled"] = screen_privacy_enabled
        _write_config(config)
        log_event("settings.ai.saved", "AI 공통 설정 저장", trace_id=trace_id,
                  path=str(CONFIG_PATH), model=model, api_key_present=bool(api_key))
    except (OSError, ValueError) as error:
        log_event("settings.ai.save_failed", "AI 설정 저장 실패: 기존 파일 유지",
                  category="오류", level="ERROR", trace_id=trace_id, error=str(error))
        raise


def _is_daily_model_quota(error_body):
    try:
        details = json.loads(error_body)["error"]["details"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(details, list):
        return False
    for detail in details:
        if not isinstance(detail, dict) or detail.get("@type") != "type.googleapis.com/google.rpc.QuotaFailure":
            continue
        violations = detail.get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if isinstance(violation, dict) and (
                violation.get("quotaId") in (
                    "GenerateRequestsPerDayPerProjectPerModel",
                    "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                )
                or violation.get("quotaMetric") == "generativelanguage.googleapis.com/generate_requests_per_model_per_day"
            ):
                return True
    return False


def request_gemini(
    prompt: str,
    config: dict,
    *,
    image=None,
    response_schema: dict | None = None,
    system_instruction: str | None = None,
    log_context: dict | None = None,
    timeout_seconds: float | None = None,
    max_attempts: int = 3,
    deadline: float | None = None,
) -> str:
    """Send one Gemini request with feature-specific output rules."""
    api_key = config.get("api_key", "")
    context = dict(log_context or {})
    trace_id = context.get("trace_id") or new_trace_id("gemini")
    register_secret(api_key)
    timeout = REQUEST_TIMEOUT_SECONDS if timeout_seconds is None else max(.1, float(timeout_seconds))
    attempts = max(1, min(3, int(max_attempts)))

    def expired():
        if deadline is not None and time.monotonic() >= deadline:
            log_event('gemini.expired', '요청 유효 시간이 지나 전송을 생략합니다.',
                      category='대화·AI', trace_id=trace_id, source=context.get('source'))
            return True
        return False
    if not api_key:
        log_event("gemini.skipped", "Gemini 호출 생략", category="대화·AI",
                  level="WARNING", trace_id=trace_id, reason="missing_api_key")
        return ""

    if expired():
        return '[gemini error] request deadline exceeded'

    unmasked_screen = (image is not None and not is_screen_privacy_enabled(config)
                       and _allows_unmasked_screen())
    if image is not None and not unmasked_screen:
        try:
            image, prompt, system_instruction = redact_screen(image, prompt, system_instruction)
        except ScreenPrivacyError:
            log_event("gemini.privacy_blocked", "화면 개인정보 보호 실패로 요청 차단", category="대화·AI",
                      level="ERROR", trace_id=trace_id, source=context.get("source"))
            return "[gemini error] 화면 개인정보 보호 처리 실패: 요청을 전송하지 않았습니다."
        log_event("gemini.screen_redacted", "활성 창 개인정보 마스킹 완료", category="대화·AI",
                  trace_id=trace_id, width=image.width, height=image.height)

    if expired():
        return '[gemini error] request deadline exceeded'

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

    log_payload = dict(payload)
    log_prompt = "[UNMASKED SCREEN CONTEXT OMITTED]" if unmasked_screen else prompt
    log_payload["contents"] = [{"parts": [
        {"inlineData": {"mimeType": "image/png", "data": "[IMAGE OMITTED]"}}
        if "inlineData" in part else {"text": log_prompt} for part in parts]}]
    if unmasked_screen:
        log_payload.pop("system_instruction", None)
    log_event("gemini.request", "Gemini 요청 본문 (이미지 데이터 제외)", category="대화·AI",
              trace_id=trace_id, model=model, payload=log_payload,
              source=context.get("source"), timeout_seconds=timeout, max_attempts=attempts,
              unmasked_screen=unmasked_screen)
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    for attempt in range(attempts):
        if expired():
            return '[gemini error] request deadline exceeded'
        if unmasked_screen and not _allows_unmasked_screen():
            log_event("gemini.skipped", "화면 마스킹 설정이 변경되어 요청을 중단했습니다.",
                      category="대화·AI", trace_id=trace_id, reason="screen_privacy_reenabled")
            return "[gemini error] 화면 마스킹 설정이 변경되었습니다. 다시 요청해 주세요."
        started = time.monotonic()
        log_event("gemini.attempt_started", "Gemini HTTP 요청 시작", category="대화·AI",
                  trace_id=trace_id, attempt=attempt + 1, model=model)
        try:
            remaining_timeout = min(timeout, max(.1, deadline - started)) if deadline is not None else timeout
            with urlopen(request, timeout=remaining_timeout) as response:
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
            if error.code == 429 and _is_daily_model_quota(error_body):
                return DAILY_REQUEST_QUOTA_EXHAUSTED
            if error.code in (500, 502, 503, 504) and attempt + 1 < attempts:
                log_event("gemini.retry_scheduled", "Gemini 서버 오류 재시도", category="대화·AI",
                          level="WARNING", trace_id=trace_id, attempt=attempt + 1,
                          next_attempt=attempt + 2, delay_seconds=1 + attempt)
                time.sleep(1 + attempt)
                continue
            return f"[gemini error] {error}"
        except (TimeoutError, URLError) as error:
            timed_out = isinstance(error, TimeoutError) or isinstance(error.reason, TimeoutError)
            retry = timed_out and attempt + 1 < attempts
            log_event("gemini.timeout" if timed_out else "gemini.connection_failed",
                      "Gemini 응답 대기 시간 초과" if timed_out else "Gemini 연결 실패", category="대화·AI",
                      level="WARNING" if retry else "ERROR", trace_id=trace_id,
                      attempt=attempt + 1, error=str(error), timeout_seconds=remaining_timeout,
                      elapsed_ms=round((time.monotonic() - started) * 1000, 2))
            if retry:
                log_event("gemini.retry_scheduled", "Gemini 시간 초과 재시도", category="대화·AI",
                          level="WARNING", trace_id=trace_id, attempt=attempt + 1,
                          next_attempt=attempt + 2, delay_seconds=1 + attempt)
                time.sleep(1 + attempt)
                continue
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
