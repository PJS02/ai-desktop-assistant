# 해상도 설정 저장/불러오기
import json
from pathlib import Path
from app_logging import log_event
from .motion_options import normalize_character_options
from .dialogue_styles import normalize_dialogue_style
from .hand_overlay_options import normalize_hand_overlay_options


CONFIG_FILE = Path.home() / ".ai_desktop_assistant" / "config.json"


def load_config():
    """저장된 설정 불러오기 (해상도, 성격)"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 새로운 형식: resolution.width/height
                if 'resolution' in config:
                    width = config['resolution'].get('width', 1920)
                    height = config['resolution'].get('height', 1080)
                else:
                    # 이전 형식 호환성: 최상위 width/height
                    width = config.get('width', 1920)
                    height = config.get('height', 1080)
                
                # 성격 불러오기
                personality = config.get('personality', 'Russell (기본)')
                
                return width, height, personality
        except Exception as e:
            log_event('settings.character.fallback', '캐릭터 설정 오류로 기본값을 사용합니다.',
                      category='오류', level='ERROR', path=str(CONFIG_FILE), error=str(e))
            print(f"[설정 읽기 오류] {e}, 기본값 사용")
            return 1920, 1080, 'Russell (기본)'
    log_event('settings.character.fallback', '캐릭터 설정 파일이 없어 기본값을 사용합니다.',
              path=str(CONFIG_FILE), reason='missing_file')
    return 1920, 1080, 'Russell (기본)'


def load_character_options():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
        return normalize_character_options(data.get('character_options', {}))
    except (OSError, ValueError, AttributeError) as exc:
        log_event('settings.motion.fallback', '동작 설정을 기본값으로 복구했습니다.',
                  level='WARNING', path=str(CONFIG_FILE), error=str(exc))
        return normalize_character_options()


def load_dialogue_style():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
        return normalize_dialogue_style(data.get('dialogue', {}).get('style'))
    except (OSError, ValueError, AttributeError) as exc:
        log_event('settings.dialogue.fallback', '말풍선 설정을 기본값으로 복구했습니다.',
                  level='WARNING', path=str(CONFIG_FILE), error=str(exc))
        return normalize_dialogue_style(None)


def load_hand_overlay_options():
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
        return normalize_hand_overlay_options(data.get('hand_overlay', {}))
    except (OSError, ValueError, AttributeError) as exc:
        log_event('settings.hand_overlay.fallback', '손 표시 설정을 기본값으로 복구했습니다.',
                  level='WARNING', path=str(CONFIG_FILE), error=str(exc))
        return normalize_hand_overlay_options()


def save_hand_overlay_options(options, *, trace_id=None):
    """Save hand settings atomically while preserving the other config sections."""
    values = normalize_hand_overlay_options(options, strict=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('설정 파일 형식이 올바르지 않습니다.')
    saved = config.get('hand_overlay', {})
    saved = saved.copy() if isinstance(saved, dict) else {}
    saved.update(values)
    config['hand_overlay'] = saved
    temporary = CONFIG_FILE.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(CONFIG_FILE)
    log_event('settings.hand_overlay.saved', '손 표시 설정을 저장했습니다.', trace_id=trace_id,
              path=str(CONFIG_FILE), values=values)
    return values


def save_config(width, height, personality='Russell (기본)', character_options=None,
                dialogue_style=None, *, trace_id=None):
    """설정 저장 (해상도, 성격)"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding='utf-8')) if CONFIG_FILE.exists() else {}
        if not isinstance(config, dict):
            raise ValueError('설정 파일 형식이 올바르지 않습니다.')
        config.update(resolution={'width': width, 'height': height}, personality=personality)
        if dialogue_style is not None:
            dialogue = config.get('dialogue', {})
            dialogue = dialogue.copy() if isinstance(dialogue, dict) else {}
            dialogue['style'] = normalize_dialogue_style(dialogue_style, strict=True)
            config['dialogue'] = dialogue
        if character_options is not None:
            saved_options = config.get('character_options', {})
            saved_options = saved_options.copy() if isinstance(saved_options, dict) else {}
            saved_options.update(normalize_character_options(character_options, strict=True))
            config['character_options'] = saved_options
        temporary = CONFIG_FILE.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(CONFIG_FILE)
        log_event('settings.character.saved', '캐릭터 설정 파일을 저장했습니다.',
                  trace_id=trace_id, path=str(CONFIG_FILE), resolution=config['resolution'],
                  personality=personality, character_options=config.get('character_options'),
                  dialogue=config.get('dialogue'))
        print(f"[설정 저장] {width}x{height}px, 성격: {personality} → {CONFIG_FILE}")
    except Exception as e:
        log_event('settings.character.save_failed', '캐릭터 설정 저장에 실패했습니다.',
                  category='오류', level='ERROR', trace_id=trace_id,
                  path=str(CONFIG_FILE), error=str(e))
        print(f"[설정 저장 오류] {e}")
        raise
