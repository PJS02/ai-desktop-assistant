"""Foreground-window occlusion and a non-destructive paper-tear escape."""
import math
import os
import time
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QPointF, QRect, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from .hide_and_seek import smooth


def covered_fraction(body, window):
    area = body.width() * body.height()
    overlap = body.intersected(window)
    return overlap.width() * overlap.height() / area if area > 0 and not overlap.isEmpty() else 0.


def _window_is_cloaked(hwnd):
    """IsWindowVisible also reports windows hidden on other virtual desktops."""
    import ctypes
    from ctypes import wintypes
    try:
        query = ctypes.windll.dwmapi.DwmGetWindowAttribute
        query.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
        query.restype = ctypes.c_long
        value = wintypes.DWORD()
        return query(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) == 0 and bool(value.value)
    except (AttributeError, OSError):
        return False


def foreground_window():
    """Only inspect the user's foreground window; never activate or alter it."""
    if os.name != 'nt':
        return None
    import win32gui
    import win32process
    from .desktop_geometry import logical_window
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return None
        if win32process.GetWindowThreadProcessId(hwnd)[1] == os.getpid():
            return None
        if win32gui.GetClassName(hwnd) in {'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Progman', 'WorkerW'}:
            return None
        # Transparent/layered overlays aren't evidence of opaque window coverage.
        if (not win32gui.GetWindowText(hwnd).strip() or _window_is_cloaked(hwnd)
                or win32gui.GetWindowLong(hwnd, -20) & (0x20 | 0x80000)):
            return None
        x, y, right, bottom = win32gui.GetWindowRect(hwnd)
        window = logical_window(SimpleNamespace(_hWnd=hwnd, left=x, top=y, width=right-x, height=bottom-y))
        return hwnd, QRect(window.left, window.top, window.width, window.height)
    except (OSError, win32gui.error):
        return None


def occluding_window(host):
    """Only the foreground application can initiate simulated occlusion.

    Background rectangles are not evidence that a topmost pet is hidden.
    If a support window is known, the foreground must also precede that support
    in native Z order. Failed native queries leave the pet visible.
    """
    if os.name != 'nt':
        return None
    import win32gui
    observed = foreground_window()
    if observed is None:
        return None
    hwnd, rectangle = observed
    body = host._physics_body_rect().translated(host.pos())
    if not body.intersects(rectangle):
        return None
    key = str(getattr(getattr(host, 'current_surface', None), 'source_key', ''))
    support = int(key.split(':', 1)[1]) if key.startswith('hWnd:') else None
    if hwnd == support:
        return None
    if support is None:
        return observed
    windows = []
    try:
        win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd) or True, None)
        if hwnd in windows and support in windows and windows.index(hwnd) < windows.index(support):
            return observed
        return None
    except (OSError, win32gui.error):
        return None


class TearOverlay(QWidget):
    """Only paper edges are drawn: the live foreground window remains intact."""
    def __init__(self, host):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.amount = 0.
        self.opacity = 1.

    def paintEvent(self, event):
        if self.amount <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        cx, cy = self.width()/2, self.height()/2
        rx, ry = self.width()*.38*self.amount, self.height()*.40*self.amount
        points = []
        for i in range(32):
            a = 2*math.pi*i/32
            r = 1.0 + (.055 if i % 2 else -.025)
            points.append(QPointF(cx+rx*r*math.cos(a), cy+ry*r*math.sin(a)))
        polygon = QPolygonF(points)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 70), 13))
        p.drawPolygon(polygon)
        p.setPen(QPen(QColor('#d2dbea'), 7))
        p.drawPolygon(polygon)
        p.setPen(QPen(QColor('#ffffff'), 2))
        p.drawPolygon(polygon)
        # Folded flaps follow the opening rather than covering the character.
        for i in (2, 9, 18, 25):
            a, b = points[i], points[(i+2) % 32]
            tip = QPointF(cx+(a.x()-cx)*1.25, cy+(a.y()-cy)*1.18)
            p.setBrush(QColor('#eef3fa'))
            p.setPen(QPen(QColor('#a8b6ca'), 1))
            p.drawPolygon(QPolygonF([a, b, tip]))
        p.end()


class WindowPresence(QObject):
    HIDDEN_SECONDS = 8.
    COVER_CONFIRM_SECONDS = .3

    def __init__(self, host, observer=None):
        super().__init__(host)
        self.host, self.observer = host, observer or (lambda: occluding_window(host))
        self.cover = None
        self.occluded = False
        self.is_active = False
        self.hidden_since = None
        self._candidate = None
        self._candidate_since = 0.
        self.front_of = None
        self.walk_after_landing = False
        self.overlay = None
        self._frame_view = None
        self._sprite_masked = False
        self._sprite_hidden = False
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    @property
    def blocks_physics(self):
        # A cover can catch the character halfway through a fall. Let gravity
        # find real support before freezing it or starting a standing animation.
        return self.is_active or (self.occluded and self._standing_support() is not None)

    def _standing_support(self):
        h = self.host
        surface = getattr(h, 'current_surface', None)
        if (not h.on_ground or surface is None or getattr(h, 'is_jumping', False)
                or getattr(h, 'velocity_y', 0) != 0
                or surface not in getattr(h, 'surfaces', ())):
            return None
        body = h._physics_body_rect().translated(h.pos())
        if (abs(body.y()+body.height()-surface.y_level) > 2
                or body.right()+1 <= surface.x_min or body.left() >= surface.x_max
                or not self.surface_visible(surface, body.left(), body.right()+1)):
            return None
        return surface

    def _anchor_escape(self):
        """Keep the standing breakout pose planted as its painted bounds change."""
        h = self.host
        surface = self._escape_surface
        body = h._physics_body_rect()
        if (surface not in getattr(h, 'surfaces', ()) or surface.y_level != self._escape_level
                or h.x()+body.x()+body.width() <= surface.x_min
                or h.x()+body.x() >= surface.x_max
                or not self.surface_visible(surface, h.x()+body.x(), h.x()+body.x()+body.width())):
            return False
        bottom = body.y()+body.height()
        h.move(h.x(), round(surface.y_level-bottom))
        h.on_ground, h.current_surface = True, surface
        h.velocity_x = h.velocity_y = 0
        h._grounded_body_bottom, h._grounded_surface_level = bottom, surface.y_level
        h._physics_position_y = float(h.y())
        h._physics_position_x = float(h.x())
        return True

    def surface_visible(self, surface, left, right):
        if not self.cover or not surface.name.startswith('window_'):
            return True
        _, r = self.cover
        # A foreground window's own upper edge remains a valid platform.
        return not (r.top()+3 < surface.y_level < r.bottom()
                    and min(right, surface.x_max, r.right()) > max(left, surface.x_min, r.left()))

    def _apply_clip(self, reveal=None):
        h = self.host
        rects = (self.cover[1].translated(-h.pos()),) if self.cover else ()
        if h.rig_view is not None:
            h.rig_view.set_scene_layer('foreground', occlusions=rects, reveal=reveal, animated=self.is_active)
        elif rects:
            from PyQt6.QtGui import QRegion
            if not self._sprite_masked:
                self._sprite_original_mask = h.mask()
                self._sprite_opacity = h.windowOpacity()
            mask = QRegion(h.rect()).subtracted(QRegion(rects[0]))
            if not self._sprite_original_mask.isEmpty():
                mask &= self._sprite_original_mask
            # Qt treats an empty mask as "no mask", so use opacity for a fully
            # hidden fallback sprite while keeping its event loop alive.
            h.setWindowOpacity(0 if mask.isEmpty() else self._sprite_opacity)
            self._sprite_hidden = mask.isEmpty()
            h.setMask(mask)
            self._sprite_masked = True
        elif self._sprite_masked:
            h.setMask(self._sprite_original_mask) if not self._sprite_original_mask.isEmpty() else h.clearMask()
            h.setWindowOpacity(self._sprite_opacity)
            self._sprite_masked = False
            self._sprite_hidden = False

    def _clear_clip(self):
        if self.host.rig_view is not None:
            self.host.rig_view.clear_scene_layer('foreground')
        if self._sprite_masked:
            h = self.host
            h.setMask(self._sprite_original_mask) if not self._sprite_original_mask.isEmpty() else h.clearMask()
            h.setWindowOpacity(self._sprite_opacity)
            self._sprite_masked = self._sprite_hidden = False

    def poll(self):
        h = self.host
        if h._character_closing:
            self.shutdown()
            return
        if not h.isVisible():
            self.cancel()
            return
        observed = self.observer() if h.window_occlusion else None
        hwnd = observed[0] if observed else None
        previous = self.cover
        # No overlap while walking away must not revoke an escape's immunity.
        if self.front_of is not None and hwnd is not None and hwnd != self.front_of:
            self.front_of = None
        if self.is_active:
            if (not observed or previous is None or observed != previous
                    or h.is_dragging or h._manual_control_active() or h._dialogue_is_busy()
                    or h.rig_view is not self._frame_view):
                self.cancel()
            elif self._frame_view is None:
                self.animate()
            return
        body = h._physics_body_rect().translated(h.pos())
        hide_playing = getattr(getattr(h, 'hide_and_seek', None), 'is_active', False)
        if self.walk_after_landing and h.on_ground and not h.is_dragging and not hide_playing:
            self.walk_after_landing = False
            self.walk_on_support()
        if hide_playing or h.is_dragging or h._manual_control_active() or self.front_of == hwnd or not observed:
            self.cover = observed
            self._candidate = None
            self.occluded = False
            self.hidden_since = None
            self._clear_clip()
            return
        now = time.monotonic()
        if self._candidate != observed:
            self._candidate = (hwnd, QRect(observed[1]))
            self._candidate_since = now
        if now-self._candidate_since < self.COVER_CONFIRM_SECONDS:
            self.cover = None
            self.occluded = False
            self.hidden_since = None
            self._clear_clip()
            return
        self.cover = observed
        fraction = covered_fraction(body, observed[1])
        self.occluded = fraction >= .6
        if fraction > 0:
            self._apply_clip()
        else:
            self._clear_clip()
        if self.occluded:
            # Keep a hidden pet still until its escape; avoid falling invisibly
            # and reappearing at an unrelated location before the effect starts.
            h._move_timer.stop()
            h.is_moving = False
            h.animation_controller.idle.stop()
            if self.hidden_since is None or not previous or previous[0] != hwnd:
                self.hidden_since = now
            if (now-self.hidden_since >= self.HIDDEN_SECONDS and not h._manual_control_active()
                    and not h._dialogue_is_busy() and h.rig_view is not None
                    and not getattr(h, '_ball_session_active', False)
                    and not any(getattr(getattr(h, n, None), 'is_active', False)
                                or (getattr(h, n, None) is not None and getattr(h, n).isVisible())
                                for n in ('cham_game', 'rps_game'))):
                self.begin_escape()
        else:
            self.hidden_since = None
            if self.walk_after_landing and h.on_ground and not h.is_dragging:
                self.walk_after_landing = False
                self.walk_on_support()

    def begin_escape(self):
        h = self.host
        support = self._standing_support()
        if support is None:
            return
        self._escape_surface, self._escape_level = support, support.y_level
        h._cancel_autonomous_behavior()
        h.automatic_actions._release()
        self.saved_override = h.sprite_animator._emotion_override
        self.saved_yaw = h.sprite_animator.yaw
        self.started = time.monotonic()
        self.is_active = True
        h._autonomous_behavior_active = True
        h._rig_manual_action = h.current_action = 'break_out'
        h.velocity_x = h.velocity_y = 0
        h.sprite_animator.set_yaw(0)
        h.sprite_animator.set_emotion_override('excited')
        h.sprite_animator.play('break_out')
        self._anchor_escape()
        body = h._physics_body_rect().translated(h.pos())
        self.overlay = TearOverlay(h)
        self.overlay.setGeometry(body.adjusted(-round(body.width()*.25), -round(body.height()*.12),
                                               round(body.width()*.25), round(body.height()*.12)))
        self.overlay.show()
        self._frame_view = h.rig_view
        self._frame_view.frame_requested.connect(self.animate)
        self._frame_view.failed.connect(self.cancel)
        self.animate()

    def animate(self):
        if not self.is_active:
            return
        h = self.host
        if not self._anchor_escape():
            self.cancel()
            return
        elapsed = time.monotonic()-self.started
        opening = smooth((elapsed-.2)/1.0)
        geometry = self.overlay.geometry()
        center = geometry.center()-h.pos()
        self._apply_clip((center.x(), center.y(), geometry.width()*.38*opening,
                          geometry.height()*.40*opening))
        self.overlay.amount = opening
        self.overlay.opacity = 1-smooth((elapsed-1.6)/.5)
        self.overlay.update()
        if elapsed >= 2.1:
            self.finish(escaped=True)

    def finish(self, escaped=False):
        if not self.is_active:
            return
        h = self.host
        self.is_active = False
        if self._frame_view is not None:
            try:
                self._frame_view.frame_requested.disconnect(self.animate)
                self._frame_view.failed.disconnect(self.cancel)
            except (TypeError, RuntimeError):
                pass
            self._frame_view = None
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None
        self.occluded = False
        self.hidden_since = None
        self._clear_clip()
        h._autonomous_behavior_active = False
        h._rig_manual_action = None
        h.sprite_animator.set_emotion_override(self.saved_override)
        h.sprite_animator.set_yaw(self.saved_yaw)
        if escaped:
            self.front_of = self.cover[0] if self.cover else None
            self.walk_after_landing = True
        h._gravity_last_time = time.monotonic()
        if not h._character_closing:
            h.update_action(h.mood_system.decide_emotion())
            if escaped:
                self._anchor_escape()

    def cancel(self):
        self.finish()
        self.occluded = False
        self.hidden_since = None
        self._candidate = None
        self._clear_clip()

    def walk_on_support(self):
        h = self.host
        surface = h.current_surface
        if surface is None or h._manual_control_active() or h._dialogue_is_busy():
            return
        body = h._physics_body_rect()
        left = surface.x_min-body.left()+8
        right = surface.x_max-body.right()-8
        if right <= left:
            return
        direction = 1 if right-h.x() >= h.x()-left else -1
        target = max(left, min(right, h.x()+direction*120))
        if abs(target-h.x()) < 8:
            return
        h.is_flipped = direction > 0
        h.current_action = 'walk'
        h.sprite_animator.set_direction(h.is_flipped)
        h.sprite_animator.play('walk')
        h._target_x = target
        h._movement_x = float(h.x())
        h._walk_last_time = time.monotonic()
        h.is_moving = True
        h.animation_controller.idle.stop()
        h._move_timer.start(16)

    def shutdown(self):
        self.timer.stop()
        self.cancel()
