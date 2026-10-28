"""Connect hand contacts to character movement and the desktop ball, without mood effects."""
import math
import time

from PyQt6.QtCore import QObject, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from app_logging import log_event, log_throttled, new_trace_id
from .interactions import Box, HandInteractionEngine


class ContactFeedback(QWidget):
    def __init__(self, character):
        super().__init__(character)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.advance)
        self.hide()

    def pulse(self, kind, point):
        self.kind, self.started = kind, time.monotonic()
        self.point = QPointF(point[0] - self.parent().x(), point[1] - self.parent().y())
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def advance(self):
        if time.monotonic() - self.started >= .55:
            self.clear()
        else:
            self.update()

    def clear(self):
        self.timer.stop()
        self.hide()

    def paintEvent(self, _event):
        phase = min(1., (time.monotonic() - self.started) / .55)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 - phase)
        p = self.point + QPointF(14 if self.kind == 'pet' else 0, -phase * 18)
        if self.kind == 'pet':
            path = QPainterPath(p + QPointF(0, 4))
            path.cubicTo(p + QPointF(-18, -6), p + QPointF(-10, -20), p + QPointF(0, -10))
            path.cubicTo(p + QPointF(10, -20), p + QPointF(18, -6), p + QPointF(0, 4))
            painter.setPen(QPen(QColor('#b97589'), 1.2))
            painter.setBrush(QColor('#ffc6d4'))
            painter.drawPath(path)
        else:
            painter.setPen(QPen(QColor('#f0b058'), 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            for i in range(6):
                angle = i * math.pi / 3
                ray = QPointF(math.cos(angle), math.sin(angle))
                painter.drawLine(p + ray * (5 + phase * 8), p + ray * (11 + phase * 8))
        painter.end()


class CharacterHandActions:
    def __init__(self, character):
        self.character = character
        self.mode = None
        self.ball = None
        self.feedback = ContactFeedback(character)
        self._last_feedback = -math.inf

    def available(self):
        c = self.character
        return (not c._character_closing and c.isVisible()
                and not c._manual_control_active()
                and QApplication.activePopupWidget() is None
                and QApplication.activeModalWidget() is None
                and not (getattr(c, 'rps_game', None) and c.rps_game.isVisible())
                and not (getattr(c, 'cham_game', None) and c.cham_game.is_active)
                and (not c.is_dragging or self.mode in ('grab', 'palm')))

    def body_rect(self):
        rect = self.character._physics_body_rect().translated(self.character.pos())
        return Box(rect.x(), rect.y(), rect.width(), rect.height())

    def ball_rect(self):
        ball = self.character.sandbox_manager.ball
        if ball is None or not ball.isVisible() or ball.is_dragging:
            return None
        return Box(ball.x(), ball.y(), ball.width(), ball.height())

    def begin_hold(self, mode, point):
        c = self.character
        if mode == 'ball':
            ball = c.sandbox_manager.ball
            if ball is None or not ball.isVisible() or ball.is_dragging:
                return False
            self.ball = ball
            ball.begin_hand_drag(point)
            c._ball_chasing = False
        else:
            if c.is_dragging:
                return False
            self.offset = (point[0] - c.x(), point[1] - c.y())
            self.palm_offset = self.body_rect().center[0] - point[0]
            c.is_dragging = True
            c._hand_control_mode = mode
            c.drag_pos = QPoint(round(point[0]), round(point[1]))
            c.drag_time = 0
            c._drag_velocity_x = c._drag_velocity_y = 0
            c._drag_trace_id = new_trace_id('hand-hold')
            c._drag_start_position = (c.x(), c.y())
            c._move_timer.stop()
            c.animation_controller.idle.stop()
            c.is_moving = c.is_jumping = c.on_ground = False
            c._ball_chasing = False
            c.current_surface = None
            c.velocity_x = c.velocity_y = 0
            c._physics_position_x = c._physics_position_y = c._jump_physics_y = None
            c.sprite_animator.stop()
            c.current_action = 'idle' if mode == 'palm' else 'hovering'
            c.update_render(c.current_action)
        self.mode = mode
        c._mark_character_interaction()
        log_event('hand_interaction.hold.started', '손으로 대상 잡기 시작',
                  category='캐릭터 상태', mode=mode)
        self.move_hold(mode, point)
        return True

    def hold_valid(self, mode):
        if mode == 'ball':
            return (self.ball is not None and self.ball.isVisible()
                    and self.character.sandbox_manager.ball is self.ball)
        return self.character.is_dragging and getattr(self.character, '_hand_control_mode', None) == mode

    def move_hold(self, mode, point):
        c = self.character
        if mode == 'ball':
            self.ball.move_hand_drag(point)
            return
        if mode == 'palm':
            body = self.body_rect()
            x = c.x() + point[0] + self.palm_offset - body.center[0]
            y = c.y() + point[1] - body.bottom
        else:
            x, y = point[0] - self.offset[0], point[1] - self.offset[1]
        c.move(round(x), round(y))
        c._clamp_position_to_screen()
        c.animation_controller.update_base_pos(c.pos())
        c.dialogue_system.update_dialogue_position()
        c._mark_character_interaction()

    def end_hold(self, reason, velocity):
        c = self.character
        mode, self.mode = self.mode, None
        if mode == 'ball':
            ball, self.ball = self.ball, None
            if ball is not None:
                ball.end_hand_drag(velocity, reason=reason)
        elif mode is not None:
            c._hand_control_mode = None
            c._drag_velocity_x = c._drag_velocity_y = 0
            if c._character_closing:
                c.is_dragging = False
            elif c.is_dragging:
                c.mouseReleaseEvent(None)  # Existing jump reset, gravity and landing path.
        if mode:
            log_event('hand_interaction.hold.finished', '손으로 잡은 대상 놓기',
                      category='캐릭터 상태', mode=mode, reason=reason)

    def pet(self, speed, elapsed, point):
        c = self.character
        c._mark_character_interaction()
        self.react('pet', point)

    def poke(self, point):
        c = self.character
        body = self.body_rect()
        direction = 1 if point[0] < body.center[0] else -1
        c._move_timer.stop()
        c.animation_controller.idle.stop()
        c.is_moving = c._ball_chasing = False
        # A small nudge plus the existing damped horizontal physics. Never
        # emulate a mouse click: that would change mood and start a drag.
        c.move(c.x() + direction * max(3, round(body.width * .04)), c.y())
        c._clamp_position_to_screen()
        c._physics_position_x = None
        c.velocity_x = direction * 2.0
        c.animation_controller.update_base_pos(c.pos())
        c.dialogue_system.update_dialogue_position()
        c._mark_character_interaction()
        self.react('poke', point)
        log_event('hand_interaction.cheek.poked', '손끝으로 볼 콕 찌르기', category='캐릭터 상태')

    def react(self, kind, point):
        now = time.monotonic()
        if kind == 'pet' and now - self._last_feedback < .4:
            return
        self._last_feedback = now
        self.feedback.pulse(kind, point)


class HandInteractionController(QObject):
    def __init__(self, character, overlay, *, clock=time.monotonic):
        super().__init__(character)
        self.overlay = overlay
        self._clock = clock
        self.actions = CharacterHandActions(character)
        self.engine = HandInteractionEngine(self.actions)
        overlay.timer.timeout.connect(self.update)
        overlay.hands_cleared.connect(self.cancel)
        overlay.tracking_interrupted.connect(self.interrupt_tracking)

    def interrupt_tracking(self):
        self.engine.interrupt_tracking(self._clock())
        self.actions.feedback.clear()

    def cancel(self, reason='tracking_reset'):
        self.engine.reset(reason, self._clock())
        self.actions.feedback.clear()

    def update(self):
        try:
            previous = self.engine.active
            self.engine.update(self.overlay.displayed_hands(), self._clock(),
                               (self.overlay._session, self.overlay._sequence))
            if (previous and self.engine.active and previous != self.engine.active
                    and previous[0] == self.engine.active[0]):
                log_event('hand_interaction.hold.reconnected', '잠깐 끊긴 손 추적을 잡기에 다시 연결',
                          category='캐릭터 상태', mode=previous[0],
                          previous_track=previous[1], current_track=self.engine.active[1])
        except (RuntimeError, OSError, ValueError) as exc:
            self.cancel('interaction_error')
            log_throttled('hand_interaction.failed', '손 상호작용 처리 실패',
                          key='hand-interaction', interval=10, level='WARNING', error=str(exc))
