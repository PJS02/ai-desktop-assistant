"""Settings UI compatibility exports; all Gemini settings live in ai/config."""

from ai.gemini_client import (
    load_gemini_config as load_ai_settings,
    save_gemini_config as save_ai_settings,
)
