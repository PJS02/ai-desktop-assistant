import json
import time

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QRect, QSize
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QWidget

from character import config_manager
from character.dialogue_system import DialogueSystem
from character.dialogue_widget import DialogueBubble
from character.overlay_geometry import place_above_character
from character.settings_dialog import SettingsDialog
from test_settings import local_settings


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def test_style_selection_draft_apply_and_reload(tmp_path, monkeypatch, qt_app):
    path = tmp_path / 'config.json'
    path.write_text('{"extra":42,"dialogue":{"other":true}}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    dialog = SettingsDialog(local_settings())
    dialog.dialogue_style.setCurrentIndex(dialog.dialogue_style.findData('rounded'))
    assert dialog.dialogue_preview.style == 'rounded'
    assert dialog.changes() == {'local': {'dialogue': {'style': 'rounded'}}, 'remote': {}}
    assert config_manager.load_dialogue_style() == 'legacy'  # Draft is not saved.
    config_manager.save_config(1280, 720, dialogue_style='rounded')
    assert config_manager.load_dialogue_style() == 'rounded'
    stored = json.loads(path.read_text(encoding='utf-8'))
    assert stored['extra'] == 42 and stored['dialogue']['other'] is True
    dialog.complete('saved', local={'dialogue': {'style': 'rounded'}})
    assert dialog.changes()['local'] == {}
    dialog.close()


@pytest.mark.parametrize('bounds', [QRect(0, 0, 1280, 720), QRect(0, 0, 1920, 1080),
                                     QRect(0, 0, 2560, 1440), QRect(-1536, -120, 1536, 864)])
def test_overlay_stays_inside_each_screen_and_avoids_game(bounds):
    size = QSize(310, 140)
    for anchor in [QRect(bounds.left(), bounds.top(), 150, 200),
                   QRect(bounds.right() - 149, bounds.bottom() - 199, 150, 200)]:
        game = QRect(anchor.center().x() - 60, max(bounds.top(), anchor.top() - 100), 120, 90)
        position = place_above_character(anchor, size, bounds, game)
        placed = QRect(position, size)
        assert bounds.contains(placed)
        assert not placed.intersects(game)


def test_top_edge_places_overlay_below_body():
    body = QRect(700, 0, 120, 200)
    placed = QRect(place_above_character(body, QSize(300, 200), QRect(0, 0, 1920, 1080)), QSize(300, 200))
    assert placed.top() > body.bottom()
    assert not placed.intersects(body)


@pytest.mark.parametrize('style', ['legacy', 'rounded', 'subtitle'])
def test_long_text_remains_accessible_and_style_change_preserves_timer(qt_app, style):
    text = ('긴 문장과 줄바꿈을 모두 확인합니다.\n' * 90) + '마지막 문장'
    bubble = DialogueBubble(text, 10000)
    before = bubble.close_timer.remainingTime()
    bubble.set_style(style)
    bubble._calculate_size(QRect(0, 0, 1280, 720))
    assert bubble.text_view.toPlainText() == text
    assert bubble.height() <= 720 * .4 + 40
    assert bubble.text_view.document().size().height() > bubble.text_view.height()
    assert 0 < bubble.close_timer.remainingTime() <= before
    assert not bubble.preview
    bubble.close()


def test_invalid_saved_style_falls_back_without_rewriting_file(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_text('{"dialogue":{"style":"unknown"}}', encoding='utf-8')
    monkeypatch.setattr(config_manager, 'CONFIG_FILE', path)
    before = path.read_bytes()
    assert config_manager.load_dialogue_style() == 'legacy'
    with pytest.raises(ValueError):
        config_manager.save_config(1280, 720, dialogue_style='unknown')
    assert path.read_bytes() == before


@pytest.fixture
def dialogue_ui(qt_app, tmp_path, monkeypatch):
    """Use real bubbles/timers without network requests, audio or user settings."""
    class SilentTTS(QObject):
        closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(config_manager, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(DialogueSystem, '_load_gemini_config', lambda self: None)
    host = QWidget()
    host.resize(180, 200)
    host.move(300, 300)
    host.rps_game = None
    tts = SilentTTS()
    system = DialogueSystem(host, tts=tts)
    yield system, tts
    system.shutdown()
    host.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_for_ui(condition):
    deadline = time.monotonic() + 2
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert condition()


def test_delayed_queue_displays_each_item_once_in_order(dialogue_ui):
    system, _tts = dialogue_ui
    started = QSignalSpy(system.dialogue_started)
    system.queue_dialogue('첫 번째', duration=0, delay_ms=15)
    system.queue_dialogue('두 번째', duration=0, delay_ms=15)
    wait_for_ui(lambda: len(started) == 1)
    assert system.current_dialogue.text == '첫 번째'
    system.current_dialogue.close()
    wait_for_ui(lambda: len(started) >= 2)
    assert system.current_dialogue.text == '두 번째'
    assert [event[0] for event in started] == ['첫 번째', '두 번째']
    system.current_dialogue.close()
    QTest.qWait(40)
    assert [event[0] for event in started] == ['첫 번째', '두 번째']
    assert system.current_dialogue is None


def test_clear_and_replace_delayed_queue_cannot_restore_old_dialogue(dialogue_ui):
    system, _tts = dialogue_ui
    started = QSignalSpy(system.dialogue_started)
    system.queue_dialogue('취소할 대화', duration=0, delay_ms=60)
    system.queue_dialogue('취소할 다음 대화', duration=0, delay_ms=15)
    system.clear_queue()
    system.queue_dialogue('새 대화', duration=0, delay_ms=15)
    wait_for_ui(lambda: len(started) >= 1)
    replacement = system.current_dialogue
    QTest.qWait(80)
    assert [event[0] for event in started] == ['새 대화']
    assert system.current_dialogue is replacement
    assert replacement.text == '새 대화'


def test_clear_pending_queue_prevents_timer_from_opening_a_bubble(dialogue_ui):
    system, _tts = dialogue_ui
    started = QSignalSpy(system.dialogue_started)
    system.queue_dialogue('대기 중', duration=0, delay_ms=15)
    system.clear_queue()
    QTest.qWait(40)
    assert len(started) == 0
    assert system.current_dialogue is None
    assert not system.is_dialogue_active()


@pytest.mark.parametrize('active_bubble', [False, True])
def test_shutdown_cancels_pending_dialogue_and_deletes_active_bubble(dialogue_ui, active_bubble):
    system, tts = dialogue_ui
    started = QSignalSpy(system.dialogue_started)
    system.queue_dialogue('첫 대화', duration=0, delay_ms=15)
    system.queue_dialogue('다음 대화', duration=0, delay_ms=15)
    current = None
    if active_bubble:
        wait_for_ui(lambda: len(started) == 1)
        current = system.current_dialogue
    count_before = len(started)
    system.shutdown()
    system.queue_dialogue('종료 후 대화', duration=0, delay_ms=15)
    system.show_dialogue('종료 후 직접 표시')
    QTest.qWait(40)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert tts.closed
    assert len(started) == count_before
    assert system.current_dialogue is None
    assert not system.is_dialogue_active()
    if current is not None:
        assert sip.isdeleted(current)


def test_replaced_bubble_late_close_does_not_clear_new_bubble_and_is_deleted(dialogue_ui):
    system, _tts = dialogue_ui
    ended = QSignalSpy(system.dialogue_ended)
    system.show_dialogue('이전 대화', duration=10000)
    previous = system.current_dialogue
    closed = QSignalSpy(previous.dialogue_closed)
    system.show_dialogue('현재 대화', duration=10000)
    current = system.current_dialogue
    assert len(closed) == 1
    # Deliver an extra old close notification before its deferred Qt deletion.
    previous.dialogue_closed.emit()
    assert system.current_dialogue is current
    assert current.isVisible() and current.text == '현재 대화'
    assert len(ended) == 0
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(previous)
    assert not sip.isdeleted(current)


@pytest.mark.parametrize('style', ['legacy', 'rounded', 'subtitle'])
def test_live_style_change_preserves_bubble_content_and_remaining_lifetime(dialogue_ui, style):
    system, _tts = dialogue_ui
    started = QSignalSpy(system.dialogue_started)
    system.show_dialogue('진행 중인 대화\n내용을 유지합니다.', duration=5000)
    current = system.current_dialogue
    QTest.qWait(20)
    remaining = current.close_timer.remainingTime()
    system.set_bubble_style(style)
    assert system.current_dialogue is current
    assert current.style == style
    assert current.text_view.toPlainText() == '진행 중인 대화\n내용을 유지합니다.'
    assert 0 < current.close_timer.remainingTime() <= remaining
    assert len(started) == 1
