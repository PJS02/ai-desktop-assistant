"""Today's Gemini calls made by this app."""
from PyQt6.QtCore import QDateTime, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ai.gemini_usage import PACIFIC_TIME, daily_usage, quota_day


class GeminiUsageView(QFrame):
    def __init__(self, saved_settings, models, parent=None):
        super().__init__(parent)
        self._saved_settings = saved_settings
        self._models = models
        self._displayed = None
        self.setObjectName('geminiUsagePanel')
        self.setStyleSheet('''
            QFrame#geminiUsagePanel {
                background: white; border: 1px solid #dce2ea; border-radius: 6px;
            }
            QLabel#usageMeta { color: #536277; font-size: 12px; }
            QLabel#usageTotal { color: #174b91; font-size: 22px; font-weight: 600; }
            QLabel#usageReset { color: #202936; font-size: 14px; font-weight: 600; }
            QTableWidget { background: white; color: #202936; border: none; }
            QTableWidget::item { border-bottom: 1px solid #eef2f7; padding: 0 4px; }
            QHeaderView::section {
                background: white; color: #536277; font-size: 12px;
                border: none; border-bottom: 1px solid #dce2ea; padding: 0 4px;
            }
        ''')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._content = QFrame()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)
        layout.addWidget(self._content)

        summary = QHBoxLayout()
        summary.setContentsMargins(8, 0, 8, 0)
        summary.setSpacing(12)
        total = QVBoxLayout()
        total.setSpacing(2)
        total.addWidget(QLabel('오늘 전체 호출 · 저장된 API 키 기준', objectName='usageMeta'))
        self._total = QLabel(objectName='usageTotal')
        total.addWidget(self._total)
        summary.addLayout(total, 1)

        reset = QVBoxLayout()
        reset.setAlignment(Qt.AlignmentFlag.AlignTop)
        reset.setSpacing(2)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        reset_title = QLabel('다음 초기화 (기기 시간)', objectName='usageMeta', alignment=right)
        self._reset = QLabel(objectName='usageReset', alignment=right)
        reset.addWidget(reset_title)
        reset.addWidget(self._reset)
        summary.addLayout(reset)
        content.addLayout(summary)

        self._table = QTableWidget(0, 5, accessibleName='모델별 오늘 호출량')
        self._table.setHorizontalHeaderLabels(['모델', '호출', '한도 사용 추정', '실패', '한도 초과'])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setWordWrap(False)
        self._table.setShowGrid(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self._table.horizontalHeader()
        header.setFixedHeight(34)
        header.setSectionsClickable(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(right)
        self._table.horizontalHeaderItem(0).setTextAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        limit_header = self._table.horizontalHeaderItem(4)
        limit_description = '실패 건수 중 API 한도에 걸린 횟수'
        limit_header.setToolTip(limit_description)
        limit_header.setData(Qt.ItemDataRole.AccessibleDescriptionRole, limit_description)
        self._table.verticalHeader().setDefaultSectionSize(36)
        self._table.verticalHeader().hide()
        content.addWidget(self._table)

        hint = QLabel('기능 추가 후 이 앱에서 기록된 호출과 재시도를 집계합니다.\n'
                      '한도 사용량 추정에는 정상 HTTP 응답과 400·500 오류가 포함됩니다.',
                      objectName='usageMeta')
        hint.setContentsMargins(8, 0, 8, 0)
        hint.setWordWrap(True)
        content.addWidget(hint)

        self._status = QLabel()
        self._status.setContentsMargins(8, 0, 8, 0)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self):
        ai = self._saved_settings()
        day = quota_day(QDateTime.currentDateTimeUtc())
        reset = day.addDays(1).startOfDay(PACIFIC_TIME).toLocalTime().toString('M월 d일 HH:mm')
        usage = daily_usage(ai.get('api_key', ''), day)
        if usage is None:
            self._show_rows('호출 기록을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.', [])
            return
        if not ai.get('api_key'):
            self._show_rows('API 키를 저장하면 모델별 호출량을 볼 수 있습니다.', [])
            return
        models = dict.fromkeys((*self._models, ai.get('model'), ai.get('automatic_model'), *sorted(usage)))
        rows = [(model, usage.get(model, (0, 0, 0, 0))) for model in models if model]
        self._show_rows('', rows, reset)

    def _show_rows(self, status, rows, reset=''):
        if (status, rows, reset) == self._displayed:
            return
        self._displayed = status, rows, reset
        self._status.setText(status)
        self._status.setVisible(bool(status))
        self._content.setVisible(not status)
        if status:
            return

        self._total.setText(f'{sum(counts[0] for _, counts in rows):,}회')
        self._reset.setText(reset)
        self._table.setRowCount(len(rows))
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for row, (model, counts) in enumerate(rows):
            name = QTableWidgetItem(model)
            name.setToolTip(model)
            self._table.setItem(row, 0, name)
            for column, count in enumerate(counts, start=1):
                cell = QTableWidgetItem(f'{count:,}')
                cell.setTextAlignment(right)
                self._table.setItem(row, column, cell)
        self._table.setFixedHeight(
            self._table.horizontalHeader().height() + self._table.verticalHeader().length())
