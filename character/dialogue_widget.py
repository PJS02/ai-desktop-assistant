# 캐릭터 대화 말풍선 UI
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QApplication, QLineEdit, QPushButton, QHBoxLayout, QTextBrowser, QFrame, QScrollArea, QSizePolicy
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont, QFontMetrics
from PyQt6.QtCore import QEvent, QSettings, QTimer, Qt, QSize, QRect, QRectF, pyqtSignal, QPoint
from pathlib import Path
from .dialogue_styles import normalize_dialogue_style
from .overlay_geometry import place_above_character, place_near_ankles


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
    """Independent user speech with a round body and a right-facing tail: 0>."""
    TAIL_WIDTH = 14

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
        self.setFixedSize(self.bubble_width + 10 + self.TAIL_WIDTH, self.bubble_height + 10)

    def _bubble_path(self):
        body = QRectF(5, 5, self.bubble_width, self.bubble_height)
        radius = min(14, self.bubble_height / 2)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        tail = QPainterPath()
        center = body.center().y()
        tail.moveTo(body.right() - 2, center - 8)
        tail.lineTo(body.right() + self.TAIL_WIDTH, center)
        tail.lineTo(body.right() - 2, center + 8)
        tail.closeSubpath()
        return path.united(tail)

    def set_position_below_character(self, character_x, character_y, character_width,
                                     character_height=100, avoid=None):
        self._anchor = (character_x, character_y, character_width, character_height, avoid)
        anchor = QRect(character_x, character_y, character_width, character_height)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        bounds = screen.geometry() if screen else QRect(0, 0, 1280, 720)
        self._calculate_size(bounds)
        self.move(place_near_ankles(anchor, self.size(), bounds, avoid))


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


class DialogueInputWidget(QWidget):
    """Scrollable chat with a saved desktop position."""

    text_submitted = pyqtSignal(str)
    POSITION_KEY = 'chat/position'

    def __init__(self, parent=None, *, settings=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else QSettings('PJS02', 'AIDesktopAssistant')
        self._drag_offset = None
        self._follow_latest = True
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('채팅하기')
        self.resize(376, 448)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
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
        self.title_bar.installEventFilter(self)
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
            QLabel[chatRole] { background: #ffffff; border: 1px solid #cbd3dc;
                               border-radius: 8px; padding: 7px 10px; }
            QLabel[chatRole="user"] { background: #e9f1fa; }
            QLineEdit, QPushButton { border: 1px solid #c2cedb; border-radius: 6px; }
            QLineEdit { background: #ffffff; padding: 0 9px; }
            QPushButton { background: #e9f1fa; color: #274965; font-weight: bold; }
            QPushButton#chatClose { background: #f1f4f8; color: #515e6a; }
            QPushButton:hover, QPushButton#chatClose:hover { background: #dfe7f0; }
            QPushButton:pressed, QPushButton#chatClose:pressed { background: #cbd7e5; }
            QLineEdit:focus, QPushButton:focus { border-color: #4d6b89; }
        """)

    def append_message(self, role, text):
        scrollbar = self.history.verticalScrollBar()
        self._follow_latest = scrollbar.value() == scrollbar.maximum()
        self._empty.hide()
        bubble = QLabel(self.history.widget())
        bubble.setProperty('chatRole', role)
        bubble.setAccessibleName('나' if role == 'user' else '캐릭터')
        bubble.setTextFormat(Qt.TextFormat.PlainText)
        bubble.setText(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._fit_bubble(bubble)
        side = Qt.AlignmentFlag.AlignRight if role == 'user' else Qt.AlignmentFlag.AlignLeft
        self._messages.insertWidget(self._messages.count() - 1, bubble, alignment=side)

    def _fit_bubble(self, bubble):
        bubble.ensurePolished()
        text_width = max(bubble.fontMetrics().horizontalAdvance(line) for line in bubble.text().split('\n'))
        width = min(text_width + 28, int(self.width() * .74))
        bubble.setFixedWidth(width)
        bubble.setFixedHeight(bubble.heightForWidth(width))

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
        self.resize(min(376, bounds.width()), min(448, bounds.height()))
        for index in range(1, self._messages.count() - 1):
            self._fit_bubble(self._messages.itemAt(index).widget())
        position = saved if screen else bounds.bottomRight() - QPoint(self.width() + 15, self.height() + 15)
        self._move_inside(position, bounds)

    def _move_inside(self, position, bounds):
        self.move(max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(position.y(), bounds.bottom() - self.height() + 1)))

    def eventFilter(self, watched, event):
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
