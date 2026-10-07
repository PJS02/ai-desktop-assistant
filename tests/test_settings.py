import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from character import ai_settings, config_manager
from character.settings_dialog import SettingsDialog
from character.tts_service import SupertonicTTS
from main import MediaPipeProcessManager
from test_mediapipe_console import HolisticGuiApp


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def local_settings():
    return {'character': {'width': 1920, 'height': 1080, 'personality': 'Russell (기본)',
                          'size_percent': 100, 'movement_speed': 80, 'jump_height': 225, 'show_hitboxes': True,
                          'movement_range_extra_percent': 0},
            'voice': {'enabled': True, 'voice_id': 'F1'}, 'ai': {'api_key': '', 'model': 'example-model'}}


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def recognition_app():
    app = HolisticGuiApp.__new__(HolisticGuiApp)
    app.camera_candidates = [{'index': 0, 'backend_label': 'DSHOW', 'backend': 700}]
    app.camera_var = Variable('index 0 / DSHOW')
    app.stt_mic_var = Variable('index 2 / TestMic')
    app.stt = SimpleNamespace(audio_devices=[SimpleNamespace(label='index 2 / TestMic', index=2)], is_running=False)
    app.emotion_model_var = Variable('EmotiEffNet B2')
    app.loaded_emotion_model_key = 'emotieff_b2'
    for key, value in {'provider': 'google', 'language': 'ko-KR', 'silence': '0.8 sec', 'sensitivity': 'medium', 'timestamps': True}.items():
        setattr(app, 'stt_' + key + '_var', Variable(value))
    for key, value in {'tracking': True, 'marker_only': False, 'mirror': False, 'info_overlay': True, 'emotion': True, 'always_recognition': True}.items():
        setattr(app, key + '_var', Variable(value))
    app.active_mode = 'air'
    app.rps_session = None
    app.cap = None
    app.camera_discovery_thread = None
    app.device_settings = {'extra': 'preserved'}
    app.update_mode_status = Mock()
    app.emit_settings = Mock()
    return app


def test_cancel_does_not_apply_and_refresh_preserves_draft(qt_app):
    dialog = SettingsDialog(local_settings())
    assert tuple(dialog.resolution_preset.currentData()) == (1920, 1080)
    app = recognition_app()
    dialog.set_remote(app.settings_state())
    dialog.controls['mirror'].setChecked(True)
    dialog.width.setValue(1280)
    dialog.set_remote(app.settings_state(), preserve_draft=True)
    assert dialog.controls['mirror'].isChecked()
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.reject()
    assert emitted == []
    assert dialog.local_baseline == local_settings()


def test_apply_emits_only_changed_fields_and_waits_for_ack(qt_app):
    dialog = SettingsDialog(local_settings())
    app = recognition_app()
    dialog.set_remote(app.settings_state())
    dialog.controls['language'].setCurrentIndex(dialog.controls['language'].findData('en-US'))
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.submit(True)
    assert dialog.pending
    assert emitted == [{'local': {}, 'remote': {'language': 'en-US'}}]
    dialog.reject()
    assert dialog.pending
    dialog.complete('failed', False, remote=app.settings_state())
    assert not dialog.pending
    assert dialog.controls['language'].currentData() == 'en-US'
    dialog.close()


def test_custom_resolution_and_invalid_ai_are_handled(qt_app):
    dialog = SettingsDialog(local_settings())
    dialog.width.setValue(1510)
    assert dialog.resolution_preset.currentData() is None
    dialog.api_key.setText('test-key')
    dialog.model.clear()
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.submit(False)
    assert emitted == []
    assert dialog.tabs.currentIndex() == 3
    assert not dialog.pending
    dialog.close()


def test_recognition_patch_persists_and_preserves_other_sections(tmp_path, monkeypatch):
    app = recognition_app()
    from app.device_settings import save_device_settings
    path = tmp_path / 'devices.json'
    monkeypatch.setattr('app.settings_bridge.save_device_settings', lambda settings: save_device_settings(settings, path))
    app.apply_unified_settings('req', {'mirror': True, 'language': 'en-US', 'mode': None})
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['extra'] == 'preserved'
    assert saved['recognition']['mode'] is None
    assert saved['recognition']['mirror'] is True
    assert saved['stt']['language'] == 'en-US'
    reply = app.emit_settings.call_args.args[0]
    assert reply['ok'] is True
    assert reply['state']['values']['mirror'] is True


def test_invalid_device_and_game_override_are_rejected_before_mutation():
    app = recognition_app()
    with pytest.raises(ValueError):
        app.apply_unified_settings('req', {'mirror': True, 'camera': 'missing-camera'})
    assert app.mirror_var.get() is False
    app.rps_session = 'session'
    app.rps_previous_mode = 'air'
    assert app.settings_state()['values']['mode'] == 'air'
    with pytest.raises(ValueError):
        app.apply_unified_settings('req', {'mode': None})


def test_save_failure_returns_failure_ack(monkeypatch):
    app = recognition_app()
    monkeypatch.setattr('app.settings_bridge.save_device_settings', Mock(side_effect=OSError('write failed')))
    app.handle_settings_command(json.dumps({'action': 'apply', 'request_id': 'req', 'values': {'mirror': True}}))
    reply = app.emit_settings.call_args.args[0]
    assert reply['ok'] is False
    assert reply['request_id'] == 'req'
    assert 'write failed' in reply['message']
    assert app.mirror_var.get() is False


def test_failed_model_keeps_requested_draft_but_reports_actual_model():
    app = recognition_app()
    app.load_emotion_model = lambda: app.emotion_model_var.set('EmotiEffNet B2')
    app.handle_settings_command(json.dumps({'action': 'apply', 'request_id': 'req', 'values': {'emotion_model': 'mobilenet_v3'}}))
    reply = app.emit_settings.call_args.args[0]
    assert reply['ok'] is False
    assert reply['state']['values']['emotion_model'] == 'emotieff_b2'


def test_stt_restart_waits_for_shutdown_and_live_stream():
    app = recognition_app()
    app.root = Mock()
    app.is_shutting_down = False
    app.stt.is_running = True
    app.stt.stream = None
    app.start_stt = Mock()
    import time
    deadline = time.monotonic() + 10
    app.restart_settings_stt('req', deadline)
    app.start_stt.assert_not_called()
    app.stt.is_running = False
    app.start_stt.side_effect = lambda **kwargs: setattr(app.stt, 'is_running', True)
    app.restart_settings_stt('req', deadline)
    app.start_stt.assert_called_once_with(show_error=False)
    assert not app.emit_settings.called
    app.stt.stream = object()
    app.restart_settings_stt('req', deadline, True)
    assert app.emit_settings.call_args.args[0]['ok'] is True


def test_process_messages_preserve_case_and_are_parsed(qt_app):
    app = recognition_app()
    import queue
    app.control_commands = queue.Queue()
    app.command_stream = StringIO('settings {"values":{"microphone":"TestMic"}}\n')
    app.read_control_commands()
    assert 'TestMic' in app.control_commands.get_nowait()
    manager = MediaPipeProcessManager()
    replies = []
    manager.settings_message.connect(replies.append)
    manager._forward_output(SimpleNamespace(stdout=StringIO('APP_SETTINGS {"kind":"state","name":"TestMic"}\n')))
    assert replies == [{'kind': 'state', 'name': 'TestMic'}, {'kind': 'unavailable'}]


def test_config_and_tts_survive_reload(tmp_path, monkeypatch, qt_app):
    config_path = tmp_path / 'character.json'
    config_path.write_text('{"extra":42}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', config_path)
    config_manager.save_config(1510, 850, '밝고 활발')
    assert config_manager.load_config() == (1510, 850, '밝고 활발')
    assert json.loads(config_path.read_text(encoding='utf-8'))['extra'] == 42
    settings_path = str(tmp_path / 'tts.ini')
    tts = SupertonicTTS(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    tts.set_enabled(False)
    tts.set_voice('M3')
    tts.sync_settings()
    reloaded = SupertonicTTS(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    assert not reloaded.enabled
    assert reloaded.voice_id == 'M3'
    tts.close()
    reloaded.close()


def test_ai_settings_sync_both_consumers_and_rollback(tmp_path, monkeypatch):
    paths = (tmp_path / 'gemini.json', tmp_path / 'config' / 'gemini.json')
    paths[1].parent.mkdir()
    for path in paths:
        path.write_text('{"api_key":"test-old","model":"old","extra":42}', encoding='utf-8')
    monkeypatch.setattr(ai_settings, 'GEMINI_PATHS', paths)
    ai_settings.save_ai_settings('test-new', 'new-model')
    for path in paths:
        assert json.loads(path.read_text(encoding='utf-8')) == {'api_key': 'test-new', 'model': 'new-model', 'extra': 42}
    originals = [path.read_bytes() for path in paths]
    replace = Path.replace
    def fail_second(path, destination):
        if destination == paths[1]:
            raise OSError('failure')
        return replace(path, destination)
    monkeypatch.setattr(Path, 'replace', fail_second)
    with pytest.raises(OSError):
        ai_settings.save_ai_settings('test-failure', 'failed-model')
    assert [path.read_bytes() for path in paths] == originals
