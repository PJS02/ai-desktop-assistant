"""Persisted hand settings and their local runtime/control behavior."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from character import config_manager
from character.hand_overlay_options import normalize_hand_overlay_options
from character.settings_controller import SettingsController
from character.settings_dialog import SettingsDialog


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def local_settings():
    return {'character': {'width': 1920, 'height': 1080, 'personality': 'Russell (기본)'},
            'voice': {'enabled': True, 'voice_id': 'F1'},
            'ai': {'api_key': '', 'model': 'example-model'}}


def remote_state(camera='camera-2'):
    keys = ('camera', 'microphone', 'emotion_model', 'provider', 'language', 'silence', 'sensitivity')
    values = {key: camera if key == 'camera' else 'test' for key in keys}
    return {'values': values, 'choices': {key: [{'label': value, 'value': value}]
                                       for key, value in values.items()}}


def test_default_controls_do_not_create_changes(qt_app):
    dialog = SettingsDialog(local_settings())
    assert dialog.hand_inputs['range_percent'].value() == 70
    assert not dialog.hand_display.isChecked()
    assert dialog.hand_smooth.isChecked()
    assert dialog.changes() == {'local': {}, 'remote': {}}
    assert '70%' in dialog.hand_range_preview.text()
    dialog.close()


def test_hand_draft_survives_remote_refresh_and_disconnect(qt_app):
    dialog = SettingsDialog(local_settings())
    dialog.set_remote(remote_state())
    dialog.hand_display.setChecked(True)
    dialog.hand_sliders['range_percent'].setValue(55)
    dialog.hand_inputs['size_percent'].setValue(120)
    dialog.hand_count.setCurrentIndex(dialog.hand_count.findData(2))
    dialog.hand_smooth.setChecked(False)
    expected = {'enabled': True, 'size_percent': 120, 'range_percent': 55,
                'max_hands': 2, 'smooth': False}
    dialog.set_remote(remote_state(), preserve_draft=True)
    dialog.remote_unavailable('카메라 연결 끊김')
    assert dialog.hand_inputs['range_percent'].isEnabled()
    assert dialog.hand_sliders['size_percent'].value() == 120
    assert dialog.changes() == {'local': {'hand_overlay': expected}, 'remote': {}}
    emitted = []
    dialog.apply_requested.connect(emitted.append)
    dialog.submit(False)
    assert emitted == [{'local': {'hand_overlay': expected}, 'remote': {}}]
    dialog.complete('applied', local={'hand_overlay': expected})
    assert dialog.changes() == {'local': {}, 'remote': {}}
    dialog.close()


def test_hand_settings_reload_preserves_other_fields(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    original = {'resolution': {'width': 1234, 'height': 800}, 'personality': '기존 성격',
                'extra': {'keep': 42}, 'dialogue': {'style': 'classic'},
                'hand_overlay': {'future_option': 'preserved'}}
    path.write_text(json.dumps(original), encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    values = normalize_hand_overlay_options({'enabled': True, 'range_percent': 60, 'max_hands': 2})
    config_manager.save_hand_overlay_options(values)
    assert config_manager.load_hand_overlay_options() == values
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert {key: saved[key] for key in original if key != 'hand_overlay'} == {
        key: value for key, value in original.items() if key != 'hand_overlay'}
    assert saved['hand_overlay']['future_option'] == 'preserved'
    config_manager.save_config(1920, 1080)
    assert config_manager.load_hand_overlay_options() == values


@pytest.mark.parametrize('bad', [{'range_percent': 0}, {'range_percent': float('nan')},
                                 {'size_percent': True}, {'max_hands': 3}, {'enabled': 'yes'}])
def test_invalid_hand_values_are_rejected_without_writing(tmp_path, monkeypatch, bad):
    path = tmp_path / 'config.json'
    path.write_text('{"extra":42}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    previous = path.read_bytes()
    with pytest.raises(ValueError):
        config_manager.save_hand_overlay_options(bad)
    assert path.read_bytes() == previous
    assert normalize_hand_overlay_options(bad) == normalize_hand_overlay_options()


def test_failed_atomic_replace_keeps_previous_config(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_text('{"extra":42}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    previous = path.read_bytes()
    replace = Path.replace

    def fail_config_replace(source, destination):
        if destination == path:
            raise OSError('write failed')
        return replace(source, destination)

    monkeypatch.setattr(Path, 'replace', fail_config_replace)
    with pytest.raises(OSError):
        config_manager.save_hand_overlay_options({'enabled': True})
    assert path.read_bytes() == previous


def test_controller_persists_then_applies_live_without_remote_settings(tmp_path, monkeypatch, qt_app):
    path = tmp_path / 'config.json'
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    character = QWidget()
    manager = SimpleNamespace(settings_message=Mock(), apply_settings=Mock())
    overlay = SimpleNamespace(options=normalize_hand_overlay_options(), apply_options=Mock())
    controller = SettingsController(character, manager, overlay)
    controller.dialog = SimpleNamespace(log_trace_id=None, complete=Mock())
    desired = normalize_hand_overlay_options({'enabled': True, 'range_percent': 50})

    def apply_live(values):
        assert config_manager.load_hand_overlay_options() == values
        overlay.options = values

    overlay.apply_options.side_effect = apply_live
    controller.apply({'local': {'hand_overlay': desired}, 'remote': {}})
    overlay.apply_options.assert_called_once_with(desired)
    manager.apply_settings.assert_not_called()
    assert controller.applied_local == {'hand_overlay': desired}
    assert controller.dialog.complete.call_args.kwargs['local'] == {'hand_overlay': desired}


def test_controller_does_not_apply_runtime_after_save_failure(monkeypatch, qt_app):
    character = QWidget()
    manager = SimpleNamespace(settings_message=Mock())
    overlay = SimpleNamespace(apply_options=Mock())
    controller = SettingsController(character, manager, overlay)
    controller.dialog = SimpleNamespace(log_trace_id=None, complete=Mock())
    monkeypatch.setattr('character.settings_controller.save_hand_overlay_options',
                        Mock(side_effect=OSError('write failed')))
    controller.apply({'local': {'hand_overlay': normalize_hand_overlay_options({'enabled': True})}, 'remote': {}})
    overlay.apply_options.assert_not_called()
    assert controller.applied_local == {}
    assert controller.dialog.complete.call_args.args[1] is False
