"""Cloudy face assignments, counterclockwise from the positive valence axis."""

import math


SECTORS = (
    ("pleasant", "유쾌"),
    ("happy", "행복한"),
    ("proud", "의기양양한"),
    ("excited", "들뜬"),
    ("thrilled", "흥분"),
    ("anxious", "초조한"),
    ("hurt", "속상한"),
    ("distressed", "괴로운"),
    ("displeased", "불쾌"),
    ("sad", "슬픈"),
    ("depressed", "우울한"),
    ("tired", "힘든"),
    ("quiet", "조용"),
    ("calm", "차분한"),
    ("relieved", "만족한"),
    ("serene", "고요한"),
)
SECTOR_ANGLE = 360 / len(SECTORS)
SECTOR_NAMES = {**dict(SECTORS), "neutral": "중립"}
# Include the mood system's resting arousal of -0.30 in the neutral center.
NEUTRAL_RADIUS = 0.30


def russell_face(valence: float, arousal: float) -> str:
    if math.hypot(valence, arousal) <= NEUTRAL_RADIUS:
        return "neutral"
    angle = math.degrees(math.atan2(arousal, valence))
    index = math.floor(angle / SECTOR_ANGLE + 0.5) % len(SECTORS)
    return SECTORS[index][0]
