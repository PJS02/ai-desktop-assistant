"""Fresh observations through the controller, producer, and character caller."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from character.mood_system import MoodSystem, OccEmotionToMood as OCC
from perception.controller import PerceptionController
from perception.events import parse_perception_event


def packet(stamp, seq, *, session='camera', **fields):
    return {'type': 'perception', 'source': 'camera', 'timestamp': stamp,
            'observation': {'session': session, 'sequence': seq, 'observed_at': stamp}, **fields}


def face(stamp, seq, label='happy', model='model-a'):
    return {'label': label, 'confidence': .9, 'observation_id': seq,
            'observed_at': stamp, 'model': model}


@pytest.fixture
def controller():
    now, calls = [100.], []

    def affect(event, **context):
        calls.append((event, context))
        return {'accepted': True}

    handler = PerceptionController(MoodSystem(), on_affect=affect, time_provider=lambda: now[0])
    return handler, now, calls


def test_cached_face_in_other_channel_packets_does_not_count_as_new_inference(controller):
    handler, now, calls = controller
    cached = face(100., 1)
    for seq, stamp in enumerate((100., 100.5, 101.), 1):
        now[0] = stamp
        handler.handle_payload(packet(stamp, seq, emotion=cached, attention='screen'))
    assert calls == []
    for seq, stamp in ((2, 101.2), (3, 101.7)):
        now[0] = stamp
        handler.handle_payload(packet(stamp, seq + 10, emotion=face(stamp, seq)))
    assert [event for event, _ in calls] == ['user_face']


def test_face_cooldown_is_shared_between_labels_and_maintenance_is_quarter_strength(controller):
    handler, now, calls = controller
    for seq in range(1, 23):
        now[0] = 99.5 + seq * .5
        handler.handle_payload(packet(now[0], seq, emotion=face(now[0], seq)))
    assert len(calls) == 2
    assert calls[0][1]['maintenance'] == 1. and calls[1][1]['maintenance'] == .25
    for seq in range(23, 26):
        now[0] += .5
        handler.handle_payload(packet(now[0], seq, emotion=face(now[0], seq, 'sadness')))
    assert len(calls) == 2


def test_models_and_sources_do_not_share_face_stability(controller):
    handler, now, calls = controller
    for seq, model in ((1, 'a'), (2, 'a'), (3, 'b'), (4, 'b')):
        now[0] += .5
        handler.handle_payload(packet(now[0], seq, emotion=face(now[0], seq, model=model)))
    assert not calls
    for seq in (1, 2):
        now[0] += .5
        payload = packet(now[0], seq, emotion=face(now[0], seq))
        payload['source'] = 'other-camera'
        handler.handle_payload(payload)
    assert not calls


def test_disconnecting_one_sender_preserves_another_senders_face_confirmation(controller):
    handler, now, calls = controller
    for source, client in (('camera', 'a'), ('other', 'b')):
        payload = packet(100., 1, emotion=face(100., 1))
        payload.update(source=source, _perception_client=client)
        handler.handle_payload(payload)
    now[0] = 100.5
    payload = packet(now[0], 2, emotion=face(now[0], 2))
    payload.update(source='other', _perception_client='b')
    handler.handle_payload(payload)
    handler.reset_connection('a')
    assert 'camera' not in handler._observations
    now[0] = 101.
    payload = packet(now[0], 3, emotion=face(now[0], 3))
    payload.update(source='other', _perception_client='b')
    handler.handle_payload(payload)
    assert len(calls) == 1


def test_restarted_model_may_reuse_inference_numbers_without_losing_new_event(controller):
    handler, now, _ = controller
    handler.on_affect = None
    for model, start in (('a', 100.), ('b', 108.)):
        for seq in (1, 2, 3):
            now[0] = start + (seq - 1) * .5
            handler.handle_payload(packet(now[0], int(now[0] * 10),
                                          emotion=face(now[0], seq, model=model)))
        if model == 'a':
            first = handler.mood_system.occ_intensities[OCC.JOY]
    assert handler.mood_system.occ_intensities[OCC.JOY] > first


def test_future_face_cannot_change_the_active_model(controller):
    handler, now, calls = controller
    handler.handle_payload(packet(100., 1, emotion=face(100., 1, model='current')))
    handler.handle_payload(packet(100., 2, emotion=face(400., 2, model='future')))
    assert handler._observations['camera']['model'] == 'current' and not calls


def test_two_hand_heart_is_one_episode_and_speech_only_payload_cannot_release_it(controller):
    handler, now, calls = controller
    hands = [{'kind': 'hand_gesture', 'label': 'heart', 'side': side} for side in ('left', 'right')]
    handler.handle_payload(packet(100., 1, motions=hands))
    now[0] = 100.3
    handler.handle_payload(packet(now[0], 2, motions=hands))
    assert len(calls) == 1 and calls[0][0] == 'user_heart'
    now[0] = 104.
    handler.handle_payload({'type': 'perception', 'source': 'camera', 'timestamp': now[0], 'speech': '안녕'})
    handler.handle_payload(packet(now[0], 3, motions=hands))
    assert len(calls) == 1
    for seq, stamp in ((4, 104.2), (5, 104.7)):
        now[0] = stamp
        handler.handle_payload(packet(stamp, seq, motions=[]))
    for seq, stamp in ((6, 105.), (7, 105.3)):
        now[0] = stamp
        handler.handle_payload(packet(stamp, seq, motions=hands))
    assert len(calls) == 2


def test_different_semantic_events_in_one_frame_get_different_child_ids(controller):
    handler, now, calls = controller
    for seq, stamp in ((1, 100.), (2, 100.3)):
        now[0] = stamp
        handler.handle_payload(packet(stamp, seq, head_motion='agree',
                                      motions=[{'label': 'heart'}]))
    assert {event for event, _ in calls} == {'user_heart', 'user_head_agree'}
    assert len({context['event_id'] for _, context in calls}) == 2


def test_stopped_camera_cannot_be_revived_by_queued_old_session(controller):
    handler, now, calls = controller
    handler.handle_payload(packet(100., 1, motions=[{'label': 'wave'}]))
    assert len(calls) == 1
    now[0] = 101.
    handler.handle_payload(packet(now[0], 2, camera_status='off', attention='away'))
    for seq in (3, 4, 5):
        now[0] += .5
        handler.handle_payload(packet(now[0], seq, emotion=face(now[0], seq)))
    assert len(calls) == 1 and 'camera' not in handler._observations
    for seq in (1, 2, 3):
        now[0] += .5
        handler.handle_payload(packet(now[0], seq, session='new', emotion=face(now[0], seq)))
    assert len(calls) == 2


def test_presence_is_debounced_and_does_not_add_idle_penalties(controller):
    handler, now, calls = controller
    for seq in range(12):
        now[0] = 100. + seq * .5
        handler.handle_payload(packet(now[0], seq, attention='away'))
        if seq < 10:
            assert handler._observations['camera']['presence'] is None
    assert handler._observations['camera']['presence'] == 'away' and not calls
    assert not any(handler.mood_system.occ_intensities.values())
    now[0] += .2
    handler.handle_payload(packet(now[0], 12, camera_status='error'))
    assert 'camera' not in handler._observations


@pytest.mark.parametrize('field,value', [('timestamp', float('nan')), ('timestamp', float('inf')),
                                        ('observation', {'sequence': float('nan')})])
def test_non_finite_or_invalid_transport_values_are_rejected(field, value):
    payload = packet(100., 1)
    payload[field] = value
    with pytest.raises(ValueError):
        parse_perception_event(payload)
    assert parse_perception_event(packet(100., 1, emotion={**face(100., 1), 'confidence': float('nan')})).emotion.confidence == 0


def test_character_caller_resets_idle_without_waking_and_greeting_wakes_once(monkeypatch):
    from character.character_widget import CharacterWidget
    from character.automatic_actions import AutomaticActions
    from character.autonomous_needs import AutonomousNeeds

    class Host:
        _perception_actor_state = CharacterWidget._perception_actor_state
        _apply_perception_affect = CharacterWidget._apply_perception_affect
        _mark_character_interaction = CharacterWidget._mark_character_interaction
        _cancel_autonomous_behavior = CharacterWidget._cancel_autonomous_behavior
        _mark_pet_interaction = CharacterWidget._mark_pet_interaction

    host = Host()
    host._character_closing = host._hand_throw_active = host._autonomous_behavior_active = False
    host._rig_manual_action = None
    host.on_ground, host.is_dragging, host.is_jumping, host.is_moving = True, False, False, False
    host.current_action = 'idle'
    host._manual_control_active = lambda: False
    host.manual_control = SimpleNamespace(display_emotion=None)
    host.mood_system = MoodSystem()
    host.autonomous_needs = AutonomousNeeds()
    host.dialogue_system = SimpleNamespace(last_output_at=99.)
    host.rig_view = object()
    host.update_action = lambda _mood: setattr(host, 'current_action', 'idle')
    host.animation_controller = SimpleNamespace(start_idle=Mock())
    host.reactions = SimpleNamespace(play=Mock(), play_perception=Mock())
    host.automatic_actions = AutomaticActions(host)
    host.automatic_actions.timer.stop()
    try:
        host._last_character_interaction_time = 0.
        result = host._apply_perception_affect('user_heart', event_id='intentional')
        assert result['applied'] and host._last_character_interaction_time > 0
        assert host.current_action == 'idle'
        host._automatic_pose = host.current_action = 'sleep'
        host._mark_pet_interaction(140.)
        assert host.current_action == 'sleep'
        assert not host._apply_perception_affect('user_heart', event_id='sleep-heart')['accepted']
        calls = []
        original = host.mood_system.on_interaction

        def capture(event, **context):
            calls.append(event)
            return original(event, **context)

        monkeypatch.setattr(host.mood_system, 'on_interaction', capture)
        result = host._apply_perception_affect('user_greeting', event_id='wave-wake')
        assert result['accepted'] and result['appraisal']['wake']
        assert host.current_action == 'idle' and host._automatic_pose is None
        assert calls == ['user_greeting']
        host._automatic_pose = host.current_action = 'sleep'
        host._mark_pet_interaction(600.)
        assert host.current_action == 'idle' and calls[-1] == 'poke_start'
    finally:
        host.automatic_actions.shutdown()


def producer():
    root = str(Path(__file__).resolve().parents[1] / 'medeapipe_capstone')
    if root not in sys.path:
        sys.path.append(root)
    from app.recognition_engine import RecognitionEngine
    engine = RecognitionEngine.__new__(RecognitionEngine)
    engine.always_results, engine.last_sent_interaction_events = {}, {}
    engine.mode_result, engine.rps_sample, engine.cham_sample = {}, None, None
    engine.rps_session = engine.cham_session = None
    engine.latest_speech_text, engine.speech_sequence = '', 0
    engine.camera_status, engine.recognition_session = 'running', 'camera'
    engine.camera_sequence, engine.camera_observed_at = 1, 100.
    engine.emotion_result = {'label': 'Happy', 'confidence': .9, 'scores': {'Happy': .9},
                             'observation_id': 1, 'observed_at': 100.}
    engine.event_client = Mock()
    engine.loaded_emotion_model_key = 'emotieff_b2'
    return engine


def test_state_transport_is_bounded_but_speech_status_and_games_are_immediate(monkeypatch):
    engine, now = producer(), [100.]
    monkeypatch.setattr('app.recognition_engine.time.monotonic', lambda: now[0])
    for seq, stamp in enumerate((100., 100.05, 100.1, 100.21), 1):
        now[0], engine.camera_sequence, engine.camera_observed_at = stamp, seq, stamp
        engine.send_recognition_state()
    assert engine.event_client.send.call_count == 2
    sent = [call.args[0] for call in engine.event_client.send.call_args_list]
    assert sent[0]['observation']['sequence'] != sent[1]['observation']['sequence']
    assert sent[0]['always']['emotion']['observation_id'] == sent[1]['always']['emotion']['observation_id']
    now[0] = 100.22
    engine.latest_speech_text, engine.speech_sequence = '새 발화', 1
    engine.send_recognition_state()
    assert engine.event_client.send.call_count == 3
    engine.camera_status = 'off'
    engine.send_recognition_state()
    assert engine.event_client.send.call_count == 4
    engine.rps_session = {'session': 'game'}
    for seq in (5, 6, 7):
        engine.camera_sequence = seq
        engine.send_recognition_state()
    assert engine.event_client.send.call_count == 7


def test_actual_inferences_get_new_ids_and_cached_interval_keeps_its_id():
    engine = producer()
    engine.emotion_recognizer = Mock()
    engine.emotion_recognizer.predict.return_value = {'scores': {'Happy': .9, 'Neutral': .1}}
    engine.extract_face_crop = Mock(return_value=object())
    engine.last_emotion_inference_ms = -1000
    engine.update_emotion_result(None, None, 0)
    first = deepcopy(engine.build_emotion_state())
    engine.update_emotion_result(None, None, 50)
    assert engine.build_emotion_state() == first
    engine.camera_observed_at = 101.
    engine.update_emotion_result(None, None, 1000)
    assert engine.build_emotion_state()['observation_id'] != first['observation_id']
    assert engine.build_emotion_state()['observed_at'] == 101.
    assert engine.emotion_recognizer.predict.call_count == 2
