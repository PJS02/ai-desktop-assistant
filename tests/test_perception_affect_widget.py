"""Offscreen production widget wiring without camera, microphone, AI, or audio."""
from unittest.mock import Mock
import time

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from ai import gemini_client
from character import character_widget, dialogue_system
from character.character_widget import CharacterWidget
from character.mood_system import OccEmotionToMood as OCC
from character.tts_service import SupertonicTTS


@pytest.fixture
def widget(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('CLOUDY_RENDERER', 'sprite')
    monkeypatch.setattr(character_widget, 'HAS_PYGETWINDOW', False)
    monkeypatch.setattr(character_widget, 'CHARACTER_ITEMS_DIRECTORY', tmp_path / 'items')
    monkeypatch.setattr(character_widget.QtPerceptionReceiver, 'start', lambda self: False)
    config = tmp_path / 'ai.json'
    config.write_text('{"api_key":"","model":"test"}', encoding='utf-8')
    monkeypatch.setattr(gemini_client, 'CONFIG_PATH', config)
    monkeypatch.setattr(gemini_client, 'LEGACY_CONFIG_PATHS', ())
    settings = QSettings(str(tmp_path / 'voice.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(dialogue_system, 'SupertonicTTS', lambda: SupertonicTTS(settings=settings))
    host = CharacterWidget(screen_width=1920, screen_height=1080)
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    for name in ('timer', 'emotion_timer', 'move_timer', 'drag_timer', '_move_timer',
                 '_gravity_timer', '_activity_monitor_timer', '_taskbar_visibility_timer'):
        getattr(host, name).stop()
    host.animation_controller.stop()
    host.automatic_actions.timer.stop()
    host.on_ground = True
    monkeypatch.setattr(host.dialogue_system.tts, 'play_clip', Mock(return_value=True))
    yield host, app
    host.close()


def test_real_receiver_callback_updates_occ_and_idle_without_auto_dialogue(widget):
    host, _ = widget
    now = [100.]
    host.perception_controller.time_provider = lambda: now[0]
    host._last_character_interaction_time = time.monotonic() - 120
    for seq, stamp in ((1, 100.), (2, 100.3)):
        now[0] = stamp
        host._handle_perception_payload({'type': 'perception', 'timestamp': stamp, 'source': 'test',
            'observation': {'session': 'test', 'sequence': seq, 'observed_at': stamp},
            'motions': [{'label': 'heart', 'side': side} for side in ('left', 'right')]})
    assert 0 < host.mood_system.occ_intensities[OCC.JOY] < .04
    assert host.get_character_idle_time() < 1.
    assert host.dialogue_system.current_dialogue is None


def test_real_sleep_greeting_is_appraised_once_and_deferred_face_uses_same_interpretation(widget, monkeypatch):
    host, _ = widget
    host._automatic_pose = host.current_action = 'sleep'
    host.dialogue_system.is_ai_responding = True
    original = host.mood_system.on_interaction
    events = []

    def capture(event, **context):
        events.append(event)
        return original(event, **context)

    monkeypatch.setattr(host.mood_system, 'on_interaction', capture)
    host.perception_controller.handle_payload({'type': 'perception', 'timestamp': time.time(),
                                              'motions': [{'label': 'wave'}]})
    assert events == ['user_greeting'] and host._automatic_pose is None
    assert time.monotonic() < host._pending_user_greeting_until <= time.monotonic() + 5.
    host._greeting_retry_timer.stop()
    appraisal = host._greeting_appraisal
    before = dict(host.mood_system.occ_intensities)
    host.dialogue_system.is_ai_responding = False
    host.mood_system.russell.valence = -.4
    with monkeypatch.context() as patch:
        patch.setattr(host, 'rig_view', Mock())
        patch.setattr(host, 'sprite_animator', Mock(is_playing=False, current_action='idle'))
        patch.setattr(host, '_play_rig_action', Mock())
        patch.setattr(host.reactions, 'play_perception', Mock(return_value=True))
        assert host._try_user_greeting()
        host.reactions.play_perception.assert_called_once_with(appraisal)
    assert events == ['user_greeting'] and host.mood_system.occ_intensities == before


@pytest.mark.parametrize('owner', ['manual', 'debug', 'game', 'physical', 'timeout'])
def test_new_owner_or_deadline_cancels_deferred_greeting(widget, owner, monkeypatch):
    host, _ = widget
    host.dialogue_system.is_ai_responding = True
    host._request_user_greeting()
    host._greeting_retry_timer.stop()
    if owner == 'manual':
        host.manual_control.active = True
    elif owner == 'debug':
        host.mood_system._manual_russell_override = True
    elif owner == 'game':
        host.rps_game = Mock(is_active=True)
    elif owner == 'physical':
        host.is_dragging = True
    else:
        host._pending_user_greeting_until = time.monotonic() - .1
    assert not host._try_user_greeting()
    assert host._pending_user_greeting_until is None and host._greeting_appraisal is None


def test_real_character_output_enables_head_context_and_user_bubble_does_not(widget):
    host, _ = widget
    host.dialogue_system.show_user_dialogue('내가 한 말')
    assert not host._apply_perception_affect('user_head_agree', event_id='no-context')['accepted']
    host.dialogue_system.show_dialogue('이렇게 해볼까?')
    result = host._apply_perception_affect('user_head_agree', event_id='context')
    assert result['accepted'] and result['changes']['satisfaction'] > 0
    assert host.dialogue_system.current_dialogue.text == '이렇게 해볼까?'
