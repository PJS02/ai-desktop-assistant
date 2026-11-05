"""User-editable game matching rules stored alongside existing app settings."""
import json
from pathlib import PureWindowsPath

from app_logging import log_event, log_throttled

DEFAULT_GAME_RULES = {'keywords': ['game', 'steam', 'unity'],
                      'included_processes': [], 'excluded_processes': []}


def normalize_game_rules(rules=None):
    if rules is None:
        rules = {}
    if not isinstance(rules, dict):
        raise ValueError('게임 목록 형식이 올바르지 않습니다.')
    result = {}
    for key, default in DEFAULT_GAME_RULES.items():
        entries = rules.get(key, default)
        if not isinstance(entries, list) or any(not isinstance(s, str) for s in entries):
            raise ValueError('게임 목록은 문자열 목록이어야 합니다.')
        values = set()
        for entry in entries:
            entry = entry.strip().lower()
            if not entry:
                continue
            if key != 'keywords':
                entry = PureWindowsPath(entry).name
                if not entry.endswith('.exe'):
                    entry += '.exe'
                if entry == '.exe' or len(entry) > 255 or any(c in entry for c in '<>:"/\\|?*') or not entry.isprintable():
                    raise ValueError('게임 목록에는 실행 파일 이름을 입력하세요. 예: MyGame.exe')
            elif len(entry) > 100 or any(c in entry for c in '\r\n'):
                raise ValueError('게임 키워드는 한 줄에 하나씩 100자 이내로 입력하세요.')
            values.add(entry)
        result[key] = sorted(values)
    return result


def load_game_rules():
    from . import config_manager
    path = config_manager.CONFIG_FILE
    try:
        config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError('설정 파일 형식이 올바르지 않습니다.')
        return normalize_game_rules(config.get('game_rules'))
    except (OSError, ValueError) as exc:
        log_throttled('settings.games.fallback', '게임 목록을 읽지 못해 기본 키워드를 사용합니다.',
                      key='game_rules', interval=30, level='WARNING', error=str(exc))
        return normalize_game_rules()


def save_game_rules(rules, *, trace_id=None):
    from . import config_manager
    values = normalize_game_rules(rules)
    path = config_manager.CONFIG_FILE
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('설정 파일 형식이 올바르지 않습니다.')
    config['game_rules'] = values
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.games.tmp')
    try:
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    log_event('settings.games.saved', '게임 목록을 저장했습니다.', trace_id=trace_id,
              included=len(values['included_processes']), excluded=len(values['excluded_processes']))
    return values


def running_process_names():
    import psutil
    names = set()
    for process in psutil.process_iter(['name']):
        try:
            name = process.info.get('name') or ''
            if name.lower().endswith('.exe'):
                names.add(name.lower())
        except psutil.Error:
            continue
    return sorted(names)
