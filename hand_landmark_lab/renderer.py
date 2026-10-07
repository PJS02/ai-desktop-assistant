"""Landmark preview and small desktop windows that follow each detected hand."""
import math
import os

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from tracker import Hand, Snapshot

CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8), (5, 9),
    (9, 10), (10, 11), (11, 12), (9, 13),
    (13, 14), (14, 15), (15, 16), (13, 17),
    (0, 17), (17, 18), (18, 19), (19, 20),
)
TIPS = {4, 8, 12, 16, 20}
PALM = (0, 5, 9, 13, 17)


def fit_rect(width: float, height: float, aspect: float) -> QRectF:
    """Letterbox the optional preview without stretching hand proportions."""
    fitted_width = min(width, height * aspect)
    fitted_height = fitted_width / aspect
    return QRectF((width - fitted_width) / 2, (height - fitted_height) / 2,
                  fitted_width, fitted_height)


def screen_point(point, rect: QRectF) -> QPointF:
    return QPointF(rect.x() + point[0] * rect.width(), rect.y() + point[1] * rect.height())


def palm_center(hand: Hand) -> tuple[float, float]:
    return tuple(sum(hand.points[i][axis] for i in PALM) / len(PALM) for axis in (0, 1))


def desktop_geometry(hand: Hand, screen: QRect, aspect: float, scale: float = 1.0):
    """Map palm position across the entire screen; preserve shape at a small scale.

    Qt coordinates are logical pixels, including monitors with a negative origin.
    Size uses a fixed camera plane rather than expanding a fist to open-palm size.
    Returns a small global window rectangle and window-local landmark points.
    """
    center_x, center_y = palm_center(hand)
    plane_height = 360 * scale
    plane_width = plane_height * aspect
    offsets = [((p[0] - center_x) * plane_width, (p[1] - center_y) * plane_height)
               for p in hand.points]
    padding = 32

    def local_bounds(values):
        left = math.floor(min(p[0] for p in values)) - padding
        top = math.floor(min(p[1] for p in values)) - padding
        width = math.ceil(max(p[0] for p in values)) + padding - left
        height = math.ceil(max(p[1] for p in values)) + padding - top
        return left, top, width, height

    left, top, width, height = local_bounds(offsets)
    # Fit unusual coordinates on small screens while preserving the shape.
    reduction = min(1.0, max(1, screen.width() - 2 * padding) / max(1, width - 2 * padding),
                    max(1, screen.height() - 2 * padding) / max(1, height - 2 * padding))
    if reduction < 1:
        offsets = [(x * reduction, y * reduction) for x, y in offsets]
        left, top, width, height = local_bounds(offsets)
    anchor_x = screen.x() + min(1, max(0, center_x)) * screen.width()
    anchor_y = screen.y() + min(1, max(0, center_y)) * screen.height()
    x = max(screen.x(), min(round(anchor_x + left), screen.x() + screen.width() - width))
    y = max(screen.y(), min(round(anchor_y + top), screen.y() + screen.height() - height))
    points = tuple(QPointF(px - left, py - top) for px, py in offsets)
    return QRect(x, y, width, height), points


def draw_hand(painter: QPainter, hand: Hand, points, numbers: bool, label: bool = False):
    color = QColor("#55e6c1" if hand.label == "Right" else "#7db9ff")
    for stroke, thickness in ((QColor("#12252e"), 7), (color, 3)):
        painter.setPen(QPen(stroke, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a, b in CONNECTIONS:
            painter.drawLine(points[a], points[b])
    for i, point in enumerate(points):
        painter.setPen(QPen(QColor("#10212a"), 2))
        painter.setBrush(QColor("#fff1ad") if i in TIPS else color)
        radius = 6 if i in TIPS else 4
        painter.drawEllipse(point, radius, radius)
        if numbers:
            painter.setPen(QColor("#ffffff"))
            painter.drawText(point + QPointF(8, -8), str(i))
    if label:
        painter.setPen(color)
        painter.drawText(points[0] + QPointF(12, 24), "오른손" if hand.label == "Right" else "왼손")


class DesktopHandWindow(QWidget):
    """A hand-sized transparent native window, with no fullscreen surface."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("손 랜드마크 · 바탕화면 손")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowTransparentForInput
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.hand = None
        self.points = ()
        self.numbers = False
        self._target = ()
        self._shown = ()
        self._image = None
        self._screen = None
        self._capacity = (0, 0)
        self._surface = None
        if os.name == "nt":
            from native_surface import LayeredSurface
            self._surface = LayeredSurface()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)

    def isVisible(self):
        return self._surface.visible if self._surface else super().isVisible()

    def show_hand(self, hand: Hand, screen, aspect: float, scale: float, numbers: bool,
                  smooth_motion: bool = True):
        geometry, points = desktop_geometry(hand, screen.geometry(), aspect, scale)
        target = tuple(QPointF(p.x() + geometry.x(), p.y() + geometry.y()) for p in points)
        if self._target and smooth_motion:
            old = tuple(sum(self._target[i].x() if axis == 0 else self._target[i].y()
                            for i in PALM) / 5 for axis in (0, 1))
            new = tuple(sum(target[i].x() if axis == 0 else target[i].y()
                            for i in PALM) / 5 for axis in (0, 1))
            if math.dist(old, new) < 2:
                target = tuple(p + QPointF(old[0] - new[0], old[1] - new[1]) for p in target)
        self.hand, self.numbers, self._screen = hand, numbers, screen
        self._target = target
        if not self._shown or not smooth_motion:
            self._shown = target
        self.advance()
        if smooth_motion and not self.timer.isActive():
            self.timer.start()
        elif not smooth_motion:
            self.timer.stop()

    def advance(self, dt: float = 1 / 60, snap: bool = False):
        if not self.hand:
            return
        gain = 1.0 if snap else 1 - math.exp(-dt / 0.024)
        self._shown = tuple(a + (b - a) * gain for a, b in zip(self._shown, self._target))
        xs, ys = [p.x() for p in self._shown], [p.y() for p in self._shown]
        screen = self._screen.geometry()
        # Grow in blocks, then retain the backing dimensions. Finger movement no longer
        # resizes the transparent surface continuously or copies an old frame into it.
        width = min(screen.width(), max(self._capacity[0], math.ceil((max(xs) - min(xs) + 64) / 64) * 64))
        height = min(screen.height(), max(self._capacity[1], math.ceil((max(ys) - min(ys) + 64) / 64) * 64))
        self._capacity = (width, height)
        x = max(screen.x(), min(round((min(xs) + max(xs) - width) / 2), screen.x() + screen.width() - width))
        y = max(screen.y(), min(round((min(ys) + max(ys) - height) / 2), screen.y() + screen.height() - height))
        self.points = tuple(p - QPointF(x, y) for p in self._shown)
        geometry = QRect(x, y, width, height)
        if self.size() != geometry.size():
            self.resize(width, height)
        if self.pos() != geometry.topLeft():
            self.move(x, y)
        ratio = self._screen.devicePixelRatio()
        image = QImage(round(width * ratio), round(height * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_hand(painter, self.hand, self.points, self.numbers)
        painter.end()
        self._image = image
        if self._surface:
            self._surface.present(image, geometry, self._screen)
        else:
            if not super().isVisible():
                self.show()
            self.update(self.rect())

    def clear_hand(self):
        self.timer.stop()
        if self._surface:
            self._surface.hide()
        else:
            self.hide()
        self.hand, self.points = None, ()
        self._shown, self._target = (), ()
        self._image = None

    def closeEvent(self, event):
        self.clear_hand()
        if self._surface:
            self._surface.close()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self._image is not None:
            painter.drawImage(QPointF(0, 0), self._image)


class LandmarkWindow(QWidget):
    """Preview and owner of at most two independently moving desktop hands."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("손 랜드마크 · 표시창")
        self.resize(900, 675)
        self.snapshot = Snapshot()
        self.overlay = False
        self.numbers = False
        self.scale = 1.0
        self.smooth_motion = True
        self._screen = None
        self.desktop_windows = []

    def set_snapshot(self, snapshot: Snapshot):
        if snapshot == self.snapshot:
            return
        self.snapshot = snapshot
        self.refresh_display()

    def set_scale(self, percent: int):
        self.scale = percent / 100
        self.refresh_display()

    def refresh_display(self):
        if not self.overlay:
            self.update()
            return
        if not self.desktop_windows:
            self.desktop_windows = [DesktopHandWindow(), DesktopHandWindow()]
        available = list(self.desktop_windows)
        for hand in self.snapshot.hands[:2]:
            same_id = [window for window in available if hand.track_id and window.hand
                       and window.hand.track_id == hand.track_id]
            same_label = same_id or [window for window in available
                                    if window.hand and window.hand.label == hand.label]
            window = min(same_label, key=lambda w: sum((a - b) ** 2 for a, b in
                         zip(palm_center(w.hand), palm_center(hand)))) if same_label else available[0]
            available.remove(window)
            window.show_hand(hand, self._screen, self.snapshot.aspect, self.scale, self.numbers, self.smooth_motion)
        for window in available:
            window.clear_hand()

    def set_overlay(self, enabled: bool, screen):
        self.overlay = enabled
        self._screen = screen
        if enabled:
            self.hide()
            self.refresh_display()
        else:
            for window in self.desktop_windows:
                window.clear_hand()
            self.show()
            self.update()

    def closeEvent(self, event):
        for window in self.desktop_windows:
            window.clear_hand()
            window.close()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101923"))
        bounds = fit_rect(self.width(), self.height(), self.snapshot.aspect)
        painter.setPen(QPen(QColor("#243342"), 1))
        for i in range(1, 8):
            x = bounds.left() + bounds.width() * i / 8
            painter.drawLine(QPointF(x, bounds.top()), QPointF(x, bounds.bottom()))
        for i in range(1, 6):
            y = bounds.top() + bounds.height() * i / 6
            painter.drawLine(QPointF(bounds.left(), y), QPointF(bounds.right(), y))
        painter.setPen(QColor("#ccd9e6"))
        painter.drawText(22, 30, "HAND LANDMARK LAB  ·  영상 없이 점과 선만 표시")
        painter.drawText(22, self.height() - 20, self.snapshot.error or self.snapshot.status)
        for hand in self.snapshot.hands:
            points = [screen_point(p, bounds) for p in hand.points]
            draw_hand(painter, hand, points, self.numbers, label=True)
