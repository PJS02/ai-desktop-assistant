# 캐릭터 대화 말풍선 UI
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QApplication, QLineEdit, QPushButton, QHBoxLayout, QTextBrowser, QFrame, QScrollArea, QSizePolicy
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont, QFontMetrics, QIcon, QTextOption
from PyQt6.QtCore import QEvent, QLocale, QSettings, QTimer, Qt, QSize, QRect, QRectF, pyqtSignal, QPoint
from math import ceil
from pathlib import Path
from .dialogue_styles import normalize_dialogue_style
from .overlay_geometry import place_above_character, place_beside_character


class DialogueBubble(QWidget):
    """One text/lifetime implementation with three selectable paint styles."""
    dialogue_closed = pyqtSignal()

    def __init__(self, text: str, duration: int = 5000, parent=None,
                 style='legacy', preview=False):
        super().__init__(parent)
        self.text = str(text)
        self.duration = duration
        self.preview = preview
        self.style = normalize_dialogue_style(style)
        self.is_hovering = False
        self._anchor = None
        self._closed = False
        if not preview:
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint
                                | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.font = QFont('Malgun Gothic', 11)
        self.text_view = QTextBrowser(self)
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_view.setOpenExternalLinks(False)
        self.text_view.setPlainText(self.text)
        self.text_view.document().setDocumentMargin(0)
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self._auto_close)
        self.hover_timer = QTimer(self)  # Compatibility with existing clients.
        self.set_style(self.style)
        if duration > 0 and not preview:
            self.close_timer.start(duration)

    def set_text(self, text: str):
        if text == self.text:
            return
        self.text = text
        self.text_view.setPlainText(text)
        if self._anchor is None:
            self._calculate_size()
        else:
            self.set_position_below_character(*self._anchor)
        self.update()

    def set_style(self, style):
        self.style = normalize_dialogue_style(style, strict=True)
        subtitle = self.style == 'subtitle'
        self.bubble_color = QColor('#202936' if subtitle else '#ffffff')
        self.text_color = QColor('#ffffff' if subtitle else '#263645')
        self.border_color = QColor('#c2cedb')
        self.border_width = 0 if subtitle else 1
        self.padding_x, self.padding_y = 14, 8
        self.tail_height = 0 if subtitle else 10
        if subtitle:
            self.font.setPointSize(11)
        else:
            self.font.setPixelSize(14)
        self.text_view.setFont(self.font)
        self.text_view.setStyleSheet(
            'QTextBrowser { background: transparent; color: ' + self.text_color.name()
            + '; border: none; } QScrollBar:vertical { width: 7px; }')
        self._calculate_size()
        if self._anchor is not None:
            self.set_position_below_character(*self._anchor)
        self.update()

    def _calculate_size(self, bounds=None):
        if bounds is None:
            screen = QApplication.primaryScreen()
            bounds = screen.geometry() if screen else QRect(0, 0, 1280, 720)
        metrics = QFontMetrics(self.font)
        max_width = min(520, max(140, int(bounds.width() * .38)))
        if self.preview:
            max_width = min(max_width, 360)
        max_width = min(max_width, max(60, bounds.width() - 20))
        widest = max((metrics.horizontalAdvance(line) for line in self.text.splitlines()), default=60)
        text_width = min(max_width - self.padding_x * 2, max(65, widest))
        self.text_view.document().setTextWidth(text_width)
        text_height = int(self.text_view.document().size().height() + .999)
        max_height = max(40, int(bounds.height() * .4) - self.padding_y * 2 - self.tail_height - 10)
        self.bubble_width = text_width + self.padding_x * 2
        self.bubble_height = min(text_height, max_height) + self.padding_y * 2
        self.setFixedSize(self.bubble_width + 10, self.bubble_height + self.tail_height + 10)
        self.text_view.setGeometry(5 + self.padding_x, 5 + self.padding_y,
                                   text_width, min(text_height, max_height))

    def _bubble_path(self):
        path = QPainterPath()
        radius = 20 if self.style == 'rounded' else 5 if self.style == 'subtitle' else 8
        path.addRoundedRect(QRectF(5, 5, self.bubble_width, self.bubble_height), radius, radius)
        if not self.tail_height:
            return path
        center = self.bubble_width * .45 + 5
        half = 10 if self.style == 'rounded' else 9
        tail = QPainterPath()
        tail.moveTo(center - half, self.bubble_height + 4)
        tail.lineTo(center + half, self.bubble_height + 4)
        tail.lineTo(center, self.bubble_height + self.tail_height + 5)
        tail.closeSubpath()
        return path.united(tail)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._bubble_path()
        painter.fillPath(path, self.bubble_color)
        if self.border_width:
            pen = painter.pen()
            pen.setColor(self.border_color)
            pen.setWidth(self.border_width)
            painter.setPen(pen)
            painter.drawPath(path)

    def enterEvent(self, event):
        self.is_hovering = True
        self._remaining = self.close_timer.remainingTime()
        self.close_timer.stop()

    def leaveEvent(self, event):
        self.is_hovering = False
        if self.duration > 0 and not self.preview:
            self.close_timer.start(max(1, getattr(self, '_remaining', self.duration)))

    def _auto_close(self):
        if not self.is_hovering:
            self._log_close_reason = 'duration_elapsed'
            self.close()

    def closeEvent(self, event):
        self.close_timer.stop()
        self.hover_timer.stop()
        if not self._closed:
            self._closed = True
            self.dialogue_closed.emit()
        super().closeEvent(event)

    def set_position_below_character(self, character_x, character_y, character_width,
                                     character_height=100, avoid=None):
        # Kept under the old method name for compatibility; prefer above the body.
        self._anchor = (character_x, character_y, character_width, character_height, avoid)
        anchor = QRect(character_x, character_y, character_width, character_height)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        bounds = screen.geometry() if screen else QRect(0, 0, 1280, 720)
        self._calculate_size(bounds)
        self.move(place_above_character(anchor, self.size(), bounds, avoid))

    def update_position_with_character(self, *args, **kwargs):
        self.set_position_below_character(*args, **kwargs)


class UserDialogueBubble(DialogueBubble):
    """Independent user speech with a rounded body and no speaker tail."""

    def set_style(self, style):
        super().set_style('rounded')
        self.bubble_color = QColor('#f4f7fb')
        self.border_color = QColor('#cbd3dc')

    def _calculate_size(self, bounds=None):
        self.tail_height = 0
        super()._calculate_size(bounds)
        height_limit = max(70, min(160, self._anchor[3] // 2)) if self._anchor else 160
        self.bubble_height = min(self.bubble_height, height_limit - 10)
        self.text_view.resize(self.text_view.width(), self.bubble_height - self.padding_y * 2)
        self.setFixedSize(self.bubble_width + 10, self.bubble_height + 10)

    def _bubble_path(self):
        body = QRectF(5, 5, self.bubble_width, self.bubble_height)
        radius = min(14, self.bubble_height / 2)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        return path

    def set_position_below_character(self, character_x, character_y, character_width,
                                     character_height=100, avoid=None):
        self._anchor = (character_x, character_y, character_width, character_height, avoid)
        anchor = QRect(character_x, character_y, character_width, character_height)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        bounds = screen.geometry() if screen else QRect(0, 0, 1280, 720)
        self._calculate_size(bounds)
        self.move(place_beside_character(anchor, self.size(), bounds, avoid))
        self.text_view.move(5 + self.padding_x, 5 + self.padding_y)
        self.update()


class DialogueNarrationBox(QWidget):
    """내레이션 박스 - 화면 하단에 표시되는 대사"""
    
    closed = pyqtSignal()
    
    def __init__(self, text: str, character_name: str = "어시스턴트", duration: int = 0, parent=None):
        """
        Args:
            text: 표시할 대사
            character_name: 캐릭터 이름
            duration: 표시 지속 시간 (0이면 자동 종료 안함)
            parent: 부모 위젯
        """
        super().__init__(parent)
        
        self.text = text
        self.character_name = character_name
        self.duration = duration
        
        # UI 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 스타일
        self.bg_color = QColor(30, 30, 40)
        self.text_color = QColor(230, 230, 240)
        self.name_color = QColor(100, 180, 255)
        self.border_color = QColor(100, 150, 200)
        
        # 글꼴
        self.name_font = QFont("맑은 고딕", 12, QFont.Weight.Bold)
        self.text_font = QFont("맑은 고딕", 11)
        
        # 패딩
        self.padding = 20
        
        # 크기 계산
        self._calculate_size()
        
        # 화면 하단에 배치
        self._position_at_bottom()
        
        # 타이머
        self.close_timer = QTimer()
        self.close_timer.timeout.connect(self._auto_close)
        if self.duration > 0:
            self.close_timer.start(self.duration)
    
    def _calculate_size(self):
        """크기 계산"""
        try:
            screen = QApplication.primaryScreen().geometry()
        except:
            # 기본 화면 크기
            screen = QRect(0, 0, 1920, 1080)
        
        # 너비: 화면의 60%
        width = int(screen.width() * 0.6)
        height = 100
        
        self.setFixedSize(width, height)
    
    def _position_at_bottom(self):
        """화면 하단 중앙에 배치"""
        try:
            screen = QApplication.primaryScreen().geometry()
        except:
            # 기본 화면 크기
            screen = QRect(0, 0, 1920, 1080)
        
        x = (screen.width() - self.width()) // 2
        y = screen.height() - self.height() - 50  # 하단에서 50px 위
        
        self.move(x, y)
    
    def paintEvent(self, event):
        """상자 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 배경
        rect = self.rect()
        painter.fillRect(rect, self.bg_color)
        
        # 테두리
        pen = painter.pen()
        pen.setColor(self.border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(0, 0, rect.width() - 1, rect.height() - 1)
        
        # 캐릭터 이름
        name_rect = QRect(
            self.padding, self.padding // 2,
            rect.width() - self.padding * 2, 25
        )
        painter.setPen(self.name_color)
        painter.setFont(self.name_font)
        painter.drawText(name_rect, Qt.TextFlag.AlignLeft | Qt.TextFlag.AlignTop,
                        f"[{self.character_name}]")
        
        # 대사
        text_rect = QRect(
            self.padding, self.padding + 20,
            rect.width() - self.padding * 2, rect.height() - self.padding * 2 - 20
        )
        painter.setPen(self.text_color)
        painter.setFont(self.text_font)
        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap | Qt.TextFlag.AlignLeft,
                        self.text)
        
        painter.end()
    
    def mousePressEvent(self, event):
        """클릭으로 종료"""
        self._log_close_reason = 'user_click'
        self.close()
    
    def _auto_close(self):
        """자동 종료"""
        self._log_close_reason = 'duration_elapsed'
        self.close()
    
    def closeEvent(self, event):
        """종료"""
        self.close_timer.stop()
        self.closed.emit()
        super().closeEvent(event)


class _ChatMessageRow(QWidget):
    def __init__(self, message, retry_icon, speaker_icon):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        role = message['role']
        self.bubble = QTextBrowser()
        self.bubble.setProperty('chatRole', role)
        self.bubble.setAccessibleName('나' if role == 'user' else '캐릭터')
        self.bubble.setPlainText(message['text'])
        self.bubble.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.bubble.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bubble.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bubble.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bubble.document().setDocumentMargin(8)
        time = message['displayed_at'].time()
        self.timestamp = QLabel(QLocale(QLocale.Language.Korean).toString(time, 'AP h:mm'))
        self.timestamp.setObjectName('chatTime')

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        self._line = QHBoxLayout()
        self._line.setContentsMargins(0, 0, 0, 0)
        self._line.setSpacing(5)
        outer.addLayout(self._line)
        bottom = Qt.AlignmentFlag.AlignBottom
        self.retry_button = self.cancel_button = self.cancelled_label = None
        self.speaker_button = None
        self.automatic_note = None
        if role == 'user':
            self.retry_button = QPushButton()
            self.retry_button.setObjectName('chatRetry')
            self.retry_button.setIcon(retry_icon)
            self.retry_button.setIconSize(QSize(15, 15))
            self.retry_button.setFixedSize(24, 24)
            self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.retry_button.setAccessibleName('실패한 메시지 다시 보내기')
            self.retry_button.setToolTip('다시 보내기')
            self.cancel_button = QPushButton('전송 취소')
            self.cancel_button.setObjectName('chatCancel')
            self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cancelled_label = QLabel('전송 취소됨')
            self.cancelled_label.setObjectName('chatNote')
            self._line.addStretch()
            self._line.addWidget(self.timestamp, alignment=bottom)
            for control in (self.retry_button, self.cancel_button, self.cancelled_label):
                self._line.addWidget(control, alignment=bottom)
            self._line.addWidget(self.bubble)
            self.set_delivery_state(message.get('state'))
        else:
            self._line.addWidget(self.bubble)
            if message.get('state') != 'failed':
                self.speaker_button = QPushButton()
                self.speaker_button.setObjectName('chatSpeaker')
                self.speaker_button.setIcon(speaker_icon)
                self.speaker_button.setIconSize(QSize(15, 15))
                self.speaker_button.setFixedSize(24, 24)
                self.speaker_button.setCursor(Qt.CursorShape.PointingHandCursor)
                self.speaker_button.setAccessibleName('이 답변 음성으로 읽기')
                self.speaker_button.setToolTip('음성으로 읽기')
                self._line.addWidget(self.speaker_button, alignment=bottom)
            self._line.addWidget(self.timestamp, alignment=bottom)
            self._line.addStretch()
            if message.get('source') == 'automatic':
                self.automatic_note = QLabel('  자동대화', self.bubble)
                self.automatic_note.setObjectName('chatAutomaticNote')
                self.automatic_note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_delivery_state(self, state):
        self.retry_button.setVisible(state == 'failed')
        self.cancel_button.setVisible(state == 'queued')
        self.cancelled_label.setVisible(state == 'cancelled')

    def fit(self, available_width):
        bubble = self.bubble
        bubble.ensurePolished()
        document = bubble.document()
        metrics = bubble.fontMetrics()
        text_width = max(metrics.horizontalAdvance(line) for line in bubble.toPlainText().split('\n'))
        note = self.automatic_note
        if note is not None:
            note.adjustSize()
            text_width = max(text_width, note.width())
        spacing = self._line.spacing()
        reserved = self.timestamp.sizeHint().width() + spacing
        for control in (self.retry_button, self.cancel_button, self.cancelled_label, self.speaker_button):
            if control is not None and not control.isHidden():
                size = control.sizeHint().expandedTo(control.minimumSize()).boundedTo(control.maximumSize())
                reserved += size.width() + spacing
        border = 2 * bubble.frameWidth()
        margin = ceil(document.documentMargin())
        preferred = text_width + 2 * margin + border + 2
        width = max(1, min(ceil(preferred), int(available_width * .78), available_width - reserved))
        bubble.setFixedWidth(width)
        document.setTextWidth(max(1, width - border))
        body_height = ceil(document.size().height())
        height = body_height + border
        if note is not None:
            gap = 2
            note.move(bubble.frameWidth() + margin, bubble.frameWidth() + body_height - margin + gap)
            height += note.height() + gap
        bubble.setFixedHeight(height)


class DialogueInputWidget(QWidget):
    """Scrollable chat with a saved desktop position and size."""

    text_submitted = pyqtSignal(str)
    retry_requested = pyqtSignal(int)
    cancel_requested = pyqtSignal(int)
    speech_requested = pyqtSignal(str)
    POSITION_KEY = 'chat/position'
    SIZE_KEY = 'chat/size'
    RESIZE_MARGIN = 8
    RESIZE_CURSORS = {
        Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
        Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
        Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
        Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, parent=None, *, settings=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else QSettings('PJS02', 'AIDesktopAssistant')
        self._drag_offset = None
        self._follow_latest = True
        self._turns = {}
        icons = Path(__file__).resolve().parent.parent / 'assets/ui'
        self._retry_icon = QIcon(str(icons / 'chat_retry.svg'))
        self._speaker_icon = QIcon(str(icons / 'chat_speaker.svg'))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('채팅하기')
        self.setMinimumSize(300, 250)
        saved_size = self._settings.value(self.SIZE_KEY)
        self.resize(saved_size if isinstance(saved_size, QSize) and not saved_size.isEmpty()
                    else QSize(376, 448))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        self._panel = panel
        panel.setObjectName('chatPanel')
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_bar = QLabel('채팅하기')
        self.title_bar.setObjectName('chatTitle')
        self.title_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.title_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        self.close_button = QPushButton('×')
        self.close_button.setObjectName('chatClose')
        self.close_button.setAccessibleName('채팅창 닫기')
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.title_bar, 1)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.history = QScrollArea(panel)
        self.history.setObjectName('chatHistory')
        self.history.setFrameShape(QFrame.Shape.NoFrame)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.setWidgetResizable(True)
        self.history.setAccessibleName('채팅 내역')
        messages = QWidget()
        messages.setObjectName('chatMessages')
        self._messages = QVBoxLayout(messages)
        self._messages.setContentsMargins(10, 10, 10, 10)
        self._messages.setSpacing(8)
        self._empty = QLabel('메시지를 보내거나 음성으로 말을 걸어보세요.')
        self._empty.setObjectName('chatEmpty')
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._messages.addWidget(self._empty, 1)
        self._messages.addStretch()
        self.history.setWidget(messages)
        self.history.verticalScrollBar().rangeChanged.connect(self._scroll_to_latest)
        layout.addWidget(self.history, 1)

        composer = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText('메시지 입력')
        self.input_field.setAccessibleName('채팅 메시지')
        self.input_field.returnPressed.connect(self._on_send)
        self.send_button = QPushButton('전송')
        self.send_button.clicked.connect(self._on_send)
        self.send_button.setFixedWidth(58)
        for control in (self.input_field, self.send_button):
            control.setFixedHeight(34)
            composer.addWidget(control)
        layout.addLayout(composer)

        self.setStyleSheet("""
            QWidget { color: #263645; font-family: 'Malgun Gothic'; font-size: 13px; }
            QFrame#chatPanel { background: #ffffff; border: 1px solid #c2cedb; border-radius: 9px; }
            QLabel#chatTitle { font-size: 16px; font-weight: bold; padding-left: 2px; }
            QScrollArea#chatHistory, QWidget#chatMessages { background: #f4f7fb; border-radius: 6px; }
            QLabel#chatEmpty { color: #515e6a; padding: 8px; }
            QTextBrowser[chatRole] { background: #ffffff; border: 1px solid #cbd3dc;
                                     border-radius: 8px; }
            QTextBrowser[chatRole="user"] { background: #e9f1fa; }
            QLabel#chatTime, QLabel#chatNote { color: #586677; font-size: 11px; }
            QLabel#chatAutomaticNote { color: rgba(73, 77, 84, 200); font-size: 6pt; background: transparent; }
            QLineEdit, QPushButton { border: 1px solid #c2cedb; border-radius: 6px; }
            QLineEdit { background: #ffffff; padding: 0 9px; }
            QPushButton { background: #e9f1fa; color: #274965; font-weight: bold; }
            QPushButton#chatClose { background: #f1f4f8; color: #515e6a; }
            QPushButton#chatCancel { padding: 2px 4px; font-size: 10px; font-weight: normal; }
            QPushButton:hover, QPushButton#chatClose:hover { background: #dfe7f0; }
            QPushButton:pressed, QPushButton#chatClose:pressed { background: #cbd7e5; }
            QLineEdit:focus, QPushButton:focus { border-color: #4d6b89; }
        """)
        panel.setMouseTracking(True)
        panel.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._viewport = self.history.viewport()
        panel.installEventFilter(self)
        self._viewport.installEventFilter(self)
        self.title_bar.installEventFilter(self)

    def append_message(self, message):
        scrollbar = self.history.verticalScrollBar()
        self._follow_latest = scrollbar.value() == scrollbar.maximum()
        self._empty.hide()
        chat_id = message['chat_id']
        turn = self._turns.get(chat_id)
        width = self._message_width()
        if turn is None:
            turn = QVBoxLayout()
            turn.setSpacing(5)
            self._turns[chat_id] = turn
            self._messages.insertLayout(self._messages.count() - 1, turn)
        else:
            self.set_message_state(chat_id, message['state'])
            if message['role'] == 'user':
                if turn.count() > 1:
                    failed_reply = turn.takeAt(1).widget()
                    failed_reply.hide()
                    failed_reply.deleteLater()
                return

        row = _ChatMessageRow(message, self._retry_icon, self._speaker_icon)
        if row.retry_button is not None:
            row.retry_button.clicked.connect(lambda: self.retry_requested.emit(chat_id))
            row.cancel_button.clicked.connect(lambda: self.cancel_requested.emit(chat_id))
        if row.speaker_button is not None:
            row.speaker_button.clicked.connect(lambda: self.speech_requested.emit(message['text']))
        turn.addWidget(row)
        row.fit(width)

    def set_message_state(self, chat_id, state):
        row = self._turns[chat_id].itemAt(0).widget()
        row.set_delivery_state(state)
        row.fit(self._message_width())

    def _message_width(self):
        margins = self._messages.contentsMargins()
        return self._viewport.width() - margins.left() - margins.right()

    def _scroll_to_latest(self):
        if self._follow_latest:
            scrollbar = self.history.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_send(self):
        text = self.input_field.text().strip()
        if text:
            self.input_field.clear()
            self.text_submitted.emit(text)
            self.input_field.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        saved = self._settings.value(self.POSITION_KEY)
        screen = QApplication.screenAt(saved) if isinstance(saved, QPoint) else None
        bounds = (screen or QApplication.primaryScreen()).availableGeometry()
        self.resize(self.size().boundedTo(bounds.size()))
        position = saved if screen else bounds.bottomRight() - QPoint(self.width() + 15, self.height() + 15)
        self._move_inside(position, bounds)

    def closeEvent(self, event):
        self._settings.setValue(self.POSITION_KEY, self.pos())
        self._settings.setValue(self.SIZE_KEY, self.size())
        self._settings.sync()
        super().closeEvent(event)

    def _move_inside(self, position, bounds):
        self.move(max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(position.y(), bounds.bottom() - self.height() + 1)))

    def _resize_edges(self, position):
        edges = Qt.Edge(0)
        margin = self.RESIZE_MARGIN
        if position.x() < margin:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if position.y() < margin:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if watched is self._viewport and event.type() == QEvent.Type.Resize:
            width = self._message_width()
            for turn in self._turns.values():
                for index in range(turn.count()):
                    turn.itemAt(index).widget().fit(width)
        if watched is self._panel:
            if event.type() == QEvent.Type.HoverMove:
                edges = self._resize_edges(event.position().toPoint())
                if edges:
                    watched.setCursor(self.RESIZE_CURSORS[edges])
                else:
                    watched.unsetCursor()
            elif event.type() == QEvent.Type.HoverLeave:
                watched.unsetCursor()
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self._resize_edges(event.position().toPoint())
                if edges and self.windowHandle().startSystemResize(edges):
                    return True
        if watched is self.title_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if (event.type() == QEvent.Type.MouseMove and self._drag_offset is not None
                    and event.buttons() & Qt.MouseButton.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if (event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                    and self._drag_offset is not None):
                self._drag_offset = None
                screen = QApplication.screenAt(event.globalPosition().toPoint()) or QApplication.primaryScreen()
                self._move_inside(self.pos(), screen.availableGeometry())
                self._settings.setValue(self.POSITION_KEY, self.pos())
                self._settings.sync()
                return True
        return super().eventFilter(watched, event)
