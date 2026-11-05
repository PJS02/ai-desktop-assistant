"""Dialogue bubbles remain above their character without taking focus."""
import sys
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from character import dialogue_system
from character.character_widget import CharacterWidget
from character.taskbar_visibility import _WindowsApi


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialogue(application, monkeypatch):
    monkeypatch.setattr(dialogue_system, 'load_dialogue_style', lambda: 'legacy')
    monkeypatch.setattr(dialogue_system, 'LongTermMemory', Mock())
    monkeypatch.setattr(dialogue_system.DialogueSystem, '_load_gemini_config', lambda self: None)
    host = QWidget()
    host.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    host.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    host.setGeometry(100, 100, 180, 200)
    host.show()
    application.processEvents()
    system = dialogue_system.DialogueSystem(host, tts=SimpleNamespace(close=lambda: None))
    yield system
    system.shutdown()
    host.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.skipif(sys.platform != 'win32', reason='Win32 window stacking')
@pytest.mark.parametrize('order', [('user',), ('character',),
                                 ('user', 'character'), ('character', 'user')])
def test_bubbles_stay_above_character_after_raise_and_taskbar_restore(application, dialogue, order):
    if application.platformName() != 'windows':
        pytest.skip('Native window stacking requires the Windows Qt platform')
    api = _WindowsApi()
    foreground = api.user32.GetForegroundWindow
    foreground.argtypes, foreground.restype = [], wintypes.HWND
    host = dialogue.character_widget
    original_foreground = foreground()
    for speaker in order:
        show = dialogue.show_user_dialogue if speaker == 'user' else dialogue.show_dialogue
        show('Window stacking regression', duration=0)
    bubbles = [bubble for bubble in (dialogue.current_dialogue, dialogue.current_user_dialogue)
               if bubble is not None]
    application.processEvents()

    def check():
        assert foreground() == original_foreground
        for bubble in bubbles:
            current = int(host.winId())
            for _ in range(1024):
                current = api.user32.GetWindow(current, 3)  # GW_HWNDPREV
                if current == int(bubble.winId()):
                    break
                assert current, 'Dialogue bubble was behind its character'
            else:
                pytest.fail('Dialogue bubble not found in native window order')
            assert api.user32.GetWindow(int(bubble.winId()), 4) == int(host.winId())  # GW_OWNER
            assert bubble.isWindow() and bubble.parentWidget() is host

    check()
    host.raise_()
    application.processEvents()
    check()
    recovery_host = SimpleNamespace(
        _character_closing=False, isVisible=host.isVisible, isWindow=host.isWindow,
        winId=host.winId, width=host.width, height=host.height,
        _physics_body_rect=host.rect, dialogue_system=dialogue,
        _taskbar_visibility_guard=SimpleNamespace(
            ensure_visible=lambda hwnd, **_kwargs: api.restore(hwnd)))
    assert CharacterWidget._ensure_taskbar_visibility(recovery_host)
    application.processEvents()
    check()
    host.move(host.x() + 50, host.y() + 40)
    dialogue.update_dialogue_position()
    application.processEvents()
    check()
