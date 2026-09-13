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
