"""Taskbar recovery stays tied to the visible host and its native lifecycle."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QRect

from character import character_widget
from character.character_widget import CharacterWidget
from test_character_options import real_character


def visibility_host():
    return SimpleNamespace(
        _character_closing=False,
        isVisible=Mock(return_value=True),
        isWindow=Mock(return_value=True),
        winId=Mock(side_effect=[101, 202]),
        _physics_body_rect=Mock(return_value=QRect(23, 15, 117, 158)),
        width=Mock(return_value=150),
        height=Mock(return_value=200),
        _taskbar_visibility_guard=SimpleNamespace(ensure_visible=Mock(return_value=True)),
    )


@pytest.fixture
def no_active_dialogs(monkeypatch):
    monkeypatch.setattr(character_widget.QApplication, 'activePopupWidget', lambda: None)
    monkeypatch.setattr(character_widget.QApplication, 'activeModalWidget', lambda: None)


def test_recovery_uses_current_host_handle_and_local_painted_body(no_active_dialogs):
    host = visibility_host()
    for _ in range(2):
        assert CharacterWidget._ensure_taskbar_visibility(host)
    calls = host._taskbar_visibility_guard.ensure_visible.call_args_list
    assert [call.args for call in calls] == [(101,), (202,)]
    assert all(call.kwargs == {
        'body_offset': (23, 15, 117, 158), 'widget_size': (150, 200),
    } for call in calls)


@pytest.mark.parametrize('state', ['hidden', 'embedded', 'closing', 'popup', 'modal'])
def test_recovery_skips_inactive_hosts_and_open_dialogs(state, no_active_dialogs, monkeypatch):
    host = visibility_host()
    if state == 'hidden':
        host.isVisible.return_value = False
    elif state == 'embedded':
        host.isWindow.return_value = False
    elif state == 'closing':
        host._character_closing = True
    elif state == 'popup':
        monkeypatch.setattr(character_widget.QApplication, 'activePopupWidget', lambda: object())
    else:
        monkeypatch.setattr(character_widget.QApplication, 'activeModalWidget', lambda: object())
    assert CharacterWidget._ensure_taskbar_visibility(host) is False
    host.winId.assert_not_called()
    host._physics_body_rect.assert_not_called()
    host._taskbar_visibility_guard.ensure_visible.assert_not_called()


def test_visibility_timer_follows_show_hide_and_shutdown(real_character, no_active_dialogs):
    host, app = real_character
    recover = Mock(return_value=True)
    host._taskbar_visibility_guard = SimpleNamespace(ensure_visible=recover)
    timer = host._taskbar_visibility_timer
    assert timer.parent() is host and timer.interval() == 300
    assert not timer.isActive()

    host.show()
    app.processEvents()
    assert timer.isActive() and recover.called
    recover.reset_mock()
    timer.timeout.emit()
    recover.assert_called_once()

    host.hide()
    app.processEvents()
    assert not timer.isActive()
    recover.reset_mock()
    timer.timeout.emit()
    recover.assert_not_called()

    host.show()
    app.processEvents()
    assert timer.isActive() and recover.called
    host.close()
    assert host._character_closing and not timer.isActive()
    recover.reset_mock()
    timer.timeout.emit()
    recover.assert_not_called()
