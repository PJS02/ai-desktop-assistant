"""Read-only views opened from the character's action menu."""
from datetime import datetime
from html import escape

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsScene, QGraphicsView, QGridLayout,
    QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from .memory_view import MemoryView
from .mood_system import OCC_EMOTION_NAMES
from .overlay_geometry import place_beside_character
from .russell_emotion_dialog import RussellEmotionCanvas, RussellEmotionDialog
from .floating_panels import configure_floating_panel


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
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowCloseButtonHint)
        configure_floating_panel(self)
        self._character = character
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
            QProgressBar#occGauge {
                background: #edf3f9; border: 1px solid #cddbec; border-radius: 4px;
                text-align: center; min-height: 16px; font-size: 12px;
            }
            QProgressBar#occGauge::chunk { background: #a9cbee; border-radius: 3px; }
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
        character = self._character
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
        self.occ_gauges = {}
        for index, (key, name) in enumerate(OCC_EMOTION_NAMES.items()):
            row, column = divmod(index, 2)
            gauge = QProgressBar(objectName='occGauge', accessibleName=f'{name} 강도')
            gauge.setRange(0, 10_000)
            gauge.setValue(0)
            components.addWidget(QLabel(name), row + 1, column * 2)
            components.addWidget(gauge, row + 1, column * 2 + 1)
            components.setColumnStretch(column * 2 + 1, 1)
            self.occ_gauges[key] = gauge
        left.addWidget(occ_panel)

        right.addWidget(QLabel('감정 변화 로그', objectName='statusHeading'))
        log_header = QLabel('캐릭터 위 감정 팝업과 러셀 목표 좌표 변화량',
                            objectName='statusMeta', wordWrap=True)
        right.addWidget(log_header)
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
            gauge = self.occ_gauges[component['name']]
            strength = component['value']
            gauge.setValue(round(strength * gauge.maximum()))
            gauge.setFormat(f'{strength:.2%}')
        popups = tuple(self.overlay.history)[:self.HISTORY_LIMIT]
        if popups == self._displayed:
            return
        self._displayed = popups
        scroll = self.log.verticalScrollBar()
        position, maximum = scroll.value(), scroll.maximum()
        self.log.setHtml(self._log_html(popups))
        if position > 0:
            scroll.setValue(position + scroll.maximum() - maximum)

    @staticmethod
    def _log_html(popups):
        if not popups:
            return '<p style="color: #516278;">아직 표시된 감정 팝업이 없어요.</p>'

        def delta_cell(delta):
            if delta is None:
                text, color = '—', '#516278'
            elif delta:
                sign = '+' if delta > 0 else '-'
                magnitude = f'{abs(delta):.4f}' if abs(delta) >= 0.0001 else '&lt;0.0001'
                text, color = sign + magnitude, '#185182' if delta > 0 else '#9a433c'
            else:
                text, color = '0', '#516278'
            return f'<td align="right"><span style="color: {color};">{text}</span></td>'

        rows = ['<tr bgcolor="#f2f6fb"><td width="52%"><b>팝업 기록</b></td>'
                '<td width="23%" align="right">각성도</td><td width="25%" align="right">쾌·불쾌</td></tr>']
        popup_text_colors = {'#a6f284': '#2f6e27', '#ff797d': '#a83a3f', '#8fc8ff': '#255c8d'}
        for popup in popups:
            timestamp = datetime.fromtimestamp(popup.timestamp)
            color = popup_text_colors.get(popup.color, '#263645')
            label = escape(f'{popup.cause} · {popup.change}')
            rows.append(f'<tr><td><b style="color: {color};">{label}</b><br>'
                        f'<span style="color: #516278; font-size: 11px;">{timestamp:%H:%M:%S}</span></td>'
                        f'{delta_cell(popup.arousal)}{delta_cell(popup.valence)}</tr>')
        return f'<table width="100%" cellspacing="0" cellpadding="5">{"".join(rows)}</table>'


class MemoryStatusWindow(CharacterStatusWindow):
    def __init__(self, character):
        super().__init__(character, '기억 표시', layout_width=330, layout_height=226)
        self.resize(414, 430)
        self.content.addWidget(QLabel('저장된 장기기억', objectName='statusHeading'))
        self.view = MemoryView(character.dialogue_system.long_term_memory, compact=True)
        self.content.addWidget(self.view)
