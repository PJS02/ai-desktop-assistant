"""Show short changes in OCC emotion strength over the character."""

import random
import time
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .mood_system import NEGATIVE_OCC_EMOTIONS, OCC_EMOTION_NAMES, OccEmotionToMood


@dataclass(frozen=True)
class EmotionPopup:
    text: QPainterPath
    color: QColor
    origin: QPointF
    drift: QPointF
    delay: float


class EmotionDeltaOverlay(QWidget):
    DURATION = 0.95

    def __init__(self, character):
        super().__init__(
            character, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(230, 120)
        self._font = QFont("Malgun Gothic")
        self._font.setPixelSize(18)
        self._font.setBold(True)
        self._pending = {}
        self._popups = []
        self._started = 0.0
        self._elapsed = 0.0
        self._batch = QTimer(self)
        self._batch.setSingleShot(True)
        self._batch.setInterval(450)
        self._batch.timeout.connect(self._show_pending)
        self._animation = QTimer(self)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._advance)

    @pyqtSlot(dict)
    def collect(self, changes):
        host = self.parentWidget()
        if not host.isVisible() or getattr(host, '_character_closing', False):
            return
        for emotion, delta in changes.items():
            self._pending[emotion] = self._pending.get(emotion, 0.0) + delta
        if not self._batch.isActive():
            self._batch.start()

    def clear(self):
        self._batch.stop()
        self._animation.stop()
        self._pending.clear()
        self._popups.clear()
        self.hide()

    def _show_pending(self):
        if self._animation.isActive():
            return
        if not self.parentWidget().isVisible():
            self.clear()
            return
        ranked = sorted(self._pending.items(), key=lambda entry: abs(entry[1]), reverse=True)
        self._pending.clear()
        lines = [
            (emotion, round(delta * 100))
            for emotion, delta in ranked[:2]
            if abs(delta) >= 0.01 - 1e-12
        ]
        if lines:
            self._popups = self._make_popups(lines)
            self._started = time.monotonic()
            self._elapsed = 0.0
            self._position()
            self.show()
            self.raise_()
            self.update()
            self._animation.start()

    def _make_popups(self, lines):
        x = self.width() / 2 + random.uniform(-11, 11)
        y = 76 + random.uniform(-2, 4)
        side = random.choice((-1, 1))
        height_gap = random.choice((-1, 1)) * random.uniform(29, 32)
        metrics = QFontMetricsF(self._font)
        popups = []
        for index, (emotion, points) in enumerate(lines):
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
            positive_gain = points > 0 and OccEmotionToMood(emotion) not in NEGATIVE_OCC_EMOTIONS
            color = QColor('#a6f284' if positive_gain else '#ff797d')
            popups.append(EmotionPopup(path, color, origin, drift, delay))
        return popups

    def _advance(self):
        self._elapsed = time.monotonic() - self._started
        if self._elapsed >= self.DURATION + self._popups[-1].delay:
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
        y = body.top() + round(body.height() * .60) - 76
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
            phase = (self._elapsed - popup.delay) / self.DURATION
            if not 0.0 <= phase < 1.0:
                continue
            painter.save()
            painter.translate(popup.origin + popup.drift * (phase * (2 - phase)))
            painter.setOpacity(min(1.0, (1.0 - phase) / .40))
            painter.strokePath(popup.text, outline)
            painter.fillPath(popup.text, popup.color)
            painter.restore()
        painter.end()
