"""Paged views of the running character's long-term memory store."""
from html import escape
import sqlite3
import threading

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from app_logging import log_event


class MemoryView(QWidget):
    PAGE_SIZE = 100
    page_ready = pyqtSignal(object)

    def __init__(self, memory, parent=None, *, compact=False):
        super().__init__(parent)
        self.memory = memory
        self._compact = compact
        self._rows = []
        self._offset = 0
        self._loading = False
        layout = QVBoxLayout(self)
        margins = 0 if compact else 22
        layout.setContentsMargins(margins, margins, margins, margins)
        if not compact:
            hint = QLabel('저장된 장기기억을 최신순으로 표시합니다. 행을 선택하면 기억 내용과 최초 원문을 확인할 수 있습니다.')
            hint.setWordWrap(True)
            layout.addWidget(hint)
        navigation = QHBoxLayout()
        self.status = QLabel('탭을 열면 저장된 기억을 불러옵니다.', objectName='statusMeta')
        self.status.setWordWrap(True)
        navigation.addWidget(self.status, 1)
        self.refresh_button = QPushButton('새로고침')
        self.previous_button = QPushButton('이전')
        self.next_button = QPushButton('다음')
        for button in (self.refresh_button, self.previous_button, self.next_button):
            button.setAutoDefault(False)
            navigation.addWidget(button)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.refresh_button.clicked.connect(lambda _checked=False: self.refresh())
        self.previous_button.clicked.connect(lambda _checked=False: self.refresh(self._offset - self.PAGE_SIZE))
        self.next_button.clicked.connect(lambda _checked=False: self.refresh(self._offset + self.PAGE_SIZE))
        layout.addLayout(navigation)
        self.page_ready.connect(self._display_page, Qt.ConnectionType.QueuedConnection)
        if compact:
            self.previous_button.hide()
            self.next_button.hide()
            self.contents = QTextBrowser(accessibleName='저장된 장기기억')
            self.contents.document().setDocumentMargin(12)
            layout.addWidget(self.contents, 1)
            return

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['기억 내용', '중요도', '저장 시각 (UTC)'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 160)
        self.table.itemSelectionChanged.connect(self._show_details)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('기억을 선택하면 상세 내용을 표시합니다.')
        layout.addWidget(self.details, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.delete_button = QPushButton('선택 항목 삭제', objectName='deleteMemoryButton')
        self.delete_button.setAutoDefault(False)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self, offset=0):
        self._request_page(offset)

    def _request_page(self, offset, *, delete_id=None):
        if self._loading:
            return
        if self.memory is None:
            self.status.setText('장기기억 저장소에 연결되지 않았습니다.')
            self.refresh_button.setEnabled(False)
            return
        self._loading = True
        self.status.setText('기억을 삭제하는 중…' if delete_id is not None else '기억을 불러오는 중…')
        for button in (self.refresh_button, self.previous_button, self.next_button):
            button.setEnabled(False)
        if not self._compact:
            self.delete_button.setEnabled(False)
        threading.Thread(target=self._load_page, args=(offset, delete_id),
                         daemon=True, name='memory-view-loader').start()

    def _load_page(self, offset, delete_id):
        rows, total, error = [], 0, None
        feedback = None
        if delete_id is not None:
            try:
                deleted = self.memory.delete(delete_id)
                feedback = '선택한 기억을 삭제했습니다.' if deleted else '이미 삭제된 기억입니다.'
            except (sqlite3.Error, OSError, ValueError) as exc:
                feedback = '기억을 삭제하지 못했습니다. 다시 시도해 주세요.'
                log_event('settings.memory.delete_failed', '장기기억 삭제에 실패했습니다.',
                          category='오류', level='ERROR', memory_id=delete_id, error=str(exc))
        try:
            total = self.memory.count()
            if offset >= total:
                offset = max(0, ((total - 1) // self.PAGE_SIZE) * self.PAGE_SIZE)
            rows = self.memory.list_memories(limit=self.PAGE_SIZE, offset=offset)
        except (sqlite3.Error, OSError, ValueError) as exc:
            error = '기억을 불러오지 못했습니다. 새로고침으로 다시 시도해 주세요.'
            log_event('settings.memory.load_failed', '장기기억 목록 조회에 실패했습니다.',
                      category='오류', level='ERROR', error=str(exc))
        try:
            self.page_ready.emit((rows, total, offset, error, feedback))
        except RuntimeError:
            pass  # The settings dialog may have been deleted while the read was pending.

    @pyqtSlot(object)
    def _display_page(self, result):
        rows, total, offset, error, feedback = result
        selected_row = (max(0, self.table.currentRow())
                        if feedback and not self._compact and offset == self._offset else 0)
        self._loading = False
        self._offset = offset
        self._rows = rows
        self.refresh_button.setEnabled(True)
        self.previous_button.setEnabled(not error and offset > 0)
        self.next_button.setEnabled(not error and offset + len(rows) < total)
        summary = f'총 {total}개 · {offset + 1}–{offset + len(rows)}번째' if rows else '저장된 장기기억이 없습니다.'
        self.status.setText(f'{feedback}\n{error or summary}' if feedback else error or summary)
        if self._compact:
            has_pages = total > self.PAGE_SIZE
            self.previous_button.setVisible(has_pages)
            self.next_button.setVisible(has_pages)
            entries = []
            for memory in rows:
                state = ('대체된 기억' if memory['superseded_by'] is not None or memory.get('superseded_at')
                         else '망각된 기억' if memory['strength'] == 0 else '')
                source = '화면 관찰' if memory.get('screen_topic') is not None else ''
                label = ' · '.join(filter(None, (source, state)))
                text = escape(memory['text']).replace('\n', '<br>')
                label_html = f'<br><span style="color: #516278; font-size: 11px;">{label}</span>' if label else ''
                entries.append(
                    '<table width="100%" cellspacing="0" cellpadding="10" '
                    'style="border: 1px solid #d6e0ea; border-collapse: collapse;">'
                    f'<tr><td bgcolor="#f4f7fb">{text}{label_html}</td></tr></table>')
            self.contents.setHtml('<p style="font-size: 6px;">&nbsp;</p>'.join(entries))
            return

        self.table.setRowCount(0)
        self.details.clear()
        self.table.setRowCount(len(rows))
        for row, memory in enumerate(rows):
            values = (' '.join(memory['text'].split()),
                      str(memory['importance']) if memory['importance'] is not None else '미평가',
                      memory['created_at'][:19].replace('T', ' '))
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if rows:
            self.table.setCurrentCell(min(selected_row, len(rows) - 1), 0)
        self._show_details()

    def _selected_memory(self):
        rows = self.table.selectionModel().selectedRows(0)
        if rows:
            index = rows[0].row()
            if 0 <= index < len(self._rows):
                return self._rows[index]
        return None

    def _delete_selected(self):
        memory = self._selected_memory()
        if self._loading or memory is None:
            return
        preview = ' '.join(memory['text'].split())
        if len(preview) > 88:
            preview = preview[:87] + '…'
        confirm = QMessageBox(self)
        confirm.setWindowTitle('장기기억 삭제')
        confirm.setTextFormat(Qt.TextFormat.PlainText)
        confirm.setText(f'“{preview}” 항목을 삭제할까요?')
        confirm.setInformativeText('이 항목의 내용과 원문이 장기기억 저장소에서 삭제됩니다.')
        cancel_button = confirm.addButton('취소', QMessageBox.ButtonRole.RejectRole)
        delete_button = confirm.addButton('삭제', QMessageBox.ButtonRole.DestructiveRole)
        confirm.setDefaultButton(cancel_button)
        confirm.setEscapeButton(cancel_button)
        confirm.exec()
        if confirm.clickedButton() is delete_button:
            self._request_page(self._offset, delete_id=memory['id'])

    def _show_details(self):
        memory = self._selected_memory()
        self.delete_button.setEnabled(memory is not None and not self._loading)
        if memory is None:
            self.details.clear()
            return
        kind = {'profile': '프로필', 'temporary': '임시 정보', 'schedule': '일정',
                'event': '사건', 'unknown': '미분류'}.get(memory['memory_type'], memory['memory_type'])
        speaker = {'user': '사용자', 'assistant': '캐릭터', 'conversation': '혼합 대화',
                   'unknown': '미지정'}.get(memory['speaker'], memory['speaker'])
        origin = (f"마지막 관찰 시각 (UTC)\n{memory.get('screen_observed_at') or '미지정'}"
                  if memory.get('screen_topic') is not None
                  else f"최초 원문\n{memory['original_text'] or '별도 원문이 없는 기록입니다.'}")
        if memory.get('screen_topic') is not None:
            speaker = '화면 관찰'
        state = (f"기억 #{memory['superseded_by']}로 대체됨" if memory['superseded_by'] is not None
                 else '대체된 기록' if memory.get('superseded_at')
                 else '수동 망각됨' if memory['strength'] == 0 else '저장됨')
        retention = '지속 보존' if memory['retention_policy'] == 'persistent' else '일반'
        emotion = memory['emotional_intensity']
        self.details.setPlainText(
            f"기억 #{memory['id']} · {kind} · {speaker}\n"
            f"\n기억 내용\n{memory['text']}\n\n"
            f"{origin}\n\n"
            f"저장 시각 (UTC): {memory['created_at']}\n"
            f"감정 강도: {emotion if emotion is not None else '미평가'} · 회상 횟수: {memory['recall_count']}\n"
            f"마지막 회상 (UTC): {memory['last_recalled_at'] or '없음'}\n"
            f"보존 정책: {retention} · 상태: {state}")
