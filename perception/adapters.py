from __future__ import annotations

import time
from typing import Any, Mapping, Protocol

from .events import SCHEMA_VERSION


class EmotionPredictor(Protocol):
    """Structural interface implemented by current and external emotion models."""

    def predict(self, input_data: Any) -> Mapping[str, Any]:
        ...


class EmotionModelAdapter:
    """Wrap a model's prediction in the common perception event contract."""

    def __init__(
        self,
        predictor: EmotionPredictor,
        source: str,
        label_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.predictor = predictor
        self.source = source
        self.label_aliases = {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in (label_aliases or {}).items()
        }

    def predict_event(self, input_data: Any, timestamp: float | None = None) -> dict[str, Any]:
        prediction = self.predictor.predict(input_data)
        if not isinstance(prediction, Mapping):
            raise ValueError("emotion predictor must return a mapping")

        raw_label = prediction.get("label")
        if raw_label is None:
            raise ValueError("emotion prediction is missing a label")
        label = str(raw_label).strip()
        label = self.label_aliases.get(label.lower(), label)

        scores_value = prediction.get("scores")
        scores = dict(scores_value) if isinstance(scores_value, Mapping) else {}
        confidence = prediction.get("confidence")
        if confidence is None:
            confidence = scores.get(raw_label, max(scores.values(), default=0.0))

        return {
            "type": "perception",
            "version": SCHEMA_VERSION,
            "source": self.source,
            "timestamp": time.time() if timestamp is None else float(timestamp),
            "emotion": {
                "label": label,
                "confidence": max(0.0, min(1.0, float(confidence))),
                "scores": scores,
            },
        }
