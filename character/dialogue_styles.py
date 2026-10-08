"""Persisted speech styles; content and playback stay in DialogueSystem."""
DIALOGUE_STYLES = (('기존형', 'legacy'), ('둥근 말풍선형', 'rounded'),
                   ('간결한 자막형', 'subtitle'))
DEFAULT_DIALOGUE_STYLE = 'legacy'


def normalize_dialogue_style(style, strict=False):
    if isinstance(style, str) and style in {value for _, value in DIALOGUE_STYLES}:
        return style
    if strict:
        raise ValueError('말풍선 스타일이 올바르지 않습니다.')
    return DEFAULT_DIALOGUE_STYLE
