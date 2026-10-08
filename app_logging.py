"""Shared, secret-safe event logging for the Qt host and recognition process.

Importing this module only buffers events. File/stream capture is explicitly
enabled by the application entry point, so libraries and tests have no I/O side
effects. Diagnostic failures must never interrupt the user's operation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
from typing import Any
import uuid
import weakref

SESSION_ID = os.environ.get('CAPSTONE_LOG_SESSION') or uuid.uuid4().hex
_lock = threading.RLock()
_events: deque = deque(maxlen=5000)
_subscribers: list = []
_secrets: set[str] = set()
_throttles: dict = {}
_writer = None
_file_error = None
_protocol_stream = sys.stdout
_protocol_lock = threading.Lock()
_secret_key = re.compile(r'^(?:api[_-]?key|key|authorization|password|passwd|access[_-]?token|refresh[_-]?token|secret|credential)s?$', re.I)
_credential_text = re.compile(r'(?i)((?:api[_-]?key|access[_-]?token|authorization|password)[\s\"\x27:=]+)([^\s\"\x27,}&]+)')
_url_key = re.compile(r'(?i)([?&](?:key|api_key|access_token)=)[^&#\s]+')


def register_secret(value) -> None:
    if isinstance(value, str) and value:
        with _lock:
            _secrets.add(value)


def register_environment_secrets() -> None:
    for key, value in os.environ.items():
        if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
            register_secret(value)


def sanitize(value: Any, _depth: int = 0) -> Any:
    """Retain diagnostic content, removing credentials before any sink sees it."""
    if _depth > 20:
        return '<nested value>'
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if _secret_key.match(str(k)) else sanitize(v, _depth + 1)
                for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v, _depth + 1) for v in value]
    if isinstance(value, str):
        with _lock:
            secrets = tuple(_secrets)
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = _url_key.sub(r'\1[REDACTED]', value)
        value = re.sub(r'AIza[\w-]{20,}', '[REDACTED]', value)
        value = re.sub(r'(?i)(Bearer\s+)[\w.\-/+=]+', r'\1[REDACTED]', value)
        return _credential_text.sub(r'\1[REDACTED]', value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (datetime, Path)):
        return str(value)
    try:
        return sanitize(str(value), _depth + 1)
    except Exception:
        return '<unprintable value>'


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime
    category: str
    message: str
    event: str = 'legacy.output'
    level: str = 'INFO'
    trace_id: str | None = None
    data: dict = field(default_factory=dict)
    session_id: str = SESSION_ID
    process_id: int = field(default_factory=os.getpid)
    thread: str = field(default_factory=lambda: threading.current_thread().name)

    def to_dict(self) -> dict:
        return {'timestamp': self.timestamp.isoformat(), 'level': self.level,
                'category': self.category, 'event': self.event,
                'trace_id': self.trace_id, 'message': self.message, 'data': self.data,
                'session_id': self.session_id, 'process_id': self.process_id,
                'thread': self.thread}

    def format(self) -> str:
        text = self.message.replace('\r', '').replace('\n', ' ↵ ')
        trace = f' [{self.trace_id}]' if self.trace_id else ''
        return f'[{self.timestamp:%H:%M:%S}] [{self.level}] [{self.category}] [{self.event}]{trace} {text}'

    def details(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


def new_trace_id(prefix='') -> str:
    return (str(prefix).rstrip('-') + '-' if prefix else '') + uuid.uuid4().hex[:16]


def get_events() -> list[LogEvent]:
    with _lock:
        return list(_events)


def clear_events() -> None:
    with _lock:
        _events.clear()


def subscribe(callback, *, replay=False):
    reference = weakref.WeakMethod(callback) if getattr(callback, '__func__', None) is not None else lambda: callback
    with _lock:
        _subscribers.append(reference)
        previous = list(_events) if replay else []
    for event in previous:
        callback(event)
    def unsubscribe():
        with _lock:
            if reference in _subscribers:
                _subscribers.remove(reference)
    return unsubscribe


def _publish(record: LogEvent, *, persist=True, protocol=True) -> LogEvent:
    with _lock:
        _events.append(record)
        callbacks = [ref() for ref in _subscribers]
        writer = _writer
        _subscribers[:] = [ref for ref in _subscribers if ref() is not None]
    for callback in callbacks:
        if callback is not None:
            try:
                callback(record)
            except Exception:
                pass
    if persist and writer is not None:
        writer.submit(record)
    if protocol and os.environ.get('CAPSTONE_LOG_PROTOCOL') == '1':
        write_protocol('APP_LOG', record.to_dict(), stream=_protocol_stream)
    return record


def write_protocol(prefix: str, payload: dict, *, stream=None) -> bool:
    """Serialize child log/settings lines together, including their newline."""
    try:
        target = stream if stream is not None else sys.stdout
        line = prefix + ' ' + json.dumps(payload, ensure_ascii=False, default=str) + '\n'
        with _protocol_lock:
            target.write(line)
            target.flush()
        return True
    except (OSError, ValueError, TypeError):
        return False


def log_event(event: str, message: str = '', *, category='시스템', level='INFO', trace_id=None, **data) -> LogEvent:
    try:
        if str(level).upper() in ('ERROR', 'CRITICAL') and category != '오류':
            data.setdefault('source_category', category)
            category = '오류'
        record = LogEvent(datetime.now().astimezone(), str(category), sanitize(str(message)),
                          str(event), str(level).upper(), trace_id, sanitize(data))
        return _publish(record)
    except Exception:
        # Even a broken __str__ or a closed output pipe must not fail the operation.
        return LogEvent(datetime.now().astimezone(), '오류', '로그 기록 실패', 'logging.internal_error', 'ERROR')


def ingest_event(payload: dict) -> LogEvent:
    """Forward a child's event without losing its PID/session/time/correlation."""
    if not isinstance(payload, dict) or not isinstance(payload.get('event'), str):
        raise ValueError('invalid structured event')
    record = LogEvent(datetime.fromisoformat(payload['timestamp']),
                      str(payload.get('category', '시스템')), sanitize(str(payload.get('message', ''))),
                      payload['event'], str(payload.get('level', 'INFO')), payload.get('trace_id'),
                      sanitize(payload.get('data', {})), str(payload.get('session_id', SESSION_ID)),
                      int(payload.get('process_id', 0)), str(payload.get('thread', 'child')))
    return _publish(record, protocol=False)


def log_throttled(event, message='', *, key=None, interval=5.0, category='시스템', level='INFO', trace_id=None, **data):
    now = time.monotonic()
    throttle_key = (event, str(key) if key is not None else '')
    with _lock:
        last, suppressed = _throttles.get(throttle_key, (float('-inf'), 0))
        if now - last < interval:
            _throttles[throttle_key] = (last, suppressed + 1)
            return None
        _throttles[throttle_key] = (now, 0)
        if len(_throttles) > 4096:
            _throttles.pop(next(iter(_throttles)))
    if suppressed:
        data['suppressed_since_previous'] = suppressed
    return log_event(event, message, category=category, level=level, trace_id=trace_id, **data)


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(record.event_record.to_dict(), ensure_ascii=False, default=str)


class _FileWriter:
    def __init__(self, path, max_bytes, backup_count):
        self.path = Path(path)
        self.queue = queue.Queue(maxsize=20000)
        self.error = None
        self.dropped = 0
        self.closed = False
        self.handler = RotatingFileHandler(self.path, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
        self.handler.setFormatter(_JsonFormatter())
        # Handler.handleError otherwise only prints (and does not expose failure).
        self.handler.handleError = self._handle_error
        self.thread = threading.Thread(target=self._run, name='app-log-writer', daemon=True)
        self.thread.start()

    def _handle_error(self, record):
        self._write_failed = True
        error = sys.exc_info()[1]
        self._report_error(str(error) if error else 'file write failed')

    def _report_error(self, message):
        changed = self.error != message
        self.error = message
        if changed:
            _publish(LogEvent(datetime.now().astimezone(), '오류', '로그 파일 기록 실패',
                              'logging.file_error', 'ERROR', data={'path': str(self.path), 'error': sanitize(message)}), persist=False)

    def submit(self, record):
        if self.closed:
            return
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                _publish(LogEvent(datetime.now().astimezone(), '오류', '로그 파일 대기열 초과',
                                  'logging.queue_dropped', 'WARNING', data={'dropped': self.dropped}), persist=False)

    def _run(self):
        while True:
            event = self.queue.get()
            try:
                if event is None:
                    break
                record = logging.LogRecord('capstone.events', logging.INFO, '', 0, '', (), None)
                record.event_record = event
                previous_error = self.error
                self._write_failed = False
                self.handler.emit(record)
                if previous_error and not self._write_failed:
                    self.error = None
                    _publish(LogEvent(datetime.now().astimezone(), '시스템', '로그 파일 기록 복구',
                                      'logging.file_recovered', data={'path': str(self.path)}), persist=False)
            except Exception as exc:
                self._report_error(str(exc))
            finally:
                self.queue.task_done()
        self.handler.close()

    def close(self, timeout=5.0):
        self.closed = True
        try:
            self.queue.put(None, timeout=timeout)
            self.thread.join(timeout)
        except queue.Full:
            self._report_error('shutdown queue timeout')
        if self.thread.is_alive():
            self._report_error(f'shutdown incomplete: {self.queue.qsize()} queued entries')


def configure_logging(directory, *, max_bytes=10 * 1024 * 1024, backup_count=5):
    global _writer, _file_error
    if _writer is not None:
        return file_status()
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        writer = _FileWriter(directory / 'app.jsonl', max_bytes, backup_count)
        with _lock:
            previous = list(_events)
            _writer = writer
            _file_error = None
        for event in previous:
            writer.submit(event)
        log_event('logging.file_ready', '로그 파일 기록 시작', path=str(_writer.path), max_bytes=max_bytes, backup_count=backup_count)
    except Exception as exc:
        _file_error = sanitize(str(exc))
        log_event('logging.file_error', '로그 파일 초기화 실패', category='오류', level='ERROR', error=str(exc), directory=str(directory))
    return file_status()


def file_status():
    return {'path': str(_writer.path) if _writer else None,
            'error': _writer.error if _writer else _file_error,
            'queued': _writer.queue.qsize() if _writer else 0,
            'dropped': _writer.dropped if _writer else 0}


def shutdown_logging():
    global _writer
    writer, _writer = _writer, None
    if writer is not None:
        writer.close()


class EventLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            log_event('python.logging', self.format(record),
                      category='오류' if record.levelno >= logging.WARNING else '시스템',
                      level=record.levelname, logger=record.name)
        except Exception:
            pass
