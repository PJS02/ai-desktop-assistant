import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from character.mood_system import MoodSystem
from character.russell_emotion_dialog import RussellEmotionDialog


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    view = RussellEmotionDialog()
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    view.canvas.animation_timer.stop()
    yield view
    view.close()


def test_live_explanation_refresh_updates_graph_and_reason_once(dialog):
    mood = MoodSystem()
    mood.on_click()
    dialog.set_state_provider(lambda: (.5, -.2, 'joy'))
    dialog.set_explanation_provider(mood.get_emotion_explanation)
    for _ in range(3):
        dialog._refresh_from_provider()
    snapshot = mood.get_emotion_explanation()
    assert len(dialog.history_canvas.samples) == 3
    assert dialog.history_canvas.samples[-1] == (snapshot['valence'], snapshot['arousal'])
    assert '캐릭터 클릭' in dialog.change_label.text()
    assert dialog.influence_table.rowCount() > 0
    assert f"{snapshot['intensity'] * 100:.0f}%" in dialog.value_label.text()


def test_failed_explanation_provider_still_updates_state_and_chart(dialog):
    dialog.set_state_provider(lambda: (.5, -.2, 'joy'))
    def broken_provider():
        raise RuntimeError('temporary failure')
    dialog.set_explanation_provider(broken_provider)
    dialog._refresh_from_provider()
    assert dialog.history_canvas.samples == [(.5, -.2)]
    assert '기쁨' in dialog.value_label.text()


def test_smaller_window_scrolls_to_chart_without_losing_explanation(dialog, app):
    dialog.resize(1040, 700)
    dialog.show()
    app.processEvents()
    assert dialog.influence_table.isVisible()
    assert dialog.history_canvas.isVisible()
    assert dialog.content_scroll.verticalScrollBar().maximum() > 0
    dialog.content_scroll.ensureWidgetVisible(dialog.history_canvas)
    app.processEvents()
    assert dialog.content_scroll.verticalScrollBar().value() > 0
    assert not dialog.grab().isNull()


def table_rows(dialog):
    table = dialog.influence_table
    return [[table.item(row, column).text() for column in range(table.columnCount())]
            for row in range(table.rowCount())]


def test_retained_events_scroll_and_recovery_uses_readable_text(dialog, app):
    mood = MoodSystem()
    for _ in range(35):
        mood.on_click()
    snapshot = mood.get_emotion_explanation()
    recovery_mood = MoodSystem()
    recovery_mood.on_external_emotion('Anger', 1.0)
    recovery_mood.decay()
    recovery = recovery_mood.get_emotion_explanation()['latest_change']
    assert recovery['category'] == 'recovery'
    snapshot['recent_events'][0] = snapshot['latest_change'] = recovery
    dialog.update_explanation(snapshot)
    dialog.resize(1040, 700)
    dialog.show()
    app.processEvents()
    assert dialog.influence_table.rowCount() == len(snapshot['recent_events']) == 30
    assert dialog.influence_table.item(0, 2).text().startswith('회복 ')
    assert '↺' not in dialog.change_label.text()
    scroll = dialog.influence_table.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    assert scroll.value() > 0
    assert dialog.influence_table.item(29, 1).text() == snapshot['recent_events'][-1]['source']


def test_pause_freezes_only_table_while_other_views_and_recording_continue(dialog, app):
    mood = MoodSystem()
    mood.on_external_emotion('Anger', 1.0)
    polls = []
    def provider():
        polls.append(True)
        return mood.get_emotion_explanation()
    dialog.set_explanation_provider(provider)
    dialog.show()
    dialog.set_live_mode()
    QTest.mouseClick(dialog.pause_button, Qt.MouseButton.LeftButton)
    assert dialog.pause_button.text() == '일시정지 해제'
    assert dialog._refresh_timer.isActive()
    assert dialog.canvas.animation_timer.isActive() and dialog.canvas.isEnabled()
    frozen_rows = table_rows(dialog)
    old_summary = dialog.value_label.text()
    old_reason = dialog.change_label.text()
    old_samples = list(dialog.history_canvas.samples)
    old_coordinates = list(dialog.canvas.coordinate_history)
    old_state = mood.get_russell_state()
    old_count = len(mood.get_emotion_explanation()['recent_events'])
    poll_count = len(polls)
    mood.on_click()
    mood.advance_emotion(1.0)
    QTest.qWait(300)
    assert len(polls) > poll_count
    assert mood.get_russell_state() != old_state
    assert len(mood.get_emotion_explanation()['recent_events']) > old_count
    assert table_rows(dialog) == frozen_rows
    assert dialog.value_label.text() != old_summary
    assert dialog.change_label.text() != old_reason
    assert len(dialog.history_canvas.samples) > len(old_samples)
    assert dialog.canvas.coordinate_history != old_coordinates
    latest = mood.get_emotion_explanation()
    assert dialog.canvas.valence_target == latest['valence']
    assert dialog.history_canvas.samples[-1] == (latest['valence'], latest['arousal'])
    QTest.mouseClick(dialog.pause_button, Qt.MouseButton.LeftButton)
    assert dialog.pause_button.text() == '일시정지'
    assert dialog.canvas.animation_timer.isActive()
    latest = mood.get_emotion_explanation()
    assert dialog.influence_table.rowCount() == len(latest['recent_events'])
    assert dialog.influence_table.item(0, 1).text() == latest['latest_change']['source']
    assert dialog.history_canvas.samples[-1] == (latest['valence'], latest['arousal'])


def test_paused_snapshot_can_scroll_and_resume_without_provider(dialog, app):
    mood = MoodSystem()
    for _ in range(20):
        mood.on_click()
    dialog.update_explanation(mood.get_emotion_explanation())
    dialog.show()
    app.processEvents()
    QTest.mouseClick(dialog.pause_button, Qt.MouseButton.LeftButton)
    old_rows = table_rows(dialog)
    scroll = dialog.influence_table.verticalScrollBar()
    scroll.setValue(scroll.maximum())
    position = scroll.value()
    assert position > 0
    mood.on_external_emotion('Anger', 1.0)
    snapshot = mood.get_emotion_explanation()
    dialog.update_explanation(snapshot)
    snapshot['recent_events'].clear()
    assert table_rows(dialog) == old_rows and scroll.value() == position
    assert mood.get_emotion_explanation()['latest_change']['source'] in dialog.change_label.text()
    QTest.mouseClick(dialog.pause_button, Qt.MouseButton.LeftButton)
    assert dialog.influence_table.item(0, 1).text() == mood.get_emotion_explanation()['latest_change']['source']
    assert dialog.influence_table.rowCount() == len(mood.get_emotion_explanation()['recent_events'])
