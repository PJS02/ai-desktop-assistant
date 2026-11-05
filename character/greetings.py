"""Authored greetings paired with pre-generated GPT-SoVITS audio."""
import json
import random
from pathlib import Path

from .personality_system import PersonalitySystem


AUDIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'audio' / 'greetings'
GREETINGS = json.loads((AUDIO_DIRECTORY / 'greetings.json').read_text(encoding='utf-8'))['personalities']


def choose_greeting(personality):
    entries = GREETINGS.get(personality, GREETINGS[PersonalitySystem.DEFAULT_PRESET])
    entry = random.choice(entries)
    return entry['text'], AUDIO_DIRECTORY / entry['file']
