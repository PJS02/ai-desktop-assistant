import pytest
from PyQt6.QtCore import Qt
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
