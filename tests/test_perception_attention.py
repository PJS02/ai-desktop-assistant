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


def attention(controller, now, state='away', **speech):
    controller.handle_event(PerceptionEvent(source='camera', timestamp=now, attention=state, **speech))


def stay_away(clock, controller, until):
    while clock.now < until:
        clock.now = min(clock.now + 1., until)
        attention(controller, clock.now)


def presence(controller):
    return controller._observations['camera']['presence']


def test_petting_does_not_gain_anger_when_camera_attention_flickers(session):
    clock, mood, controller = session
    for frame in range(100):
        clock.now += .125
        clock.last_interaction = clock.now
        mood.on_pet(140, .125)
        attention(controller, clock.now, 'away' if frame % 2 else 'searching')
        assert presence(controller) is None
    mood.on_idle.assert_not_called()
    assert mood.occ_intensities[OccEmotionToMood.ANGER] == 0
    assert mood.occ_intensities[OccEmotionToMood.JOY] > 0


def test_real_absence_is_confirmed_once_without_a_second_mood_penalty(session, monkeypatch):
    clock, mood, controller = session
    log = Mock()
    monkeypatch.setattr('perception.controller.log_event', log)
    attention(controller, clock.now)
    stay_away(clock, controller, 1004.999)
    assert presence(controller) is None
    stay_away(clock, controller, 1005.)
    assert presence(controller) == 'away'
    stay_away(clock, controller, 1010.)
    changes = [call for call in log.call_args_list if call.args[0] == 'perception.attention.changed']
    assert [call.kwargs['current'] for call in changes] == ['away']
    mood.on_idle.assert_not_called()
    assert mood.occ_intensities[OccEmotionToMood.ANGER] == 0


def test_direct_interaction_restarts_pending_absence_grace_period(session):
    clock, _, controller = session
    attention(controller, clock.now)
    stay_away(clock, controller, 1004.)
    clock.last_interaction = clock.now
    stay_away(clock, controller, 1008.999)
    assert presence(controller) is None
    stay_away(clock, controller, 1009.)
    assert presence(controller) == 'away'


def test_returning_attention_cancels_deferred_absence(session):
    clock, _, controller = session
    attention(controller, clock.now)
    stay_away(clock, controller, 1004.)
    attention(controller, 1004.5, 'searching')
    clock.now = 1005.
    attention(controller, clock.now)
    stay_away(clock, controller, 1009.999)
    assert presence(controller) is None
    stay_away(clock, controller, 1010.)
    assert presence(controller) == 'away'


def test_speech_in_same_away_packet_counts_as_interaction_first(session):
    clock, _, controller = session
    attention(controller, clock.now)
    stay_away(clock, controller, 1004.)

    def accept_speech(text):
        clock.last_interaction = clock.now
        return True

    controller.on_speech = Mock(side_effect=accept_speech)
    clock.now = 1005.
    attention(controller, clock.now, speech='hello', speech_id=1)
    assert presence(controller) is None
    # Cached speech must not keep treating a genuine later absence as input.
    stay_away(clock, controller, 1009.)
    clock.now = 1010.
    attention(controller, clock.now, speech='hello', speech_id=1)
    controller.on_speech.assert_called_once_with('hello')
    assert presence(controller) == 'away'


def test_suppressed_speech_does_not_reset_absence(session):
    clock, _, controller = session
    attention(controller, clock.now)
    stay_away(clock, controller, 1004.)
    controller.on_speech = Mock()
    controller.set_speech_suppressed(True)
    clock.now = 1005.
    attention(controller, clock.now, speech='speaker echo', speech_id=1)
    controller.on_speech.assert_not_called()
    assert presence(controller) == 'away'


@pytest.mark.parametrize('input_kind', ['mouse', 'hand'])
def test_real_pet_handlers_refresh_the_idle_time_used_by_attention(session, monkeypatch, input_kind):
    from PyQt6.QtCore import QPoint, QPointF, QRect
    from character.character_widget import CharacterWidget
    from hand_overlay.interaction_host import CharacterHandActions

    clock, mood, controller = session
    clock.now = 1005.
    attention(controller, clock.now)
    stay_away(clock, controller, 1009.)
    clock.now = 1010.
    monkeypatch.setattr('character.character_widget.time.monotonic', lambda: clock.now)
    host = SimpleNamespace(
        mood_system=mood, contact_feedback=Mock(),
        _last_character_interaction_time=1000., _cancel_autonomous_behavior=Mock(),
        hide_and_seek=SimpleNamespace(is_active=False), is_dragging=False,
        current_action='idle', _automatic_pose=None,
        _perception_actor_state=lambda: {'manual_motion': False},
        _refresh_body_hover=Mock(return_value=True), _physics_body_rect=lambda: QRect(0, 0, 200, 200),
        _pet_last_position=QPoint(10, 10), _pet_last_time=1009.875,
        PET_MIN_SAMPLE_INTERVAL=CharacterWidget.PET_MIN_SAMPLE_INTERVAL,
        PET_MIN_DISTANCE=CharacterWidget.PET_MIN_DISTANCE,
        _pet_trace_id='test-pet', _pet_session_logged=True,
        _pet_log_count=0, _pet_total_count=0, _pet_log_reward=0.,
    )
    host.contact_feedback.pulse.return_value = False
    host._mark_character_interaction = MethodType(CharacterWidget._mark_character_interaction, host)
    host._mark_pet_interaction = MethodType(CharacterWidget._mark_pet_interaction, host)
    host.get_character_idle_time = MethodType(CharacterWidget.get_character_idle_time, host)
    controller.get_character_idle_time = host.get_character_idle_time
    if input_kind == 'mouse':
        event = Mock()
        event.position.return_value = event.globalPosition.return_value = QPointF(30, 10)
        CharacterWidget.mouseMoveEvent(host, event)
    else:
        CharacterHandActions(host).pet(160, .125, (30, 10))
    assert host.get_character_idle_time() == 0
    attention(controller, clock.now)
    assert presence(controller) is None
    stay_away(clock, controller, 1015.)
    assert presence(controller) == 'away'
    mood.on_idle.assert_not_called()
