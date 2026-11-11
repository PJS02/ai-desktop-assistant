import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest

from character.game_detection import GameActivity, game_context_instruction
from character.game_reactions import decode_game_response, game_response_schema, prepare_game_image
from character.game_rules import save_game_rules


@pytest.fixture
def registered_game(tmp_path):
    with patch('character.config_manager.CONFIG_FILE', tmp_path / 'config.json'):
        save_game_rules({'keywords': [], 'included_processes': ['CustomArena.exe']})
        yield {'process': 'customarena.exe', 'title': 'Custom Arena - Match'}


def test_registered_game_supplies_identity_and_visual_context(registered_game):
    activity = GameActivity(registered_game['process'], registered_game['title'])
    visual = game_context_instruction(activity, visual=True)
    assert '"registered_by_user": true' in visual
    assert 'customarena.exe' in visual and 'Custom Arena - Match' in visual
    assert '첨부된 현재 게임 창' in visual
    assert '훈수' in visual
    assert '게임 화면은 이 대화에 첨부되지 않았습니다' in game_context_instruction(activity)


@pytest.mark.parametrize('reply,text,reaction', [
    ('{"dialogue":"nice", "game_reaction":"cheer"}', 'nice', 'cheer'),
    ('```json\n{"dialogue":"careful", "game_reaction":"tip"}\n```', 'careful', 'tip'),
    ('{"dialogue":"", "game_reaction":"none"}', '', 'none'),
    ('{"dialogue":"watching", "game_reaction":"delete_files"}', 'watching', 'none'),
    ('{"dialogue":"watching", "game_reaction":[]}', 'watching', 'none'),
    ('plain legacy response', None, 'none'),
    ('{"dialogue":null}', None, 'none'),
])
def test_only_supported_ai_reactions_are_admitted(reply, text, reaction):
    assert decode_game_response(reply) == (text, reaction)


@pytest.mark.parametrize('text,reaction', [('nice', 'cheer'), ('', 'none')])
def test_automatic_worker_uses_saved_list_image_and_ai_gesture(registered_game, text, reaction):
    from character.character_widget import CharacterWidget
    context = {'trace_id': 'game-test', 'input_epoch': 2, 'source': 'activity'}
    host = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock(),
                           dialogue_system=SimpleNamespace(_process_gemini_response=Mock()))
    image = Mock()
    reply = json.dumps({'dialogue': text, 'game_reaction': reaction})
    with patch('character.character_widget.get_active_window_info', return_value=registered_game), \
            patch('character.character_widget.capture_active_window_image', return_value=image), \
            patch('character.character_widget.request_gemini', return_value=reply) as send:
        CharacterWidget._check_active_window_async(host, 1, 2, {}, 'calm', 'friendly', context)
    assert send.call_args.kwargs['response_schema'] == game_response_schema()
    assert send.call_args.kwargs['image'] is image
    assert send.call_args.kwargs['timeout_seconds'] == 8
    assert send.call_args.kwargs['max_attempts'] == 1
    assert '"registered_by_user": true' in send.call_args.args[0]
    assert context['game_process'] == registered_game['process']
    assert context['game_reaction'] == reaction
    assert host.automatic_response_ready.emit.call_args.args[0][2] == text
    host.dialogue_system._process_gemini_response.assert_not_called()


def test_game_switch_during_capture_does_not_send_the_wrong_window(registered_game):
    from character.character_widget import CharacterWidget
    host = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock())
    with patch('character.character_widget.get_active_window_info', side_effect=[
            registered_game, {'process': 'code.exe', 'title': 'Editor'}]), \
            patch('character.character_widget.capture_active_window_image', return_value=Mock()), \
            patch('character.character_widget.request_gemini') as send:
        CharacterWidget._check_active_window_async(host, 1, 2, {}, 'calm', 'friendly')
    send.assert_not_called()


def test_native_game_gestures_keep_current_emotion():
    from PyQt6.QtWidgets import QApplication
    from character.rig_planner import RigPlanner
    app = QApplication.instance() or QApplication([])
    planner = RigPlanner()
    rest = planner.sample({'action': 'idle', 'time': 1., 'emotion': 'sad'})['pose']
    cheer = planner.sample({'action': 'game_cheer', 'time': 1., 'emotion': 'sad'})['pose']
    oops = planner.sample({'action': 'game_oops', 'time': 1., 'emotion': 'sad'})['pose']
    assert cheer['armNear'] > rest['armNear'] + 60
    assert oops['elbowNear'] > rest['elbowNear'] + 60
    assert cheer['exprSad'] == oops['exprSad'] == rest['exprSad']
    assert cheer['exprHappy'] == rest['exprHappy']


@pytest.mark.parametrize('current', [True, False])
def test_reaction_starts_with_display_and_discards_late_audio(current):
    from character.dialogue_system import DialogueSystem
    context = {'trace_id': 'game-test', 'source': 'activity', 'game_process': 'custom.exe',
               'game_reaction': 'cheer'}
    spectator = Mock()
    spectator.response_is_current.return_value = current
    cancelled = []

    class Voice:
        def stop_clip(self, source):
            cancelled.append(source)

    dialogue = SimpleNamespace(
        _pending_ai_response=('nice', context, False), _closed=False,
        character_widget=SimpleNamespace(game_spectator=spectator),
        ai_motion_changed=Mock(), _response_hold_until=0, _time_provider=lambda: 100,
        show_dialogue=Mock(), current_user_dialogue=None, tts=Voice(),
    )
    assert DialogueSystem._flush_ai_response(dialogue, 'playback_started') is current
    assert dialogue.show_dialogue.called is current
    assert spectator.play_ai_reaction.called is current
    assert cancelled == ([] if current else ['activity'])


def test_large_game_frame_is_bounded_before_the_normal_privacy_check():
    from PIL import Image
    original = Image.new('RGB', (2560, 1440), 'white')
    frame = prepare_game_image(original)
    assert frame.size == (960, 540)
    assert original.size == (2560, 1440)


def test_slow_privacy_processing_does_not_send_an_expired_game_frame():
    from PIL import Image
    from ai import gemini_client
    clock = SimpleNamespace(now=100.)
    frame = Image.new('RGB', (960, 540), 'white')

    def slow_redact(*args):
        clock.now = 131
        return frame, 'safe prompt', None

    with patch.object(gemini_client.time, 'monotonic', side_effect=lambda: clock.now), \
            patch.object(gemini_client, 'redact_screen', side_effect=slow_redact) as redact, \
            patch.object(gemini_client, 'urlopen') as send:
        result = gemini_client.request_gemini('game', {'api_key': 'test'}, image=frame,
                                              timeout_seconds=8, max_attempts=1, deadline=130)
    assert 'deadline exceeded' in result
    redact.assert_called_once()
    send.assert_not_called()
