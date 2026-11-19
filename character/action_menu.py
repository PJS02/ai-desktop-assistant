"""Nearby actions for the character's games, chat, emotion and memory."""
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QIcon
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
                             QStyle, QStyleOptionToolButton, QStylePainter, QToolButton)

from app_logging import log_event


def action_menu_position(body, size, available, avoid=()):
    """Prefer above the visible character, then find an unobstructed screen edge."""
    bounds = available.adjusted(8, 8, -8, -8)
    x = body.center().x() - size.width() // 2
    obstacles = [body, *avoid]
    candidates = [QPoint(x, body.top() - size.height() - 12)]
    candidates += [QPoint(x, rect.top() - size.height() - 8) for rect in avoid]
    candidates += [QPoint(x, body.bottom() + 12),
                   QPoint(body.left() - size.width() - 12, body.top()),
                   QPoint(body.right() + 12, body.top())]
    candidates += [QPoint(x, rect.bottom() + 8) for rect in avoid]
    placements = []
    for point in candidates:
        point = QPoint(max(bounds.left(), min(point.x(), bounds.right() - size.width() + 1)),
                       max(bounds.top(), min(point.y(), bounds.bottom() - size.height() + 1)))
        rect = QRect(point, size)
        overlap = sum(rect.intersected(other).width() * rect.intersected(other).height()
                      for other in obstacles if rect.intersects(other))
        if not overlap:
            return point
        placements.append((overlap, point))
    return min(placements, key=lambda item: item[0])[1]


@lru_cache(maxsize=6)
def action_icon(kind):
    directory = Path(__file__).resolve().parent.parent / 'assets/ui/character_actions'
    return QIcon(str(directory / f'{kind}.svg'))


class _ActionButton(QToolButton):
    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.toolButtonStyle = Qt.ToolButtonStyle.ToolButtonIconOnly
        option.text = ''
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)

        name, _, action = self.text().partition('\n')
        enabled = self.isEnabled()
        font = self.font()
        painter.setPen(QColor('#273542' if enabled else '#65717c'))
        painter.setFont(font)
        painter.drawText(QRect(0, 32 if action else 36, self.width(), 18),
                         Qt.AlignmentFlag.AlignCenter, name)

        font.setPixelSize(11)
        font.setBold(False)
        painter.setPen(QColor('#515e6a' if enabled else '#65717c'))
        painter.setFont(font)
        painter.drawText(QRect(0, 49, self.width(), 15), Qt.AlignmentFlag.AlignCenter, action)


class CharacterActionMenu(QFrame):
    closed = pyqtSignal(str)

    def __init__(self, character):
        super().__init__(character, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.character = character
        self.setWindowTitle('캐릭터 상호작용')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._dispatching = False
        self._opened = False
        self._close_reason = 'dismissed'
        self._callbacks = {}
        self.buttons = {}
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        panel = QFrame(self)
        panel.setObjectName('characterActions')
        panel.setStyleSheet('''
            QFrame#characterActions { background: #ffffff; border: 1px solid #cbd3dc;
                border-radius: 9px; }
            QToolButton { background: #ffffff; border: 1px solid #d6e0ea;
                border-radius: 6px; padding: 0; padding-bottom: 32px; }
            QToolButton[infoAction="true"] { background: #f4f7fb; }
            QToolButton:hover, QToolButton[infoAction="true"]:hover {
                background: #e8f0fa; border-color: #a6b5c4;
            }
            QToolButton:pressed { background: #cdd6de; }
            QToolButton:focus { border: 2px solid #4d6b89; }
            QToolButton:disabled { background: #f0f3f7; }
        ''')
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(25, 45, 69, 30))
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)
        grid = QGridLayout(panel)
        grid.setContentsMargins(7, 7, 7, 7)  # The panel border adds the remaining pixel.
        grid.setSpacing(6)
        font = QFont('Malgun Gothic')
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        for index, key in enumerate(('cham', 'rps', 'ball', 'talk', 'emotion', 'memory')):
            button = _ActionButton(panel)
            button.setProperty('infoAction', index >= 3)
            button.setFont(font)
            button.setFixedSize(72, 68)
            button.setIcon(action_icon(key))
            button.setIconSize(QSize(24, 24))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, action=key: self.select_action(action))
            button.installEventFilter(self)
            self.buttons[key] = button
            grid.addWidget(button, index // 3, index % 3)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)

    def _game_action(self, name, title, start, end, finished):
        game = getattr(self.character, name + '_game', None)
        state = getattr(game, 'state', 'idle')
        label = title + '\n시작'
        if game is not None and game.isVisible() and state != 'idle':
            if state in finished:
                label = title + '\n다시 하기'
            else:
                return title + '\n끝내기', end, ''
        if name == 'cham' and (self.character.is_dragging or self.character.is_jumping
                               or not self.character.on_ground):
            return label, None, '착지한 뒤 참참참을 시작할 수 있어요.'
        return label, start, ''

    def refresh(self):
        c = self.character
        ball = c.sandbox_manager.ball
        actions = {
            'talk': ('채팅하기', c.dialogue_system.open_input_dialog, ''),
            'cham': self._game_action('cham', '참참참', c.show_cham_game, c.end_cham_game,
                                      {'finished', 'error'}),
            'rps': self._game_action('rps', '가위바위보', c.show_rps_game, c.end_rps_game,
                                     {'result', 'error'}),
            'ball': ('공\n치우기', ball.close, '') if ball is not None else ('공\n꺼내기', c.select_ball, ''),
            'emotion': ('감정 표시', c.show_emotion_status, ''),
            'memory': ('기억 표시', c.show_memory_status, ''),
        }
        for key, (text, callback, reason) in actions.items():
            button = self.buttons[key]
            button.setText(text)
            button.setAccessibleName(text.replace('\n', ' '))
            button.setToolTip(reason or text.replace('\n', ' '))
            button.setEnabled(callback is not None and not self._dispatching)
            self._callbacks[key] = callback
        self.adjustSize()
        if self.isVisible():
            self.reposition()

    def reposition(self):
        c = self.character
        body = c._physics_body_rect().translated(c.pos())
        screen = QApplication.screenAt(body.center()) or c.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        dialogue = c.dialogue_system
        widgets = [getattr(c, name, None) for name in
                   ('rps_game', 'cham_game', '_emotion_status', '_memory_status')]
        widgets += [getattr(dialogue, name, None) for name in
                    ('current_dialogue', 'current_user_dialogue', 'current_narration', 'current_input_widget')]
        avoid = [widget.geometry() for widget in widgets if widget is not None and widget.isVisible()]
        self.move(action_menu_position(body, self.size(), screen.availableGeometry(), avoid))

    def show_for_character(self):
        if self._dispatching:
            return
        self.refresh()
        self.reposition()
        self._close_reason = 'dismissed'
        self._opened = True
        self.show()
        self.raise_()
        self.buttons['talk'].setFocus(Qt.FocusReason.PopupFocusReason)
        self.timer.start()
        log_event('character.action_menu.opened', '캐릭터 상호작용 메뉴 열기', category='캐릭터 상태')

    def dismiss(self, reason):
        self._close_reason = reason
        self.hide()

    def select_action(self, key):
        if self._dispatching:
            return
        self.refresh()
        callback = self._callbacks.get(key)
        if callback is None:
            return
        label = self.buttons[key].accessibleName()
        self._dispatching = True
        self.dismiss('selected')
        log_event('character.action_menu.selected', '캐릭터 상호작용 선택',
                  category='캐릭터 상태', action=label)

        def run():
            try:
                if not self.character._character_closing:
                    callback()
            except Exception as error:
                log_event('character.action_menu.failed', '캐릭터 상호작용 실행 실패',
                          category='오류', level='ERROR', action=label, error=str(error))
                if not self.character._character_closing:
                    self.character.dialogue_system.show_dialogue('동작을 시작하지 못했어요. 다시 선택해주세요.')
            finally:
                self._dispatching = False

        QTimer.singleShot(0, run)

    def hideEvent(self, event):
        self.timer.stop()
        if self._opened:
            self._opened = False
            reason = self._close_reason
            body = self.character._physics_body_rect().translated(self.character.pos())
            if (reason == 'dismissed' and body.contains(QCursor.pos())
                    and QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                reason = 'character_click'
            self.closed.emit(reason)
            log_event('character.action_menu.closed', '캐릭터 상호작용 메뉴 닫기',
                      category='캐릭터 상태', reason=reason)
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if not self.rect().contains(event.position().toPoint()):
            body = self.character._physics_body_rect().translated(self.character.pos())
            reason = 'character_click' if body.contains(event.globalPosition().toPoint()) else 'outside_click'
            self.dismiss(reason)
            event.accept()
            return
        super().mousePressEvent(event)

    def _key(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss('escape')
            return True
        buttons = list(self.buttons.values())
        current = next((index for index, button in enumerate(buttons) if button.hasFocus()), 3)
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1,
                Qt.Key.Key_Up: -3, Qt.Key.Key_Down: 3}.get(event.key())
        if step is not None:
            if abs(step) == 3:
                candidates = [buttons[(current + step) % len(buttons)]]
            else:
                candidates = [buttons[(current + step * offset) % len(buttons)]
                              for offset in range(1, len(buttons))]
            target = next((button for button in candidates if button.isEnabled()), None)
            if target is not None:
                target.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            buttons[current].click()
            return True
        return False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and self._key(event):
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if self._key(event):
            event.accept()
        else:
            super().keyPressEvent(event)
