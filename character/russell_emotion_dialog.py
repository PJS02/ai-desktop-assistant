import math
import json
from copy import deepcopy
from datetime import datetime
from app_logging import log_event, log_throttled

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QPainterPath
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal


class RussellEmotionCanvas(QWidget):
    state_changed = pyqtSignal(float, float, str)
    RING_LABELS = (
        ("초조한", 112.5),
        ("들뜬", 67.5),
        ("의기양양한", 45),
        ("행복한", 22.5),
        ("고요한", -22.5),
        ("만족한", -45),
        ("차분한", -67.5),
        ("힘든", -112.5),
        ("우울한", -135),
        ("슬픈", -157.5),
        ("괴로운", 157.5),
        ("속상한", 135),
    )
    AXIS_LABELS = (("흥분 +", 90), ("조용 -", -90), ("불쾌 -", 180), ("유쾌 +", 0))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.valence_current = 0.0
        self.arousal_current = 0.0
        self.valence_target = 0.0
        self.arousal_target = 0.0
        self.dominant = "idle"
        self._dragging = False
        self.coordinate_history = []
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

    def _label_metrics(self):
        return QFontMetrics(QFont("Malgun Gothic", 9), self)

    def _label_rect(self, text, angle_deg, radius, center, metrics):
        angle = math.radians(angle_deg)
        dx, dy = math.cos(angle), -math.sin(angle)
        width, height = metrics.horizontalAdvance(text) + 2, metrics.height()
        # Keep the whole text box beyond the circle's tangent, with an equal gap.
        offset = 10 + abs(dx) * width / 2 + abs(dy) * height / 2
        x = center.x() + (radius + offset) * dx
        y = center.y() + (radius + offset) * dy
        return QRectF(x - width / 2, y - height / 2, width, height)

    def _plot_geometry(self):
        center = QPointF(self.width() / 2, self.height() / 2)
        horizontal_space, vertical_space = center.x() - 8, center.y() - 8
        radius = min(horizontal_space, vertical_space)
        metrics = self._label_metrics()
        for text, angle_deg in self.RING_LABELS + self.AXIS_LABELS:
            angle = math.radians(angle_deg)
            dx, dy = abs(math.cos(angle)), abs(math.sin(angle))
            half_width, half_height = (metrics.horizontalAdvance(text) + 2) / 2, metrics.height() / 2
            offset = 10 + dx * half_width + dy * half_height
            if dx > 1e-6:
                radius = min(radius, (horizontal_space - half_width) / dx - offset)
            if dy > 1e-6:
                radius = min(radius, (vertical_space - half_height) / dy - offset)
        radius = max(1.0, radius)
        return QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2), radius, center

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

    def set_history(self, points) -> None:
        """최근 감정 좌표 궤적을 오래된 순서로 설정한다."""
        self.coordinate_history = [
            (max(-1.0, min(1.0, float(v))), max(-1.0, min(1.0, float(a))))
            for v, a in (points or [])[-12:]
        ]
        self.update()

    def _dominant_color(self) -> QColor:
        color_map = {
            "joy": QColor(255, 196, 0),
            "delight": QColor(255, 196, 0),
            "excitement": QColor(255, 150, 40),
            "interest": QColor(80, 190, 140),
            "contentment": QColor(100, 200, 130),
            "sadness": QColor(100, 150, 255),
            "melancholy": QColor(90, 120, 200),
            "despair": QColor(80, 90, 150),
            "anger": QColor(255, 80, 80),
            "disgust": QColor(170, 110, 80),
            "fear": QColor(180, 80, 255),
            "anxiety": QColor(255, 150, 80),
            "calm": QColor(70, 180, 190),
            "peaceful": QColor(80, 170, 220),
            "neutral": QColor(80, 200, 200),
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
        metrics = self._label_metrics()
        for text, angle_deg in self.RING_LABELS + self.AXIS_LABELS:
            label_rect = self._label_rect(text, angle_deg, radius, center, metrics)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

        neutral_width, neutral_height = metrics.horizontalAdvance("중립") + 2, metrics.height()
        neutral_rect = QRectF(center.x() - neutral_width / 2, center.y() + 6,
                             neutral_width, neutral_height)
        painter.drawText(neutral_rect, Qt.AlignmentFlag.AlignCenter, "중립")

        # 최근 판단 사건의 Russell 좌표 궤적. 오래된 선은 옅고 최신 선은 진하다.
        if len(self.coordinate_history) >= 2:
            screen_points = [
                QPointF(center.x() + value * radius, center.y() - arousal * radius)
                for value, arousal in self.coordinate_history
            ]
            segment_count = len(screen_points) - 1
            for index in range(segment_count):
                alpha = 55 + int(170 * (index + 1) / segment_count)
                painter.setPen(QPen(QColor(66, 133, 244, alpha), 2.5))
                painter.drawLine(screen_points[index], screen_points[index + 1])

            start = screen_points[-2]
            end = screen_points[-1]
            angle = math.atan2(end.y() - start.y(), end.x() - start.x())
            arrow_size = 8.0
            left = QPointF(
                end.x() - arrow_size * math.cos(angle - math.pi / 6),
                end.y() - arrow_size * math.sin(angle - math.pi / 6),
            )
            right = QPointF(
                end.x() - arrow_size * math.cos(angle + math.pi / 6),
                end.y() - arrow_size * math.sin(angle + math.pi / 6),
            )
            painter.setPen(QPen(QColor(66, 133, 244), 2.5))
            painter.drawLine(end, left)
            painter.drawLine(end, right)

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


class RussellHistoryCanvas(QWidget):
    """Russell 정서가와 각성도의 최근 변화를 주식 차트처럼 표시한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.max_samples = 180
        self.setMinimumHeight(210)

    def add_sample(self, valence: float, arousal: float) -> None:
        self.samples.append((float(valence), float(arousal)))
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]
        self.update()

    def _plot_rect(self):
        return self.rect().adjusted(42, 18, -14, -30)

    @staticmethod
    def _y_for_value(value: float, rect) -> float:
        return rect.bottom() - ((value + 1.0) / 2.0) * rect.height()

    def _draw_series(self, painter: QPainter, values, color: QColor, rect) -> None:
        if len(values) < 2:
            return
        path = QPainterPath()
        for index, value in enumerate(values):
            x = rect.left() + index * rect.width() / max(1, self.max_samples - 1)
            y = self._y_for_value(value, rect)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(color, 2))
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(248, 250, 252))
        rect = self._plot_rect()

        painter.setFont(QFont("Malgun Gothic", 8))
        painter.setPen(QPen(QColor(205, 211, 218), 1))
        for value in (-1.0, -0.5, 0.0, 0.5, 1.0):
            y = self._y_for_value(value, rect)
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
            painter.setPen(QColor(100, 108, 118))
            painter.drawText(4, int(y + 4), f"{value:+.1f}")
            painter.setPen(QPen(QColor(205, 211, 218), 1))

        painter.setPen(QPen(QColor(150, 158, 168), 1))
        painter.drawRect(rect)
        painter.setPen(QColor(80, 88, 98))
        painter.drawText(rect.left(), self.height() - 8, "과거")
        painter.drawText(rect.right() - 22, self.height() - 8, "현재")

        if self.samples:
            self._draw_series(
                painter,
                [sample[0] for sample in self.samples],
                QColor(30, 125, 215),
                rect,
            )
            self._draw_series(
                painter,
                [sample[1] for sample in self.samples],
                QColor(225, 118, 45),
                rect,
            )

        painter.end()


class RussellEmotionDialog(QDialog):
    closed = pyqtSignal()
    EMOTION_NAMES = {
        "joy": "기쁨", "delight": "즐거움", "excitement": "흥분",
        "interest": "관심", "contentment": "만족", "anger": "분노",
        "disgust": "불쾌", "fear": "두려움", "anxiety": "불안",
        "calm": "차분함", "peaceful": "평온", "sadness": "슬픔",
        "melancholy": "우울", "despair": "절망", "neutral": "중립",
        "idle": "중립",
    }
    OCC_NAMES = {
        "joy": "기쁨", "distress": "고통", "hope": "희망", "fear": "두려움",
        "satisfaction": "만족", "relief": "안도", "pride": "자부심",
        "shame": "수치심", "gratitude": "감사", "anger": "분노",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Russell 감정 판단 근거 · Explainable Emotion AI")
        self.setFont(QFont("Malgun Gothic", 9))
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._state_provider = None
        self._manual_control_callback = None
        self._explanation_provider = None
        self._influence_paused = False
        self._latest_events = []
        self._displayed_events = []
        self._selected_event = None
        self._selected_event_id = None
        self._last_explanation_at = None
        self._last_state_at = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_from_provider)

        self.title_label = QLabel("Russell 감정 판단 근거")
        title_font = QFont("Malgun Gothic", 15)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setObjectName("title")

        self.subtitle_label = QLabel("OCC 사건 평가 → 성격 가중치 → Russell Valence/Arousal")
        self.subtitle_label.setObjectName("subtitle")

        self.value_label = QLabel("현재 감정 정보를 기다리는 중입니다.")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("summary")
        self.target_label = QLabel("목표 좌표를 기다리는 중입니다.")
        self.target_label.setWordWrap(True)
        self.refresh_status_label = QLabel("근거 갱신 대기 중")
        self.refresh_status_label.setWordWrap(True)

        # 설명 라벨 추가
        description_font = QFont("Malgun Gothic", 9)
        description_font.setItalic(True)
        
        self.description_label = QLabel(
            "정서가(Valence): -1(부정적 왼쪽)  +1(긍정적 오른쪽)\n"
            "각성도(Arousal): -1(진정 아래)   +1(흥분 위)"
        )
        self.description_label.setFont(description_font)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        description_color = QColor(100, 100, 100)
        self.description_label.setStyleSheet(f"color: rgb({description_color.red()}, {description_color.green()}, {description_color.blue()});")

        self.canvas = RussellEmotionCanvas(self)
        self.history_canvas = RussellHistoryCanvas(self)
        self.canvas.state_changed.connect(self._on_canvas_state_changed)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.value_label)
        left_layout.addWidget(self.target_label)
        left_layout.addWidget(self.canvas, 1)
        left_layout.addWidget(self.description_label)

        self.chart_title = QLabel("최근 감정 흐름 · 약 45초")
        self.chart_title.setFont(description_font)
        self.chart_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_legend = QLabel("● 정서가(Valence)    ● 각성도(Arousal)")
        self.chart_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_legend.setStyleSheet("color: rgb(75, 84, 95);")
        left_layout.addWidget(self.chart_title)
        left_layout.addWidget(self.chart_legend)
        left_layout.addWidget(self.history_canvas)

        left_panel = QWidget()
        left_panel.setLayout(left_layout)
        left_panel.setMinimumWidth(420)

        self.change_label = QLabel("아직 기록된 감정 사건이 없습니다.")
        self.change_label.setObjectName("changeCard")
        self.change_label.setWordWrap(True)
        self.change_label.setMinimumHeight(72)

        self.influence_table = QTableWidget(0, 5)
        self.influence_table.setHorizontalHeaderLabels(
            ["시각", "영향 요인", "좌표 변화 크기", "ΔV", "ΔA"]
        )
        self.influence_table.verticalHeader().setVisible(False)
        self.influence_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.influence_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.influence_table.itemSelectionChanged.connect(self._on_influence_selected)
        self.influence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.influence_table.setAlternatingRowColors(True)
        self.influence_table.setWordWrap(False)
        self.influence_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.influence_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.influence_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.influence_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.influence_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.influence_table.setMinimumHeight(225)

        influence_group = QGroupBox()
        influence_layout = QVBoxLayout()
        self.influence_title = QLabel("최근 영향 요인")
        influence_font = self.influence_title.font()
        influence_font.setBold(True)
        self.influence_title.setFont(influence_font)
        self.pause_button = QPushButton("일시정지")
        self.pause_button.setToolTip("최근 영향 요인 목록만 고정합니다. 감정 처리와 기록은 계속됩니다.")
        self.pause_button.clicked.connect(self._toggle_influence_pause)
        self.pause_label = QLabel("실시간")
        self.pause_label.setStyleSheet("color: #4667a8;")
        influence_header = QHBoxLayout()
        influence_header.addWidget(self.influence_title)
        influence_header.addWidget(self.pause_button)
        influence_header.addWidget(self.pause_label)
        influence_header.addStretch()
        influence_layout.addLayout(influence_header)
        self.history_status_label = QLabel("실행 중 기록을 기다리는 중입니다.")
        self.history_status_label.setWordWrap(True)
        influence_layout.addWidget(self.history_status_label)
        influence_layout.addWidget(self.influence_table)
        influence_group.setLayout(influence_layout)

        detail_group = QGroupBox("선택한 기록의 상세 근거")
        detail_layout = QVBoxLayout()
        detail_header = QHBoxLayout()
        self.detail_status_label = QLabel("최신 기록 따라가는 중")
        self.detail_status_label.setWordWrap(True)
        self.follow_latest_button = QPushButton("최신 따라가기")
        self.follow_latest_button.clicked.connect(self._follow_latest)
        detail_header.addWidget(self.detail_status_label, 1)
        detail_header.addWidget(self.follow_latest_button)
        detail_layout.addLayout(detail_header)
        self.detail_view = QTextBrowser()
        self.detail_view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.detail_view.setMinimumHeight(240)
        self.detail_view.setOpenExternalLinks(False)
        self.detail_view.setPlainText("기록을 기다리는 중입니다.")
        detail_layout.addWidget(self.detail_view)
        detail_group.setLayout(detail_layout)

        self.personality_label = QLabel("성격 보정 기록을 기다리는 중입니다.")
        self.personality_label.setWordWrap(True)
        personality_group = QGroupBox("성격 기반 가중치")
        personality_layout = QVBoxLayout()
        personality_layout.addWidget(self.personality_label)
        personality_group.setLayout(personality_layout)

        self.recovery_bar = QProgressBar()
        self.recovery_bar.setRange(0, 100)
        self.recovery_bar.setValue(100)
        self.recovery_bar.setFormat("최대 감정 성분 강도 %p%")
        self.recovery_label = QLabel("활성 감정이 없어 안정된 상태입니다.")
        self.recovery_label.setWordWrap(True)
        recovery_group = QGroupBox("감정 강도와 자연 감쇠 상태")
        recovery_layout = QVBoxLayout()
        recovery_layout.addWidget(self.recovery_bar)
        recovery_layout.addWidget(self.recovery_label)
        recovery_group.setLayout(recovery_layout)

        self.occ_rows = []
        occ_group = QGroupBox("현재 활성 OCC 성분")
        occ_layout = QGridLayout()
        self.occ_row_names = list(self.OCC_NAMES)
        for index, name in enumerate(self.occ_row_names):
            row = QHBoxLayout()
            label = QLabel(self.OCC_NAMES[name])
            label.setFixedWidth(60)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            row.addWidget(label)
            row.addWidget(bar)
            occ_layout.addLayout(row, index // 2, index % 2)
            self.occ_rows.append((label, bar))
        occ_group.setLayout(occ_layout)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.change_label)
        right_layout.addWidget(influence_group, 1)
        right_layout.addWidget(personality_group)
        right_layout.addWidget(detail_group)
        right_layout.addWidget(recovery_group)
        right_layout.addWidget(occ_group)

        right_panel = QWidget()
        right_panel.setLayout(right_layout)

        content_layout = QHBoxLayout()
        content_layout.addWidget(left_panel, 5)
        content_layout.addWidget(right_panel, 7)

        content_panel = QWidget()
        content_panel.setLayout(content_layout)
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setWidget(content_panel)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.refresh_status_label)
        layout.addWidget(self.content_scroll, 1)
        self.setLayout(layout)
        self.setMinimumSize(980, 700)
        self.resize(1040, min(900, max(700, self.screen().availableGeometry().height() - 80)))
        self.setStyleSheet("""
            QDialog { background: #f6f8fb; color: #202124; }
            QLabel#title { color: #202124; padding-left: 6px; }
            QLabel#subtitle { color: #687386; padding: 0 0 8px 7px; }
            QLabel#summary { background: #17223b; color: white; border-radius: 10px;
                             padding: 12px; font-size: 14px; font-weight: 700; }
            QLabel#changeCard { background: #eaf1ff; border: 1px solid #c8d9ff;
                                border-radius: 9px; padding: 10px; color: #263b69; }
            QGroupBox { font-weight: 700; border: 1px solid #d9dfe9; border-radius: 8px;
                        margin-top: 10px; padding-top: 10px; background: white; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QTableWidget { border: none; gridline-color: #e7eaf0; alternate-background-color: #f7f9fc;
                           selection-background-color: #ddeaff; selection-color: #263b69; }
            QTextBrowser { border: 1px solid #e7eaf0; background: #fcfdff; padding: 6px; }
            QHeaderView::section { background: #eef2f8; color: #4b5568; border: none;
                                   border-bottom: 1px solid #d9dfe9; padding: 6px; font-weight: 700; }
            QProgressBar { border: 1px solid #d6dce7; border-radius: 5px; text-align: center;
                           background: #edf0f5; min-height: 17px; }
            QProgressBar::chunk { background: #5b8def; border-radius: 4px; }
            QPushButton { background: white; color: #263b69; border: 1px solid #c8d9ff;
                          border-radius: 6px; padding: 7px 14px; }
            QPushButton:hover { background: #eaf1ff; }
        """)

    def set_state_provider(self, provider):
        self._state_provider = provider

    def set_state_change_callback(self, callback):
        self._manual_control_callback = callback

    def set_live_mode(self):
        self._refresh_from_provider()
        if self._state_provider is not None or self._explanation_provider is not None:
            self.start_auto_refresh()

    def set_explanation_provider(self, provider):
        self._explanation_provider = provider

    def update_state(self, valence: float, arousal: float, dominant: str, intensity: float | None = None) -> None:
        self.canvas.set_state(valence, arousal, dominant)
        self.history_canvas.add_sample(valence, arousal)
        emotion_name = self.EMOTION_NAMES.get(dominant, dominant)
        strength = f"{intensity * 100:.0f}%" if intensity is not None else "강도 정보 없음"
        self.value_label.setText(
            f"현재 감정: {emotion_name} {strength}  ·  "
            f"Valence {valence:+.2f}  ·  Arousal {arousal:+.2f}"
        )

    def _on_canvas_state_changed(self, valence: float, arousal: float, dominant: str) -> None:
        self.update_state(valence, arousal, dominant)
        if self._manual_control_callback is not None:
            self._manual_control_callback(valence, arousal, dominant)

    def update_explanation(self, snapshot: dict) -> None:
        """MoodSystem의 설명 스냅샷을 분석 패널 전체에 반영한다."""
        self._latest_events = deepcopy(snapshot.get("recent_events", []))
        self.update_state(
            snapshot.get("valence", 0.0),
            snapshot.get("arousal", 0.0),
            snapshot.get("emotion", "neutral"),
            snapshot.get("intensity", 0.0),
        )
        self.canvas.set_history(snapshot.get("coordinate_history", []))
        target = snapshot.get("target")
        if target:
            self.target_label.setText(
                f"목표 좌표: V {target['valence']:+.3f} · A {target['arousal']:+.3f}\n"
                "현재 좌표는 목표를 향해 점진적으로 이동합니다."
            )

        latest = snapshot.get("latest_change")
        if latest:
            category = latest.get("category", "")
            marker = {"positive": "+", "negative": "-", "recovery": "회복"}.get(category, "변화")
            score = abs(int(latest.get("impact_score", 0)))
            self.change_label.setText(
                f"가장 최근 변화: {marker}  {latest.get('source', '감정 사건')}  ·  좌표 변화 크기 {score}\n"
                f"Valence {latest.get('before_valence', 0):+.2f} → {latest.get('after_valence', 0):+.2f}   "
                f"Arousal {latest.get('before_arousal', 0):+.2f} → {latest.get('after_arousal', 0):+.2f}\n"
                f"{latest.get('details', '')}"
            )
        else:
            self.change_label.setText("아직 기록된 감정 사건이 없습니다. 캐릭터와 상호작용해 보세요.")

        if not self._influence_paused:
            self._render_influence_events(self._latest_events)

        personality = snapshot.get("personality", {})
        preset = personality.get("preset", "미설정")
        event_preset = latest.get("personality", {}).get("preset", preset) if latest else preset
        if latest and latest.get("weight_applied", True):
            factors = latest.get("personality_factors") or ["추가 성격 보정 없음"]
            multiplier = latest.get("personality_multiplier", 1.0)
            self.personality_label.setText(
                f"최근 사건 당시 프리셋: {event_preset}\n"
                f"{' · '.join(factors)}\n"
                f"기본 {latest.get('base_weight', 0):.2f} × 성격 {multiplier:.2f} "
                f"= 최종 {latest.get('adjusted_weight', 0):.2f}"
            )
        elif latest:
            self.personality_label.setText(f"최근 사건 당시 프리셋: {event_preset}\n이 경로에는 성격 가중치 보정을 적용하지 않습니다.")
        else:
            self.personality_label.setText(f"프리셋: {preset}\n감정 사건을 기다리는 중입니다.")

        self.recovery_bar.setValue(int(snapshot.get("peak_occ_percent", 100 - snapshot.get("recovery_percent", 100))))
        status = snapshot.get("decay_status", {})
        reason = status.get("reason", "active")
        status_text = {"active": "자연 감쇠 가능 상태 · 주기적으로 반영",
                       "manual_override": "수동 좌표 조정으로 자연 감쇠 보류",
                       "emotion_hold": f"강한 사건의 여운으로 자연 감쇠 보류 · 남은 {status.get('remaining_seconds', 0):.1f}초"}
        self.recovery_label.setText(status_text.get(reason, reason))

        components = {item["name"]: item for item in snapshot.get("occ_components", [])}
        for index, (label, bar) in enumerate(self.occ_rows):
            component = components.get(self.occ_row_names[index], {"name": self.occ_row_names[index], "value": 0.0})
            name = component.get("name", "")
            value = float(component.get("value", 0.0))
            label.setText(self.OCC_NAMES.get(name, name or "-"))
            bar.setValue(int(round(value * 100)))
            bar.setFormat(f"{value * 100:.0f}%")
            bar.setToolTip(f"실제 성분 강도 {value:.6f} ({value * 100:.4f}%)")
        history = snapshot.get("history", {})
        self.history_status_label.setText(
            f"목록 {len(self._displayed_events)}건 표시 · 현재 {history.get('retained', len(self._latest_events))}건 보관 · "
            f"최대 {history.get('capacity', 300)}건 보관 · 이전 {history.get('excluded', 0)}건 제외"
        )
        self._update_selected_detail()
        self._last_explanation_at = datetime.now()
        self._last_state_at = self._last_explanation_at
        self._update_refresh_status()

    def _render_influence_events(self, events):
        scroll_position = self.influence_table.verticalScrollBar().value()
        self._displayed_events = deepcopy(events)
        self.influence_table.blockSignals(True)
        self.influence_table.clearSelection()
        self.influence_table.setRowCount(len(events))
        for row, item in enumerate(self._displayed_events):
            if not item.get("event_id"):
                item["event_id"] = f"{item.get('timestamp', 0)}:{item.get('source', '')}:{row}"
            category = item.get("category", "")
            marker = {"positive": "+", "negative": "-", "recovery": "회복 "}.get(category, "변화 ")
            score = abs(int(item.get("impact_score", 0)))
            values = [
                datetime.fromtimestamp(item.get("timestamp", 0)).strftime("%H:%M:%S"),
                item.get("source", "") + (f" · {item['sample_count']}회" if item.get("sample_count", 1) > 1 else ""),
                f"{marker}{score}",
                f"{item.get('delta_valence', 0):+.3f}",
                f"{item.get('delta_arousal', 0):+.3f}",
            ]
            color = {
                "positive": QColor("#16804b"),
                "negative": QColor("#c23b3b"),
                "recovery": QColor("#4667a8"),
            }.get(category, QColor("#4b5563"))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole, item.get("event_id"))
                cell.setToolTip(value)
                if column == 2:
                    cell.setToolTip("사건 반영 시 현재 좌표가 이동한 크기(0~99). 목표 좌표·감정 성분 변화는 상세에서 확인하세요.")
                if column >= 2:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    cell.setForeground(color)
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                self.influence_table.setItem(row, column, cell)
            if self._selected_event_id is not None and item.get("event_id") == self._selected_event_id:
                self.influence_table.selectRow(row)
        self.influence_table.blockSignals(False)
        self.influence_table.verticalScrollBar().setValue(scroll_position)

    def _on_influence_selected(self):
        selected = self.influence_table.selectedItems()
        if not selected:
            return
        self._selected_event = deepcopy(self._displayed_events[selected[0].row()])
        self._selected_event_id = self._selected_event.get("event_id")
        self._update_selected_detail()

    def _follow_latest(self):
        self._selected_event_id = None
        self._selected_event = None
        self.influence_table.blockSignals(True)
        self.influence_table.clearSelection()
        self.influence_table.blockSignals(False)
        self._update_selected_detail()

    def _update_selected_detail(self):
        if self._selected_event is None:
            item = self._latest_events[0] if self._latest_events else None
            self.detail_status_label.setText("최신 기록 따라가는 중")
        else:
            matching = next((event for event in self._displayed_events
                             if event.get("event_id") == self._selected_event_id), None)
            if matching is not None:
                self._selected_event = deepcopy(matching)
            item = self._selected_event
            suffix = "목록 고정 중" if self._influence_paused else "선택 유지 중"
            if matching is None:
                suffix = "최근 목록에서 제외된 기록 · 상세 보존"
            self.detail_status_label.setText(suffix)
        self._render_event_detail(item)

    def _render_event_detail(self, item):
        if not item:
            self.detail_view.setPlainText("기록을 기다리는 중입니다.")
            return
        start = datetime.fromtimestamp(item.get("started_at") or item.get("timestamp", 0))
        end = datetime.fromtimestamp(item.get("timestamp", 0))
        lines = [f"{item.get('source', '감정 사건')} · {start:%H:%M:%S} ~ {end:%H:%M:%S}",
                 f"반영 {item.get('sample_count', 1)}회 · {item.get('details') or '추가 설명 없음'}", "",
                 "현재 좌표 · 구간 시작 → 마지막 반영 직후",
                 f"V {item.get('before_valence', 0):+.3f} → {item.get('after_valence', 0):+.3f} · "
                 f"A {item.get('before_arousal', 0):+.3f} → {item.get('after_arousal', 0):+.3f}",
                 f"이 사건의 직접 좌표 변화 합계: ΔV {item.get('delta_valence', 0):+.3f}, ΔA {item.get('delta_arousal', 0):+.3f}"]
        if item.get("target_before") and item.get("target_after"):
            before, after = item["target_before"], item["target_after"]
            change = item.get("target_changes", {})
            lines.extend(["목표 좌표 · 구간 시작 → 마지막 반영 직후",
                          f"V {before['valence']:+.3f} → {after['valence']:+.3f} · A {before['arousal']:+.3f} → {after['arousal']:+.3f}",
                          f"목표 변화 합계: ΔV {change.get('valence', 0):+.3f}, ΔA {change.get('arousal', 0):+.3f}"])
        final = item.get("final_emotion", {})
        if final:
            lines.append(f"마지막 반영 직후 감정: {self.EMOTION_NAMES.get(final['emotion'], final['emotion'])} · 강도 {final['intensity']:.1%}")
        lines.extend(["", "감정 성분 변화 · %는 성분 강도, %p는 증감량"])
        changes = item.get("occ_changes", {})
        if not changes:
            lines.append("감정 성분의 직접 증감 없음")
        for name, delta in changes.items():
            before = item.get("occ_before", {}).get(name)
            after = item.get("occ_after", {}).get(name)
            values = f"{before:.1%} → {after:.1%} · " if before is not None and after is not None else ""
            lines.append(f"{self.OCC_NAMES.get(name, name)}: {values}{delta * 100:+.2f}%p")
        personality = item.get("personality", {})
        lines.extend(["", f"당시 성격 프리셋: {personality.get('preset', '기록 없음')}"])
        if item.get("weight_applied", True):
            lines.append(f"기본 가중치 {item.get('base_weight', 0):.3f} × 보정 {item.get('personality_multiplier', 1):.3f} = 최종 {item.get('adjusted_weight', 0):.3f}")
        else:
            lines.append("성격 가중치 보정 적용 없음")
        lines.extend(item.get("personality_factors", []))
        trait_names = {"extraversion": "외향성", "agreeableness": "친화성", "conscientiousness": "성실성",
                       "neuroticism": "신경증", "openness": "개방성"}
        traits = personality.get("traits", {})
        if traits:
            lines.append(" · ".join(f"{trait_names.get(key, key)} {value:.2f}" for key, value in traits.items()))
        inputs = item.get("event_input", {})
        lines.extend(["", "입력값 · 마지막 반영 기준" if item.get("sample_count", 1) > 1 else "입력값"])
        names = {"movement_speed": "쓰다듬기 속도(px/초)", "elapsed_seconds": "지속 시간(초)",
                 "comfort": "부드러움 계수", "amount": "이번 보상량", "idle_seconds": "방치 시간(초)",
                 "pressure_before": "방치 압력 전", "pressure_after": "방치 압력 후",
                 "idle_valence_before": "방치의 V 기여 전", "idle_valence_after": "방치의 V 기여 후",
                 "idle_arousal_before": "방치의 A 기여 전", "idle_arousal_after": "방치의 A 기여 후",
                 "goal_relevance": "목표 관련성", "expectedness": "예상도", "controllability": "통제 가능성(참고 입력)",
                 "self_attribution": "자기 귀속", "agent_benevolence": "타인 의도", "confidence": "인식 신뢰도",
                 "label": "인식 표정", "normalized_label": "해석한 표정", "occ_weights": "감정 성분 반영 비율",
                 "influence": "인식 반영 계수", "valence_bias": "사건의 V 추가 보정", "arousal_bias": "사건의 A 추가 보정",
                 "negative_retention": "부정 성분 유지율", "positive_retention": "긍정 성분 유지율",
                 "bias_retention": "사건 좌표 보정 유지율",
                 "progress": "드래그 진행 비율", "step": "이번 누적량", "valence": "입력 V", "arousal": "입력 A"}
        if not inputs:
            lines.append("별도 입력값 없음")
        for key, value in inputs.items():
            text = f"{value:.4f}" if isinstance(value, (int, float)) else json.dumps(value, ensure_ascii=False)
            limits = item.get("input_ranges", {}).get(key, {})
            if limits and limits["min"] != limits["max"]:
                text += f" (구간 범위 {limits['min']:.4f}~{limits['max']:.4f})"
            lines.append(f"{names.get(key, key)}: {text}")
        if item.get("source") == "쓰다듬기" and item.get("sample_count", 1) > 1:
            lines.append(f"구간 누적 보상량: {item.get('adjusted_weight', 0):.4f} · 실제 성분 변화는 위 증감량 참조")
        position = self.detail_view.verticalScrollBar().value()
        text = "\n".join(lines)
        if self.detail_view.toPlainText() != text:
            self.detail_view.setPlainText(text)
            self.detail_view.verticalScrollBar().setValue(position)

    def _update_refresh_status(self):
        failed = getattr(self, "_explanation_provider_failed", False)
        state_failed = getattr(self, "_state_provider_failed", False)
        last = self._last_explanation_at.strftime("%H:%M:%S") if self._last_explanation_at else "없음"
        if failed:
            state = "좌표도 갱신 실패 · 마지막 좌표 보존" if state_failed else (
                "좌표 별도 갱신 중" if self._state_provider is not None else "마지막 좌표 보존")
            self.refresh_status_label.setText(f"근거 갱신 실패 · 마지막 정상 갱신 {last} · {state}")
            self.refresh_status_label.setStyleSheet("color: #a53c22;")
        elif state_failed:
            self.refresh_status_label.setText("좌표 갱신 실패 · 마지막 정상 좌표 보존")
            self.refresh_status_label.setStyleSheet("color: #a53c22;")
        elif self._last_explanation_at:
            self.refresh_status_label.setText(f"근거 실시간 · 마지막 정상 갱신 {last}")
            self.refresh_status_label.setStyleSheet("color: #4667a8;")

    def _toggle_influence_pause(self):
        self.set_influence_paused(not self._influence_paused)

    def set_influence_paused(self, paused: bool):
        """Freeze only the influence table; all other views stay live."""
        paused = bool(paused)
        if paused == self._influence_paused:
            return
        self._influence_paused = paused
        self.pause_button.setText("일시정지 해제" if paused else "일시정지")
        self.pause_label.setText("목록 고정 중" if paused else "실시간")
        if not paused:
            self._refresh_from_provider()
            self._render_influence_events(self._latest_events)
            self._update_selected_detail()

    def _refresh_from_provider(self):
        if self._explanation_provider is not None:
            try:
                snapshot = self._explanation_provider()
                self.update_explanation(snapshot)
            except Exception as exc:
                self._explanation_provider_failed = True
                log_throttled('mood.ui.explanation_failed', '감정 설명 공급자 갱신에 실패했습니다.',
                              key=f'explanation:{id(self)}', interval=5,
                              category='오류', level='ERROR', error=str(exc))
            else:
                if getattr(self, '_explanation_provider_failed', False):
                    log_event('mood.ui.explanation_recovered', '감정 설명 공급자 갱신을 복구했습니다.',
                              category='캐릭터 상태')
                    self._explanation_provider_failed = False
                # The explanation already contains coordinates and intensity.
                # Record one graph sample per refresh, preserving the 45s span.
                self._state_provider_failed = False
                self._update_refresh_status()
                return
        if self._state_provider is None:
            self._update_refresh_status()
            return
        try:
            valence, arousal, dominant = self._state_provider()
        except Exception as exc:
            self._state_provider_failed = True
            log_throttled('mood.ui.state_fallback', '감정 좌표 갱신이 실패해 마지막 정상값을 보존합니다.',
                          key=f'state:{id(self)}', interval=5,
                          category='오류', level='ERROR', error=str(exc))
            self._update_refresh_status()
            return
        else:
            if getattr(self, '_state_provider_failed', False):
                log_event('mood.ui.state_recovered', '감정 좌표 공급자 갱신을 복구했습니다.',
                          category='캐릭터 상태')
                self._state_provider_failed = False
        self._last_state_at = datetime.now()
        self.update_state(valence, arousal, dominant)
        self._update_refresh_status()

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
        if not self.canvas.animation_timer.isActive():
            self.canvas.animation_timer.start(16)
        self._refresh_from_provider()
        super().showEvent(event)
        if not getattr(self, "_has_been_shown", False):
            self._has_been_shown = True
            self.pause_button.setFocus(Qt.FocusReason.OtherFocusReason)
            QTimer.singleShot(0, lambda: self.content_scroll.verticalScrollBar().setValue(0))
