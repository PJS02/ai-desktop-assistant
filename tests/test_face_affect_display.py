"""Facial perception must stay visible without inflating the actual mood effect."""
from unittest.mock import Mock
import time

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from app_logging import get_events
from character.emotion_delta_overlay import EmotionDeltaOverlay
from character.log_console import AppLogManager, LogWindow
from character.log_presentation import present_event
from character.mood_system import MoodSystem, OccEmotionToMood as OCC
from character.russell_emotion_dialog import RussellEmotionDialog
from perception.controller import PerceptionController


@pytest.fixture
def display():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    host.show()
    overlay = EmotionDeltaOverlay(host, 950)
    overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    overlay._position = Mock()
    overlay._make_popups = Mock(wraps=overlay._make_popups)
    mood = MoodSystem(on_occ_change=overlay.collect, on_arousal_change=overlay.collect_arousal)
    yield app, overlay, mood
    overlay.clear()
    host.close()


def show_pending(overlay):
    overlay._batch.stop()
    overlay._animation.stop()
    overlay._show_pending()


@pytest.mark.parametrize('label,component', [('happy', 'joy'), ('sadness', 'distress'),
                                          ('anger', 'distress'), ('fear', 'fear'),
                                          ('disgust', 'distress'), ('contempt', 'distress')])
def test_small_real_face_effect_displays_fractional_points(display, label, component):
    _, overlay, mood = display
    result = mood.on_interaction('user_face', label=label, quality=.9)
    delta = result['changes'][component]
    assert 0 < delta < .01
    before_show = dict(mood.occ_intensities)
    show_pending(overlay)
    assert overlay.isVisible() and overlay._popups
    lines = overlay._make_popups.call_args.args[0]
    shown = next(points for _, emotion, points in lines if emotion == component)
    assert 0 < shown < 1.
    assert shown == round(delta * 100, 2)
    assert mood.occ_intensities == before_show


def test_negative_face_recovery_keeps_its_sign_and_improvement_color(display):
    _, overlay, mood = display
    mood.occ_intensities[OCC.FEAR] = .9
    mood.russell.valence, mood.russell.arousal = -.4, .5
    result = mood.on_interaction('user_face', label='happy', quality=.9)
    assert result['changes']['fear'] < 0
    show_pending(overlay)
    lines = overlay._make_popups.call_args.args[0]
    index = next(index for index, (_, emotion, _) in enumerate(lines) if emotion == 'fear')
    assert lines[index][2] < 0
    assert overlay._popups[index].color.name() == '#a6f284'


@pytest.mark.parametrize('signal', ['heart', 'thumbs_up', 'ok', 'head_agree', 'head_negative'])
def test_small_perception_gesture_displays_fractional_points(display, signal):
    _, overlay, mood = display
    mood.occ_intensities[OCC.ANGER] = .9
    mood.russell.valence, mood.russell.arousal = -.5, .3
    result = mood.on_interaction('user_' + signal, actor_state={'recent_dialogue': True})
    assert result['applied'] and all(abs(value) < .01 for value in result['changes'].values())
    before_show = dict(mood.occ_intensities)
    show_pending(overlay)
    assert overlay.isVisible() and overlay._popups
    for _, emotion, points in overlay._make_popups.call_args.args[0]:
        assert points == round(result['changes'][emotion] * 100, 2)
    assert mood.occ_intensities == before_show


def test_small_contact_samples_keep_existing_integer_accumulation(display):
    _, overlay, _ = display
    for _ in range(2):
        overlay.collect('쓰다듬기', {'joy': .004})
        show_pending(overlay)
        assert not overlay._popups
    overlay.collect('쓰다듬기', {'joy': .004})
    show_pending(overlay)
    assert overlay._make_popups.call_args.args[0] == [('쓰다듬기', 'joy', 1)]
    assert overlay._pending['쓰다듬기', 'joy'] == pytest.approx(.002)


def test_face_maintenance_after_eight_seconds_displays_without_stale_accumulation(display, monkeypatch):
    _, overlay, mood = display
    now = [100.]
    monkeypatch.setattr('character.emotion_delta_overlay.time.monotonic', lambda: now[0])
    controller = PerceptionController(mood, time_provider=lambda: now[0])
    for seq in range(1, 25):
        now[0] = 100. + seq * .4
        controller.handle_payload({'type': 'perception', 'timestamp': now[0],
            'observation': {'session': 'camera', 'sequence': seq, 'observed_at': now[0]},
            'emotion': {'label': 'happy', 'confidence': .9, 'model': 'test',
                        'observation_id': seq, 'observed_at': now[0]}})
        if seq in (4, 24):
            show_pending(overlay)
            assert overlay.isVisible() and overlay._popups
    assert overlay._make_popups.call_count == 2
    assert len(mood.get_emotion_explanation()['recent_events']) == 2
    latest_delta = mood.get_emotion_explanation()['latest_change']['occ_changes']['joy']
    last_points = overlay._make_popups.call_args.args[0][0][2]
    assert 0 < last_points < 1
    assert last_points == round(latest_delta * 100, 2)


def test_sub_point_remainder_is_kept_and_disabled_overlay_discards_it(display):
    _, overlay, _ = display
    overlay.collect('사용자 웃음 감지', {'joy': .007116})
    show_pending(overlay)
    assert overlay._make_popups.call_args.args[0] == [('사용자 웃음 감지', 'joy', .71)]
    assert overlay._pending['사용자 웃음 감지', 'joy'] == pytest.approx(.000016)
    overlay.clear()
    overlay.collect('사용자 웃음 감지', {'joy': .00004})
    show_pending(overlay)
    assert not overlay._popups
    overlay.set_enabled(False)
    assert not overlay._pending
    overlay.set_enabled(True)
    overlay.collect('사용자 웃음 감지', {'joy': .00007})
    show_pending(overlay)
    assert not overlay._popups


def test_surprise_records_arousal_without_inventing_occ(display):
    _, _, mood = display
    now = [100.]
    controller = PerceptionController(mood, time_provider=lambda: now[0])
    for seq in range(4):
        now[0] = 100. + seq * .4
        controller.handle_payload({'type': 'perception', 'timestamp': now[0],
                                   'trace_id': 'surprise-display-test',
                                   'emotion': {'label': 'surprise', 'confidence': .9,
                                               'observation_id': seq, 'observed_at': now[0]}})
    item = mood.get_emotion_explanation()['latest_change']
    assert item['occ_changes'] == {}
    assert item['event_input']['arousal_change'] > 0
    event = next(entry for entry in reversed(get_events())
                 if entry.event == 'perception.affect.result' and entry.trace_id == 'surprise-display-test')
    assert event.data['applied'] and not event.data['occ_changes']
    assert '흥분도' in present_event(event).summary
    show_pending(display[1])
    assert display[1].isVisible() and display[1]._popups
    assert display[1]._make_popups.call_args.args[0] == [
        ('사용자 놀람 감지', 'arousal', round(item['event_input']['arousal_change'] * 100, 2))]
    assert all(value == 0 for value in mood.occ_intensities.values())


@pytest.mark.parametrize('points', [-.9, .9])
def test_arousal_popup_does_not_label_activation_as_good_or_bad(display, points):
    _, overlay, _ = display
    popup, = overlay._make_popups([('사용자 놀람 감지', 'arousal', points)])
    assert popup.color.name() == '#8fc8ff'


def test_arousal_callback_ignores_duplicate_capped_and_recovery_events(display):
    _, overlay, mood = display
    callback = Mock(wraps=overlay.collect_arousal)
    occ_callback = Mock(wraps=overlay.collect)
    mood._on_arousal_change = callback
    mood._on_occ_change = occ_callback
    result = mood.on_interaction('user_face', label='surprise', event_id='surprise:1')
    assert result['applied'] and callback.call_count == 1 and occ_callback.call_count == 0
    assert mood.on_interaction('user_face', label='surprise', event_id='surprise:1')['duplicate']
    mood.interactions.perception_budget.append((time.monotonic(), 'face', 0., .06))
    capped = mood.on_interaction('user_face', label='surprise', event_id='surprise:2')
    assert not capped['applied'] and capped['appraisal']['reason'] == 'budget_exhausted'
    mood.decay()
    assert callback.call_count == 1
    assert not any(mood.occ_intensities.values())


@pytest.mark.parametrize('reason', ['disabled', 'hidden', 'closing'])
def test_arousal_popup_respects_existing_display_gates(display, reason):
    _, overlay, mood = display
    if reason == 'disabled':
        overlay.set_enabled(False)
    elif reason == 'hidden':
        overlay.parentWidget().hide()
    else:
        overlay.parentWidget()._character_closing = True
    mood.on_interaction('user_face', label='surprise')
    show_pending(overlay)
    assert not overlay.isVisible() and not overlay._pending


def test_surprise_influence_is_consistent_in_popup_log_and_history(display):
    app, overlay, mood = display
    manager = AppLogManager()
    history = RussellEmotionDialog()
    history.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    history.canvas.animation_timer.stop()
    try:
        result = mood.on_interaction('user_face', label='surprise', quality=.9)
        snapshot = mood.get_emotion_explanation()
        history.update_explanation(snapshot)
        show_pending(overlay)
        app.processEvents()
        amount = snapshot['latest_change']['event_input']['arousal_change']
        expected = f'흥분도 {amount * 100:+.2f}점'
        event = next(entry for entry in reversed(manager.entries()) if entry.event == 'mood.influence')
        assert expected in history.change_label.text()
        assert expected in history.influence_table.item(0, 1).toolTip()
        assert f'{amount * 100:+.2f}점' in history.detail_view.toPlainText()
        assert expected in present_event(event).summary
        assert overlay._make_popups.call_args.args[0] == [('사용자 놀람 감지', 'arousal', round(amount * 100, 2))]
        assert result['changes'] == event.data['influence']['occ_changes'] == {}
    finally:
        manager._unsubscribe()
        history.close()


def test_small_face_change_is_readable_in_history_and_live_log_window(display):
    app, _, mood = display
    manager = AppLogManager()
    log_window = LogWindow(manager)
    history = RussellEmotionDialog()
    history.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    history.canvas.animation_timer.stop()
    try:
        result = mood.on_interaction('user_face', label='happy', quality=.9,
                                     event_id='face:1', perception_context={'trace_id': 'camera:1'})
        snapshot = mood.get_emotion_explanation()
        history.set_explanation_provider(mood.get_emotion_explanation)
        history._refresh_from_provider()
        app.processEvents()
        log_window.refresh()
        expected = f"기쁨 {result['changes']['joy'] * 100:+.2f}%p"
        assert history.influence_table.item(0, 1).text() == '사용자 웃음 감지'
        assert expected in history.change_label.text()
        assert expected in history.influence_table.item(0, 1).toolTip()
        assert f"{result['changes']['joy'] * 100:+.2f}%p" in history.detail_view.toPlainText()
        event = next(item for item in reversed(manager.entries()) if item.event == 'mood.influence')
        assert event.data['influence']['occ_changes'] == result['changes']
        assert expected in present_event(event).summary
        assert expected in log_window.output.toPlainText()
        assert '인식 신뢰도: 90.0%' in history.detail_view.toPlainText()
        assert snapshot['latest_change']['event_input']['event_id'] == 'face:1'
    finally:
        log_window.shutdown()
        manager._unsubscribe()
        history.close()


def test_controller_logs_actual_face_change_and_bounded_no_change_without_fake_history(display):
    _, _, mood = display
    now = [100.]
    controller = PerceptionController(mood, time_provider=lambda: now[0])
    for label, start in (('happy', 100.), ('sadness', 109.)):
        if label == 'sadness':
            mood.interactions.perception_budget.append((time.monotonic(), 'face', .06, 0.))
        for seq in range(4):
            now[0] = start + seq * .4
            controller.handle_payload({'type': 'perception', 'timestamp': now[0],
                'source': 'display-log-test', 'trace_id': 'face-log-' + label,
                'emotion': {'label': label, 'confidence': .9, 'observed_at': now[0],
                            'observation_id': int(start) + seq, 'model': 'test'}})
    results = [item for item in get_events() if item.event == 'perception.affect.result'
               and item.trace_id in ('face-log-happy', 'face-log-sadness')]
    assert len(results) == 2
    first, capped = results
    assert first.data['applied'] and first.data['occ_changes']['joy'] > 0
    assert not capped.data['applied'] and capped.data['occ_changes'] == {}
    assert capped.data['reason'] == 'budget_exhausted'
    assert len(mood.get_emotion_explanation()['recent_events']) == 1
    assert '반영 없음' in present_event(capped).summary
    assert '누적 반영 상한' in present_event(capped).summary
