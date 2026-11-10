"""A presentation-only entrance, isolated from falling and mood reactions."""
import json
import math
import time

from PyQt6.QtCore import QObject, QTimer

from .config_manager import CONFIG_FILE


class Entrance(QObject):
    RETURN_AFTER_SECONDS = 10 * 60
    PEEK_SECONDS = .45
    RISE_SECONDS = .7
    LOOK_SECONDS = .45
    WAVE_SECONDS = 3.65

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.active = True
        self.started = False
        self.completed = False
        self.path = CONFIG_FILE.with_name('entrance.json')
        self.saved = None
        self.use_peek = True
        self.closed_at = None
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
            point = state['position']
            if len(point) == 2 and all(type(n) in (int, float) and math.isfinite(n) for n in point):
                self.saved = point
                closed_at = state.get('closed_at')
                if type(closed_at) in (int, float) and math.isfinite(closed_at):
                    self.use_peek = not 0 <= time.time() - closed_at < self.RETURN_AFTER_SECONDS
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def start(self):
        if self.started:
            return
        self.started = True
        h = self.host
        h.reactions.cancel()
        h._scan_windows()
        screen = h._get_screen_geometry()
        body = h._physics_body_rect()
        self.bottom = body.y() + body.height()
        x = self.saved[0] if self.saved else screen.x() + screen.width() * .78 - body.center().x()
        x = max(screen.x() - body.x(), min(x, screen.x() + screen.width() - body.x() - body.width()))
        ground = next(s for s in h.surfaces if s.name == 'ground')
        self.surface = ground
        if self.saved and not self.use_peek:
            feet = self.saved[1] + self.bottom
            candidates = [s for s in h.surfaces
                          if s.x_min <= x + body.center().x() <= s.x_max
                          and abs(s.y_level - feet) <= 24]
            if candidates:
                self.surface = min(candidates, key=lambda s: abs(s.y_level - feet))
        self.x, self.y = round(x), self.surface.y_level - self.bottom
        self.peek_y = screen.y() + screen.height() - body.y() - body.height() * .55
        h.move(self.x, round(self.peek_y if self.use_peek else self.y))
        if h.rig_view is not None:
            h.sprite_animator.set_direction(front=True)
        self.pose('peek' if self.use_peek else 'wave')
        self.clock = time.monotonic()
        self.waiting_for_renderer = True
        self.timer.start()

    def pose(self, action):
        h = self.host
        h.current_action = action
        # Native entrance actions leave the existing emotion channels intact.
        if h.rig_view is not None:
            h.sprite_animator.set_mood_emotion(h.mood_system.decide_emotion()['emotion'])
        h.update_render(action if h.rig_view is not None else 'idle')

    @staticmethod
    def ease(value):
        t = max(0., min(1., value))
        return t * t * (3 - 2 * t)

    def tick(self):
        h = self.host
        if self.waiting_for_renderer:
            if (h.rig_view is not None and h.rig_view._program is None
                    and time.monotonic() - self.clock < 2):
                return
            self.waiting_for_renderer = False
            self.clock = time.monotonic()
        t = time.monotonic() - self.clock
        if h.is_dragging:
            self.finish(interrupted=True)
            return
        if self.use_peek:
            y = self.peek_y + (self.y - self.peek_y) * self.ease(
                (t - self.PEEK_SECONDS) / self.RISE_SECONDS)
            h.move(self.x, round(y))
            if t >= self.PEEK_SECONDS + self.RISE_SECONDS and h.current_action == 'peek':
                self.pose('arrive')
        duration = (self.PEEK_SECONDS + self.RISE_SECONDS + self.LOOK_SECONDS
                    if self.use_peek else self.WAVE_SECONDS)
        if t >= duration:
            self.finish()

    def finish(self, interrupted=False):
        h = self.host
        self.timer.stop()
        self.pose('idle')
        body = h._physics_body_rect()
        self.bottom = body.y() + body.height()
        # A support may disappear while the entrance is playing.
        if self.surface not in h.surfaces:
            self.surface = next(s for s in h.surfaces if s.name == 'ground')
        self.y = self.surface.y_level - self.bottom
        if not interrupted:
            h.move(self.x, round(self.y))
            h.current_surface = self.surface
            h.on_ground = True
            h.velocity_x = h.velocity_y = 0
            h._grounded_body_bottom = self.bottom
            h._grounded_surface_level = self.surface.y_level
            h._physics_position_x, h._physics_position_y = float(self.x), float(self.y)
        h._gravity_last_time = time.monotonic()
        self.active = False
        self.completed = True
        h.animation_controller.update_base_pos(h.pos())
        self.save()

    def save(self, position=None):
        if not self.completed and position is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({
                'position': position if position is not None else [self.host.x(), self.host.y()],
                'closed_at': self.closed_at,
            }), encoding='utf-8')
            temporary.replace(self.path)
        except OSError:
            pass

    def close(self):
        self.timer.stop()
        if self.started:
            self.closed_at = time.time()
            # Closing during a peek must not persist the partly offscreen pose.
            position = ([self.host.x(), self.host.y()] if self.completed or self.host.is_dragging
                        else [self.x, self.y])
            self.save(position=position)
