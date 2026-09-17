"""Sandbox item and physics interaction controller."""
from dataclasses import dataclass
import random
import time

from PyQt6.QtCore import QPoint, QRect, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import QApplication, QWidget


@dataclass(frozen=True)
class SandboxItem:
    item_id: str
    name: str
    cooldown_seconds: float = 1.0


class BallWidget(QWidget):
    """A small generated ball with simple desktop physics."""

    SIZE = 44

    def __init__(self, manager):
        super().__init__(None)
        self.manager = manager
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        character = manager.character_widget
        self.x_velocity = 4.5 if character.x() < manager.screen_center_x else -4.5
        self.y_velocity = -8.0
        self.is_dragging = False
        self._drag_offset = QPoint()
        self._last_drag_pos = QPoint()
        self._last_collision_at = 0.0
        self.interaction_enabled = False

        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self._update_physics)
        self.physics_timer.start(16)

    def spawn(self):
        character = self.manager.character_widget
        spawn_x = character.x() + (character.width() - self.width()) // 2
        spawn_y = max(0, character.y() - self.height() - 8)
        spawn_x = max(self.manager.screen_left, min(spawn_x, self.manager.screen_right - self.width()))
        spawn_y = max(self.manager.screen_top, min(spawn_y, self.manager.screen_bottom - self.height()))
        self.move(spawn_x, spawn_y)
        self.show()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        gradient = QRadialGradient(14, 12, 32)
        gradient.setColorAt(0.0, QColor(255, 245, 190))
        gradient.setColorAt(0.35, QColor(255, 190, 45))
        gradient.setColorAt(1.0, QColor(205, 75, 15))
        painter.setPen(QColor(120, 45, 10))
        painter.setBrush(gradient)
        painter.drawEllipse(3, 3, self.SIZE - 6, self.SIZE - 6)

        painter.setPen(QColor(255, 255, 255, 180))
        painter.drawEllipse(12, 9, 7, 5)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self._drag_offset = event.position().toPoint()
            self._last_drag_pos = event.globalPosition().toPoint()
            self.x_velocity = 0
            self.y_velocity = 0
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self._last_drag_pos
            self.move(current_pos - self._drag_offset)
            self.x_velocity = delta.x()
            self.y_velocity = delta.y()
            self._last_drag_pos = current_pos
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            if self.manager.can_interact_with_ball(self):
                self.manager.character_widget.mood_system.on_ball_play()
            event.accept()

    def _update_physics(self):
        if self.is_dragging:
            return

        character = self.manager.character_widget
        screen_left = self.manager.screen_left
        screen_right = self.manager.screen_right
        screen_top = self.manager.screen_top
        screen_bottom = self.manager.screen_bottom
        next_x = self.x() + self.x_velocity
        next_y = self.y() + self.y_velocity
        self.y_velocity += 0.42

        if next_x <= screen_left or next_x + self.width() >= screen_right:
            next_x = max(screen_left, min(next_x, screen_right - self.width()))
            self.x_velocity *= -0.78
        if next_y + self.height() >= screen_bottom:
            next_y = screen_bottom - self.height()
            self.y_velocity *= -0.72
            self.x_velocity *= 0.96
        elif next_y <= screen_top:
            next_y = screen_top
            self.y_velocity = abs(self.y_velocity) * 0.7

        self.move(int(next_x), int(next_y))
        self.manager.update_character_chase(self)
        self._check_character_collision(character)

    def _check_character_collision(self, character):
        ball_rect = QRect(self.x(), self.y(), self.width(), self.height())
        character_rect = QRect(character.x(), character.y(), character.width(), character.height())
        if not ball_rect.intersects(character_rect):
            return

        if not self.manager.can_interact_with_ball(self):
            return

        now = time.monotonic()
        if now - self._last_collision_at < 0.8:
            return

        self._last_collision_at = now
        ball_center_x = self.x() + self.width() // 2
        character_center_x = character.x() + character.width() // 2
        kick_direction = 1 if ball_center_x >= character_center_x else -1
        self.x_velocity = 14.0 * kick_direction
        self.y_velocity = -9.0
        character.mood_system.on_ball_play()
        character.update_action(character.mood_system.decide_emotion())
        self.manager.start_interaction_cooldown(self)

    def closeEvent(self, event):
        self.physics_timer.stop()
        self.manager.character_widget._ball_session_active = False
        self.manager.character_widget._ball_chasing = False
        if not self.manager.character_widget.is_dragging:
            self.manager.character_widget.sprite_animator.stop()
            self.manager.character_widget.update_action(
                self.manager.character_widget.mood_system.decide_emotion()
            )
        if self.manager.ball is self:
            self.manager.ball = None
        super().closeEvent(event)


class SandboxManager:
    """Tracks the selected sandbox item without moving files on disk."""

    def __init__(self, character_widget):
        self.character_widget = character_widget
        self.selected_item = None
        self.ball = None
        self._last_used_at = {}
        self.items = {
            "ball": SandboxItem("ball", "공", cooldown_seconds=1.0),
        }
        self._cooldown_until = 0.0
        self._warmup_timer = None

        self._refresh_screen_bounds()

    def _refresh_screen_bounds(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            self.screen_left = geometry.left()
            self.screen_top = geometry.top()
            self.screen_right = geometry.right() + 1
            self.screen_bottom = geometry.bottom() + 1
        else:
            width, height = self.character_widget._get_screen_dimensions()
            self.screen_left = 0
            self.screen_top = 0
            self.screen_right = width
            self.screen_bottom = height

        self.screen_center_x = (self.screen_left + self.screen_right) // 2

    def select_ball(self) -> str:
        self.selected_item = self.items["ball"]
        self._refresh_screen_bounds()
        if self.ball is not None:
            self.ball.close()
        self.character_widget._ball_session_active = True
        self.character_widget._ball_chasing = False
        if self.character_widget.is_moving:
            self.character_widget._move_timer.stop()
            self.character_widget.is_moving = False
        self.character_widget.sprite_animator.stop()
        self.ball = BallWidget(self)
        self.ball.spawn()
        self.ball.interaction_enabled = False
        self._warmup_timer = QTimer(self.character_widget)
        self._warmup_timer.setSingleShot(True)
        self._warmup_timer.timeout.connect(self._enable_ball_interaction)
        self._warmup_timer.start(3000)
        self.clear_selection()
        return None

    def clear_selection(self) -> None:
        self.selected_item = None

    def update_character_chase(self, ball: BallWidget) -> None:
        """Keep the character moving toward the ball while it is active."""
        if not self.can_interact_with_ball(ball):
            return
        self.character_widget.move_toward_ball(
            ball.x() + ball.width() // 2
        )

    def can_interact_with_ball(self, ball: BallWidget) -> bool:
        """Return whether the ball is past warmup and interaction cooldown."""
        return self.ball is ball and ball.interaction_enabled and time.monotonic() >= self._cooldown_until

    def _enable_ball_interaction(self) -> None:
        if self.ball is not None:
            self.ball.interaction_enabled = True

    def start_interaction_cooldown(self, ball: BallWidget) -> None:
        cooldown_seconds = random.uniform(3.0, 10.0)
        self._cooldown_until = time.monotonic() + cooldown_seconds
        ball.interaction_enabled = False
        self.character_widget._ball_chasing = False
        print(f"[공 상호작용 쿨타임] {cooldown_seconds:.2f}초")

        QTimer.singleShot(
            int(cooldown_seconds * 1000),
            lambda: self._resume_ball_interaction(ball),
        )

    def _resume_ball_interaction(self, ball: BallWidget) -> None:
        if self.ball is ball and self.character_widget._ball_session_active:
            ball.interaction_enabled = True

    def use_selected_item(self) -> str | None:
        item = self.selected_item
        if item is None:
            return None

        now = time.monotonic()
        last_used_at = self._last_used_at.get(item.item_id, 0.0)
        if now - last_used_at < item.cooldown_seconds:
            return None

        self._last_used_at[item.item_id] = now
        self.clear_selection()

        if item.item_id == "ball":
            self.character_widget.mood_system.on_ball_play()
            self.character_widget.jump()
            return None

        return None
