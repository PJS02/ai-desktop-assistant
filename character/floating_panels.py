"""Keep interactive Cloudy windows above desktop apps and below a dragged character."""

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QApplication, QWidget


_PANEL_PROPERTY = 'cloudyFloatingPanel'
_PRESS_EVENTS = (QEvent.Type.MouseButtonPress, QEvent.Type.NonClientAreaMouseButtonPress)
_ORDER_EVENTS = (QEvent.Type.Show, QEvent.Type.WindowActivate, QEvent.Type.ZOrderChange)


def configure_floating_panel(widget):
    widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    widget.setProperty(_PANEL_PROPERTY, True)


def raise_active_panel():
    panel = QApplication.activeWindow()
    if panel is not None and panel.property(_PANEL_PROPERTY):
        panel.raise_()


class FloatingPanels(QObject):
    def __init__(self, character):
        super().__init__(character)
        self.character = character
        self._raise_timer = QTimer(self)
        self._raise_timer.setSingleShot(True)
        self._raise_timer.timeout.connect(self.raise_character)
        QApplication.instance().installEventFilter(self)

    def raise_character(self):
        character = self.character
        if character.is_dragging and character.isVisible():
            character.raise_()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type not in _PRESS_EVENTS and event_type not in _ORDER_EVENTS:
            return False
        if isinstance(watched, QWidget):
            panel = watched.window()
        elif isinstance(watched, QWindow):
            panel = QWidget.find(watched.winId())
        else:
            return False
        if panel is None or not panel.property(_PANEL_PROPERTY):
            return False
        if self.character.is_dragging:
            if event_type in _PRESS_EVENTS or watched is panel or isinstance(watched, QWindow):
                # Raise after Qt and Windows finish showing or activating the panel.
                self._raise_timer.start(0)
        elif event_type in _PRESS_EVENTS and event.button() == Qt.MouseButton.LeftButton:
            panel.raise_()
        return False
