"""Foreground-window occlusion and a non-destructive paper-tear escape."""
import math
import os
import time
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from .desktop_geometry import logical_window, support_span, window_is_cloaked as _window_is_cloaked
from .hide_and_seek import smooth


def covered_fraction(body, window):
    area = body.width() * body.height()
    overlap = QRectF(body).intersected(QRectF(window))
    return overlap.width() * overlap.height() / area if area > 0 and not overlap.isEmpty() else 0.


def foreground_window():
    """Only inspect the user's foreground window; never activate or alter it."""
    if os.name != 'nt':
        return None
    import win32gui
    import win32process
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
        return hwnd, getattr(window, 'clip_rect', QRectF(window.left, window.top, window.width, window.height))
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
    hwnd, _ = observed
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
    def __init__(self, host, body, window):
        super().__init__(host, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        pad_x, pad_y = round(body.width() * .25), round(body.height() * .12)
        full_bounds = body.adjusted(-pad_x, -pad_y, pad_x, pad_y)
        self._center = QRectF(full_bounds).center()
        self._radii = full_bounds.width() * .38, full_bounds.height() * .40
        # Crop the overlay after laying out the full tear, including strokes and flaps.
        self._window_clip = QRectF(window)
        self.setGeometry(full_bounds.adjusted(-7, -7, 7, 7).intersected(self._window_clip.toAlignedRect()))
        self.amount = 0.
        self.opacity = 1.

    def reveal_ellipse(self):
        """Center and radii in desktop coordinates, shared with the rig mask."""
        rx, ry = self._radii
        return self._center.x(), self._center.y(), rx * self.amount, ry * self.amount

    def paintEvent(self, event):
        if self.amount <= 0:
            return
        p = QPainter(self)
        p.setClipRect(self._window_clip.translated(-self.x(), -self.y()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        cx, cy, rx, ry = self.reveal_ellipse()
        cx, cy = cx - self.x(), cy - self.y()
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
        self._candidate_hwnd = None
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
                or support_span(surface, body.left(), body.right()+1) is None):
            return None
        return surface

    def _anchor_escape(self):
        """Keep the standing breakout pose planted as its painted bounds change."""
        h = self.host
        surface = self._escape_surface
        body = h._physics_body_rect()
        left = h.x() + body.x()
        if (surface not in getattr(h, 'surfaces', ()) or surface.y_level != self._escape_level
                or support_span(surface, left, left + body.width()) is None):
            return False
        bottom = body.y()+body.height()
        h.move(h.x(), round(surface.y_level-bottom))
        h.on_ground, h.current_surface = True, surface
        h.velocity_x = h.velocity_y = 0
        h._grounded_body_bottom, h._grounded_surface_level = bottom, surface.y_level
        h._physics_position_y = float(h.y())
        h._physics_position_x = float(h.x())
        return True

    def _apply_clip(self, reveal=None):
        h = self.host
        rects = (self.cover[1],) if self.cover else ()
        if h.rig_view is not None:
            cover_hwnd = self.cover[0] if self.cover and not self.is_active and reveal is None else None
            h.rig_view.set_scene_layer('foreground', occlusions=rects, reveal=reveal,
                                       animated=self.is_active, cover_hwnd=cover_hwnd)
        else:
            self.refresh_sprite_clip()

    def refresh_sprite_clip(self):
        if self.cover is None or self.cover[0] != self._candidate_hwnd:
            return
        from PyQt6.QtGui import QRegion
        h = self.host
        clipped = QRectF(self.cover[1]).toRect().translated(-h.pos()).intersected(h.rect())
        if clipped.isEmpty():
            self._clear_clip()
            return
        if not self._sprite_masked:
            self._sprite_original_mask = h.mask()
            self._sprite_opacity = h.windowOpacity()
            self._sprite_hidden = False
        mask = QRegion(h.rect()).subtracted(QRegion(clipped))
        if not self._sprite_original_mask.isEmpty():
            mask &= self._sprite_original_mask
        # Qt treats an empty mask as "no mask", so hide a fully covered sprite by opacity.
        hidden = mask.isEmpty()
        if hidden and not self._sprite_hidden:
            h.setWindowOpacity(0)
        if h.mask() != mask:
            h.setMask(mask)
        if not hidden and self._sprite_hidden:
            h.setWindowOpacity(self._sprite_opacity)
        self._sprite_hidden = hidden
        self._sprite_masked = True

    def _clear_clip(self):
        if self.host.rig_view is not None:
            self.host.rig_view.clear_scene_layer('foreground')
        if self._sprite_masked:
            h = self.host
            h.setMask(self._sprite_original_mask) if not self._sprite_original_mask.isEmpty() else h.clearMask()
            if self._sprite_hidden:
                h.setWindowOpacity(self._sprite_opacity)
            self._sprite_masked = self._sprite_hidden = False

    def clear_cover(self):
        self.cover = None
        self.occluded = False
        self.hidden_since = None
        self._candidate_hwnd = None
        self._clear_clip()

    def poll(self, *, resume_from_peek=False):
        if getattr(getattr(self.host, 'game_spectator', None), 'is_game_mode', False):
            self.cancel()
            self.walk_after_landing = False
            return
        if getattr(getattr(self.host, 'entrance', None), 'active', False):
            return
        h = self.host
        if h._character_closing:
            self.shutdown()
            return
        if not h.isVisible():
            self.cancel()
            return
        observed = self.observer() if h.window_occlusion else None
        hwnd = observed[0] if observed else None
        window = QRectF(observed[1]) if observed else QRectF()
        # No overlap while walking away must not revoke an escape's immunity.
        body = QRectF(h._physics_body_rect().translated(h.pos()))
        if self.front_of is not None and observed and hwnd != self.front_of and body.intersects(window):
            self.front_of = None
        if self.is_active:
            if (not observed or observed != self.cover or not body.intersects(window)
                    or h.is_dragging or h._manual_control_active() or h._dialogue_is_busy()
                    or h.rig_view is not self._frame_view):
                self.cancel()
            elif self._frame_view is None:
                self.animate()
            return
        hide_playing = not resume_from_peek and getattr(getattr(h, 'hide_and_seek', None), 'is_active', False)
        if (self.walk_after_landing and not h.is_dragging and not hide_playing
                and self._standing_support() is not None):
            self.walk_after_landing = False
            self.walk_on_support()
        if hide_playing or h.is_dragging or h._manual_control_active() or self.front_of == hwnd or not observed:
            self.clear_cover()
            # A visible pet can still stand in front of a window that covers a platform.
            if observed and body.intersects(window):
                self.cover = observed
            return
        fraction = covered_fraction(body, window)
        now = time.monotonic()
        if self._candidate_hwnd != hwnd:
            self._candidate_hwnd = hwnd
            self._candidate_since = now
            self.hidden_since = None
        if resume_from_peek:
            self._candidate_since = now - self.COVER_CONFIRM_SECONDS
        # Debounce the foreground window identity independently of character movement.
        confirmed = resume_from_peek or now >= self._candidate_since + self.COVER_CONFIRM_SECONDS
        self.cover = observed if confirmed else None
        self.occluded = confirmed and fraction >= .6
        if confirmed:
            self._apply_clip()
        else:
            self._clear_clip()
        if self.occluded:
            # Keep a hidden pet still until its escape; avoid falling invisibly
            # and reappearing at an unrelated location before the effect starts.
            h._move_timer.stop()
            h.is_moving = False
            h.animation_controller.idle.stop()
            if self.hidden_since is None:
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

    def begin_escape(self):
        h = self.host
        support = self._standing_support()
        if support is None or not self.cover:
            return
        window = self.cover[1]
        body = h._physics_body_rect().translated(h.pos())
        if not QRectF(body).intersects(QRectF(window)):
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
        self.overlay = TearOverlay(h, body, window)
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
        elapsed = time.monotonic() - self.started
        fade = smooth((elapsed - 1.6) / .5)
        self.overlay.amount = smooth((elapsed - .2) / 1.0)
        cx, cy, rx, ry = self.overlay.reveal_ellipse()
        # Finish revealing the corners before removing the foreground mask.
        spread = 1 + .6 * fade**3
        self._apply_clip((cx, cy, rx * spread, ry * spread))
        self.overlay.opacity = 1 - fade
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
        self.clear_cover()

    def walk_on_support(self):
        h = self.host
        if getattr(getattr(h, 'game_spectator', None), 'is_game_mode', False):
            return
        surface = h.current_surface
        if surface is None or surface not in h.surfaces or h._manual_control_active() or h._dialogue_is_busy():
            return
        body = h._physics_body_rect()
        span = support_span(surface, h.x()+body.left(), h.x()+body.right()+1)
        if span is None:
            return
        left = span[0]-body.left()+8
        right = span[1]-body.right()-1-8
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
        h._walk_surface = surface
        h._movement_x = float(h.x())
        h._walk_last_time = time.monotonic()
        h.is_moving = True
        h.animation_controller.idle.stop()
        h._move_timer.start(16)

    def shutdown(self):
        self.timer.stop()
        self.cancel()
