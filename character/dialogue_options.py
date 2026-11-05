"""Dialogue timing settings shared by storage, controls and runtime."""

# True: 활성 창·프로그램을 주기적으로 감지하고 자동 대화를 생성합니다.
# False: 자동 감지를 끄고 사용자가 입력한 대화만 처리합니다.
DEFAULT_DIALOGUE_OPTIONS = {
    'auto_program_detection': True,
    'activity_monitor_interval': 30,
    'auto_dialogue_cooldown': 20,  # 자동 감지 쿨다운: 20초 (API 제한 방지)
    'request_cooldown': 10,  # 수동 요청 사이 최소 10초 (자동 감지와 분리)
}
DIALOGUE_OPTION_RANGES = {
    'activity_monitor_interval': (5, 3600),
    'auto_dialogue_cooldown': (5, 3600),
    'request_cooldown': (0, 300),
}


def normalize_dialogue_options(options=None, strict=False):
    options = options if isinstance(options, dict) else {}
    result = {}
    for key, default in DEFAULT_DIALOGUE_OPTIONS.items():
        value = options.get(key, default)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        else:
            low, high = DIALOGUE_OPTION_RANGES[key]
            valid = (isinstance(value, int) and not isinstance(value, bool)
                     and low <= value <= high)
        if not valid and strict:
            raise ValueError(f'{key}: 대화 설정 값이 올바르지 않습니다.')
        result[key] = value if valid else default
    return result
