from perception.controller import PerceptionController
from perception.events import parse_perception_event


class FakeMoodSystem:
    def __init__(self):
        self.external_emotions = []
        self.clicks = 0
        self.idles = 0

    def on_external_emotion(self, label, confidence):
        self.external_emotions.append((label, confidence))
        return True

    def on_click(self):
        self.clicks += 1

    def on_idle(self):
        self.idles += 1


def _legacy_payload(
    timestamp,
    emotion=None,
    wave="NONE",
    attention="SCREEN",
    speech="",
    speech_sequence=0,
):
    return {
        "type": "recognition_state",
        "timestamp": timestamp,
        "always": {
            "wave": {"left": wave, "right": "NONE"},
            "hand_gesture": {"left": "NONE", "right": "NONE"},
            "head": {"value": "WAIT"},
            "attention": {"value": attention},
            "emotion": emotion or {"label": None, "scores": {}},
        },
        "speech": {"latest_text": speech, "sequence": speech_sequence},
    }


def test_requires_stable_emotion_before_applying_it():
    now = [100.0]
    mood = FakeMoodSystem()
    controller = PerceptionController(mood, time_provider=lambda: now[0])
    payload = _legacy_payload(
        100.0,
        emotion={"label": "Happy", "scores": {"Happy": 0.9}},
    )

    controller.handle_payload(payload)
    controller.handle_payload(payload)
    assert mood.external_emotions == []

    controller.handle_payload(payload)
    assert mood.external_emotions == [("happy", 0.9)]

    controller.handle_payload(payload)
    assert len(mood.external_emotions) == 1


def test_reacts_only_when_gesture_becomes_active():
    now = [100.0]
    dialogues = []
    mood = FakeMoodSystem()
    controller = PerceptionController(
        mood,
        on_dialogue=dialogues.append,
        time_provider=lambda: now[0],
    )

    controller.handle_payload(_legacy_payload(100.0, wave="HELLO"))
    controller.handle_payload(_legacy_payload(100.0, wave="HELLO"))
    assert dialogues == ["안녕! 👋"]
    assert mood.clicks == 1

    controller.handle_payload(_legacy_payload(100.0, wave="NONE"))
    now[0] += 4.0
    controller.handle_payload(_legacy_payload(104.0, wave="HELLO"))
    assert dialogues == ["안녕! 👋", "안녕! 👋"]
    assert mood.clicks == 2


def test_ignores_stale_events_and_tracks_attention_transition():
    now = [100.0]
    mood = FakeMoodSystem()
    controller = PerceptionController(mood, time_provider=lambda: now[0])

    stale = parse_perception_event(_legacy_payload(90.0, attention="AWAY"))
    controller.handle_event(stale)
    assert mood.idles == 0

    controller.handle_payload(_legacy_payload(100.0, attention="AWAY"))
    controller.handle_payload(_legacy_payload(100.0, attention="AWAY"))
    assert mood.idles == 1


def test_logs_each_speech_sequence_once(capsys):
    mood = FakeMoodSystem()
    controller = PerceptionController(mood, time_provider=lambda: 100.0)

    controller.handle_payload(
        _legacy_payload(100.0, speech="안녕하세요", speech_sequence=1)
    )
    controller.handle_payload(
        _legacy_payload(100.0, speech="안녕하세요", speech_sequence=1)
    )
    controller.handle_payload(
        _legacy_payload(100.0, speech="안녕하세요", speech_sequence=2)
    )

    output = capsys.readouterr().out
    assert output.count("[외부 음성 인식] 안녕하세요") == 2
