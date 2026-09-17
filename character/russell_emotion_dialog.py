import math
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QToolTip
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal


class RussellEmotionCanvas(QWidget):
    state_changed = pyqtSignal(float, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.valence_current = 0.0
        self.arousal_current = 0.0
        self.valence_target = 0.0
        self.arousal_target = 0.0
        self.dominant = "idle"
        self._dragging = False
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)  # 마우스 추적 활성화
        
        # 애니메이션 타이머 (매 16ms = 60fps)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._update_animation)
        self.animation_timer.start(16)
    
    def _update_animation(self) -> None:
        """부드러운 이동 애니메이션"""
        # 선형 보간 (lerp) - 속도: 0.15 (0-1 범위에서 스무스함)
        speed = 0.15
        
        if abs(self.valence_current - self.valence_target) > 0.01:
            self.valence_current += (self.valence_target - self.valence_current) * speed
        else:
            self.valence_current = self.valence_target
        
        if abs(self.arousal_current - self.arousal_target) > 0.01:
            self.arousal_current += (self.arousal_target - self.arousal_current) * speed
        else:
            self.arousal_current = self.arousal_target
        
        self.update()

    def set_state(self, valence: float, arousal: float, dominant: str, immediate: bool = False) -> None:
        valence = float(valence)
        arousal = float(arousal)
        distance = math.hypot(valence, arousal)
        if distance > 1.0:
            valence /= distance
            arousal /= distance

        self.valence_target = valence
        self.arousal_target = arousal
        self.dominant = dominant or "idle"
        if immediate:
            self.valence_current = self.valence_target
            self.arousal_current = self.arousal_target

    def _plot_geometry(self):
        rect = self.rect().adjusted(20, 20, -20, -20)
        radius = min(rect.width(), rect.height()) / 2
        center = QPointF(rect.center())
        return rect, radius, center

    def _emotion_from_coordinates(self, valence: float, arousal: float) -> str:
        emotion_points = {
            "joy": (0.80, 0.70),
            "delight": (0.70, 0.60),
            "excitement": (0.60, 0.80),
            "interest": (0.50, 0.60),
            "contentment": (0.70, 0.40),
            "anger": (-0.70, 0.80),
            "disgust": (-0.80, 0.70),
            "fear": (-0.60, 0.75),
            "anxiety": (-0.50, 0.65),
            "calm": (0.60, -0.50),
            "peaceful": (0.50, -0.60),
            "sadness": (-0.60, -0.50),
            "melancholy": (-0.50, -0.60),
            "despair": (-0.80, -0.40),
            "neutral": (0.00, 0.00),
        }

        closest_emotion = "neutral"
        min_distance = float("inf")
        for emotion_name, (target_valence, target_arousal) in emotion_points.items():
            distance = math.sqrt((valence - target_valence) ** 2 + (arousal - target_arousal) ** 2)
            if distance < min_distance:
                min_distance = distance
                closest_emotion = emotion_name
        return closest_emotion

    def _state_from_mouse_pos(self, pos: QPointF) -> tuple[float, float, str]:
        _, radius, center = self._plot_geometry()
        dx = pos.x() - center.x()
        dy = center.y() - pos.y()

        distance = math.sqrt(dx * dx + dy * dy)
        if distance > radius and distance > 0:
            scale = radius / distance
            dx *= scale
            dy *= scale

        valence = max(-1.0, min(1.0, dx / radius if radius > 0 else 0.0))
        arousal = max(-1.0, min(1.0, dy / radius if radius > 0 else 0.0))
        dominant = self._emotion_from_coordinates(valence, arousal)
        return valence, arousal, dominant

    def _apply_mouse_state(self, pos: QPointF) -> None:
        valence, arousal, dominant = self._state_from_mouse_pos(pos)
        self.set_state(valence, arousal, dominant, immediate=True)
        self.state_changed.emit(valence, arousal, dominant)
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

        rect, radius, center = self._plot_geometry()

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

        point_x = center.x() + self.valence_current * radius
        point_y = center.y() - self.arousal_current * radius
        point_color = self._dominant_color()

        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(point_color)
        painter.drawEllipse(QPointF(point_x, point_y), 6, 6)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._apply_mouse_state(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_mouse_state(event.position())
            event.accept()
            return

        """마우스 이동 시 점 위에 있으면 툴팁 표시"""
        _, radius, center = self._plot_geometry()
        
        # 점의 화면 좌표
        point_x = center.x() + self.valence_current * radius
        point_y = center.y() - self.arousal_current * radius
        
        # 마우스와 점 사이의 거리
        mouse_pos = event.pos()
        distance = math.sqrt((mouse_pos.x() - point_x)**2 + (mouse_pos.y() - point_y)**2)
        
        # 점(반경 6픽셀) 근처면 (15픽셀 이내) 툴팁 표시
        if distance <= 15:
            tooltip_text = (
                f"정서가(Valence): {self.valence_target:+.3f}\n"
                f"각성도(Arousal): {self.arousal_target:+.3f}\n"
                f"감정: {self.dominant}"
            )
            global_pos = event.globalPosition().toPoint()
            QToolTip.showText(global_pos, tooltip_text, self)
        else:
            QToolTip.hideText()
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        """마우스가 위젯을 떠날 때 툴팁 숨김"""
        QToolTip.hideText()
        super().leaveEvent(event)


class RussellEmotionDialog(QDialog):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Russell 감정 상태")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._state_provider = None
        self._manual_control_callback = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_from_provider)

        self.title_label = QLabel("Russell 감정 상태")
        title_font = QFont("Malgun Gothic", 11)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("정서가: 0.00 | 각성도: 0.00 | 감정: idle")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 설명 라벨 추가
        description_font = QFont("Malgun Gothic", 9)
        description_font.setItalic(True)
        
        self.description_label = QLabel(
            "정서가(Valence): -1(부정적 왼쪽)  +1(긍정적 오른쪽)\n"
            "각성도(Arousal): -1(진정 아래)   +1(흥분 위)"
        )
        self.description_label.setFont(description_font)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description_color = QColor(100, 100, 100)
        self.description_label.setStyleSheet(f"color: rgb({description_color.red()}, {description_color.green()}, {description_color.blue()});")

        self.canvas = RussellEmotionCanvas(self)
        self.canvas.state_changed.connect(self._on_canvas_state_changed)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.description_label)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        self.setFixedSize(420, 560)

    def set_state_provider(self, provider):
        self._state_provider = provider

    def set_state_change_callback(self, callback):
        self._manual_control_callback = callback

    def set_live_mode(self):
        self._refresh_from_provider()
        if self._state_provider is not None:
            self.start_auto_refresh()

    def update_state(self, valence: float, arousal: float, dominant: str) -> None:
        self.canvas.set_state(valence, arousal, dominant)
        self.value_label.setText(
            f"정서가: {valence:+.2f} | 각성도: {arousal:+.2f} | 감정: {dominant}"
        )

    def _on_canvas_state_changed(self, valence: float, arousal: float, dominant: str) -> None:
        self.value_label.setText(
            f"정서가: {valence:+.2f} | 각성도: {arousal:+.2f} | 감정: {dominant}"
        )
        if self._manual_control_callback is not None:
            self._manual_control_callback(valence, arousal, dominant)

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
        if hasattr(self.canvas, 'animation_timer'):
            self.canvas.animation_timer.stop()
        self.closed.emit()
        super().closeEvent(event)

    def showEvent(self, event):
        print("[RussellEmotionDialog] showEvent")
        super().showEvent(event)
