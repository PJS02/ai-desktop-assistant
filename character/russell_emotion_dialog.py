import math
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QToolTip
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics
from PyQt6.QtCore import Qt, QTimer, QPointF


class RussellEmotionCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.valence = 0.0
        self.arousal = 0.0
        self.dominant = "idle"
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)  # 마우스 추적 활성화

    def set_state(self, valence: float, arousal: float, dominant: str) -> None:
        self.valence = max(-1.0, min(1.0, float(valence)))
        self.arousal = max(-1.0, min(1.0, float(arousal)))
        self.dominant = dominant or "idle"
        self.update()

    def _dominant_color(self) -> QColor:
        color_map = {
            "happy": QColor(255, 196, 0),
            "sad": QColor(100, 150, 255),
            "angry": QColor(255, 80, 80),
            "fear": QColor(180, 80, 255),
            "bored": QColor(130, 130, 130),
            "anxiety": QColor(255, 150, 80),
            "idle": QColor(80, 200, 200),
        }
        return color_map.get(self.dominant, QColor(80, 200, 200))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(20, 20, -20, -20)
        radius = min(rect.width(), rect.height()) / 2
        center = QPointF(rect.center())

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRect(self.rect())

        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.drawLine(int(center.x() - radius), int(center.y()), int(center.x() + radius), int(center.y()))
        painter.drawLine(int(center.x()), int(center.y() - radius), int(center.x()), int(center.y() + radius))

        painter.setPen(QPen(QColor(0, 0, 0), 1))
        label_font = QFont("Malgun Gothic", 9)
        painter.setFont(label_font)
        metrics = QFontMetrics(label_font)

        def draw_label(text: str, x: float, y: float):
            w = metrics.horizontalAdvance(text)
            h = metrics.height()
            painter.drawText(int(x - w / 2), int(y + h / 2), text)

        draw_label("흥분 +", center.x(), center.y() - radius - 12)
        draw_label("조용 -", center.x(), center.y() + radius + 18)
        draw_label("불쾌 -", center.x() - radius - 22, center.y())
        draw_label("유쾌 +", center.x() + radius + 22, center.y())

        ring_labels = [
            ("초조한", 130),
            ("들뜬", 60),
            ("의기양양한", 30),
            ("행복한", 10),
            ("만족한", -10),
            ("고요한", -40),
            ("만족한", -65),
            ("힘든", -130),
            ("우울한", -150),
            ("슬픈", -170),
            ("괴로운", 160),
            ("속상한", 145),
        ]

        for text, angle_deg in ring_labels:
            angle_rad = angle_deg * math.pi / 180.0
            r = radius + 16
            x = center.x() + r * math.cos(angle_rad)
            y = center.y() - r * math.sin(angle_rad)
            draw_label(text, x, y)

        draw_label("중립", center.x(), center.y())

        point_x = center.x() + self.valence * radius
        point_y = center.y() - self.arousal * radius
        point_color = self._dominant_color()

        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(point_color)
        painter.drawEllipse(QPointF(point_x, point_y), 6, 6)

        painter.end()

    def mouseMoveEvent(self, event):
        """마우스 이동 시 점 위에 있으면 툴팁 표시"""
        rect = self.rect().adjusted(20, 20, -20, -20)
        radius = min(rect.width(), rect.height()) / 2
        center = QPointF(rect.center())
        
        # 점의 화면 좌표
        point_x = center.x() + self.valence * radius
        point_y = center.y() - self.arousal * radius
        
        # 마우스와 점 사이의 거리
        mouse_pos = event.pos()
        distance = math.sqrt((mouse_pos.x() - point_x)**2 + (mouse_pos.y() - point_y)**2)
        
        # 점(반경 6픽셀) 근처면 (15픽셀 이내) 툴팁 표시
        if distance <= 15:
            tooltip_text = (
                f"호가도(Valence): {self.valence:+.3f}\n"
                f"각성도(Arousal): {self.arousal:+.3f}\n"
                f"감정: {self.dominant}"
            )
            global_pos = event.globalPosition().toPoint()
            QToolTip.showText(global_pos, tooltip_text, self)
        else:
            QToolTip.hideText()
        
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        """마우스가 위젯을 떠날 때 툴팁 숨김"""
        QToolTip.hideText()
        super().leaveEvent(event)


class RussellEmotionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Russell 감정 상태")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._state_provider = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_from_provider)

        self.title_label = QLabel("Russell 감정 상태")
        title_font = QFont("Malgun Gothic", 11)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("호가도: 0.00 | 각성도: 0.00 | 감정: idle")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 설명 라벨 추가
        description_font = QFont("Malgun Gothic", 9)
        description_font.setItalic(True)
        
        self.description_label = QLabel(
            "호가도(Valence): -1(부정적 왼쪽)  +1(긍정적 오른쪽)\n"
            "각성도(Arousal): -1(진정 아래)   +1(흥분 위)"
        )
        self.description_label.setFont(description_font)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_color = QColor(100, 100, 100)
        self.description_label.setStyleSheet(f"color: rgb({description_color.red()}, {description_color.green()}, {description_color.blue()});")

        self.canvas = RussellEmotionCanvas(self)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.description_label)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setFixedSize(420, 560)

    def set_state_provider(self, provider):
        self._state_provider = provider

    def update_state(self, valence: float, arousal: float, dominant: str) -> None:
        self.canvas.set_state(valence, arousal, dominant)
        self.value_label.setText(
            f"호가도: {valence:+.2f} | 각성도: {arousal:+.2f} | 감정: {dominant}"
        )

    def _refresh_from_provider(self):
        if self._state_provider is None:
            return
        try:
            valence, arousal, dominant = self._state_provider()
        except Exception:
            return
        self.update_state(valence, arousal, dominant)

    def start_auto_refresh(self, interval_ms: int = 250) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(interval_ms)

    def stop_auto_refresh(self) -> None:
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()

    def closeEvent(self, event):
        self.stop_auto_refresh()
        super().closeEvent(event)

    def showEvent(self, event):
        print("[RussellEmotionDialog] showEvent")
        super().showEvent(event)
