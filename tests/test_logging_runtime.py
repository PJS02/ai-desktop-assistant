"""Core/file/UI and child protocol diagnostics, without live app or devices."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import queue
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

import app_logging as logs
import main as app_main
from character.log_console import AppLogManager, LogStream, LogWindow
from character import log_console


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def records():
    received = []
    unsubscribe = logs.subscribe(received.append)
    try:
        yield received
    finally:
        unsubscribe()


@pytest.fixture
def clean_writer():
    logs.shutdown_logging()
    logs.clear_events()
    try:
        yield
    finally:
        logs.shutdown_logging()


def find(records, name):
    return next(record for record in records if record.event == name)


def test_concurrent_protocol_writers_keep_log_and_settings_json_lines_intact():
    import time
    class FragmentingStream:
        def __init__(self):
            self.parts = []
        def write(self, value):
            for piece in (value[:12], value[12:]):
                self.parts.append(piece)
                time.sleep(0)
            return len(value)
        def flush(self):
            pass
    stream = FragmentingStream()
    def send(prefix):
        for index in range(30):
            assert logs.write_protocol(prefix, {'request_id': index, 'text': '여러 줄\n응답'}, stream=stream)
    threads = [threading.Thread(target=send, args=(prefix,)) for prefix in ('APP_LOG', 'APP_SETTINGS')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    lines = ''.join(stream.parts).splitlines()
    assert len(lines) == 60
    assert {line.split(' ', 1)[0] for line in lines} == {'APP_LOG', 'APP_SETTINGS'}
    for line in lines:
        assert json.loads(line.split(' ', 1)[1])['text'] == '여러 줄\n응답'


def test_clear_removes_visible_and_detail_rows_while_display_is_paused(qt_app):
    manager = AppLogManager()
    window = LogWindow(manager)
    try:
        manager.add('clear even when paused')
        window.show_entry_details()
        window.toggle_pause()
        manager.clear()
        assert window.output.toPlainText() == ''
        assert window.details.toPlainText() == ''
        assert window.is_paused
    finally:
        window.shutdown()
        manager._unsubscribe()


def test_old_queued_ui_event_cannot_reappear_after_clear(qt_app):
    manager = AppLogManager()
    window = LogWindow(manager)
    try:
        manager.add('already cleared')
        old_event = manager.entries()[-1]
        manager.clear()
        window.on_entry_added(old_event)
        assert window.output.toPlainText() == ''
        assert window._visible_entries == []
    finally:
        window.shutdown()
        manager._unsubscribe()


def test_secret_redaction_precedes_every_subscriber_and_error_keeps_origin(records):
    key = 'registered-runtime-secret'
    logs.register_secret(key)
    event = logs.log_event('runtime.failure', 'body ' + key, category='대화·AI', level='ERROR',
                           trace_id='trace-runtime', payload={'api_key': 'unknown-secret',
                           'system': 'instructions\nsecond line',
                           'url': 'https://example.test/?key=' + key}, raw='Bearer bearer-secret')
    assert event is records[-1]
    assert event.category == '오류' and event.data['source_category'] == '대화·AI'
    assert event.trace_id == 'trace-runtime'
    details = event.details()
    assert key not in details and 'unknown-secret' not in details and 'bearer-secret' not in details
    assert event.data['payload']['system'] == 'instructions\nsecond line'
    assert '[REDACTED]' in details


def test_broken_subscriber_does_not_block_following_subscriber(records):
    def broken(_event):
        raise OSError('subscriber failure')
    unsubscribe = logs.subscribe(broken)
    try:
        record = logs.log_event('runtime.subscriber', 'delivered')
        assert records[-1] is record
    finally:
        unsubscribe()


def test_file_writer_replays_early_events_drains_on_shutdown_and_keeps_multiline(tmp_path, clean_writer):
    logs.log_event('runtime.early', 'before configuration', trace_id='trace-early')
    status = logs.configure_logging(tmp_path)
    assert status['path'] == str(tmp_path / 'app.jsonl')
    for index in range(150):
        logs.log_event('runtime.file', 'single summary', trace_id=f'trace-{index}',
                       index=index, body='line 1\nline 2\n' + 'long ' * 50)
    logs.shutdown_logging()
    rows = [json.loads(line) for line in (tmp_path / 'app.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [row['event'] for row in rows[:2]] == ['runtime.early', 'logging.file_ready']
    written = [row for row in rows if row['event'] == 'runtime.file']
    assert [row['data']['index'] for row in written] == list(range(150))
    assert written[-1]['data']['body'].startswith('line 1\nline 2\n')


def test_file_rotation_keeps_each_json_record_valid(tmp_path, clean_writer):
    logs.configure_logging(tmp_path, max_bytes=650, backup_count=2)
    for index in range(15):
        logs.log_event('runtime.rotate', 'rotation record', index=index, text='unchanged ' * 10)
    logs.shutdown_logging()
    files = list(tmp_path.glob('app.jsonl*'))
    assert len(files) == 3
    assert all(json.loads(line)['event'] in {'runtime.rotate', 'logging.file_ready'}
               for path in files for line in path.read_text(encoding='utf-8').splitlines())


def test_initial_file_failure_exposes_status_and_stays_in_memory(tmp_path, clean_writer, records):
    blocked = tmp_path / 'occupied'
    blocked.write_text('file instead of directory', encoding='utf-8')
    status = logs.configure_logging(blocked)
    assert find(records, 'logging.file_error').category == '오류'
    assert status['error'], 'UI status must retain initialization failure even without a writer'
    record = logs.log_event('runtime.after_file_failure', 'operation continues')
    assert records[-1] is record


def test_runtime_disk_error_is_visible_without_recursive_file_logging(tmp_path, clean_writer, records, monkeypatch):
    logs.configure_logging(tmp_path)
    writer = logs._writer
    writer.queue.join()

    def fail_emit(_record):
        raise OSError('simulated disk unavailable')

    monkeypatch.setattr(writer.handler, 'emit', fail_emit)
    logs.log_event('runtime.disk_failure', 'cannot persist')
    writer.queue.join()
    assert logs.file_status()['error'] == 'simulated disk unavailable'
    failures = [record for record in records if record.event == 'logging.file_error']
    assert len(failures) == 1 and failures[0].category == '오류'
    assert writer.queue.qsize() == 0


def test_event_published_during_configuration_is_persisted_once(tmp_path, clean_writer):
    appended = threading.Event()
    release = threading.Event()

    def hold_publication(record):
        if record.event == 'runtime.configure_race':
            appended.set()
            assert release.wait(3)

    unsubscribe = logs.subscribe(hold_publication)
    publisher = threading.Thread(target=lambda: logs.log_event('runtime.configure_race', 'one event'))
    try:
        publisher.start()
        assert appended.wait(2)
        logs.configure_logging(tmp_path)
        release.set()
        publisher.join(3)
        assert not publisher.is_alive()
        logs.shutdown_logging()
        written = [json.loads(line) for line in (tmp_path / 'app.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len([record for record in written if record['event'] == 'runtime.configure_race']) == 1
    finally:
        release.set()
        publisher.join(3)
        unsubscribe()


def test_file_queue_overflow_is_counted_and_reported_without_throwing(records, clean_writer):
    writer = logs._FileWriter.__new__(logs._FileWriter)
    writer.closed = False
    writer.queue = queue.Queue(maxsize=1)
    writer.dropped = 0
    record = logs.log_event('runtime.overflow_record', 'record')
    writer.submit(record)
    writer.submit(record)
    writer.submit(record)
    assert writer.dropped == 2
    warning = find(records, 'logging.queue_dropped')
    assert warning.data['dropped'] == 1


def test_log_stream_flushes_current_and_remaining_worker_buffers(qt_app):
    manager = AppLogManager()
    terminal = io.StringIO()
    stream = LogStream(manager, terminal, False)
    try:
        stream.write('main partial')
        worker = threading.Thread(target=lambda: stream.write('worker partial'))
        worker.start()
        worker.join()
        assert manager.entries() == []
        stream.flush()
        assert [event.message for event in manager.entries()] == ['main partial']
        stream.flush_all()
        assert [event.message for event in manager.entries()] == ['main partial', 'worker partial']
        assert terminal.getvalue() == 'main partialworker partial'
    finally:
        manager._unsubscribe()


def test_ui_row_details_preserve_full_payload_and_search(qt_app):
    manager = AppLogManager()
    window = LogWindow(manager)
    try:
        logs.log_event('runtime.prompt', 'summary\nsecond summary', category='대화·AI',
                       trace_id='trace-visible', prompt='first\nlast searchable unique body')
        qt_app.processEvents()
        assert window.output.topLevelItemCount() == 1
        window.show_entry_details()
        assert json.loads(window.details.toPlainText())['data']['prompt'] == 'first\nlast searchable unique body'
        window.search_input.setText('searchable unique body')
        assert len(window._visible_entries) == 1
        window.tabs.setCurrentIndex(5)
        assert window.output.toPlainText() == ''
    finally:
        window.shutdown()
        manager._unsubscribe()


def test_visible_retention_tracks_manager_and_details_rows(qt_app):
    manager = AppLogManager(max_entries=2)
    window = LogWindow(manager)
    try:
        for index in range(4):
            logs.log_event('runtime.retention', f'row-{index}', index=index)
        qt_app.processEvents()
        assert manager.evicted_count == 2
        assert len(window._visible_entries) == 2, 'live display must evict the same entries as the manager'
        assert window.output.topLevelItemCount() == 2
        window.output.setCurrentItem(window.output.topLevelItem(0))
        assert json.loads(window.details.toPlainText())['data']['index'] == 2
        assert '제외 2개' in window.status_label.text()
    finally:
        window.shutdown()
        manager._unsubscribe()


def test_filtered_live_view_removes_matching_entry_evicted_by_other_categories(qt_app):
    manager = AppLogManager(max_entries=2)
    window = LogWindow(manager)
    window.tabs.setCurrentIndex(3)  # dialogue tab
    try:
        logs.log_event('runtime.filtered_old', 'old dialogue', category='대화·AI')
        assert len(window._visible_entries) == 1
        for index in range(3):
            logs.log_event('runtime.other_category', f'system row {index}', category='시스템')
        qt_app.processEvents()
        assert window._visible_entries == [], 'filtered live view must not retain globally evicted entries'
        assert window.output.toPlainText() == ''
    finally:
        window.shutdown()
        manager._unsubscribe()


def test_install_capture_replay_does_not_duplicate_concurrent_live_event(qt_app, monkeypatch):
    logs.clear_events()
    manager = AppLogManager()
    original_get_events = log_console.get_events

    def publish_between_snapshot_and_replay():
        logs.log_event('runtime.install_race', 'one install event')
        return original_get_events()

    monkeypatch.setattr(log_console, 'get_events', publish_between_snapshot_and_replay)
    try:
        manager.install_capture()
        assert len([record for record in manager.entries() if record.event == 'runtime.install_race']) == 1
    finally:
        manager.restore_capture()
        manager._unsubscribe()


def test_child_app_log_and_settings_forward_once_keep_correlation_and_pid(records):
    payload = {'timestamp': '2026-10-08T10:11:12+09:00', 'category': '사용자 인식',
               'message': 'child model result', 'event': 'child.result', 'level': 'INFO',
               'trace_id': 'trace-child', 'data': {'text': 'long child text\nsecond line'},
               'session_id': 'child-session', 'process_id': 314, 'thread': 'child-thread'}
    settings = {'kind': 'apply_result', 'request_id': 'settings-trace', 'ok': True}
    process = SimpleNamespace(stdout=io.StringIO('APP_LOG ' + json.dumps(payload) + '\nAPP_SETTINGS ' + json.dumps(settings) + '\nplain stdout\n'),
                              pid=314, poll=lambda: 7)
    manager = app_main.MediaPipeProcessManager()
    received = []
    manager.settings_message.connect(received.append)
    manager._forward_output(process)
    child = find(records, 'child.result')
    assert child.trace_id == 'trace-child' and child.process_id == 314
    assert child.session_id == 'child-session' and child.data['text'].endswith('second line')
    assert received == [settings, {'kind': 'unavailable'}]
    assert find(records, 'settings.remote_response').trace_id == 'settings-trace'
    stdout = [record for record in records if record.event == 'recognition.process_stdout']
    assert [record.message for record in stdout] == ['plain stdout']
    assert find(records, 'recognition.process_output_closed').data['exit_code'] == 7


def test_malformed_protocol_does_not_stop_later_output_and_unknown_stderr_is_warning(records):
    manager = app_main.MediaPipeProcessManager()
    process = SimpleNamespace(stdout=io.StringIO('APP_LOG broken\nAPP_SETTINGS broken\nlater line\n'),
                              stderr=io.StringIO('native diagnostic\n'), pid=271, poll=lambda: 1)
    manager._forward_output(process)
    manager._forward_stderr(process)
    assert find(records, 'recognition.invalid_log').category == '오류'
    assert find(records, 'settings.invalid_response').category == '오류'
    assert find(records, 'recognition.process_stdout').message == 'later line'
    stderr = find(records, 'recognition.process_stderr')
    assert stderr.category == '사용자 인식' and stderr.level == 'WARNING'
    assert stderr.message == 'native diagnostic' and stderr.data['stream'] == 'stderr'


def test_child_that_closes_stdout_before_exit_still_logs_actual_exit_code(tmp_path, records):
    script = tmp_path / 'fake_child.py'
    script.write_text('import os, time\nos.close(1)\ntime.sleep(0.05)\nraise SystemExit(7)\n', encoding='utf-8')
    manager = app_main.MediaPipeProcessManager(script)
    assert manager.start()
    process = manager.process
    try:
        assert process.wait(timeout=3) == 7
        for reader in list(manager._readers):
            reader.join(2)
        manager.stop()
        assert any(record.event.startswith('recognition.process_') and record.data.get('exit_code') == 7
                   for record in records), 'stdout EOF poll=None must not hide the final abnormal exit code'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


_NATIVE_PROBE = r'''
import ctypes, json, os, sys
from app_logging import get_events, clear_events
from native_log_capture import StartupCapture
clear_events()
capture = StartupCapture()
print('python-bootstrap-once')
sys.stdout.write('python-partial')
sys.stdout.flush()
os.write(1, 'native-fd-out-once\n'.encode())
os.write(2, 'native-fd-err-once\n'.encode())
encoded = '한글 분할 출력\n'.encode('utf-8')
os.write(1, encoded[:2])
os.write(1, encoded[2:])
if os.name == 'nt':
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    kernel32.WriteFile.restype = ctypes.c_int
    for kind, text in ((-11, b'native-win-out-once\n'), (-12, b'native-win-err-once\n')):
        written = ctypes.c_uint32()
        handle = kernel32.GetStdHandle(ctypes.c_uint32(kind))
        assert kernel32.WriteFile(handle, text, len(text), ctypes.byref(written), None), ctypes.get_last_error()
capture.close()
capture.close()
print('PROBE_EVENTS ' + json.dumps([event.to_dict() for event in get_events()]))
'''


def test_bootstrap_subprocess_captures_python_fd_and_windows_handles_without_duplicates(tmp_path):
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run([sys.executable, '-c', _NATIVE_PROBE], cwd=Path(__file__).resolve().parents[1],
                            env=environment, text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15)
    (tmp_path / 'native-probe.stdout.txt').write_text(result.stdout, encoding='utf-8')
    (tmp_path / 'native-probe.stderr.txt').write_text(result.stderr, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    payload = next(line[len('PROBE_EVENTS '):] for line in result.stdout.splitlines() if line.startswith('PROBE_EVENTS '))
    records = json.loads(payload)
    messages = [record['message'] for record in records]
    for message in ('python-bootstrap-once', 'python-partial', 'native-fd-out-once', 'native-fd-err-once', '한글 분할 출력'):
        assert messages.count(message) == 1
    if os.name == 'nt':
        assert messages.count('native-win-out-once') == 1, 'Win32 standard handles must follow fd capture'
        assert messages.count('native-win-err-once') == 1


_PARTIAL_NATIVE_FAILURE_PROBE = r'''
import json, os, sys
from app_logging import get_events
from native_log_capture import StartupCapture
saved_out = os.dup(1)
original_setter = StartupCapture._set_windows_handle
failed = [False]
def fail_once(fd):
    if fd == 1 and not failed[0]:
        failed[0] = True
        raise OSError('forced failure after dup2')
    return original_setter(fd)
StartupCapture._set_windows_handle = staticmethod(fail_once)
capture = StartupCapture()
capture.close()
os.write(1, b'OUTPUT_AFTER_PARTIAL_FAILURE\n')
os.write(saved_out, ('PROBE_EVENTS ' + json.dumps([event.to_dict() for event in get_events()]) + '\n').encode())
os.close(saved_out)
'''


def test_partial_native_initialization_failure_restores_stdout_in_subprocess(tmp_path):
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run([sys.executable, '-c', _PARTIAL_NATIVE_FAILURE_PROBE],
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=15)
    (tmp_path / 'native-failure-probe.stdout.txt').write_text(result.stdout, encoding='utf-8')
    (tmp_path / 'native-failure-probe.stderr.txt').write_text(result.stderr, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert 'OUTPUT_AFTER_PARTIAL_FAILURE' in result.stdout, 'partial native failure must restore fd 1 before fallback'
    payload = next(line[len('PROBE_EVENTS '):] for line in result.stdout.splitlines() if line.startswith('PROBE_EVENTS '))
    assert any(record['event'] == 'logging.native_unavailable' for record in json.loads(payload))
