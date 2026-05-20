# 캐릭터 대화 말풍선 UI
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QApplication, QLineEdit, QPushButton, QHBoxLayout
from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QFont, QFontMetrics
from PyQt6.QtCore import QTimer, Qt, QSize, QRect, QRectF, pyqtSignal, QPoint
from pathlib import Path


class DialogueBubble(QWidget):
    """캐릭터 대화 말풍선 위젯"""
    
    dialogue_closed = pyqtSignal()  # 말풍선이 닫힐 때 신호
    
    def __init__(self, text: str, duration: int = 5000, parent=None):
        """
        Args:
            text: 표시할 대화 텍스트
            duration: 표시 지속 시간 (밀리초) - 0이면 자동 종료 안함
            parent: 부모 위젯
        """
        super().__init__(parent)
        
        self.text = text
        self.duration = duration
        self.is_hovering = False
        
        # UI 설정
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 색상 및 스타일
        self.bubble_color = QColor(50, 50, 60)  # 어두운 회색
        self.text_color = QColor(255, 255, 255)  # 흰색
        self.border_color = QColor(150, 150, 200)  # 밝은 파란색
        self.border_width = 2
        
        # 글꼴
        self.font = QFont("맑은 고딕", 11)
        self.font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.setFont(self.font)
        
        # 패딩
        self.padding_x = 16
        self.padding_y = 12
        self.tail_height = 12  # 꼬리 높이
        
        # 텍스트 크기 계산
        self._calculate_size()
        
        # 타이머 (자동 종료용)
        self.close_timer = QTimer()
        self.close_timer.timeout.connect(self._auto_close)
        if self.duration > 0:
            self.close_timer.start(self.duration)
        
        # 마우스 호버 타이머 (자동 종료 연기용)
        self.hover_timer = QTimer()
        self.hover_timer.timeout.connect(self._check_hover)
        self.hover_timer.start(100)
    
    def _calculate_size(self):
        """텍스트 크기를 기반으로 말풍선 크기 계산"""
        metrics = QFontMetrics(self.font)
        
        # 텍스트 높이 (개행 처리)
        text_lines = self.text.split('\n')
        line_height = metrics.height()
        
        # 최대 텍스트 너비 계산 (줄 바꿈 대비)
        max_width = max(metrics.horizontalAdvance(line) for line in text_lines)
        text_height = line_height * len(text_lines)
        
        # 최대 너비 제한 (화면 너비의 30%)
        try:
            screen = QApplication.primaryScreen()
            screen_width = screen.geometry().width()
        except:
            screen_width = 1920  # 기본값
        
        max_text_width = int(screen_width * 0.3)
        
        if max_width > max_text_width:
            # 텍스트 줄 바꿈 필요
            # 간단히 최대 너비로 설정
            max_width = max_text_width
            # 실제 줄 수 재계산 (근사)
            estimated_lines = max(len(text_lines), (len(self.text) * metrics.averageCharWidth()) // max_text_width)
            text_height = line_height * estimated_lines
        
        # 말풍선 전체 크기
        self.bubble_width = max_width + self.padding_x * 2
        self.bubble_height = text_height + self.padding_y * 2
        self.bubble_width = max(self.bubble_width, 100)  # 최소 너비
        self.bubble_height = max(self.bubble_height, 50)  # 최소 높이
        
        # 전체 위젯 크기 (꼬리 포함)
        total_width = self.bubble_width + 10
        total_height = self.bubble_height + self.tail_height + 10
        
        self.setFixedSize(total_width, total_height)
    
    def paintEvent(self, event):
        """말풍선 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 말풍선 경로 (둥근 모서리)
        bubble_rect = QRectF(
            5, 5,
            self.bubble_width,
            self.bubble_height
        )
        
        path = QPainterPath()
        corner_radius = 10
        path.addRoundedRect(bubble_rect, corner_radius, corner_radius)
        
        # 꼬리 (아래쪽 삼각형)
        tail_left = self.bubble_width * 0.3 + 5
        tail_right = self.bubble_width * 0.6 + 5
        tail_bottom = self.bubble_height + self.tail_height + 5
        
        path.moveTo(tail_left, self.bubble_height + 5)
        path.lineTo(tail_right, self.bubble_height + 5)
        path.lineTo((tail_left + tail_right) / 2, tail_bottom)
        path.closeSubpath()
        
        # 배경 채우기
        painter.fillPath(path, self.bubble_color)
        
        # 테두리 그리기
        pen = painter.pen()
        pen.setColor(self.border_color)
        pen.setWidth(self.border_width)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # 텍스트 그리기
        text_rect = QRect(
            5 + self.padding_x,
            5 + self.padding_y,
            self.bubble_width - self.padding_x * 2,
            self.bubble_height - self.padding_y * 2
        )
        
        painter.setPen(self.text_color)
        painter.setFont(self.font)
        painter.drawText(text_rect, Qt.TextFlag.TextWordWrap, self.text)
        
        painter.end()
    
    def mousePressEvent(self, event):
        """마우스 클릭으로 말풍선 종료"""
        self.close()
    
    def mouseDoubleClickEvent(self, event):
        """더블 클릭도 반응"""
        self.close()
    
    def enterEvent(self, event):
        """마우스 진입 - 자동 종료 연기"""
        self.is_hovering = True
        self.close_timer.stop()
    
    def leaveEvent(self, event):
        """마우스 이탈 - 자동 종료 재개"""
        self.is_hovering = False
        if self.duration > 0:
            self.close_timer.start(self.duration)
    
    def _check_hover(self):
        """호버 상태 확인"""
        # 호버 타이머는 단순히 상태 유지용
        pass
    
    def _auto_close(self):
        """자동 종료"""
        if not self.is_hovering:
            self.close()
    
    def closeEvent(self, event):
        """종료 이벤트"""
        self.close_timer.stop()
        self.hover_timer.stop()
        self.dialogue_closed.emit()
        super().closeEvent(event)
    
    def set_position_below_character(self, character_x: int, character_y: int, character_width: int):
        """캐릭터 바로 위에 말풍선 위치 지정"""
        # 캐릭터 중앙 상단에 배치
        x = character_x + character_width // 2 - self.width() // 2
        y = character_y - self.height() - 10
        
        # 화면 범위 체크
        try:
            screen_geometry = QApplication.primaryScreen().geometry()
        except:
            # 기본 화면 크기
            screen_geometry = QRect(0, 0, 1920, 1080)
        
        if x < 0:
            x = 0
        if x + self.width() > screen_geometry.width():
            x = screen_geometry.width() - self.width()
        if y < 0:
            y = character_y + 100  # 아래에 배치
        
        self.move(x, y)
    
    def update_position_with_character(self, character_x: int, character_y: int, character_width: int):
        """캐릭터 위치 변화에 따라 말풍선 위치 업데이트 (드래그 중 호출됨)"""
        self.set_position_below_character(character_x, character_y, character_width)


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
        self.close()
    
    def _auto_close(self):
        """자동 종료"""
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
