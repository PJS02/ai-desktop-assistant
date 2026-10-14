"""LLM이 반환한 장기기억 중요도 점수를 읽는다."""

import json


def get_importance_score(response: str) -> int:
    """0~10 정수만 유효한 중요도 점수로 반환한다."""
    try:
        score = json.loads(response).get("importance", 0)
        return score if type(score) is int and 0 <= score <= 10 else 0
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return 0
