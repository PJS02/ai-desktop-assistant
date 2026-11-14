"""Read-only views opened from the character's action menu."""
from datetime import datetime
from html import escape

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsScene, QGraphicsView, QGridLayout,
    QHBoxLayout, QLabel, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from .memory_view import MemoryView
from .mood_system import OCC_EMOTION_NAMES
from .overlay_geometry import place_beside_character
from .russell_emotion_dialog import RussellEmotionCanvas, RussellEmotionDialog


class _StatusContentView(QGraphicsView):
    """Keep the layout in logical pixels and scale both axes together."""

    def __init__(self, content, layout_width, layout_height, parent):
        super().__init__(parent)
        self._layout_width = layout_width
        self._layout_height = layout_height
        self.setScene(QGraphicsScene(self))
        self._content = self.scene().addWidget(content)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width, height = self.viewport().width(), self.viewport().height()
        if not width or not height:
            return
        scale = min(1.0, width / self._layout_width, height / self._layout_height)
        self._content.resize(width / scale, height / scale)
        self.setSceneRect(self._content.geometry())
        self.resetTransform()
        self.scale(scale, scale)


class CharacterStatusWindow(QDialog):
    def __init__(self, character, title, *, layout_width, layout_height):
        super().__init__(character, Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(title)
        self.setMinimumSize(round(layout_width * .55), round(layout_height * .55))
        self._panel = QWidget(objectName='characterStatusContent')
        self._panel.setStyleSheet('''
            QWidget#characterStatusContent { background: #ffffff; }
            QWidget { color: #263645; font-family: 'Malgun Gothic'; font-size: 13px; }
            QLabel#statusHeading { font-size: 16px; font-weight: 700; }
            QLabel#statusMeta { color: #516278; font-size: 12px; }
            QLabel#statusValue { color: #203a54; font-size: 19px; font-weight: 700; }
            QWidget#occStrength QLabel { color: #245885; font-weight: 700; }
            QFrame#statusSummary { background: #f2f6fb; border-radius: 7px; }
            QTextBrowser {
                background: white; border: 1px solid #d6e0ea; border-radius: 7px;
            }
            QScrollBar:vertical { width: 8px; background: #f4f7fb; }
            QScrollBar::handle:vertical {
                min-height: 28px; background: #bfccdb; border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            QPushButton {
                padding: 4px 9px; border: 1px solid #c2cedb; border-radius: 5px;
                background: #e9f1fa;
            }
            QPushButton:hover { background: #dfe7f0; }
            QPushButton:focus { border-color: #4d6b89; }
            QPushButton:disabled { background: #f4f7fb; color: #647387; }
        ''')
        self.content = QVBoxLayout(self._panel)
        self.content.setContentsMargins(16, 14, 16, 14)
        self.content.setSpacing(10)
        self._graphics = _StatusContentView(self._panel, layout_width, layout_height, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._graphics)
        self._panel.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._panel.show()

    def hideEvent(self, event):
        self._panel.hide()
        super().hideEvent(event)

    def open_beside_character(self, avoid=None):
        character = self.parentWidget()
        if not self.isVisible():
            body = character._physics_body_rect().translated(character.pos())
            screen = QApplication.screenAt(body.center()) or character.screen()
            if screen is not None:
                bounds = screen.availableGeometry().adjusted(8, 8, -8, -8)
                self.resize(self.size().boundedTo(bounds.size()))
                other = avoid.frameGeometry() if avoid is not None and avoid.isVisible() else None
                self.move(place_beside_character(body, self.frameSize(), bounds, other))
        self.showNormal()
        self.raise_()
        self.activateWindow()


class EmotionStatusWindow(CharacterStatusWindow):
    HISTORY_LIMIT = 30

    def __init__(self, character):
        super().__init__(character, '감정 표시', layout_width=760, layout_height=500)
        self.mood = character.mood_system
        self.overlay = character.emotion_delta_overlay
        self.resize(974, 626)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.content.addLayout(columns)
        left = QVBoxLayout()
        left.setSpacing(8)
        columns.addLayout(left, 5)
        right = QVBoxLayout()
        right.setSpacing(8)
        columns.addLayout(right, 5)

        left.addWidget(QLabel('러셀 원형 모델', objectName='statusHeading'))
        summary = QFrame(objectName='statusSummary')
        metrics = QGridLayout(summary)
        metrics.setContentsMargins(12, 8, 12, 9)
        metrics.setVerticalSpacing(2)
        self.values = []
        for column, title in enumerate(('현재 감정', '쾌·불쾌', '각성도')):
            label = QLabel(title, objectName='statusMeta')
            value = QLabel(objectName='statusValue', accessibleName=title)
            metrics.addWidget(label, 0, column)
            metrics.addWidget(value, 1, column)
            metrics.setColumnStretch(column, 1)
            self.values.append(value)
        left.addWidget(summary)

        self.canvas = RussellEmotionCanvas(interactive=False)
        self.canvas.setMinimumSize(350, 230)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setAccessibleName('러셀 원형 모델')
        left.addWidget(self.canvas, 1)
        occ_panel = QWidget(objectName='occStrength')
        components = QGridLayout(occ_panel)
        components.setContentsMargins(0, 0, 0, 0)
        components.setHorizontalSpacing(12)
        components.setVerticalSpacing(5)
        components.addWidget(QLabel('현재 OCC 성분 강도', objectName='statusHeading'), 0, 0, 1, 4)
        self.occ_values = {}
        for index, (key, name) in enumerate(OCC_EMOTION_NAMES.items()):
            row, column = divmod(index, 2)
            value = QLabel(accessibleName=name, alignment=Qt.AlignmentFlag.AlignRight)
            components.addWidget(QLabel(name), row + 1, column * 2)
            components.addWidget(value, row + 1, column * 2 + 1)
            components.setColumnStretch(column * 2 + 1, 1)
            self.occ_values[key] = value
        left.addWidget(occ_panel)

        right.addWidget(QLabel('감정 변화 로그', objectName='statusHeading'))
        self.log_header = QLabel(objectName='statusMeta', wordWrap=True)
        self.log_header.setToolTip('같은 입력에서 OCC 팝업이 여러 개 뜨면 러셀 변화량은 각 행에 동일하게 표시됩니다.')
        right.addWidget(self.log_header)
        self.log = QTextBrowser(accessibleName='감정 변화 로그')
        self.log.document().setDocumentMargin(10)
        right.addWidget(self.log, 1)
        self._displayed = None
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self):
        state = self.mood.get_emotion_explanation(limit=12)
        valence, arousal, emotion = state['valence'], state['arousal'], state['emotion']
        self.canvas.set_state(valence, arousal, emotion, immediate=True)
        self.canvas.set_history(state['coordinate_history'])
        name = RussellEmotionDialog.EMOTION_NAMES.get(emotion, emotion)
        for label, value in zip(self.values, (name, f'{valence:+.3f}', f'{arousal:+.3f}')):
            label.setText(value)
        for component in state['occ_components']:
            self.occ_values[component['name']].setText(f"{component['value']:.2%}")
        events = tuple(self.overlay.history)[:self.HISTORY_LIMIT]
        displayed = (self.overlay.enabled, events)
        if displayed == self._displayed:
            return
        self._displayed = displayed
        self.log_header.setText('팝업에 포함된 입력이 러셀 현재 좌표에 반영된 양' if self.overlay.enabled
                                else '감정 팝업 표시가 꺼져 있어 새 기록이 추가되지 않아요.')
        scroll = self.log.verticalScrollBar()
        position, maximum = scroll.value(), scroll.maximum()
        self.log.setHtml(self._log_html(events))
        if position > 0:
            scroll.setValue(position + scroll.maximum() - maximum)

    @staticmethod
    def _log_html(events):
        if not events:
            return '<p style="color: #516278;">아직 표시된 감정 팝업이 없어요.</p>'

        def delta_cell(delta):
            if delta is None:
                text, color = '—', '#516278'
            elif delta:
                sign = '+' if delta > 0 else '−'
                magnitude = f'{abs(delta):.4f}' if abs(delta) >= 0.0001 else '&lt;0.0001'
                text, color = sign + magnitude, '#185182' if delta > 0 else '#9a433c'
            else:
                text, color = '0', '#516278'
            return f'<td align="right"><span style="color: {color};">{text}</span></td>'

        rows = ['<tr bgcolor="#f2f6fb"><td width="52%"><b>팝업 기록</b></td>'
                '<td width="23%" align="right">각성도</td><td width="25%" align="right">쾌·불쾌</td></tr>']
        popup_text_colors = {'#a6f284': '#2f6e27', '#ff797d': '#a83a3f', '#8fc8ff': '#255c8d'}
        for event in events:
            timestamp = datetime.fromtimestamp(event.timestamp)
            color = popup_text_colors.get(event.color, '#263645')
            rows.append(f'<tr><td><b style="color: {color};">{escape(event.cause)} · {escape(event.change)}</b><br>'
                        f'<span style="color: #516278; font-size: 11px;">{timestamp:%H:%M:%S}</span></td>'
                        f'{delta_cell(event.arousal)}{delta_cell(event.valence)}</tr>')
        return f'<table width="100%" cellspacing="0" cellpadding="5">{"".join(rows)}</table>'


class MemoryStatusWindow(CharacterStatusWindow):
    def __init__(self, character):
        super().__init__(character, '기억 표시', layout_width=330, layout_height=226)
        self.resize(414, 430)
        self.content.addWidget(QLabel('저장된 장기기억', objectName='statusHeading'))
        self.view = MemoryView(character.dialogue_system.long_term_memory, compact=True)
        self.content.addWidget(self.view)
