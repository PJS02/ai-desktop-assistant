import ast
from pathlib import Path
import unittest

from character.dialogue_persona import BASE_VOICE, character_voice
from character.personality_system import PersonalitySystem


class DialoguePersonaTests(unittest.TestCase):
    def test_same_base_voice_across_personality_presets(self):
        for preset in PersonalitySystem.PERSONALITY_PRESETS:
            personality = PersonalitySystem(preset)
            voice = character_voice(personality)
            assert voice.startswith(BASE_VOICE)
            assert personality.get_dialogue_tone_hints() in voice
            assert personality.get_personality_for_prompt() in voice

    def test_personality_change_updates_voice_snapshot(self):
        p = PersonalitySystem('밝고 활발')
        first = character_voice(p)
        p.load_preset('진중하고 신중')
        assert first != character_voice(p)
        assert first.startswith(BASE_VOICE) and character_voice(p).startswith(BASE_VOICE)

    def test_system_contract_keeps_voice_and_json_format(self):
        # Read the pure builder without importing the standalone classifier's
        # device/config startup code or contacting any service.
        tree = ast.parse(Path('context/active_window_classifier.py').read_text(encoding='utf-8-sig'))
        builder = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                       and n.name == 'build_system_instruction')
        namespace = {}
        exec(compile(ast.Module(body=[builder], type_ignores=[]), '<system-builder>', 'exec'), namespace)
        instruction = namespace['build_system_instruction']('stable-personality-snapshot')
        assert 'stable-personality-snapshot' in instruction
        assert 'JSON' in instruction and 'dialogue' in instruction


if __name__ == '__main__':
    unittest.main()
