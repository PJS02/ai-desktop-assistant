"""Personality-specific game lines paired with prerecorded audio."""

import json
from pathlib import Path
import random

from .personality_system import PersonalitySystem


GAME_AUDIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'audio' / 'games'
RESULTS = json.loads((GAME_AUDIO_DIRECTORY / 'results.json').read_text(encoding='utf-8'))['personalities']
RESULT_LINES = {
    entry['file'].removesuffix('.wav'): entry['text']
    for games in RESULTS.values()
    for outcomes in games.values()
    for entries in outcomes.values()
    for entry in entries
}


def choose_result_cue(game, personality, event):
    outcome = {
        'game_win': 'win',
        'game_loss': 'loss',
        'game_disappointed': 'loss',
        'game_draw': 'draw',
    }.get(event)
    if outcome is None:
        return None
    games = RESULTS.get(personality, RESULTS[PersonalitySystem.DEFAULT_PRESET])
    entries = games[game].get(outcome)
    if entries:
        return random.choice(entries)['file'].removesuffix('.wav')
    return None
