from character.mood_system import MoodSystem


def test_positive_external_emotion_moves_valence_positive():
    mood = MoodSystem()

    assert mood.on_external_emotion("Happy", 0.9)
    assert mood.russell.valence > 0


def test_negative_external_emotion_moves_valence_negative():
    mood = MoodSystem()

    assert mood.on_external_emotion("Anger", 0.9)
    assert mood.russell.valence < 0


def test_unknown_and_neutral_emotions_are_ignored():
    mood = MoodSystem()

    assert not mood.on_external_emotion("neutral", 0.9)
    assert not mood.on_external_emotion("not-a-real-emotion", 0.9)


def test_emotion_moves_toward_target_over_time():
    mood = MoodSystem()

    mood.on_external_emotion("anger", 0.9)
    initial_valence = mood.russell.valence
    target_valence = mood._target_valence

    mood.advance_emotion(0.1)

    assert target_valence < initial_valence < 0


def test_idle_pressure_is_continuous_and_bounded():
    mood = MoodSystem()

    mood.update_idle_pressure(10.0)
    at_start = mood._target_valence
    mood.update_idle_pressure(60.0)
    after_fifty_seconds = mood._target_valence
    mood.update_idle_pressure(600.0)
    after_long_idle = mood._target_valence

    assert at_start == 0.0
    assert -0.18 < after_fifty_seconds < 0.0
    assert after_long_idle == -0.18
