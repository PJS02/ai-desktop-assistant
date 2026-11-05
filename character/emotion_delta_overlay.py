"""Show short changes in OCC emotion strength over the character."""

import random
import math
import time
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .mood_system import NEGATIVE_OCC_EMOTIONS, OCC_EMOTION_NAMES, OccEmotionToMood


SOURCE_LABELS = {
    "캐릭터 클릭": "클릭",
    "캐릭터 클릭 (위로)": "클릭으로 위로",
    "빠른 캐릭터 드래그": "거친 드래그",
    "지속적인 캐릭터 드래그": "오래 끌기",
    "갑작스러운 화면 변화": "화면 변화",
    "복잡한 작업 감지": "복잡한 작업",
    "파일 전달받음": "파일 받기",
    "파일 놓침": "파일 반환",
    "파일 반환 완료": "파일 반환",
    "거친 드래그로 파일 놓침": "파일 놓침",
    "손으로 쓰다듬기": "손 쓰다듬기",
    "안전하게 착지": "안전한 착지",
}


@dataclass(frozen=True)
class EmotionPopup:
    cause: QPainterPath
    text: QPainterPath
    color: QColor
    origin: QPointF
    drift: QPointF
    delay: float


class EmotionDeltaOverlay(QWidget):
    BASELINE = 110

    def __init__(self, character, duration_ms, *, enabled=True):
        super().__init__(
            character, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(248, 170)
        self._font = QFont("Malgun Gothic")
        self._font.setPixelSize(18)
        self._font.setBold(True)
        self._cause_font = QFont(self._font)
        self._cause_font.setPixelSize(13)
        self._pending = {}
        self._pending_at = {}
        self._popups = []
        self.enabled = enabled
        self.duration_ms = duration_ms
        self._duration = duration_ms / 1000
        self._started = 0.0
        self._elapsed = 0.0
        self._batch = QTimer(self)
        self._batch.setSingleShot(True)
        self._batch.setInterval(450)
        self._batch.timeout.connect(self._show_pending)
        self._animation = QTimer(self)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._advance)

    @pyqtSlot(str, dict)
    def collect(self, source, changes):
        host = self.parentWidget()
        if not self.enabled or not host.isVisible() or getattr(host, '_character_closing', False):
            return
        for emotion, delta in changes.items():
            key = (source, emotion)
            now = time.monotonic()
            if now - self._pending_at.get(key, now) > 4.:
                self._pending.pop(key, None)
            self._pending[key] = self._pending.get(key, 0.0) + delta
            self._pending_at[key] = now
        if not self._batch.isActive():
            self._batch.start()

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.clear()

    def clear(self):
        self._batch.stop()
        self._animation.stop()
        self._pending.clear()
        self._pending_at.clear()
        self._popups.clear()
        self.hide()

    def _show_pending(self):
        if self._animation.isActive():
            return
        if not self.enabled or not self.parentWidget().isVisible():
            self.clear()
            return
        now = time.monotonic()
        for key in list(self._pending):
            if now - self._pending_at.get(key, now) > 4.:
                del self._pending[key]
                self._pending_at.pop(key, None)
        ranked = sorted(((key, delta) for key, delta in self._pending.items()
                         if abs(delta) >= .01 - 1e-12),
                        key=lambda entry: abs(entry[1]), reverse=True)
        lines = []
        for (source, emotion), delta in ranked[:2]:
            points = math.trunc(delta * 100 + math.copysign(1e-9, delta))
            lines.append((source, emotion, points))
            self._pending[source, emotion] -= points / 100
        if lines:
            self._popups = self._make_popups(lines)
            self._duration = self.duration_ms / 1000
            self._started = time.monotonic()
            self._elapsed = 0.0
            self._position()
            self.show()
            self.raise_()
            self.update()
            self._animation.start()

    def _make_popups(self, lines):
        x = self.width() / 2 + random.uniform(-11, 11)
        y = self.BASELINE + random.uniform(-2, 4)
        side = random.choice((-1, 1))
        height_gap = random.choice((-1, 1)) * random.uniform(44, 46)
        metrics = QFontMetricsF(self._font)
        cause_metrics = QFontMetricsF(self._cause_font)
        popups = []
        for index, (source, emotion, points) in enumerate(lines):
            label = cause_metrics.elidedText(
                SOURCE_LABELS.get(source, source), Qt.TextElideMode.ElideRight, 126
            )
            cause = QPainterPath()
            cause.addText(-cause_metrics.horizontalAdvance(label) / 2, -22, self._cause_font, label)
            sign = '+' if points > 0 else '−'
            text = f'{OCC_EMOTION_NAMES[emotion]} {sign}{abs(points)}'
            path = QPainterPath()
            path.addText(-metrics.horizontalAdvance(text) / 2, 0, self._font, text)
            if index:
                origin = QPointF(x + side * random.uniform(17, 30), y + height_gap)
                drift_x = side * random.uniform(8, 17)
                delay = random.uniform(.065, .11)
            else:
                origin = QPointF(x, y)
                drift_x = -side * random.uniform(4, 12)
                delay = 0.0
            drift = QPointF(drift_x, -random.uniform(22, 27))
            positive_gain = (points > 0) != (OccEmotionToMood(emotion) in NEGATIVE_OCC_EMOTIONS)
            color = QColor('#a6f284' if positive_gain else '#ff797d')
            popups.append(EmotionPopup(cause, path, color, origin, drift, delay))
        return popups

    def _advance(self):
        self._elapsed = time.monotonic() - self._started
        if self._elapsed >= self._duration + self._popups[-1].delay:
            self._animation.stop()
            self.hide()
            if not self._batch.isActive():
                self._show_pending()
        else:
            self._position()
            self.update()

    def _position(self):
        host = self.parentWidget()
        body = host._physics_body_rect().translated(host.mapToGlobal(QPoint()))
        screen = QApplication.screenAt(body.center()) or host.screen()
        bounds = screen.availableGeometry()
        x = body.center().x() - self.width() // 2
        y = body.top() + round(body.height() * .60) - self.BASELINE
        self.move(
            max(bounds.left(), min(x, bounds.right() + 1 - self.width())),
            max(bounds.top(), min(y, bounds.bottom() + 1 - self.height())),
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = QPen(QColor('#27312d'), 2.5)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for popup in self._popups:
            phase = (self._elapsed - popup.delay) / self._duration
            if not 0.0 <= phase < 1.0:
                continue
            painter.save()
            painter.translate(popup.origin + popup.drift * (phase * (2 - phase)))
            painter.setOpacity(min(1.0, (1.0 - phase) / .40))
            painter.strokePath(popup.cause, outline)
            painter.fillPath(popup.cause, QColor('#f5f5ea'))
            painter.strokePath(popup.text, outline)
            painter.fillPath(popup.text, popup.color)
            painter.restore()
        painter.end()
