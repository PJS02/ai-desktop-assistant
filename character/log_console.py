from __future__ import annotations
from collections import deque
import logging
import re
import sys
import threading
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, qInstallMessageHandler
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTabBar, QVBoxLayout, QWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QTabWidget, QComboBox, QMenu, QFrame, QToolButton)
from app_logging import EventLoggingHandler, LogEvent, file_status, get_events, log_event, subscribe
from log_classification import classify_output
from .log_presentation import CATEGORY_TABS, present_event

LOG_CATEGORIES = ('전체', '사용자 인식', '캐릭터 상태', '대화·AI', '시스템', '오류')
LogEntry = LogEvent

def classify_log_message(message, is_error=False):
    category, level = classify_output(message, is_error=is_error)
    return '오류' if level in ('WARNING', 'ERROR', 'CRITICAL') else category

class AppLogManager(QObject):
    entry_added = pyqtSignal(object)
    logs_cleared = pyqtSignal()
    def __init__(self, max_entries=5000):
        super().__init__()
        self._entries = deque(maxlen=max_entries)
        self._entry_ids = set()
        self._entry_sequences = {}
        self._next_sequence = 0
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
                oldest_id = id(self._entries[0])
                self._entry_ids.discard(oldest_id)
                self._entry_sequences.pop(oldest_id, None)
            self._entries.append(entry)
            self._entry_ids.add(id(entry))
            self._entry_sequences[id(entry)] = self._next_sequence
            self._next_sequence += 1
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
            category, level = classify_output(message, is_error=is_error)
            log_event('legacy.stderr' if is_error else 'legacy.stdout', message, category=category,
                level=level)

    def entries(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._entry_ids.clear()
            self._entry_sequences.clear()
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

def format_readable_event(entry, presentation=None, *, raw=False, milliseconds=False):
    if raw:
        return entry.format().replace('\n', ' ↵ ')
    presentation = presentation or present_event(entry)
    action, summary = presentation.action, presentation.summary
    plain_summary = re.sub(r'^(?:\[[^\]]+\]\s*)+', '', summary)
    if summary == '추가 내용 없음':
        content = action
    elif plain_summary.startswith(action.rstrip('…')):
        content = summary
    else:
        content = action + ': ' + summary
    timestamp = entry.timestamp.strftime('%H:%M:%S.%f')[:-3] if milliseconds else entry.timestamp.strftime('%H:%M:%S')
    level = {'WARNING': '경고', 'ERROR': '오류', 'CRITICAL': '심각', 'DEBUG': '디버그'}.get(entry.level)
    severity = f' [{level}]' if level else ''
    return f'[{timestamp}] [{presentation.domain}]{severity} {content}'


class LogTimeline(QTreeWidget):
    """Readable rows, with every represented record available for export."""
    def toPlainText(self):
        lines = []
        for row in range(self.topLevelItemCount()):
            item = self.topLevelItem(row)
            for entry in item.data(0, Qt.ItemDataRole.UserRole) or ():
                lines.append(format_readable_event(entry, raw=getattr(self, 'raw_mode', False)))
        return "\n".join(lines)


class LogWindow(QWidget):
    """One chronological integrated view and domain-specific views of the same records."""
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.is_paused = False
        self._allow_close = False
        self._visible_entries = []
        self._entry_items = {}
        self._presentations = {}
        self._last_evicted_count = 0
        self._refresh_pending = False
        self._previous_source_entry = None
        self._last_source_sequence = -1
        self._saved_topics = {}
        self.setWindowTitle('AI Desktop Assistant 로그')
        self.resize(1150, 750)
        self.setMinimumSize(850, 500)
        self.setFont(QFont('Segoe UI', 10))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)

        self.tabs = QTabBar()
        self.tabs.setObjectName('logCategoryTabs')
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setStyleSheet('''
            QTabBar#logCategoryTabs::tab { color: #44556b; border: 1px solid transparent;
                border-radius: 4px; padding: 5px 9px; margin-right: 2px; }
            QTabBar#logCategoryTabs::tab:hover { background: #e7eef7; }
            QTabBar#logCategoryTabs::tab:selected { background: #dce9f8; color: #234c78;
                border-color: #abc3de; font-weight: 600; }
        ''')
        for category in LOG_CATEGORIES:
            self.tabs.addTab('오류·경고' if category == '오류' else category)
        self.pause_button = QPushButton('일시정지')
        self.pause_button.clicked.connect(self.toggle_pause)
        self.controls_button = QToolButton()
        self.controls_button.setText('도구')
        self.controls_button.setCheckable(True)
        self.controls_button.setArrowType(Qt.ArrowType.RightArrow)
        self.controls_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.controls_button.setToolTip('세부 보기 · 검색 · 수준 · 자동 스크롤 · 반복 접기')
        self.controls_button.toggled.connect(self._toggle_controls)
        self.detail_button = QToolButton()
        self.detail_button.setText('상세')
        self.detail_button.setCheckable(True)
        self.detail_button.setArrowType(Qt.ArrowType.RightArrow)
        self.detail_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.detail_button.setToolTip('선택한 기록의 전문과 원본 JSON 보기 · 행을 두 번 클릭해도 열립니다.')
        self.detail_button.toggled.connect(self._toggle_details)
        self.copy_button = QPushButton('복사')
        copy_menu = QMenu(self.copy_button)
        copy_menu.addAction('표시된 전체 복사', lambda: self.copy_logs())
        copy_menu.addAction('선택한 기록 복사', lambda: self.copy_logs(selected_only=True))
        self.copy_button.setMenu(copy_menu)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.tabs, 1)
        for widget in (self.pause_button, self.controls_button, self.detail_button, self.copy_button):
            top.addWidget(widget)
        layout.addLayout(top)

        self.controls_panel = QFrame()
        self.controls_panel.setObjectName('logToolsPanel')
        self.controls_panel.setStyleSheet('QFrame#logToolsPanel { background: #f8fafc; border: 1px solid #dce3eb; border-radius: 5px; }')
        controls = QVBoxLayout(self.controls_panel)
        controls.setContentsMargins(8, 6, 8, 6)
        controls.setSpacing(6)
        topic_row = QHBoxLayout()
        self.topic_heading = QLabel('전체 · 세부 보기')
        self.subtabs = QTabBar()
        self.subtabs.setExpanding(False)
        self.subtabs.setDrawBase(False)
        self.subtabs.setUsesScrollButtons(True)
        self.subtabs.setStyleSheet('QTabBar::tab { padding: 4px 9px; margin-right: 3px; border: 1px solid transparent; border-radius: 4px; } '
                                  'QTabBar::tab:selected { background: white; color: #234c78; border-color: #abc3de; }')
        topic_row.addWidget(self.topic_heading)
        topic_row.addWidget(self.subtabs, 1)
        controls.addLayout(topic_row)
        toolbar = QHBoxLayout()
        self.auto_scroll = QCheckBox('자동 스크롤')
        self.auto_scroll.setChecked(True)
        self.fold_repeats = QCheckBox('동일 반복 접기')
        self.fold_repeats.setToolTip('내용·추적 ID·수준이 같은 연속 기록만 묶습니다. 펼치면 각 발생을 모두 확인할 수 있습니다.')
        self.fold_repeats.toggled.connect(self.refresh)
        self.level_filter = QComboBox()
        self.level_filter.addItems(['모든 수준', '오류', '경고', '정보', '디버그'])
        self.level_filter.currentIndexChanged.connect(self.refresh)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('문장 · 원인 · 추적 ID · 요청·응답 전문 검색')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.refresh)
        self.clear_button = QPushButton('지우기')
        self.clear_button.clicked.connect(manager.clear)
        for widget in (self.auto_scroll, self.fold_repeats, self.level_filter, self.search_input, self.clear_button):
            toolbar.addWidget(widget, 1 if widget is self.search_input else 0)
        controls.addLayout(toolbar)
        self.view_hint = QLabel()
        self.view_hint.setWordWrap(True)
        self.view_hint.setStyleSheet('color: #65738a;')
        controls.addWidget(self.view_hint)
        layout.addWidget(self.controls_panel)
        self.controls_panel.hide()

        self.filter_bar = QWidget()
        filter_layout = QHBoxLayout(self.filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_label = QLabel()
        self.filter_label.setWordWrap(True)
        self.filter_label.setStyleSheet('color: #536b87;')
        self.reset_filters_button = QToolButton()
        self.reset_filters_button.setText('필터 해제')
        self.reset_filters_button.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.filter_label, 1)
        filter_layout.addWidget(self.reset_filters_button)
        layout.addWidget(self.filter_bar)
        self.filter_bar.hide()

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.output = LogTimeline()
        self.output.setColumnCount(1)
        self.output.setHeaderHidden(True)
        self.output.setFont(QFont('Consolas', 10))
        self.output.setAlternatingRowColors(False)
        self.output.setSortingEnabled(False)
        self.output.setWordWrap(False)
        self.output.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.output.setRootIsDecorated(True)
        self.output.setIndentation(14)
        self.output.setExpandsOnDoubleClick(False)
        self.output.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.output.setUniformRowHeights(False)
        self.output.setStyleSheet('QTreeWidget::item { padding-top: 1px; padding-bottom: 1px; } '
                                  'QTreeWidget::item:selected { background: #e3edf9; color: #123451; }')
        self.output.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.output.currentItemChanged.connect(self.show_entry_details)
        self.output.itemExpanded.connect(self._expand_item)
        self.output.itemDoubleClicked.connect(self.show_details)
        self.splitter.addWidget(self.output)
        self.detail_tabs = QTabWidget()
        self.content_details = QPlainTextEdit()
        self.content_details.setReadOnly(True)
        self.content_details.setPlaceholderText('로그 행을 선택하면 입력·요청·응답·결과를 표시합니다.')
        self.content_details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(QFont('Consolas', 10))
        self.detail_tabs.addTab(self.content_details, '내용·전문')
        self.detail_tabs.addTab(self.details, '원본 JSON')
        self.trace_button = QPushButton('같은 흐름 보기')
        self.trace_button.setToolTip('선택한 기록의 추적 ID로 전체 분류에서 검색합니다.')
        self.trace_button.clicked.connect(self.show_trace)
        self.trace_button.setEnabled(False)
        self.detail_tabs.setCornerWidget(self.trace_button, Qt.Corner.TopRightCorner)
        self.splitter.addWidget(self.detail_tabs)
        self.detail_tabs.hide()
        layout.addWidget(self.splitter, 1)
        self.status_label = QLabel()
        self.status_label.setStyleSheet('color: #65738a;')
        layout.addWidget(self.status_label)
        self.tabs.currentChanged.connect(self._category_changed)
        self.subtabs.currentChanged.connect(self._topic_changed)
        manager.entry_added.connect(self.on_entry_added)
        manager.logs_cleared.connect(self._on_logs_cleared)
        self._category_changed()

    def _toggle_controls(self, checked):
        self.controls_panel.setVisible(checked)
        self.controls_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def _toggle_details(self, checked):
        self.detail_tabs.setVisible(checked)
        self.detail_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.show_entry_details()
            self.splitter.setSizes([max(250, self.height() - 260), 200])

    def show_details(self, *_args):
        self.detail_button.setChecked(True)

    def reset_filters(self):
        self.search_input.clear()
        self.level_filter.setCurrentIndex(0)
        self.subtabs.setCurrentIndex(0)

    def _update_filter_badge(self):
        filters = []
        if self.current_topic() != '통합':
            filters.append(f'{self.tabs.tabText(self.tabs.currentIndex())} · {self.current_topic()}')
        if self.level_filter.currentIndex():
            filters.append(self.level_filter.currentText())
        query = self.search_input.text().strip()
        if query:
            filters.append('검색: ' + (query[:40] + '…' if len(query) > 40 else query))
        self.filter_label.setText('적용 중: ' + ' / '.join(filters))
        self.filter_bar.setVisible(bool(filters))
        self.filter_label.setToolTip('검색: ' + query if query else '')

    def _presentation(self, entry):
        key = id(entry)
        if key not in self._presentations:
            self._presentations[key] = present_event(entry)
        return self._presentations[key]

    def _category_changed(self, *_args):
        category = self.current_category()
        visible_category = self.tabs.tabText(max(0, self.tabs.currentIndex()))
        self.topic_heading.setText(f'{visible_category} · 세부 보기')
        self.subtabs.blockSignals(True)
        while self.subtabs.count():
            self.subtabs.removeTab(0)
        for name in CATEGORY_TABS[category]:
            self.subtabs.addTab(name)
        remembered = self._saved_topics.get(category, '통합')
        names = CATEGORY_TABS[category]
        self.subtabs.setCurrentIndex(names.index(remembered) if remembered in names else 0)
        self.subtabs.blockSignals(False)
        self._update_hint()
        self.refresh()

    def _topic_changed(self, *_args):
        self._saved_topics[self.current_category()] = self.current_topic()
        self._update_hint()
        self.refresh()

    def _update_hint(self):
        topic = self.current_topic()
        self.output.raw_mode = topic == '원본'
        if topic == '원본':
            text = '수집한 원문과 이벤트명을 그대로 표시합니다. 각 행의 원본 JSON에서 전체 기록을 확인할 수 있습니다.'
        elif topic == '요청·응답 전문':
            text = '요청·프롬프트·HTTP 응답·가공 단계를 표시합니다. 행을 펼치거나 아래 내용·전문에서 전체 본문을 읽을 수 있습니다.'
        else:
            text = '모든 단계를 수집 순서대로 표시하며 각 행에 발생 시각을 보여줍니다. 행을 펼치면 전문과 상세 내용을 볼 수 있습니다.'
        self.view_hint.setText(text)

    def current_category(self):
        return LOG_CATEGORIES[max(0, self.tabs.currentIndex())]

    def current_topic(self):
        index = self.subtabs.currentIndex()
        return self.subtabs.tabText(index) if index >= 0 else '통합'

    def matches_filters(self, entry):
        presentation = self._presentation(entry)
        category, topic = self.current_category(), self.current_topic()
        level = entry.level.upper()
        if category == '오류':
            if level not in ('WARNING', 'ERROR', 'CRITICAL') and entry.category != '오류':
                return False
            if topic == '오류' and level not in ('ERROR', 'CRITICAL'):
                return False
            if topic == '경고' and level != 'WARNING':
                return False
        elif category != '전체' and presentation.domain != category:
            return False
        if category not in ('전체', '오류') and topic not in ('통합', '원본') and presentation.topic != topic:
            return False
        chosen_level = {1: ('ERROR', 'CRITICAL'), 2: ('WARNING',), 3: ('INFO',), 4: ('DEBUG',)}.get(self.level_filter.currentIndex())
        if chosen_level and level not in chosen_level:
            return False
        query = self.search_input.text().strip().casefold()
        if not query:
            return True
        return query in (entry.details() + '\n' + presentation.action + '\n' + presentation.summary
                         + '\n' + '\n'.join(label + '\n' + value for label, value in presentation.sections)).casefold()

    def _update_status(self):
        status = file_status()
        with self.manager._lock:
            count = len(self.manager._entries)
        storage = f"파일: {status['path']}" if status['path'] else '파일 기록 꺼짐'
        if status['error']:
            storage += f" | 기록 오류: {status['error']}"
        text = f'표시 {len(self._visible_entries)}건 · 보관 {count}건'
        if self.is_paused:
            text = '일시정지 · ' + text
        if self.manager.evicted_count:
            text += f' · 메모리에서 제외 {self.manager.evicted_count}개'
        if status['dropped']:
            text += f' · 파일 대기열 누락 {status["dropped"]}개'
        if status['error']:
            text += ' · 파일 기록 오류'
        self.status_label.setText(text)
        self.status_label.setStyleSheet('color: #be3030;' if status['error'] or status['dropped'] else 'color: #65738a;')
        self.status_label.setToolTip(storage + f'\n메모리에서 제외 {self.manager.evicted_count}개 · 파일 대기열 누락 {status["dropped"]}개')
        self._update_filter_badge()

    @staticmethod
    def _fingerprint(entry):
        return (entry.event, entry.category, entry.level, entry.trace_id, entry.message,
                repr(entry.data), entry.session_id, entry.process_id, entry.thread)

    def _make_row(self, entries):
        entry = entries[0]
        row = QTreeWidgetItem([self._row_text(entries)])
        row.setData(0, Qt.ItemDataRole.UserRole, tuple(entries))
        row.setData(0, Qt.ItemDataRole.UserRole + 1, 'record')
        row.setToolTip(0, row.text(0) + '\n' + entry.event)
        color = QColor('#be3030') if entry.level in ('ERROR', 'CRITICAL') else QColor('#956000') if entry.level == 'WARNING' else None
        if color:
            row.setForeground(0, color)
        row.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        for represented in entries:
            self._entry_items[id(represented)] = row
        return row

    def _row_text(self, entries):
        entry = entries[0]
        text = format_readable_event(entry, self._presentation(entry), raw=self.current_topic() == '원본')
        return text + (f' · 동일 반복 {len(entries)}건' if len(entries) > 1 else '')

    def _append_row(self, entry):
        if self.fold_repeats.isChecked() and entry.level in ('DEBUG', 'INFO') and self.output.topLevelItemCount():
            previous = self.output.topLevelItem(self.output.topLevelItemCount() - 1)
            entries = previous.data(0, Qt.ItemDataRole.UserRole) or ()
            if (entries and entries[-1] is self._previous_source_entry
                    and self._fingerprint(entries[-1]) == self._fingerprint(entry)):
                entries = (*entries, entry)
                previous.setData(0, Qt.ItemDataRole.UserRole, entries)
                previous.setText(0, self._row_text(entries))
                previous.setToolTip(0, previous.text(0) + '\n' + entry.event)
                self._entry_items[id(entry)] = previous
                if previous.isExpanded():
                    self._populate_expansion(previous)
                return
        self.output.addTopLevelItem(self._make_row((entry,)))

    def _friendly_details(self, entry):
        presentation = self._presentation(entry)
        heading = f'{entry.timestamp:%Y-%m-%d %H:%M:%S}  {presentation.domain} · {presentation.action}'
        sections = [heading, presentation.summary]
        if presentation.sections:
            first = {'문장', '입력 원문', '발화 준비 문장', '프롬프트 전문', '전송 본문',
                     'HTTP 응답 전문', '응답 전문', '모델 응답 원문', '최종 대사', '감정 상태 전문'}
            ordered = sorted(presentation.sections, key=lambda section: 0 if section[0] in first else 2 if section[0] == '기록 설명' else 1)
            for label, text in ordered:
                sections.append(label + '\n' + text)
        else:
            sections.append('원문\n' + entry.message)
        metadata = f'이벤트: {entry.event}\n수준: {entry.level}\n추적 ID: {entry.trace_id or "없음"}\n프로세스: {entry.process_id}\n스레드: {entry.thread}\n세션: {entry.session_id}'
        sections.append('기록 정보\n' + metadata)
        return '\n\n'.join(sections)

    def _expand_item(self, item):
        if item.data(0, Qt.ItemDataRole.UserRole + 1) == 'record':
            self._populate_expansion(item)

    def _populate_expansion(self, row):
        selected = self.output.currentItem()
        selected_entry = self._selected_entry() if selected and selected.parent() is row else None
        self.output.blockSignals(True)
        for index in range(row.childCount()):
            child = row.child(index)
            self.output.removeItemWidget(child, 0)
        for child in row.takeChildren():
            del child
        entries = row.data(0, Qt.ItemDataRole.UserRole) or ()
        if len(entries) > 1:
            for entry in entries:
                child = QTreeWidgetItem([format_readable_event(entry, self._presentation(entry),
                                         raw=self.current_topic() == '원본', milliseconds=True)])
                child.setToolTip(0, child.text(0))
                child.setData(0, Qt.ItemDataRole.UserRole, (entry,))
                child.setData(0, Qt.ItemDataRole.UserRole + 1, 'repeat')
                row.addChild(child)
                if entry is selected_entry:
                    self.output.setCurrentItem(child)
        else:
            child = QTreeWidgetItem()
            child.setData(0, Qt.ItemDataRole.UserRole, entries)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, 'detail')
            row.addChild(child)
            child.setFirstColumnSpanned(True)
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setFont(self.font())
            editor.setPlainText(self._friendly_details(entries[0]))
            editor.setMinimumHeight(120)
            editor.setMaximumHeight(220)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.output.setItemWidget(child, 0, editor)
            if selected_entry is not None:
                self.output.setCurrentItem(child)
        self.output.blockSignals(False)
        if selected_entry is not None:
            self.show_entry_details()

    def _selected_entry(self):
        row = self.output.currentItem()
        if row is None and self.output.topLevelItemCount():
            row = self.output.topLevelItem(0)
        entries = row.data(0, Qt.ItemDataRole.UserRole) if row else ()
        return entries[0] if entries else None

    def show_entry_details(self, *_args):
        entry = self._selected_entry()
        self.content_details.setPlainText(self._friendly_details(entry) if entry else '')
        self.details.setPlainText(entry.details() if entry else '')
        self.trace_button.setEnabled(bool(entry and entry.trace_id))

    def show_trace(self):
        entry = self._selected_entry()
        if entry is None or not entry.trace_id:
            return
        self._saved_topics['전체'] = '통합'
        self.tabs.setCurrentIndex(0)
        self.subtabs.setCurrentIndex(0)
        self.level_filter.setCurrentIndex(0)
        self.search_input.setText(entry.trace_id)

    def on_entry_added(self, entry):
        if self.is_paused:
            self._update_status()
            return
        with self.manager._lock:
            retained = id(entry) in self.manager._entry_ids
            sequence = self.manager._entry_sequences.get(id(entry), -1)
        if not retained or id(entry) in self._entry_items:
            return
        if sequence != self._last_source_sequence + 1:
            if not self._refresh_pending:
                self._refresh_pending = True
                QTimer.singleShot(0, self._refresh_retained)
            return
        if self.manager.evicted_count != self._last_evicted_count:
            self._trim_evicted()
        if self.matches_filters(entry):
            self._visible_entries.append(entry)
            self._append_row(entry)
            if self.output.currentItem() is None:
                self.output.setCurrentItem(self.output.topLevelItem(0))
            if self.auto_scroll.isChecked():
                self.output.scrollToBottom()
        self._previous_source_entry = entry
        self._last_source_sequence = sequence
        self._update_status()

    def _trim_evicted(self):
        with self.manager._lock:
            retained = set(self.manager._entry_ids)
            self._last_evicted_count = self.manager.evicted_count
        removed = []
        while self._visible_entries and id(self._visible_entries[0]) not in retained:
            removed.append(self._visible_entries.pop(0))
        affected = {}
        for entry in removed:
            row = self._entry_items.pop(id(entry), None)
            if row is not None:
                affected[id(row)] = row
        for row in affected.values():
            remaining = tuple(entry for entry in row.data(0, Qt.ItemDataRole.UserRole) if id(entry) in retained)
            if not remaining:
                self.output.takeTopLevelItem(self.output.indexOfTopLevelItem(row))
                continue
            row.setData(0, Qt.ItemDataRole.UserRole, remaining)
            first = remaining[0]
            row.setText(0, self._row_text(remaining))
            row.setToolTip(0, row.text(0) + '\n' + first.event)
            if row.isExpanded():
                self._populate_expansion(row)
        self._presentations = {key: value for key, value in self._presentations.items() if key in retained}
        if removed:
            self.show_entry_details()

    def _refresh_retained(self):
        self._refresh_pending = False
        self.refresh()

    def refresh(self, *_args):
        if self.is_paused:
            self._update_status()
            return
        selected = self._selected_entry()
        scroll_position = self.output.verticalScrollBar().value()
        with self.manager._lock:
            entries = list(self.manager._entries)
            self._last_source_sequence = self.manager._entry_sequences.get(id(entries[-1]), -1) if entries else self.manager._next_sequence - 1
            self._last_evicted_count = self.manager.evicted_count
        retained = {id(entry) for entry in entries}
        self._presentations = {key: value for key, value in self._presentations.items() if key in retained}
        self._visible_entries = []
        self.output.setUpdatesEnabled(False)
        self.output.blockSignals(True)
        self.output.clear()
        self._entry_items.clear()
        self._previous_source_entry = None
        for entry in entries:
            if self.matches_filters(entry):
                self._visible_entries.append(entry)
                self._append_row(entry)
            self._previous_source_entry = entry
        selected_item = self._entry_items.get(id(selected)) if selected else None
        if selected_item is not None:
            self.output.setCurrentItem(selected_item)
        elif self.output.topLevelItemCount():
            self.output.setCurrentItem(self.output.topLevelItem(0))
        self.output.blockSignals(False)
        self.output.setUpdatesEnabled(True)
        self.show_entry_details()
        if self.auto_scroll.isChecked():
            self.output.scrollToBottom()
        else:
            self.output.verticalScrollBar().setValue(scroll_position)
        self._update_status()

    def _on_logs_cleared(self):
        self._visible_entries.clear()
        self._entry_items.clear()
        self._presentations.clear()
        self._last_evicted_count = 0
        self._previous_source_entry = None
        with self.manager._lock:
            self._last_source_sequence = self.manager._next_sequence - 1
        self.output.clear()
        self.content_details.clear()
        self.details.clear()
        self.trace_button.setEnabled(False)
        self._update_status()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.pause_button.setText('재개' if self.is_paused else '일시정지')
        if not self.is_paused:
            self.refresh()
        else:
            self._update_status()

    def copy_logs(self, *, selected_only=False):
        selected = self.output.selectedItems() if selected_only else []
        if selected:
            entries = []
            seen = set()
            for row in selected:
                for entry in row.data(0, Qt.ItemDataRole.UserRole) or ():
                    if id(entry) not in seen:
                        entries.append(entry)
                        seen.add(id(entry))
        else:
            entries = list(self._visible_entries)
        lines = []
        for entry in entries:
            lines.append(format_readable_event(entry, self._presentation(entry), raw=self.current_topic() == '원본'))
        QApplication.clipboard().setText('\n'.join(lines))

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def shutdown(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            self.hide()
            event.ignore()
