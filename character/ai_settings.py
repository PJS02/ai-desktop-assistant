"""Shared Gemini settings for the character and standalone context classifier."""
import json
from pathlib import Path

CONTEXT_ROOT = Path(__file__).resolve().parents[1] / 'context'
GEMINI_PATHS = (CONTEXT_ROOT / 'gemini_config.json', CONTEXT_ROOT / 'config' / 'gemini_config.json')


def load_ai_settings():
    for path in GEMINI_PATHS:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('AI 설정 파일 형식이 올바르지 않습니다.')
            return data
    return {'api_key': '', 'model': ''}


def save_ai_settings(api_key, model):
    """Preserve extra keys and restore both consumers' files if a write fails."""
    originals = {path: path.read_bytes() if path.exists() else None for path in GEMINI_PATHS}
    staged = []
    replaced = []
    try:
        for path, original in originals.items():
            data = json.loads(original.decode('utf-8')) if original is not None else {}
            if not isinstance(data, dict):
                raise ValueError('AI 설정 파일 형식이 올바르지 않습니다.')
            data.update(api_key=api_key, model=model)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.json.tmp')
            staged.append(temp)
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        for path, temp in zip(GEMINI_PATHS, staged):
            temp.replace(path)
            replaced.append(path)
    except Exception:
        for path in replaced:
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(originals[path])
        raise
    finally:
        for temp in staged:
            temp.unlink(missing_ok=True)
