import pytest

from character.mood_system import MoodSystem, OccEmotionToMood
from character.personality_system import PersonalitySystem


def test_appraised_event_exposes_personality_weight_and_coordinate_delta():
    mood = MoodSystem(PersonalitySystem("Russell (기본)"))

    mood.on_click()

    snapshot = mood.get_emotion_explanation()
    latest = snapshot["latest_change"]
    assert latest["source"] == "캐릭터 클릭"
    assert latest["category"] == "positive"
    assert latest["personality_multiplier"] > 1.0
    assert latest["adjusted_weight"] > latest["base_weight"]
    assert latest["personality_factors"]
    assert latest["occ_changes"]
    assert len(snapshot["coordinate_history"]) == 2


def test_external_emotion_is_named_as_an_explanation_source():
    mood = MoodSystem()

    assert mood.on_external_emotion("Happy", 0.9)

    snapshot = mood.get_emotion_explanation()
    latest = snapshot["latest_change"]
    assert latest["source"] == "사용자 웃음 감지"
    assert latest["category"] == "positive"
    assert latest["details"] == "인식 신뢰도 90%"


def test_decay_adds_recovery_step_and_updates_recovery_percent():
    mood = MoodSystem()
    mood.on_external_emotion("Anger", 1.0)
    before = mood.get_emotion_explanation()["recovery_percent"]

    mood.decay()

    snapshot = mood.get_emotion_explanation()
    assert snapshot["latest_change"]["category"] == "recovery"
    assert snapshot["latest_change"]["source"] == "시간 경과에 따른 자연 회복"
    assert snapshot["latest_change"]["personality_factors"] == [
        "부정 감정 95% · 긍정 감정 94% 유지"
    ]
    assert snapshot["recovery_percent"] >= before


def test_recovery_explanation_uses_the_factors_applied_to_emotion_intensity(monkeypatch):
    monkeypatch.setattr(MoodSystem, "_NEGATIVE_EMOTION_RETENTION", 0.8)
    monkeypatch.setattr(MoodSystem, "_POSITIVE_EMOTION_RETENTION", 0.7)
    mood = MoodSystem()
    mood.on_external_emotion("Anger", 1.0)
    mood.occ_intensities[OccEmotionToMood.JOY] = 0.5
    before_anger = mood.occ_intensities[OccEmotionToMood.ANGER]

    mood.decay()

    assert mood.occ_intensities[OccEmotionToMood.ANGER] == pytest.approx(before_anger * 0.8)
    assert mood.occ_intensities[OccEmotionToMood.JOY] == pytest.approx(0.35)
    assert mood.get_emotion_explanation()["latest_change"]["personality_factors"] == [
        "부정 감정 80% · 긍정 감정 70% 유지"
    ]


def test_repeated_drag_samples_are_coalesced_for_readable_history():
    mood = MoodSystem()

    mood.apply_drag_displeasure(4.0)
    mood.apply_drag_displeasure(4.1)
    mood.apply_drag_displeasure(4.2)

    snapshot = mood.get_emotion_explanation()
    assert len(snapshot["recent_events"]) == 1
    assert snapshot["latest_change"]["source"] == "지속적인 캐릭터 드래그"
    assert snapshot["latest_change"]["base_weight"] > 0.03


def test_manual_russell_adjustment_is_visible_as_a_reason():
    mood = MoodSystem()

    mood.set_russell_state(0.5, -0.2)

    latest = mood.get_emotion_explanation()["latest_change"]
    assert latest["source"] == "수동 감정 좌표 조정"
    assert latest["category"] == "manual"
    assert latest["after_valence"] == mood.russell.valence
    assert latest["impact_score"] > 0


def test_explanation_returns_retained_history_and_explicit_limit():
    mood = MoodSystem()
    for _ in range(305):
        mood.on_click()
    snapshot = mood.get_emotion_explanation()
    assert len(snapshot['recent_events']) == 300
    assert snapshot['history'] == {'capacity': 300, 'retained': 300, 'shown': 300, 'excluded': 5}
    assert len(mood.get_emotion_explanation(limit=8)['recent_events']) == 8


def test_pet_records_occ_and_target_without_forcing_instant_coordinate_movement():
    mood = MoodSystem()
    amount = mood.on_pet(140, 0.5)
    latest = mood.get_emotion_explanation()['latest_change']
    assert amount == pytest.approx(0.5)
    assert latest['source'] == '쓰다듬기'
    assert latest['delta_valence'] == latest['delta_arousal'] == 0
    assert latest['occ_changes']['joy'] == pytest.approx(0.45)
    assert latest['target_changes']['valence'] > 0
    assert latest['event_input']['movement_speed'] == 140
    assert latest['weight_applied'] is False


def test_pet_burst_keeps_identity_and_excludes_interpolation_from_direct_delta(monkeypatch):
    import character.mood_system as module
    clock = [100.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    mood = MoodSystem()
    mood.on_pet(140, .1)
    first = mood.get_emotion_explanation()['latest_change']
    mood.advance_emotion(1)
    clock[0] += .1
    mood.on_pet(180, .1)
    merged = mood.get_emotion_explanation()['latest_change']
    assert merged['event_id'] == first['event_id']
    assert merged['sample_count'] == 2
    assert merged['started_at'] == 100.0
    assert merged['delta_valence'] == 0
    assert merged['after_valence'] > merged['before_valence']
    assert merged['occ_changes']['joy'] == pytest.approx(mood.occ_intensities[OccEmotionToMood.JOY])
    assert merged['input_ranges']['movement_speed'] == {'min': 140, 'max': 180}
    clock[0] += .6
    mood.on_pet(140, .1)
    assert len(mood.get_emotion_explanation()['recent_events']) == 2


def test_idle_pressure_records_its_contribution_and_interaction_reset():
    mood = MoodSystem()
    mood.update_idle_pressure(100)
    latest = mood.get_emotion_explanation()['latest_change']
    assert latest['occ_changes'] == {}
    assert latest['delta_valence'] == 0
    assert latest['event_input']['idle_valence_after'] == pytest.approx(-.18)
    assert latest['event_input']['idle_arousal_after'] == pytest.approx(-.08)
    mood.update_idle_pressure(101)
    assert len(mood.get_emotion_explanation()['recent_events']) == 1
    mood.update_idle_pressure(0)
    assert mood.get_emotion_explanation()['latest_change']['category'] == 'recovery'
    assert mood.get_emotion_explanation()['latest_change']['event_input']['pressure_after'] == 0


@pytest.mark.parametrize('method,factor', [('on_self_rest', .88), ('on_ball_play', .9)])
def test_rest_and_ball_evidence_includes_pre_appraisal_anger_recovery(method, factor):
    mood = MoodSystem()
    mood.occ_intensities[OccEmotionToMood.ANGER] = .5
    getattr(mood, method)()
    snapshot = mood.get_emotion_explanation()
    latest = snapshot['latest_change']
    assert len(snapshot['recent_events']) == 1
    assert latest['occ_before']['anger'] == .5
    assert latest['occ_after']['anger'] == pytest.approx(.5 * factor)
    assert latest['occ_changes']['anger'] == pytest.approx(.5 * (factor - 1))
    assert latest['source'] != '감정 사건'
    assert latest['details']


def test_all_autonomous_events_have_distinct_names_and_details():
    mood = MoodSystem()
    for method in ('on_self_play', 'on_self_rest', 'on_self_curiosity'):
        getattr(mood, method)()
    events = mood.get_emotion_explanation()['recent_events']
    assert {item['source'] for item in events} == {'혼자 놀기', '스스로 쉬기', '주변 살피기'}
    assert all(item['details'] for item in events)


def test_recovery_accumulates_all_steps_and_splits_at_another_cause():
    mood = MoodSystem()
    mood.on_external_emotion('anger', 1)
    initial = mood.occ_intensities[OccEmotionToMood.ANGER]
    for _ in range(3):
        mood.decay()
    latest = mood.get_emotion_explanation()['latest_change']
    assert latest['sample_count'] == 3
    assert latest['occ_changes']['anger'] == pytest.approx(initial * (.95 ** 3 - 1))
    old_id = latest['event_id']
    mood.on_pet(140, .1)
    before = mood.occ_intensities[OccEmotionToMood.ANGER]
    mood.decay()
    latest = mood.get_emotion_explanation()['latest_change']
    assert latest['event_id'] != old_id
    assert latest['sample_count'] == 1
    assert latest['occ_changes']['anger'] == pytest.approx(before * -.05)


def test_history_is_a_detached_snapshot_of_event_time_personality():
    personality = PersonalitySystem()
    mood = MoodSystem(personality)
    mood.on_click()
    first = mood.get_emotion_explanation()['latest_change']
    recorded = first['personality']['traits']['extraversion']
    personality.personality.extraversion = -.9
    first['personality']['traits']['extraversion'] = 999
    first['event_input']['goal_relevance'] = 999
    latest = mood.get_emotion_explanation()['latest_change']
    assert latest['personality']['traits']['extraversion'] == recorded
    assert latest['event_input']['goal_relevance'] != 999


def test_recovery_status_distinguishes_hold_manual_and_live_decay():
    mood = MoodSystem()
    mood.on_click()
    assert mood.get_emotion_explanation()['decay_status']['reason'] == 'emotion_hold'
    count = len(mood.get_emotion_explanation()['recent_events'])
    mood.decay()
    assert len(mood.get_emotion_explanation()['recent_events']) == count
    mood.set_russell_state(.1, .2)
    assert mood.get_emotion_explanation()['decay_status']['reason'] == 'manual_override'
    mood.clear_manual_russell_state()
    mood._emotion_hold_until = 0
    assert mood.get_emotion_explanation()['decay_status']['reason'] == 'active'
