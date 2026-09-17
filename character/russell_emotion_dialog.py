import math
from datetime import datetime

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
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

    def _plot_geometry(self):
        rect = self.rect().adjusted(55, 45, -55, -45)
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
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._state_provider = None
        self._manual_control_callback = None
        self._explanation_provider = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_from_provider)

        self.title_label = QLabel("Russell 감정 판단 근거")
        title_font = QFont("Malgun Gothic", 15)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setObjectName("title")

        self.subtitle_label = QLabel("OCC 사건 평가 → 성격 가중치 → Russell Valence/Arousal")
        self.subtitle_label.setObjectName("subtitle")

        self.value_label = QLabel("현재 감정: 중립 0%  ·  V +0.00  A +0.00")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("summary")

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
        self.canvas.state_changed.connect(self._on_canvas_state_changed)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self.value_label)
        left_layout.addWidget(self.canvas, 1)
        left_layout.addWidget(self.description_label)

        left_panel = QWidget()
        left_panel.setLayout(left_layout)
        left_panel.setMinimumWidth(420)

        self.change_label = QLabel("아직 기록된 감정 사건이 없습니다.")
        self.change_label.setObjectName("changeCard")
        self.change_label.setWordWrap(True)
        self.change_label.setMinimumHeight(72)

        self.influence_table = QTableWidget(0, 5)
        self.influence_table.setHorizontalHeaderLabels(
            ["시각", "영향 요인", "영향", "Valence", "Arousal"]
        )
        self.influence_table.verticalHeader().setVisible(False)
        self.influence_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.influence_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.influence_table.setAlternatingRowColors(True)
        self.influence_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.influence_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.influence_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.influence_table.setMinimumHeight(225)

        influence_group = QGroupBox("최근 영향 요인")
        influence_layout = QVBoxLayout()
        influence_layout.addWidget(self.influence_table)
        influence_group.setLayout(influence_layout)

        self.personality_label = QLabel("성격 보정 기록을 기다리는 중입니다.")
        self.personality_label.setWordWrap(True)
        personality_group = QGroupBox("성격 기반 가중치")
        personality_layout = QVBoxLayout()
        personality_layout.addWidget(self.personality_label)
        personality_group.setLayout(personality_layout)

        self.recovery_bar = QProgressBar()
        self.recovery_bar.setRange(0, 100)
        self.recovery_bar.setValue(100)
        self.recovery_bar.setFormat("중립 안정화 %p%")
        self.recovery_label = QLabel("활성 감정이 없어 안정된 상태입니다.")
        self.recovery_label.setWordWrap(True)
        recovery_group = QGroupBox("감정 회복 과정")
        recovery_layout = QVBoxLayout()
        recovery_layout.addWidget(self.recovery_bar)
        recovery_layout.addWidget(self.recovery_label)
        recovery_group.setLayout(recovery_layout)

        self.occ_rows = []
        occ_group = QGroupBox("현재 활성 OCC 성분")
        occ_layout = QVBoxLayout()
        for _ in range(4):
            row = QHBoxLayout()
            label = QLabel("-")
            label.setFixedWidth(60)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            row.addWidget(label)
            row.addWidget(bar)
            occ_layout.addLayout(row)
            self.occ_rows.append((label, bar))
        occ_group.setLayout(occ_layout)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.change_label)
        right_layout.addWidget(influence_group, 1)
        right_layout.addWidget(personality_group)
        right_layout.addWidget(recovery_group)
        right_layout.addWidget(occ_group)

        right_panel = QWidget()
        right_panel.setLayout(right_layout)

        content_layout = QHBoxLayout()
        content_layout.addWidget(left_panel, 5)
        content_layout.addWidget(right_panel, 7)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addLayout(content_layout, 1)
        self.setLayout(layout)
        self.setMinimumSize(980, 700)
        self.resize(1040, 740)
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
            QTableWidget { border: none; gridline-color: #e7eaf0; alternate-background-color: #f7f9fc; }
            QHeaderView::section { background: #eef2f8; color: #4b5568; border: none;
                                   border-bottom: 1px solid #d9dfe9; padding: 6px; font-weight: 700; }
            QProgressBar { border: 1px solid #d6dce7; border-radius: 5px; text-align: center;
                           background: #edf0f5; min-height: 17px; }
            QProgressBar::chunk { background: #5b8def; border-radius: 4px; }
        """)

    def set_state_provider(self, provider):
        self._state_provider = provider

    def set_state_change_callback(self, callback):
        self._manual_control_callback = callback

    def set_live_mode(self):
        self._refresh_from_provider()
        if self._state_provider is not None:
            self.start_auto_refresh()

    def set_explanation_provider(self, provider):
        self._explanation_provider = provider

    def update_state(self, valence: float, arousal: float, dominant: str, intensity: float = 0.0) -> None:
        self.canvas.set_state(valence, arousal, dominant)
        emotion_name = self.EMOTION_NAMES.get(dominant, dominant)
        self.value_label.setText(
            f"현재 감정: {emotion_name} {intensity * 100:.0f}%  ·  "
            f"Valence {valence:+.2f}  ·  Arousal {arousal:+.2f}"
        )

    def _on_canvas_state_changed(self, valence: float, arousal: float, dominant: str) -> None:
        self.update_state(valence, arousal, dominant)
        if self._manual_control_callback is not None:
            self._manual_control_callback(valence, arousal, dominant)

    def update_explanation(self, snapshot: dict) -> None:
        """MoodSystem의 설명 스냅샷을 분석 패널 전체에 반영한다."""
        self.update_state(
            snapshot.get("valence", 0.0),
            snapshot.get("arousal", 0.0),
            snapshot.get("emotion", "neutral"),
            snapshot.get("intensity", 0.0),
        )
        self.canvas.set_history(snapshot.get("coordinate_history", []))

        latest = snapshot.get("latest_change")
        if latest:
            category = latest.get("category", "")
            marker = {"positive": "+", "negative": "−", "recovery": "↺"}.get(category, "•")
            score = abs(int(latest.get("impact_score", 0)))
            self.change_label.setText(
                f"{marker}  {latest.get('source', '감정 사건')}  ·  영향도 {score}\n"
                f"Valence {latest.get('before_valence', 0):+.2f} → {latest.get('after_valence', 0):+.2f}   "
                f"Arousal {latest.get('before_arousal', 0):+.2f} → {latest.get('after_arousal', 0):+.2f}\n"
                f"{latest.get('details', '')}"
            )
        else:
            self.change_label.setText("아직 기록된 감정 사건이 없습니다. 캐릭터와 상호작용해 보세요.")

        events = snapshot.get("recent_events", [])[:7]
        self.influence_table.setRowCount(len(events))
        for row, item in enumerate(events):
            category = item.get("category", "")
            marker = {"positive": "+", "negative": "−", "recovery": "↺"}.get(category, "•")
            score = abs(int(item.get("impact_score", 0)))
            values = [
                datetime.fromtimestamp(item.get("timestamp", 0)).strftime("%H:%M:%S"),
                item.get("source", ""),
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
                if column >= 2:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    cell.setForeground(color)
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                self.influence_table.setItem(row, column, cell)

        personality = snapshot.get("personality", {})
        preset = personality.get("preset", "미설정")
        if latest:
            factors = latest.get("personality_factors") or ["추가 성격 보정 없음"]
            multiplier = latest.get("personality_multiplier", 1.0)
            self.personality_label.setText(
                f"프리셋: {preset}\n"
                f"{' · '.join(factors)}\n"
                f"기본 {latest.get('base_weight', 0):.2f} × 성격 {multiplier:.2f} "
                f"= 최종 {latest.get('adjusted_weight', 0):.2f}"
            )
        else:
            self.personality_label.setText(f"프리셋: {preset}\n감정 사건을 기다리는 중입니다.")

        recovery = int(snapshot.get("recovery_percent", 100))
        self.recovery_bar.setValue(recovery)
        self.recovery_label.setText(
            "OCC 감정 강도가 매초 감쇠하며 중립 좌표로 회복 중입니다."
            if recovery < 98 else "활성 감정이 낮아 안정된 상태입니다."
        )

        components = snapshot.get("occ_components", [])
        for index, (label, bar) in enumerate(self.occ_rows):
            component = components[index] if index < len(components) else {"name": "", "value": 0.0}
            name = component.get("name", "")
            value = float(component.get("value", 0.0))
            label.setText(self.OCC_NAMES.get(name, name or "-"))
            bar.setValue(int(round(value * 100)))
            bar.setFormat(f"{value * 100:.0f}%")

    def _refresh_from_provider(self):
        if self._state_provider is None:
            return
        try:
            valence, arousal, dominant = self._state_provider()
        except Exception:
            valence, arousal, dominant = 0.0, 0.0, "neutral"
        self.update_state(valence, arousal, dominant)
        if self._explanation_provider is not None:
            try:
                snapshot = self._explanation_provider()
            except Exception as exc:
                print(f"[RussellEmotionDialog] 설명 데이터 갱신 실패: {exc}")
            else:
                self.update_explanation(snapshot)

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
