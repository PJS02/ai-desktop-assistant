"""User-facing units shared by the settings UI, storage and character host."""
import math

DEFAULT_CHARACTER_OPTIONS = {'size_percent': 100, 'movement_speed': 80, 'jump_height': 225,
                             'show_hitboxes': True}
CHARACTER_OPTION_RANGES = {'size_percent': (50, 200), 'movement_speed': (20, 400), 'jump_height': (20, 500)}


def normalize_character_options(options=None, strict=False):
    options = options if isinstance(options, dict) else {}
    result = {}
    for key, default in DEFAULT_CHARACTER_OPTIONS.items():
        value = options.get(key, default)
        if isinstance(default, bool):
            if not isinstance(value, bool) and strict:
                raise ValueError(f'{key}: 켜기/끄기 값이 올바르지 않습니다.')
            result[key] = value if isinstance(value, bool) else default
            continue
        low, high = CHARACTER_OPTION_RANGES[key]
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and low <= value <= high)
        if not valid and strict:
            raise ValueError(f'{key}: 설정 범위를 벗어났습니다.')
        result[key] = round(value) if valid else default
    return result
