import pytest

from perception.events import parse_perception_event


def test_parses_existing_mediapipe_recognition_state():
    event = parse_perception_event(
        {
            "type": "recognition_state",
            "timestamp": 100.0,
            "always": {
                "wave": {"left": "HELLO", "right": "NONE"},
                "hand_gesture": {"left": "NONE", "right": "THUMBS_UP"},
                "head": {"value": "AGREE", "label": "동의"},
                "attention": {"value": "SCREEN", "label": "화면 응시"},
                "emotion": {
                    "label": "Happy",
                    "scores": {"Happy": 0.91, "Sadness": 0.09},
                },
            },
            "speech": {"latest_text": "안녕", "sequence": 3},
        }
    )

    assert event.source == "mediapipe_capstone"
    assert event.emotion is not None
    assert event.emotion.label == "happy"
    assert event.emotion.confidence == pytest.approx(0.91)
    assert {(item.kind, item.side, item.label) for item in event.gestures} == {
        ("wave", "left", "hello"),
        ("hand_gesture", "right", "thumbs_up"),
    }
    assert event.head_motion == "agree"
    assert event.attention == "screen"
    assert event.speech == "안녕"
    assert event.speech_id == 3


def test_parses_source_independent_perception_event():
    event = parse_perception_event(
        {
            "type": "perception",
            "version": 1,
            "source": "external-fer-model",
            "timestamp": 123.0,
            "emotion": {"label": "Happiness", "confidence": 0.8},
            "motions": [
                {"kind": "gesture", "label": "HEART", "side": "right", "confidence": 0.7}
            ],
            "attention": "LOOKING_AWAY",
        }
    )

    assert event.source == "external-fer-model"
    assert event.emotion is not None
    assert event.emotion.label == "happy"
    assert event.gestures[0].label == "heart"
    assert event.attention == "looking_away"


def test_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="unsupported perception event type"):
        parse_perception_event({"type": "something_else"})
