"""User-facing units shared by the settings UI, storage and character host."""
import math

DEFAULT_CHARACTER_OPTIONS = {'size_percent': 100, 'movement_speed': 80, 'jump_height': 225}
CHARACTER_OPTION_RANGES = {'size_percent': (50, 200), 'movement_speed': (20, 400), 'jump_height': (20, 500)}


def normalize_character_options(options=None, strict=False):
    options = options if isinstance(options, dict) else {}
    result = {}
    for key, default in DEFAULT_CHARACTER_OPTIONS.items():
        value = options.get(key, default)
        low, high = CHARACTER_OPTION_RANGES[key]
        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and low <= value <= high)
        if not valid and strict:
            raise ValueError(f'{key}: 설정 범위를 벗어났습니다.')
        result[key] = round(value) if valid else default
    return result
