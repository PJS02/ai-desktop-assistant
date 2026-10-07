import pytest

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

    def thumbs(stamp):
        payload = _legacy_payload(stamp)
        payload['always']['hand_gesture']['left'] = 'THUMBS_UP'
        return payload
    controller.handle_payload(thumbs(100.0))
    controller.handle_payload(thumbs(100.0))
    assert dialogues == ["좋아! 👍"]
    assert mood.clicks == 1

    controller.handle_payload(_legacy_payload(100.0, wave="NONE"))
    now[0] += 4.0
    controller.handle_payload(thumbs(104.0))
    assert dialogues == ["좋아! 👍", "좋아! 👍"]
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


@pytest.mark.parametrize('side', ['left', 'right', 'both'])
@pytest.mark.parametrize('speech', ['', '안녕', '다른 말'])
def test_wave_alone_greets_once_and_logs_detection(side, speech, capsys):
    greetings = []
    mood = FakeMoodSystem()
    controller = PerceptionController(mood, on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: 100.0)
    payload = _legacy_payload(100.0, speech=speech, speech_sequence=1)
    for hand in (['left', 'right'] if side == 'both' else [side]):
        payload['always']['wave'][hand] = 'HELLO'
    controller.handle_payload(payload)
    controller.handle_payload(payload)
    assert greetings == [True] and mood.clicks == 1
    output = capsys.readouterr().out
    assert output.count('[외부 동작 인식] 손 흔들기') == 1


def test_speech_without_wave_does_not_trigger_greeting():
    dialogues = []
    controller = PerceptionController(FakeMoodSystem(), on_dialogue=dialogues.append,
                                      time_provider=lambda: 100.0)
    controller.handle_payload(_legacy_payload(100.0, speech='안녕', speech_sequence=1))
    assert dialogues == []


def test_continuing_wave_does_not_greet_after_cooldown_and_new_wave_does():
    now = [100.0]
    greetings = []
    controller = PerceptionController(FakeMoodSystem(), on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: now[0])
    controller.handle_payload(_legacy_payload(100.0, wave='HELLO'))
    now[0] = 108.0
    controller.handle_payload(_legacy_payload(108.0, wave='HELLO'))
    assert len(greetings) == 1
    controller.handle_payload(_legacy_payload(108.0, wave='NONE'))
    controller.handle_payload(_legacy_payload(108.0, wave='HELLO'))
    assert len(greetings) == 2


def test_wave_during_cooldown_is_logged_without_delayed_replay(capsys):
    now = [100.0]
    greetings = []
    controller = PerceptionController(FakeMoodSystem(), on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: now[0])
    controller.handle_payload(_legacy_payload(100.0, wave='HELLO'))
    now[0] = 104.0
    controller.handle_payload(_legacy_payload(104.0, wave='NONE'))
    controller.handle_payload(_legacy_payload(104.0, wave='HELLO'))
    now[0] = 107.0
    controller.handle_payload(_legacy_payload(107.0, wave='HELLO'))
    assert greetings == [True]
    output = capsys.readouterr().out
    assert output.count('[외부 동작 인식] 손 흔들기') == 2
    assert '재인사 대기 중' in output


def test_stale_cached_wave_after_reconnect_does_not_greet():
    greetings = []
    controller = PerceptionController(FakeMoodSystem(), on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: 100.0)
    payload = _legacy_payload(100.0, wave='HELLO')
    payload['always']['wave']['started_at'] = 90.0
    controller.handle_payload(payload)
    assert greetings == []


def test_wave_state_is_tracked_per_source():
    now = [100.0]
    greetings = []
    controller = PerceptionController(FakeMoodSystem(), on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: now[0])
    payload = _legacy_payload(100.0, wave='HELLO')
    payload['source'] = 'camera_a'
    controller.handle_payload(payload)
    now[0] = 108.0
    payload = _legacy_payload(108.0)
    payload['source'] = 'camera_b'
    controller.handle_payload(payload)
    payload = _legacy_payload(108.0, wave='HELLO')
    payload['source'] = 'camera_a'
    controller.handle_payload(payload)
    assert greetings == [True]


def test_common_perception_schema_wave_without_speech_also_greets():
    greetings = []
    controller = PerceptionController(FakeMoodSystem(), on_greeting=lambda: greetings.append(True),
                                      time_provider=lambda: 100.0)
    controller.handle_payload({'type': 'perception', 'source': 'external', 'timestamp': 100.0,
                               'motions': [{'kind': 'gesture', 'label': 'wave', 'side': 'right'}]})
    assert greetings == [True]
