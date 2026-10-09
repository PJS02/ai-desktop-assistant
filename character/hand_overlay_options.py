"""Hand display settings shared by storage, controls and the desktop overlay."""
import math


DEFAULT_HAND_OVERLAY_OPTIONS = {
    'enabled': False,
    'size_percent': 100,
    'range_percent': 70,
    'max_hands': 1,
    'smooth': True,
}
HAND_OVERLAY_OPTION_RANGES = {'size_percent': (50, 200), 'range_percent': (30, 100)}


def normalize_hand_overlay_options(options=None, strict=False):
    if strict and options is not None and not isinstance(options, dict):
        raise ValueError('손 표시 설정 형식이 올바르지 않습니다.')
    options = options if isinstance(options, dict) else {}
    result = {}
    for key, default in DEFAULT_HAND_OVERLAY_OPTIONS.items():
        value = options.get(key, default)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif key == 'max_hands':
            valid = isinstance(value, int) and not isinstance(value, bool) and value in (1, 2)
        else:
            low, high = HAND_OVERLAY_OPTION_RANGES[key]
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(value) and low <= value <= high)
        if not valid and strict:
            raise ValueError(f'{key}: 손 표시 설정값이 올바르지 않습니다.')
        if not valid:
            result[key] = default
        else:
            result[key] = value if isinstance(default, bool) else round(value)
    return result
