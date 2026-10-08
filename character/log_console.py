from __future__ import annotations
from collections import deque
import logging
import sys
import threading
from PyQt6.QtCore import QObject, Qt, pyqtSignal, qInstallMessageHandler
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTabBar, QVBoxLayout, QWidget)
from app_logging import EventLoggingHandler, LogEvent, file_status, get_events, log_event, subscribe

LOG_CATEGORIES = ('전체', '사용자 인식', '캐릭터 상태', '대화·AI', '시스템', '오류')
LogEntry = LogEvent

def classify_log_message(message, is_error=False):
    lowered = message.lower()
    if is_error or any(t in lowered for t in ('[오류]', '[경고]', 'traceback', '실패]', 'error]')):
        return '오류'
    if any(t in lowered for t in ('gemini', 'api 요청', 'api 응답', '대사', '대화', 'dialogue', '말풍선', 'tts')):
        return '대화·AI'
    if any(t in lowered for t in ('mediapipe', '외부 감정', '외부 동작', '사용자 인사', '외부 고개',
        '외부 상태', '인식 수신기', 'recognition', 'speech', 'stt', '음성 인식', '카메라')):
        return '사용자 인식'
    if any(t in lowered for t in ('점프', '착지', '애니메이션', '감정 상태', 'mood', 'idle', 'surface',
        'on_', 'random skip', '드래그', '자율 이벤트', 'self_play', 'self_rest', 'self_curiosity',
        '쓰다듬기', '수동 제어', 'rps', '표정')):
        return '캐릭터 상태'
    return '시스템'

class AppLogManager(QObject):
    entry_added = pyqtSignal(object)
    logs_cleared = pyqtSignal()
    def __init__(self, max_entries=5000):
        super().__init__()
        self._entries = deque(maxlen=max_entries)
        self._entry_ids = set()
        self._lock = threading.Lock()
        self.evicted_count = 0
        self.max_entries = max_entries
        self._stdout_original = self._stderr_original = None
        self._capture_streams = []
        self._qt_previous = None
        self._logging_handler = None
        self._unsubscribe = subscribe(self._accept)

    def _accept(self, entry):
        with self._lock:
            if id(entry) in self._entry_ids:
                return
            if len(self._entries) == self._entries.maxlen:
                self.evicted_count += 1
                self._entry_ids.discard(id(self._entries[0]))
            self._entries.append(entry)
            self._entry_ids.add(id(entry))
        self.entry_added.emit(entry)

    def install_capture(self):
        if self._stdout_original is not None:
            return
        with self._lock:
            existing = {id(event) for event in self._entries}
        for entry in get_events():
            if id(entry) not in existing:
                self._accept(entry)
        self._stdout_original, self._stderr_original = sys.stdout, sys.stderr
        self._capture_streams = [LogStream(self, sys.stdout, False), LogStream(self, sys.stderr, True)]
        sys.stdout, sys.stderr = self._capture_streams
        self._logging_handler = EventLoggingHandler()
        logging.getLogger().addHandler(self._logging_handler)
        self._qt_previous = qInstallMessageHandler(self._qt_message)

    def _qt_message(self, kind, context, message):
        name = getattr(kind, 'name', str(kind))
        level = 'ERROR' if 'Critical' in name or 'Fatal' in name else 'WARNING' if 'Warning' in name else 'INFO'
        log_event('qt.message', message, category='오류' if level != 'INFO' else '시스템', level=level,
            kind=name, file=getattr(context, 'file', None), line=getattr(context, 'line', None),
            function=getattr(context, 'function', None))

    def restore_capture(self):
        if self._stdout_original is None:
            return
        for stream in self._capture_streams:
            stream.flush_all()
        sys.stdout, sys.stderr = self._stdout_original, self._stderr_original
        self._stdout_original = self._stderr_original = None
        self._capture_streams = []
        qInstallMessageHandler(self._qt_previous)
        if self._logging_handler is not None:
            logging.getLogger().removeHandler(self._logging_handler)
            self._logging_handler = None

    def add(self, message, is_error=False):
        message = message.strip()
        if message:
            category = classify_log_message(message, is_error)
            log_event('legacy.stderr' if is_error else 'legacy.stdout', message, category=category,
                level='ERROR' if is_error else 'WARNING' if category == '오류' else 'INFO')

    def entries(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._entry_ids.clear()
            self.evicted_count = 0
        self.logs_cleared.emit()

class LogStream:
    def __init__(self, manager, original, is_error):
        self.manager, self.original, self.is_error = manager, original, is_error
        self._buffers = {}
        self._lock = threading.Lock()
    @property
    def encoding(self):
        return getattr(self.original, 'encoding', 'utf-8')
    def isatty(self):
        return bool(getattr(self.original, 'isatty', lambda: False)())
    def fileno(self):
        return self.original.fileno()
    def write(self, text):
        written = self.original.write(text)
        completed = []
        thread_id = threading.get_ident()
        with self._lock:
            pieces = (self._buffers.get(thread_id, '') + text).splitlines(keepends=True)
            remainder = ''
            for piece in pieces:
                if piece.endswith(('\n', '\r')):
                    completed.append(piece.rstrip('\r\n'))
                else:
                    remainder = piece
            self._buffers[thread_id] = remainder
        for line in completed:
            self.manager.add(line, self.is_error)
        return written
    def _flush_buffers(self, all_threads=False):
        with self._lock:
            ids = list(self._buffers) if all_threads else [threading.get_ident()]
            lines = [self._buffers.pop(key, '') for key in ids]
        for line in lines:
            if line:
                self.manager.add(line, self.is_error)
    def flush(self):
        self._flush_buffers()
        self.original.flush()
    def flush_all(self):
        self._flush_buffers(all_threads=True)
        self.original.flush()

class LogWindow(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.is_paused = False
        self._allow_close = False
        self._visible_entries = []
        self._last_evicted_count = 0
        self.setWindowTitle('AI Desktop Assistant 로그')
        self.resize(1150, 750)
        layout = QVBoxLayout(self)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        for category in LOG_CATEGORIES:
            self.tabs.addTab(category)
        self.tabs.currentChanged.connect(self.refresh)
        layout.addWidget(self.tabs)
        toolbar = QHBoxLayout()
        self.auto_scroll = QCheckBox('자동 스크롤')
        self.auto_scroll.setChecked(True)
        self.pause_button = QPushButton('일시정지')
        self.pause_button.clicked.connect(self.toggle_pause)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('메시지·추적 ID·상세 내용 검색')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        self.copy_button = QPushButton('복사')
        self.copy_button.clicked.connect(self.copy_logs)
        self.clear_button = QPushButton('지우기')
        self.clear_button.clicked.connect(manager.clear)
        for widget in (self.auto_scroll, self.pause_button, self.search_input, self.copy_button, self.clear_button):
            toolbar.addWidget(widget, 1 if widget is self.search_input else 0)
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFont('Consolas', 10))
        self.output.document().setMaximumBlockCount(manager.max_entries)
        self.output.cursorPositionChanged.connect(self.show_entry_details)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('로그 행을 선택하면 요청·응답 전문과 상세 정보를 표시합니다.')
        splitter.addWidget(self.output)
        splitter.addWidget(self.details)
        splitter.setSizes([450, 200])
        layout.addWidget(splitter, 1)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        manager.entry_added.connect(self.on_entry_added)
        manager.logs_cleared.connect(self._on_logs_cleared)
        self._update_status()
    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()
    def current_category(self):
        return LOG_CATEGORIES[max(0, self.tabs.currentIndex())]
    def matches_filters(self, entry):
        category = self.current_category()
        if category != '전체' and entry.category != category:
            return False
        query = self.search_input.text().strip().lower()
        return not query or query in entry.details().lower()
    def _update_status(self):
        status = file_status()
        storage = f"파일: {status['path']}" if status['path'] else '파일 기록 꺼짐'
        if status['error']:
            storage += f" | 기록 오류: {status['error']}"
        self.status_label.setText(f'보관 {len(self.manager.entries())}개 | 메모리에서 제외 {self.manager.evicted_count}개 | 파일 대기열 누락 {status["dropped"]}개 | {storage}')
    def on_entry_added(self, entry):
        self._update_status()
        if self.is_paused:
            return
        with self.manager._lock:
            if id(entry) not in self.manager._entry_ids:
                return
        if self.manager.evicted_count != self._last_evicted_count:
            with self.manager._lock:
                retained = self.manager._entry_ids.copy()
            previous = self._visible_entries
            self._visible_entries = [event for event in previous if id(event) in retained]
            if len(previous) != len(self._visible_entries):
                self.output.setPlainText('\n'.join(event.format() for event in self._visible_entries))
                self.show_entry_details()
            self._last_evicted_count = self.manager.evicted_count
        if not self.matches_filters(entry):
            return
        self._visible_entries.append(entry)
        self._visible_entries = self._visible_entries[-self.manager.max_entries:]
        self.output.appendPlainText(entry.format())
        if self.auto_scroll.isChecked():
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())
    def refresh(self):
        self._update_status()
        if self.is_paused:
            return
        self._visible_entries = [entry for entry in self.manager.entries() if self.matches_filters(entry)]
        self._last_evicted_count = self.manager.evicted_count
        self.output.setPlainText('\n'.join(entry.format() for entry in self._visible_entries))
        self.show_entry_details()
        if self.auto_scroll.isChecked():
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())
    def _on_logs_cleared(self):
        self._visible_entries = []
        self._last_evicted_count = 0
        self.output.clear()
        self.details.clear()
        self._update_status()
    def show_entry_details(self):
        row = self.output.textCursor().blockNumber()
        self.details.setPlainText(self._visible_entries[row].details() if 0 <= row < len(self._visible_entries) else '')
    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.pause_button.setText('재개' if self.is_paused else '일시정지')
        if not self.is_paused:
            self.refresh()
    def copy_logs(self):
        selected = self.output.textCursor().selectedText().replace('\u2029', '\n')
        QApplication.clipboard().setText(selected or self.output.toPlainText())
    def shutdown(self):
        self._allow_close = True
        self.close()
    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            self.hide()
            event.ignore()
