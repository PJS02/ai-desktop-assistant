import pytest

from perception.adapters import EmotionModelAdapter


class FakePredictor:
    def predict(self, _input_data):
        return {
            "label": "Happiness",
            "confidence": 0.82,
            "scores": {"Happiness": 0.82, "Sadness": 0.18},
        }


def test_wraps_external_model_prediction_in_common_event():
    adapter = EmotionModelAdapter(
        predictor=FakePredictor(),
        source="external-test-model",
        label_aliases={"happiness": "happy"},
    )

    event = adapter.predict_event(object(), timestamp=123.0)

    assert event["type"] == "perception"
    assert event["version"] == 1
    assert event["source"] == "external-test-model"
    assert event["timestamp"] == 123.0
    assert event["emotion"]["label"] == "happy"
    assert event["emotion"]["confidence"] == pytest.approx(0.82)
