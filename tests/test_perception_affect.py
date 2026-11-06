"""State-dependent interpretation and bounded effects on the real OCC store."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from character.mood_system import MoodSystem, OccEmotionToMood as OCC
from character.perception_affect import appraise_perception, choose_perception_face, profile_weights, state_labels
from character.personality_system import PersonalitySystem


@pytest.fixture
def clock(monkeypatch):
    now = [100.]
    monkeypatch.setattr('character.interaction_emotions.time.monotonic', lambda: now[0])
    return now


def test_mixed_profiles_preserve_both_fear_and_guard_without_double_counting():
    weights = profile_weights({'fear': .8, 'anger': .6, 'distress': .5}, (-.6, -.4))
    assert weights == pytest.approx({'normal': 0., 'fear': .4, 'guard': .3, 'down': .3})
    appraisal = appraise_perception('heart', {'fear': .8, 'anger': .6, 'distress': .5}, (-.6, -.4))
    assert appraisal['requested_occ']['fear'] < 0 and appraisal['requested_occ']['anger'] < 0
    assert appraisal['requested_occ']['relief'] > 0 and appraisal['requested_occ']['gratitude'] > 0


@pytest.mark.parametrize('seed,coordinates,expected,palette', [
    ({}, (.2, .1), 'joy', {'pleasant', 'happy', 'excited', 'serene'}),
    ({OCC.FEAR: .9}, (-.4, .5), 'fear', {'calm', 'relieved', 'serene'}),
    ({OCC.ANGER: .9}, (-.5, .3), 'anger', {'quiet', 'displeased', 'calm'}),
    ({OCC.DISTRESS: .9}, (-.6, -.5), 'distress', {'quiet', 'calm', 'serene'}),
])
def test_same_heart_changes_real_emotion_and_face_by_pre_event_state(seed, coordinates, expected, palette):
    mood = MoodSystem()
    mood.occ_intensities.update(seed)
    mood.russell.valence, mood.russell.arousal = coordinates
    result = mood.on_interaction('user_heart', event_id='heart:1')
    assert result['applied']
    assert result['changes'][expected] * (-1 if seed else 1) > 0
    assert choose_perception_face(result['appraisal']) in palette
    assert result['before'] == coordinates
    assert mood.get_emotion_explanation()['latest_change']['event_input']['actual_occ'] == result['changes']
    before = dict(mood.occ_intensities)
    assert mood.on_interaction('user_heart', event_id='heart:1')['duplicate']
    assert mood.occ_intensities == before


def test_ok_means_satisfaction_and_passive_smile_does_not_infer_gratitude():
    ok = appraise_perception('ok', {}, (0., 0.))['requested_occ']
    smile = appraise_perception('face', {}, (0., 0.), label='happy')['requested_occ']
    assert 'joy' not in ok and ok['satisfaction'] > 0
    assert 'gratitude' not in smile and smile['joy'] > 0


@pytest.mark.parametrize('label', ['anger', 'disgust', 'contempt', 'fear', 'sadness'])
def test_passive_negative_faces_do_not_assign_blame_or_shame(label):
    mood = MoodSystem()
    result = mood.on_interaction('user_face', label=label, quality=.9)
    assert result['applied'] and mood.occ_intensities[OCC.DISTRESS] > 0
    assert mood.occ_intensities[OCC.ANGER] == mood.occ_intensities[OCC.SHAME] == 0


def test_surprise_only_adds_small_arousal_without_imposed_negative_valence():
    mood = MoodSystem()
    result = mood.on_interaction('user_face', label='surprise')
    assert result['applied'] and not result['changes']
    assert 0 < mood._event_arousal_bias <= .02
    assert all(value == 0 for value in mood.occ_intensities.values())
    assert mood._target_valence == 0


@pytest.mark.parametrize('actor,signal,label,accepted,face,wake', [
    ({'closing': True}, 'heart', None, False, True, False),
    ({'physical': True}, 'heart', None, False, True, False),
    ({'manual_emotion': True}, 'heart', None, False, True, False),
    ({'manual_motion': True}, 'heart', None, True, True, False),
    ({'manual_face': True}, 'heart', None, True, False, False),
    ({'game': True}, 'heart', None, False, True, False),
    ({'game': True}, 'face', 'happy', True, False, False),
    ({'sleeping': True}, 'heart', None, False, True, False),
    ({'sleeping': True}, 'face', 'happy', False, True, False),
    ({'sleeping': True}, 'greeting', None, True, True, True),
    ({'sleeping': True, 'manual_motion': True}, 'greeting', None, False, True, False),
])
def test_behavior_ownership(actor, signal, label, accepted, face, wake):
    appraisal = appraise_perception(signal, {}, (0., -.5), actor, label=label)
    assert appraisal['accepted'] == accepted
    assert appraisal['reaction_allowed'] == face and appraisal['wake'] == wake


def test_head_interpretation_needs_recent_dialogue_and_tiredness_softens_response():
    assert not appraise_perception('head_negative', {}, (0., 0.))['accepted']
    assert appraise_perception('head_negative', {}, (0., 0.), {'recent_dialogue': True})['accepted']
    assert appraise_perception('heart', {}, (0., 0.), {'rest': .7})['multiplier'] == .7


def test_personality_and_repetition_scale_the_common_result(clock):
    mood = MoodSystem(PersonalitySystem())
    first = mood.on_interaction('user_heart')
    second = mood.on_interaction('user_heart')
    assert .25 <= first['appraisal']['personality_multiplier'] <= 2.
    assert first['appraisal']['repetition_multiplier'] > second['appraisal']['repetition_multiplier']
    assert sum(map(abs, first['changes'].values())) > sum(map(abs, second['changes'].values()))
    assert mood.get_emotion_explanation()['latest_change']['personality_factors']


def test_rolling_budgets_count_actual_absolute_changes_and_expire(clock):
    mood = MoodSystem()
    totals = {'face': 0., 'gesture': 0.}
    for index in range(90):
        family = 'face' if index % 3 == 0 else 'gesture'
        signal = 'user_face' if family == 'face' else 'user_heart'
        before = dict(mood.occ_intensities)
        mood.interactions.exposure.clear()
        result = mood.on_interaction(signal, label='happy', event_id=f'camera:{index}')
        amount = sum(abs(value) for value in result['changes'].values())
        totals[family] += amount
        assert amount <= .06 + 1e-12
        assert max(map(abs, result['changes'].values()), default=0) <= .04 + 1e-12
        assert all(value >= -.1 * before[OCC(name)] - 1e-12 for name, value in result['changes'].items())
        clock[0] += .25
    assert totals['face'] <= .06 + 1e-12 and totals['gesture'] <= .20 + 1e-12
    assert sum(totals.values()) <= .25 + 1e-12
    assert result['accepted'] and not result['applied']
    clock[0] += 61
    assert mood.on_interaction('user_heart', event_id='after-window')['applied']


def test_fear_recovery_never_erases_unrelated_fear_or_outstanding_fall_claim(clock):
    mood = MoodSystem()
    mood.occ_intensities[OCC.FEAR] = .4
    mood.on_interaction('fall_risk', distance=2.)
    before = mood.occ_intensities[OCC.FEAR]
    result = mood.on_interaction('user_heart')
    assert -.1 * before <= result['changes']['fear'] < 0
    mood.on_interaction('safe_landing')
    assert .3 < mood.occ_intensities[OCC.FEAR] <= .4


def test_arousal_budget_counts_actual_clipped_bias_and_excludes_physical_events(clock):
    mood = MoodSystem()
    mood.on_pet(140., .5)
    assert not mood.interactions.perception_budget
    mood._event_arousal_bias = .995
    mood.on_interaction('user_face', label='surprise')
    assert mood.interactions.perception_budget[-1][3] == pytest.approx(.005)
    mood._event_arousal_bias = 0.
    for index in range(10):
        clock[0] += .5
        mood.interactions.exposure.clear()
        result = mood.on_interaction('user_face', label='surprise', event_id=f'surprise:{index}')
    assert sum(item[3] for item in mood.interactions.perception_budget) <= .06 + 1e-12
    assert result['accepted'] and not result['applied']


def test_diagnostic_states_and_contact_refusal_have_hysteresis(clock):
    active, pending = set(), {}
    occ = {'fear': .5, 'anger': .7, 'distress': .5}
    state_labels(occ, (-.5, -.4), .7, active, pending, 100.)
    assert not active
    state_labels(occ, (-.5, -.4), .7, active, pending, 100.31)
    assert {'fear', 'guard', 'down', 'tired', 'contact_refusal'} <= active
    state_labels({}, (0., 0.), 0., active, pending, 101.)
    state_labels({}, (0., 0.), 0., active, pending, 101.9)
    assert active
    state_labels({}, (0., 0.), 0., active, pending, 102.01)
    assert not active
    mood = MoodSystem()
    mood.russell.valence = -.5
    mood.occ_intensities[OCC.ANGER] = .7
    assert not mood.should_refuse_pet()
    clock[0] += .31
    assert mood.should_refuse_pet()
    mood.occ_intensities[OCC.ANGER] = .55
    assert mood.should_refuse_pet()
    mood.occ_intensities[OCC.ANGER] = .4
    assert mood.should_refuse_pet()
    clock[0] += 1.01
    assert not mood.should_refuse_pet()


def test_manual_russell_pause_drops_inputs_without_deferred_replay():
    mood = MoodSystem()
    mood._manual_russell_override = True
    assert not mood.on_interaction('user_heart', event_id='held')['accepted']
    mood._manual_russell_override = False
    assert mood.on_interaction('user_heart', event_id='held')['duplicate']
    assert all(value == 0 for value in mood.occ_intensities.values())


def test_reaction_priority_manual_pin_and_restoring_current_mood():
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from character.reactions import Reactions, experience
    from character.rig_state import RigAnimator
    app = QApplication.instance() or QApplication([])

    class View(QObject):
        animation_finished = pyqtSignal()

        def set_emotion(self, face):
            self.face = face

        def release(self):
            pass

    host = QObject()
    host.mood_system = MoodSystem()
    host.rig_view = View(host)
    host.sprite_animator = RigAnimator(host.rig_view, mood_face=host.mood_system.get_display_emotion)
    host._character_closing = host._hand_throw_active = False
    host.isVisible = lambda: True
    host.manual_control = SimpleNamespace(display_emotion=None)
    host.reactions = Reactions(host)
    try:
        experience(host, 'user_heart', event_id='h1')
        assert host.reactions.event == 'user_heart'
        host.reactions.play('game_loss')
        face = host.rig_view.face
        result = experience(host, 'user_heart', event_id='h2')
        assert result['applied'] and host.rig_view.face == face
        host.reactions.clear()
        host.manual_control.display_emotion = 'sad'
        host.sprite_animator.set_emotion_override('sad')
        experience(host, 'user_heart', event_id='h3')
        assert host.rig_view.face == 'sad' and host.reactions.event is None
        host.reactions.play('fall_risk', source='fall')
        assert host.rig_view.face != 'sad'
        host.manual_control.display_emotion = None
        host.sprite_animator.set_emotion_override(None)
        host.mood_system.advance_emotion(30.)
        host.reactions.clear()
        assert host.rig_view.face == host.mood_system.get_display_emotion()
    finally:
        host.reactions.cancel()
        host.sprite_animator.release()
