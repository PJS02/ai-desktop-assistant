"""Gemini API request and configuration shared by all app features."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


AI_DIR = Path(__file__).resolve().parent
CONFIG_PATH = AI_DIR / "config" / "gemini_config.json"
LEGACY_CONFIG_PATHS = (AI_DIR.parent / "context" / "config" / "gemini_config.json",)


def load_gemini_config() -> dict:
    """Load central config and migrate the existing context config once."""
    for index, path in enumerate((CONFIG_PATH, *LEGACY_CONFIG_PATHS)):
        if path.exists():
            try:
                config = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            if index:
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
            return config
    return {}


def request_gemini(
    prompt: str,
    config: dict,
    *,
    image=None,
    response_schema: dict | None = None,
    system_instruction: str | None = None,
) -> str:
    """Send one Gemini request with feature-specific output rules."""
    api_key = config.get("api_key", "")
    if not api_key:
        return ""

    model = config.get("model", "gemma-3-4b-it")
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

    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/json")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as error:
            if error.code == 500 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            return f"[gemini error] {error}"
        except URLError as error:
            return f"[gemini error] {error}"
        except Exception as error:
            return f"[gemini error] {error}"

    candidates = data.get("candidates", [])
    if not candidates:
        return "[gemini error] no candidates"
    response_parts = candidates[0].get("content", {}).get("parts", [])
    return response_parts[0].get("text", "").strip() if response_parts else "[gemini error] empty content"
