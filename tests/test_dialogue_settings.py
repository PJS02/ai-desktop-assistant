"""Settings persistence and Qt controls without camera, models or API requests."""
import json
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from character import config_manager
from character.character_widget import CharacterWidget
from character.dialogue_options import DEFAULT_DIALOGUE_OPTIONS, normalize_dialogue_options
from character.dialogue_system import DialogueSystem
from character.personality_system import PersonalitySystem
from character.settings_controller import SettingsController
from character.settings_dialog import SettingsDialog
from character.tts_service import available_voices


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    return path


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('content', [None, '{}', '{"dialogue":{"style":"rounded"}}',
                                     '[]', '{"dialogue":null}', 'invalid JSON'])
def test_old_missing_or_invalid_config_uses_defaults(config_path, content):
    if content is not None:
        config_path.write_text(content, encoding='utf-8')
    assert config_manager.load_dialogue_options() == DEFAULT_DIALOGUE_OPTIONS


@pytest.mark.parametrize('key,value', [
    ('auto_program_detection', 'false'), ('auto_program_detection', 1),
    ('activity_monitor_interval', 0), ('activity_monitor_interval', 3601),
    ('auto_dialogue_cooldown', True), ('auto_dialogue_cooldown', 20.5),
    ('request_cooldown', -1), ('request_cooldown', None),
])
def test_invalid_values_fall_back_on_load_but_cannot_overwrite_config(config_path, key, value):
    assert normalize_dialogue_options({key: value})[key] == DEFAULT_DIALOGUE_OPTIONS[key]
    original = '{"dialogue":{"style":"subtitle"},"unrelated":42}'
    config_path.write_text(original, encoding='utf-8')
    with pytest.raises(ValueError):
        config_manager.save_config(1920, 1080, dialogue_options={key: value})
    assert config_path.read_text(encoding='utf-8') == original


def test_saving_dialogue_preserves_other_settings_and_style_only_changes(config_path):
    config_path.write_text(json.dumps({'dialogue': {'style': 'rounded', 'future': 7},
                                      'hand_overlay': {'enabled': False}, 'unrelated': 42}),
                           encoding='utf-8')
    options = dict(DEFAULT_DIALOGUE_OPTIONS, auto_program_detection=False,
                   activity_monitor_interval=60, auto_dialogue_cooldown=120, request_cooldown=0)
    config_manager.save_config(1920, 1080, dialogue_options=options)
    config_manager.save_config(1280, 720, dialogue_style='subtitle')
    assert config_manager.load_dialogue_options() == options
    saved = json.loads(config_path.read_text(encoding='utf-8'))
    assert saved['dialogue'] == dict(options, style='subtitle', future=7)
    assert saved['hand_overlay'] == {'enabled': False}
    assert saved['unrelated'] == 42


def test_runtime_can_enable_disable_and_change_timing(app):
    character = QWidget()
    character._activity_monitor_timer = QTimer(character)
    character.dialogue_system = Mock()
    with patch('character.character_widget.HAS_CONTEXT', True):
        CharacterWidget.apply_dialogue_options(character, {'auto_program_detection': False})
        assert not character._activity_monitor_timer.isActive()
        CharacterWidget.apply_dialogue_options(character, {
            'activity_monitor_interval': 60, 'auto_dialogue_cooldown': 90, 'request_cooldown': 5})
        assert character._activity_monitor_timer.isActive()
        assert character._activity_monitor_timer.interval() == 60000
        assert character.auto_dialogue_cooldown == 90
        assert character.dialogue_system.request_cooldown == 5
        CharacterWidget.apply_dialogue_options(character, {'auto_program_detection': False})
        assert not character._activity_monitor_timer.isActive()
    with patch('character.character_widget.HAS_CONTEXT', False):
        CharacterWidget.apply_dialogue_options(character, {})
        assert not character._activity_monitor_timer.isActive()
    character.close()


def test_changing_manual_cooldown_reschedules_waiting_input(app):
    dialogue = SimpleNamespace(
        _input_timer=QTimer(), _closed=False, pending_inputs=deque([{}]),
        is_ai_responding=False, _speaking=False, _tts_busy=False,
        _time_provider=lambda: 100, last_request_time=90, _response_hold_until=0,
        _log_input_wait=Mock())
    dialogue._process_next_input = lambda: DialogueSystem._process_next_input(dialogue)
    character = SimpleNamespace(_activity_monitor_timer=QTimer(), dialogue_system=dialogue)
    CharacterWidget.apply_dialogue_options(character, {
        'auto_program_detection': False, 'request_cooldown': 20})
    assert 9000 <= dialogue._input_timer.remainingTime() <= 10000
    dialogue._input_timer.stop()


def test_disabled_detection_still_allows_explicit_generation():
    dialogue = Mock(user_input_epoch=0)
    dialogue.is_conversation_busy.return_value = False
    character = SimpleNamespace(auto_program_detection=False, gemini_config={'api_key': 'test'},
                                dialogue_system=dialogue, mood_system=Mock(),
                                _automatic_request_generation=0, _mark_character_interaction=Mock(),
                                _check_active_window_async=Mock())
    with patch('character.character_widget.HAS_CONTEXT', True), patch(
            'character.character_widget.threading.Thread') as worker:
        assert not CharacterWidget._on_activity_monitor(character)
        worker.assert_not_called()
        assert CharacterWidget._on_activity_monitor(character, manual=True)
        worker.return_value.start.assert_called_once()


@pytest.mark.parametrize('source,shown', [('activity', False), ('manual_generation', True)])
def test_disabled_detection_discards_only_automatic_results(source, shown):
    character = SimpleNamespace(
        auto_program_detection=False, _automatic_request_generation=1,
        _automatic_request_active=True, dialogue_system=Mock(user_input_epoch=2),
        _automatic_log_contexts={1: {'source': source}})
    CharacterWidget._finish_automatic_response(character, (1, 2, 'reply', None, 100, False))
    assert character.dialogue_system.show_automatic_response.called == shown
    assert not character._automatic_request_active


def test_settings_dialog_and_controller_round_trip(app, config_path):
    config_manager.save_config(1920, 1080)
    local = {'character': {'width': 1920, 'height': 1080,
                           'personality': PersonalitySystem.DEFAULT_PRESET},
             'voice': {'enabled': False, 'voice_id': available_voices()[0].id},
             'ai': {'api_key': '', 'model': ''}, 'dialogue': {'style': 'rounded'}}
    character = QWidget()
    character._activity_monitor_timer = QTimer(character)
    character.dialogue_system = Mock()
    character.apply_dialogue_options = lambda values: CharacterWidget.apply_dialogue_options(character, values)
    controller = SettingsController(character, Mock())
    with patch.object(SettingsDialog, '_refresh_voice_models'):
        dialog = SettingsDialog(local, character, model_manager=Mock())
    controller.dialog = dialog
    assert dialog.changes() == {'local': {}, 'remote': {}}
    dialog.auto_program_detection.setChecked(False)
    assert not dialog.dialogue_inputs['activity_monitor_interval'].isEnabled()
    assert dialog.dialogue_inputs['request_cooldown'].isEnabled()
    dialog.dialogue_inputs['activity_monitor_interval'].setValue(45)
    dialog.dialogue_inputs['auto_dialogue_cooldown'].setValue(60)
    dialog.dialogue_inputs['request_cooldown'].setValue(0)
    controller.apply(dialog.changes())
    assert not dialog.pending
    assert dialog.changes() == {'local': {}, 'remote': {}}
    options = config_manager.load_dialogue_options()
    assert options == dict(DEFAULT_DIALOGUE_OPTIONS, auto_program_detection=False,
                           activity_monitor_interval=45, auto_dialogue_cooldown=60, request_cooldown=0)
    assert not character._activity_monitor_timer.isActive()
    assert character.dialogue_system.request_cooldown == 0
    dialog.close()
    with patch.object(SettingsDialog, '_refresh_voice_models'):
        reopened = SettingsDialog(dict(local, dialogue=dict(options, style='rounded')),
                                  character, model_manager=Mock())
    assert not reopened.auto_program_detection.isChecked()
    assert reopened.dialogue_inputs['activity_monitor_interval'].value() == 45
    assert reopened.changes() == {'local': {}, 'remote': {}}
    reopened.close()
    character.close()
