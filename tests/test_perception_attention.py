from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest

from character.mood_system import MoodSystem, OccEmotionToMood
from perception.controller import PerceptionController
from perception.events import PerceptionEvent


@pytest.fixture
def session():
    clock = SimpleNamespace(now=1000., last_interaction=1000.)
    mood = MoodSystem()
    mood.on_idle = Mock(wraps=mood.on_idle)
    controller = PerceptionController(
        mood,
        time_provider=lambda: clock.now,
        get_character_idle_time=lambda: clock.now - clock.last_interaction,
    )
    return clock, mood, controller


def attention(controller, state='away'):
    controller.handle_event(PerceptionEvent(source='camera', timestamp=0, attention=state))


def test_petting_does_not_gain_anger_when_camera_attention_flickers(session):
    clock, mood, controller = session
    for frame in range(100):
        clock.now += .125
        clock.last_interaction = clock.now
        mood.on_pet(140, .125)
        attention(controller, 'away' if frame % 2 else 'searching')
    mood.on_idle.assert_not_called()
    assert mood.occ_intensities[OccEmotionToMood.ANGER] == 0
    assert mood.occ_intensities[OccEmotionToMood.JOY] > 0


def test_real_absence_reacts_after_five_seconds_only_once(session):
    clock, mood, controller = session
    attention(controller)
    clock.now = 1004.999
    attention(controller)
    mood.on_idle.assert_not_called()
    clock.now = 1005
    attention(controller)
    mood.on_idle.assert_called_once()
    assert mood.occ_intensities[OccEmotionToMood.ANGER] > 0
    clock.now = 1010
    attention(controller)
    mood.on_idle.assert_called_once()


def test_direct_interaction_restarts_pending_absence_grace_period(session):
    clock, mood, controller = session
    attention(controller)
    clock.now = clock.last_interaction = 1004
    attention(controller)
    clock.now = 1008.999
    attention(controller)
    mood.on_idle.assert_not_called()
    clock.now = 1009
    attention(controller)
    mood.on_idle.assert_called_once()


def test_returning_attention_cancels_deferred_absence(session):
    clock, mood, controller = session
    attention(controller)
    clock.now = 1006
    attention(controller, 'searching')
    mood.on_idle.assert_not_called()
    clock.now = 1007
    attention(controller)
    mood.on_idle.assert_called_once()


def test_speech_in_same_away_packet_counts_as_interaction_first(session):
    clock, mood, controller = session
    clock.now = 1010

    def accept_speech(text):
        clock.last_interaction = clock.now
        return True

    controller.on_speech = Mock(side_effect=accept_speech)
    event = PerceptionEvent(source='camera', timestamp=0, attention='away',
                            speech='hello', speech_id=1)
    controller.handle_event(event)
    controller.on_speech.assert_called_once_with('hello')
    mood.on_idle.assert_not_called()
    # Cached speech must not keep treating a genuine later absence as input.
    clock.now = 1020
    controller.handle_event(event)
    controller.on_speech.assert_called_once()
    mood.on_idle.assert_called_once()


def test_suppressed_speech_does_not_reset_absence(session):
    clock, mood, controller = session
    clock.now = 1010
    controller.on_speech = Mock()
    controller.set_speech_suppressed(True)
    controller.handle_event(PerceptionEvent(source='camera', timestamp=0, attention='away',
                                           speech='speaker echo', speech_id=1))
    controller.on_speech.assert_not_called()
    mood.on_idle.assert_called_once()


@pytest.mark.parametrize('input_kind', ['mouse', 'hand'])
def test_real_pet_handlers_refresh_the_idle_time_used_by_attention(session, monkeypatch, input_kind):
    from PyQt6.QtCore import QPoint, QPointF, QRect
    from character.character_widget import CharacterWidget
    from hand_overlay.interaction_host import CharacterHandActions

    clock, mood, controller = session
    clock.now = 1010
    monkeypatch.setattr('character.character_widget.time.monotonic', lambda: clock.now)
    host = SimpleNamespace(
        mood_system=mood, contact_feedback=Mock(),
        _last_character_interaction_time=1000., _cancel_autonomous_behavior=Mock(),
        hide_and_seek=SimpleNamespace(is_active=False), is_dragging=False,
        _refresh_body_hover=Mock(return_value=True), _physics_body_rect=lambda: QRect(0, 0, 200, 200),
        _pet_last_position=QPoint(10, 10), _pet_last_time=1009.875,
        PET_MIN_SAMPLE_INTERVAL=CharacterWidget.PET_MIN_SAMPLE_INTERVAL,
        PET_MIN_DISTANCE=CharacterWidget.PET_MIN_DISTANCE,
        _pet_trace_id='test-pet', _pet_session_logged=True,
        _pet_log_count=0, _pet_total_count=0, _pet_log_reward=0.,
    )
    host.contact_feedback.pulse.return_value = False
    host._mark_character_interaction = MethodType(CharacterWidget._mark_character_interaction, host)
    host.get_character_idle_time = MethodType(CharacterWidget.get_character_idle_time, host)
    controller.get_character_idle_time = host.get_character_idle_time
    if input_kind == 'mouse':
        event = Mock()
        event.position.return_value = event.globalPosition.return_value = QPointF(30, 10)
        CharacterWidget.mouseMoveEvent(host, event)
    else:
        CharacterHandActions(host).pet(160, .125, (30, 10))
    assert host.get_character_idle_time() == 0
    attention(controller)
    mood.on_idle.assert_not_called()
    clock.now += 5
    attention(controller)
    mood.on_idle.assert_called_once()
