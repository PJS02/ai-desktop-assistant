from character.mood_system import MoodSystem
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
    assert snapshot["recovery_percent"] >= before


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
