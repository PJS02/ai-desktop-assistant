"""Failure, correlation and rate-limit regressions for character diagnostics."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from types import MethodType
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from app_logging import clear_events, get_events
from character import ai_settings, desktop_geometry, settings_controller
from character.mood_system import MoodSystem
from character.motion_options import DEFAULT_CHARACTER_OPTIONS
from character.rig_v8 import NodeRigPlanner
from character.rps_game import RpsGameOverlay
from character.sandbox_manager import SandboxManager
from character.settings_dialog import SettingsDialog
from character.sprite_animator import SpriteAnimator
from character.cloudy_rig_view import CloudyRigView


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_events():
    clear_events()


def events(name):
    return [event for event in get_events() if event.event == name]


def test_ai_rollback_has_operation_id_and_redacts_both_secrets(tmp_path, monkeypatch):
    paths = (tmp_path / 'ai.json', tmp_path / 'other.json')
    original = json.dumps({'api_key': 'original-secret-972', 'model': 'old'})
    for path in paths:
        path.write_text(original, encoding='utf8')
    monkeypatch.setattr(ai_settings, 'GEMINI_PATHS', paths)
    replace = Path.replace

    def failed_replace(source, destination):
        if destination == paths[1]:
            raise OSError('new-secret-184 original-secret-972 could not be written')
        return replace(source, destination)

    monkeypatch.setattr(Path, 'replace', failed_replace)
    with pytest.raises(OSError):
        ai_settings.save_ai_settings('new-secret-184', 'new', trace_id='settings-test')
    assert all(path.read_text(encoding='utf8') == original for path in paths)
    assert not events('settings.ai.saved')
    assert events('settings.ai.rolled_back')[0].trace_id == 'settings-test'
    detail = '\n'.join(event.details() for event in get_events())
    assert 'original-secret-972' not in detail and 'new-secret-184' not in detail


class Manager(QObject):
    settings_message = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.apply_settings = Mock(return_value=True)


def test_settings_local_and_remote_share_id_and_late_ack_is_still_recorded(qt_app):
    character = QWidget()
    tts = SimpleNamespace(set_voice=Mock(), set_enabled=Mock(), sync_settings=Mock())
    character.dialogue_system = SimpleNamespace(tts=tts)
    manager = Manager()
    controller = settings_controller.SettingsController(character, manager)
    controller.dialog = SimpleNamespace(pending=True, complete=Mock())
    controller.apply({'local': {'voice': {'enabled': False, 'voice_id': 'M3'}},
                      'remote': {'language': 'en-US'}})
    trace = controller.request_id
    assert trace and trace == events('settings.local.applied')[0].trace_id
    manager.apply_settings.assert_called_once_with(trace, {'language': 'en-US'})
    assert not events('settings.apply.completed')
    controller.dialog = None
    controller.handle_message({'kind': 'result', 'request_id': trace, 'ok': True,
                               'message': 'applied', 'state': {}})
    record = events('settings.remote.acknowledged')[0]
    assert record.trace_id == trace and record.data['late'] is True
    character.close()


@pytest.mark.parametrize('supports_trace', [False, True])
def test_character_runtime_trace_support_keeps_legacy_callback_contract(qt_app, monkeypatch, supports_trace):
    character = QWidget()
    received = []

    def legacy(width, height, personality, **options):
        received.append(options)

    def contextual(width, height, personality, *, trace_id=None, **options):
        received.append({**options, 'trace_id': trace_id})

    character.apply_character_settings = contextual if supports_trace else legacy
    controller = settings_controller.SettingsController(character, Manager())
    controller.dialog = SimpleNamespace(pending=True, complete=Mock())
    monkeypatch.setattr(settings_controller, 'save_config', Mock())
    values = {'width': 1920, 'height': 1080, 'personality': 'Russell (기본)',
              **DEFAULT_CHARACTER_OPTIONS}
    controller.apply({'local': {'character': values}, 'remote': {}})
    assert ('trace_id' in received[0]) is supports_trace
    if supports_trace:
        assert received[0]['trace_id'] == controller.operation_id
    character.close()


def test_settings_timeout_records_unknown_instead_of_failed(qt_app):
    local = {'character': {'width': 1920, 'height': 1080, 'personality': 'Russell (기본)'},
             'voice': {'enabled': True, 'voice_id': 'F1'}, 'ai': {'api_key': '', 'model': ''}}
    dialog = SettingsDialog(local)
    dialog.log_trace_id = 'settings-timeout'
    dialog.set_pending(True)
    dialog._timed_out()
    record = events('settings.remote.timeout')[0]
    assert record.trace_id == 'settings-timeout' and record.data['result'] == 'unknown'
    assert not dialog.pending
    dialog.close()


def test_mood_logs_appraisal_input_and_continuous_drag_does_not_log_each_tick(monkeypatch):
    import app_logging
    monkeypatch.setattr(app_logging.time, 'monotonic', lambda: 10.0)
    mood = MoodSystem()
    mood.on_click()
    record = events('mood.influence')[0]
    assert 'goal_relevance' in record.data['event_input']
    assert 'final_emotion' in record.data and record.data['occ_after']
    for _ in range(40):
        mood.apply_drag_displeasure(4.0)
    drag_records = [event for event in events('mood.influence')
                    if event.data['influence']['source'] == '지속적인 캐릭터 드래그']
    assert len(drag_records) <= 2
    assert mood._emotion_influences[-1].adjusted_weight > drag_records[0].data['influence']['adjusted_weight']
    mood.set_russell_state(.1, .2)
    mood.clear_manual_russell_state()
    assert events('mood.manual.released')


def test_interleaved_mood_sources_preserve_each_new_group_within_merge_window(monkeypatch):
    import app_logging
    monkeypatch.setattr(app_logging.time, 'monotonic', lambda: 10.0)
    monkeypatch.setattr(app_logging.time, 'time', lambda: 100.0)
    mood = MoodSystem()
    mood.on_external_emotion('anger', .9)
    mood.set_russell_state(.1, .2)
    mood.on_external_emotion('anger', .9)
    anger = [event for event in events('mood.influence')
             if (event.data.get('event_input') or {}).get('normalized_label') == 'anger']
    assert len(anger) == 2
    assert all(record.data['merged'] is False for record in anger)
    assert anger[0].trace_id != anger[1].trace_id


def test_node_startup_crash_preserves_stderr_stack_and_exit_code(tmp_path):
    with pytest.raises(RuntimeError):
        NodeRigPlanner(tmp_path / 'missing-rig')
    records = events('renderer.worker.stderr')
    stderr = '\n'.join(record.data['output'] for record in records)
    assert 'ENOENT' in stderr and 'rig_worker.cjs' in stderr
    stopped = events('renderer.worker.stopped')[0]
    assert stopped.data['exit_code'] != 0
    assert 'ENOENT' in stopped.data['stderr']
    assert events('renderer.worker.init_failed')[0].trace_id == stopped.trace_id


def test_corrupt_png_frame_reports_exact_path_without_changing_selection(tmp_path, qt_app):
    folder = tmp_path / 'idle'
    folder.mkdir()
    path = folder / 'frame_000.png'
    path.write_bytes(b'corrupt image')
    animator = SpriteAnimator(tmp_path)
    assert animator.load_animation('idle') is True
    assert animator.current_frames[0].isNull()
    record = events('renderer.sprite.decode_failed')[0]
    assert record.data['invalid_paths'] == [str(path)]
    assert record.data['valid_frame_count'] == 0
    assert not events('renderer.sprite.loaded')


def test_renderer_snapshot_error_preserves_fallback_and_resource_release():
    renderer = SimpleNamespace(_error=None, _released=False, _timer=SimpleNamespace(stop=Mock()),
        failed=SimpleNamespace(emit=Mock()), planner=SimpleNamespace(log_trace_id='rig-failure', close=Mock()),
        rig_root=Path('example-rig'), stats=Mock(side_effect=RuntimeError('cache statistics unavailable')),
        _state=Mock(side_effect=RuntimeError('render state unavailable')), _cleanup_gl=Mock())
    renderer._diagnostic_snapshot = MethodType(CloudyRigView._diagnostic_snapshot, renderer)
    CloudyRigView._fail(renderer, RuntimeError('OpenGL failed'))
    renderer.failed.emit.assert_called_once_with('OpenGL failed')
    record = events('renderer.opengl.failed')[0]
    assert record.data['stats_error'] == 'cache statistics unavailable'
    assert record.data['state_error'] == 'render state unavailable'
    CloudyRigView.release(renderer)
    renderer._cleanup_gl.assert_called_once()
    renderer.planner.close.assert_called_once()
    assert renderer._released


def test_failed_win32_monitor_lookup_logs_reason_and_preserves_coordinates(monkeypatch, qt_app):
    user32 = SimpleNamespace(MonitorFromWindow=Mock(return_value=0), GetMonitorInfoW=Mock())
    monkeypatch.setattr(desktop_geometry.ctypes.windll, 'user32', user32)
    window = SimpleNamespace(_hWnd=5829, left=10, top=20, width=30, height=40)
    assert desktop_geometry.logical_window(window) is window
    record = events('desktop.dpi.fallback')[0]
    assert record.data['reason'] == 'monitor_lookup_failed'


def test_rps_result_and_timeout_keep_the_session_id(qt_app, monkeypatch):
    import character.rps_game as rps
    clock = [100.0]
    monkeypatch.setattr(rps.time, 'time', lambda: clock[0])
    overlay = RpsGameOverlay(Mock(return_value=True))
    overlay.start_round()
    session = overlay.session
    overlay._begin_capture()
    overlay.finish_round('ROCK')
    overlay.close()
    assert events('game.rps.result')[0].trace_id == session
    assert events('game.rps.ended')[0].trace_id == session
    overlay.start_round()
    clock[0] = overlay.deadline + overlay.CAPTURE_SECONDS + 1
    overlay.tick()
    record = events('game.rps.no_result')[0]
    assert record.trace_id == overlay.session and record.data['reason'] == 'timeout'
    overlay.close()


def test_ball_kick_cooldown_resume_and_end_share_session(qt_app, monkeypatch):
    import character.sandbox_manager as sandbox
    character = QWidget()
    character.resize(100, 100)
    character.is_moving = character.is_dragging = False
    character.sprite_animator = Mock()
    character.mood_system = SimpleNamespace(on_ball_play=Mock(), decide_emotion=Mock(return_value={}))
    character.update_action = Mock()
    character.move_toward_ball = Mock()
    manager = SandboxManager(character)
    monkeypatch.setattr(sandbox.random, 'uniform', lambda *_: 3.0)
    manager.select_ball()
    manager._warmup_timer.stop()
    ball = manager.ball
    ball.physics_timer.stop()
    manager._enable_ball_interaction()
    ball.move(character.pos())
    ball._check_character_collision(character)
    assert events('sandbox.ball.kicked') and events('sandbox.ball.cooldown')
    manager._resume_ball_interaction(ball)
    ball.close()
    records = [event for event in get_events() if event.event.startswith('sandbox.ball.')]
    assert {event.trace_id for event in records} == {manager.log_trace_id}
    assert events('sandbox.ball.resumed') and events('sandbox.ball.ended')
    character.close()
