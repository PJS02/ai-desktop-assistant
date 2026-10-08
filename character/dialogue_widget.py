# 캐릭터 대화 말풍선 UI
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QApplication, QLineEdit, QPushButton, QHBoxLayout, QTextBrowser, QFrame
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont, QFontMetrics
from PyQt6.QtCore import QTimer, Qt, QSize, QRect, QRectF, pyqtSignal, QPoint
from pathlib import Path
from .dialogue_styles import normalize_dialogue_style
from .overlay_geometry import place_above_character


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
        self.font = QFont('맑은 고딕', 11)
        self.text_view = QTextBrowser(self)
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_view.setOpenExternalLinks(False)
        self.text_view.setFont(self.font)
        self.text_view.setPlainText(self.text)
        self.text_view.document().setDocumentMargin(0)
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self._auto_close)
        self.hover_timer = QTimer(self)  # Compatibility with existing clients.
        self.set_style(self.style)
        if duration > 0 and not preview:
            self.close_timer.start(duration)

    def set_style(self, style):
        self.style = normalize_dialogue_style(style, strict=True)
        rounded = self.style == 'rounded'
        subtitle = self.style == 'subtitle'
        self.bubble_color = QColor('#fffdf6' if rounded else '#32323c' if not subtitle else '#202936')
        self.text_color = QColor('#263448' if rounded else '#ffffff')
        self.border_color = QColor('#8ab4cc' if rounded else '#9696c8')
        self.border_width = 0 if subtitle else 2
        self.padding_x, self.padding_y = (14, 8) if subtitle else (16, 12)
        self.tail_height = 0 if subtitle else 12
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        radius = 20 if self.style == 'rounded' else 5 if self.style == 'subtitle' else 10
        path.addRoundedRect(QRectF(5, 5, self.bubble_width, self.bubble_height), radius, radius)
        if self.tail_height:
            center = self.bubble_width * .45 + 5
            half = self.bubble_width * .15 if self.style == 'legacy' else 10
            path.moveTo(center - half, self.bubble_height + 5)
            path.lineTo(center + half, self.bubble_height + 5)
            path.lineTo(center, self.bubble_height + self.tail_height + 5)
            path.closeSubpath()
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
    """대화 입력 창 - 사용자가 캐릭터와 대화할 수 있음"""
    
    text_submitted = pyqtSignal(str)  # 텍스트 입력됨
    
    def __init__(self, parent=None):
        """
        Args:
            parent: 부모 위젯
        """
        super().__init__(parent)
        
        # UI 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("AI 대화")
        
        # 레이아웃
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        # 입력 필드
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("캐릭터에게 말해보세요...")
        self.input_field.returnPressed.connect(self._on_send)
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a3a;
                color: #ffffff;
                border: 2px solid #6666cc;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
                font-family: '맑은 고딕';
            }
            QLineEdit:focus {
                border: 2px solid #9999ff;
            }
        """)
        
        # 전송 버튼
        self.send_button = QPushButton("전송")
        self.send_button.clicked.connect(self._on_send)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #4444aa;
                color: #ffffff;
                border: 1px solid #6666cc;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 11px;
                font-family: '맑은 고딕';
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5555bb;
            }
            QPushButton:pressed {
                background-color: #3333aa;
            }
        """)
        
        # 닫기 버튼
        self.close_button = QPushButton("✕")
        self.close_button.clicked.connect(self.close)
        self.close_button.setMaximumWidth(35)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: #aa4444;
                color: #ffffff;
                border: 1px solid #cc6666;
                border-radius: 5px;
                padding: 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #bb5555;
            }
        """)
        
        # 레이아웃 추가
        layout.addWidget(self.input_field)
        layout.addWidget(self.send_button)
        layout.addWidget(self.close_button)
        
        # 크기
        self.setFixedHeight(50)
        self.setMinimumWidth(400)
        
        # 포커스
        self.input_field.setFocus()
    
    def _on_send(self):
        """전송 버튼 클릭 또는 엔터 키"""
        text = self.input_field.text().strip()
        if text:
            self.text_submitted.emit(text)
            self.input_field.clear()
            self.input_field.setFocus()
    
    def set_position_below_character(self, character_x: int, character_y: int, character_width: int):
        """캐릭터 아래에 입력창 위치 지정"""
        x = character_x + character_width // 2 - self.width() // 2
        y = character_y + 450  # 캐릭터 높이가 400px이므로 아래에 배치
        
        # 화면 범위 체크
        try:
            screen_geometry = QApplication.primaryScreen().geometry()
        except:
            screen_geometry = QRect(0, 0, 1920, 1080)
        
        if x < 0:
            x = 0
        if x + self.width() > screen_geometry.width():
            x = screen_geometry.width() - self.width()
        if y + self.height() > screen_geometry.height():
            y = character_y - self.height() - 10  # 위에 배치
        
        self.move(x, y)
    
    def closeEvent(self, event):
        """종료 이벤트"""
        super().closeEvent(event)
