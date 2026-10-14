"""Shared Gemini settings for the character and standalone context classifier."""
import json
from pathlib import Path
from app_logging import log_event, register_secret

CONTEXT_ROOT = Path(__file__).resolve().parents[1] / 'context'
GEMINI_PATHS = (CONTEXT_ROOT / 'gemini_config.json', CONTEXT_ROOT / 'config' / 'gemini_config.json')


def load_ai_settings():
    for path in GEMINI_PATHS:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('AI 설정 파일 형식이 올바르지 않습니다.')
            register_secret(data.get('api_key', ''))
            log_event('settings.ai.loaded', 'AI 설정을 읽었습니다.', path=str(path),
                      model=data.get('model', ''), api_key_present=bool(data.get('api_key')))
            return data
    log_event('settings.ai.fallback', 'AI 설정 파일이 없어 기본값을 사용합니다.',
              level='WARNING', paths=[str(path) for path in GEMINI_PATHS])
    return {'api_key': '', 'model': ''}


def save_ai_settings(api_key, model, *, trace_id=None):
    """Preserve extra keys and restore both consumers' files if a write fails."""
    originals = {path: path.read_bytes() if path.exists() else None for path in GEMINI_PATHS}
    staged = []
    replaced = []
    register_secret(api_key)
    try:
        for path, original in originals.items():
            data = json.loads(original.decode('utf-8')) if original is not None else {}
            if not isinstance(data, dict):
                raise ValueError('AI 설정 파일 형식이 올바르지 않습니다.')
            register_secret(data.get('api_key', ''))
            data.update(api_key=api_key, model=model)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.json.tmp')
            staged.append(temp)
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        for path, temp in zip(GEMINI_PATHS, staged):
            temp.replace(path)
            replaced.append(path)
        log_event('settings.ai.saved', '두 AI 설정 파일을 저장했습니다.', trace_id=trace_id,
                  paths=[str(path) for path in replaced], model=model,
                  api_key_present=bool(api_key))
    except Exception as exc:
        log_event('settings.ai.save_failed', 'AI 설정 저장에 실패해 원본을 복원합니다.',
                  category='오류', level='ERROR', trace_id=trace_id,
                  error=str(exc), replaced_paths=[str(path) for path in replaced])
        for path in replaced:
            try:
                if originals[path] is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(originals[path])
            except OSError as rollback_exc:
                log_event('settings.ai.rollback_failed', 'AI 설정 원본 복원에 실패했습니다.',
                          category='오류', level='ERROR', trace_id=trace_id,
                          path=str(path), error=str(rollback_exc))
                raise
        log_event('settings.ai.rolled_back', '변경된 AI 설정 파일을 원본으로 복원했습니다.',
                  trace_id=trace_id, paths=[str(path) for path in replaced])
        raise
    finally:
        for temp in staged:
            temp.unlink(missing_ok=True)
