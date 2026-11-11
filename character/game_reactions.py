"""Small, validated AI choices; model output never names arbitrary rig actions."""
import json
import re

GAME_RESPONSE_MAX_AGE = 30


def prepare_game_image(image):
    """Bound the frame before the normal privacy check; never send the original."""
    from PIL import Image
    if not isinstance(image, Image.Image):
        return image
    frame = image.copy()
    frame.thumbnail((960, 540), Image.Resampling.LANCZOS)
    return frame


GAME_REACTIONS = {
    'none': None,
    'cheer': ('game_cheer', 3.2),
    'oops': ('game_oops', 2.8),
    'tip': ('thinking', 3.6),
    'watch': ('spectate', 4.5),
}


def game_response_schema():
    return {
        'type': 'object',
        'properties': {
            'dialogue': {'type': 'string'},
            'game_reaction': {'type': 'string', 'enum': list(GAME_REACTIONS)},
        },
        'required': ['dialogue', 'game_reaction'],
        'additionalProperties': False,
    }


def game_response_instruction(voice):
    return (str(voice or '') + '\n'
            'JSON 객체 {"dialogue":"한국어 짧은 한 문장 또는 빈 문자열",'
            '"game_reaction":"none|cheer|oops|tip|watch"}만 출력하세요. '
            '현재 게임 화면과 감정에 맞춰 대사와 동작을 함께 선택하세요. '
            'cheer는 칭찬·응원, oops는 아쉬움·움찔, tip은 짧은 조언, watch는 조용한 관람입니다. '
            '반응할 근거가 없으면 none과 빈 dialogue로 조용히 지켜보세요. '
            '모든 화면에 훈수를 만들지 말고 응원·가벼운 농담·조용한 관람을 섞으세요. '
            '마크다운이나 선택지 목록은 출력하지 마세요.')


def decode_game_response(response):
    """None text permits the normal legacy decoder; an empty string means quiet."""
    try:
        candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', response.strip(), flags=re.I)
        data = json.loads(candidate)
    except (TypeError, AttributeError, ValueError):
        return None, 'none'
    if not isinstance(data, dict):
        return None, 'none'
    text = data.get('dialogue')
    if not isinstance(text, str):
        return None, 'none'
    reaction = data.get('game_reaction')
    return text.strip(), reaction if isinstance(reaction, str) and reaction in GAME_REACTIONS else 'none'
