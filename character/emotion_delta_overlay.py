"""Show short OCC changes and event arousal adjustments over the character."""

import random
import math
import time
from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .mood_system import NEGATIVE_OCC_EMOTIONS, OCC_EMOTION_NAMES, OccEmotionToMood
from .interaction_emotions import FACE_SOURCES, GESTURE_SOURCES


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
PRECISE_SOURCES = frozenset((*FACE_SOURCES.values(), *GESTURE_SOURCES.values()))
DELTA_EPSILON = 1e-12


@dataclass(frozen=True)
class EmotionPopup:
    cause: QPainterPath
    text: QPainterPath
    cause_label: str
    change_label: str
    color: QColor
    origin: QPointF
    drift: QPointF
    delay: float


@dataclass(frozen=True)
class PopupRecord:
    timestamp: float
    cause: str
    change: str
    valence: float | None
    arousal: float | None
    color: str


class EmotionDeltaOverlay(QWidget):
    PADDING = 3

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
        self._popup_bounds = QRectF()
        self._paint_scale = 1.0
        self._font = QFont("Malgun Gothic")
        self._font.setPixelSize(18)
        self._font.setBold(True)
        self._cause_font = QFont(self._font)
        self._cause_font.setPixelSize(13)
        self._pending = {}
        self._pending_at = {}
        self._pending_coordinates = {}
        self._popups = []
        self.history = deque(maxlen=100)
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
        now = time.monotonic()
        for emotion, delta in changes.items():
            key = (source, emotion)
            self._discard_stale_fragment(key, now)
            self._pending[key] = self._pending.get(key, 0.0) + delta
            self._pending_at[key] = now
        if not self._batch.isActive():
            self._batch.start()

    @pyqtSlot(str, float)
    def collect_arousal(self, source, change):
        self.collect(source, {'arousal': change})

    @pyqtSlot(str, tuple, float, float)
    def collect_coordinates(self, source, emotions, valence, arousal):
        for emotion in emotions:
            key = (source, emotion)
            if key in self._pending:
                before_valence, before_arousal = self._pending_coordinates.get(key, (0.0, 0.0))
                self._pending_coordinates[key] = (before_valence + valence, before_arousal + arousal)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.clear()

    def clear(self):
        self._batch.stop()
        self._animation.stop()
        self._pending.clear()
        self._pending_at.clear()
        self._pending_coordinates.clear()
        self._popups.clear()
        self.hide()

    @staticmethod
    def _threshold_scale(key):
        source, emotion = key
        return 10_000 if source in PRECISE_SOURCES or emotion == 'arousal' else 1_000

    @staticmethod
    def _meets_threshold(delta, scale):
        return abs(delta) >= 1 / scale - DELTA_EPSILON

    def _discard_stale_fragment(self, key, now):
        # Keep displayable changes queued even if an earlier popup takes several seconds.
        if (now - self._pending_at.get(key, now) > 4.0
                and not self._meets_threshold(self._pending[key], self._threshold_scale(key))):
            del self._pending[key]
            del self._pending_at[key]
            self._pending_coordinates.pop(key, None)

    def _show_pending(self):
        if self._animation.isActive():
            return
        if not self.enabled or not self.parentWidget().isVisible():
            self.clear()
            return
        now = time.monotonic()
        for key in list(self._pending):
            self._discard_stale_fragment(key, now)
        ranked = []
        for key, delta in self._pending.items():
            scale = self._threshold_scale(key)
            if self._meets_threshold(delta, scale):
                ranked.append((key, delta, scale))
        ranked.sort(key=lambda entry: abs(entry[1]), reverse=True)
        lines = []
        for (source, emotion), delta, scale in ranked[:2]:
            points = (round(delta * 100, 2) if scale == 10_000 else
                      math.trunc((delta + math.copysign(DELTA_EPSILON, delta)) * 10_000) / 100)
            lines.append((source, emotion, points))
            self._pending[source, emotion] -= points / 100
        if lines:
            self._popups = self._make_popups(lines)
            timestamp = time.time()
            for (source, emotion, _), popup in zip(lines, self._popups):
                # The leftover display fraction can contribute to another popup.
                # Its event's actual coordinate movement was already recorded here.
                valence, arousal = self._pending_coordinates.pop((source, emotion), (None, None))
                self.history.appendleft(PopupRecord(timestamp, popup.cause_label, popup.change_label,
                                                    valence, arousal, popup.color.name()))
            self._duration = self.duration_ms / 1000
            self._started = time.monotonic()
            self._elapsed = 0.0
            self._position()
            self.show()
            self.raise_()
            self.update()
            self._animation.start()

    def _make_popups(self, lines):
        x = random.uniform(-11, 11)
        y = random.uniform(-2, 4)
        side = random.choice((-1, 1))
        second_below = random.choice((True, False))
        metrics = QFontMetricsF(self._font)
        cause_metrics = QFontMetricsF(self._cause_font)
        popups = []
        bounds = QRectF()
        for index, (source, emotion, points) in enumerate(lines):
            label = SOURCE_LABELS.get(source, source)
            if label.isascii():
                label = '감정 사건'
            cause = QPainterPath()
            cause.addText(-cause_metrics.horizontalAdvance(label) / 2, -22, self._cause_font, label)
            sign = '+' if points > 0 else '−'
            name = '흥분도' if emotion == 'arousal' else OCC_EMOTION_NAMES[emotion]
            text = f'{name} {sign}{abs(points):g}'
            path = QPainterPath()
            path.addText(-metrics.horizontalAdvance(text) / 2, 0, self._font, text)
            if index:
                x += side * random.uniform(17, 30)
                drift_x = side * random.uniform(8, 17)
                delay = random.uniform(.065, .11)
            else:
                drift_x = -side * random.uniform(4, 12)
                delay = 0.0
            drift = QPointF(drift_x, -random.uniform(22, 27))
            text_bounds = cause.boundingRect().united(path.boundingRect())
            travel_bounds = text_bounds.united(text_bounds.translated(drift))
            if index:
                # Separate the paths for the whole ascent, including the delayed popup.
                y = (bounds.bottom() - travel_bounds.top() + 5 if second_below else
                     bounds.top() - travel_bounds.bottom() - 5)
            origin = QPointF(x, y)
            bounds = bounds.united(travel_bounds.translated(origin))
            if emotion == 'arousal':
                color = QColor('#8fc8ff')
            else:
                positive_gain = (points > 0) != (OccEmotionToMood(emotion) in NEGATIVE_OCC_EMOTIONS)
                color = QColor('#a6f284' if positive_gain else '#ff797d')
            popups.append(EmotionPopup(cause, path, label, text, color, origin, drift, delay))
        self._popup_bounds = bounds
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
        popup = self._popup_bounds
        padding = self.PADDING
        scale = min(1.0, (bounds.width() - 2 * padding) / popup.width(),
                    (bounds.height() - 2 * padding) / popup.height())
        self._paint_scale = scale
        width = min(bounds.width(), math.ceil(popup.width() * scale) + 2 * padding)
        height = min(bounds.height(), math.ceil(popup.height() * scale) + 2 * padding)
        x = body.center().x() + round(popup.left() * scale) - padding
        y = body.top() + round(body.height() * .60 + popup.top() * scale) - padding
        self.setGeometry(
            max(bounds.left(), min(x, bounds.right() + 1 - width)),
            max(bounds.top(), min(y, bounds.bottom() + 1 - height)),
            width, height,
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.PADDING, self.PADDING)
        painter.scale(self._paint_scale, self._paint_scale)
        painter.translate(-self._popup_bounds.topLeft())
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
