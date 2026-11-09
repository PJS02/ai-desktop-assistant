"""Recognize deliberate horizontal shaking independently of mouse event rate."""
from collections import deque


class DragShakeDetector:
    WINDOW_SECONDS = 1.4
    COOLDOWN_SECONDS = 1.8
    MIN_SPEED = 350.

    def __init__(self, min_travel=28.):
        self.min_travel = max(24., float(min_travel))
        self.last_trigger = float('-inf')
        self.reset(0., 0., 0.)

    def reset(self, x, y, now):
        self.x, self.y, self.at = x, y, now
        self.direction = 0
        self.turns = deque()
        self.last_sample = now

    def update(self, x, y, now):
        if now < self.last_sample or now-self.last_sample > .35:
            self.reset(x, y, now)
            return False
        self.last_sample = now
        dx = x-self.x
        if self.direction == 0:
            if abs(dx) >= self.min_travel:
                self.direction = 1 if dx > 0 else -1
                self.x, self.y, self.at = x, y, now
            return False
        if dx*self.direction >= 0:
            self.x, self.y, self.at = x, y, now
            return False
        if abs(dx) < self.min_travel:
            return False
        speed = abs(dx)/max(.001, now-self.at)
        horizontal = abs(y-self.y) <= max(20., abs(dx)*.8)
        self.direction *= -1
        self.x, self.y, self.at = x, y, now
        while self.turns and now-self.turns[0] > self.WINDOW_SECONDS:
            self.turns.popleft()
        if not horizontal or speed < self.MIN_SPEED:
            self.turns.clear()
            return False
        self.turns.append(now)
        if len(self.turns) >= 3 and now-self.last_trigger >= self.COOLDOWN_SECONDS:
            self.last_trigger = now
            self.turns.clear()
            return True
        return False
