from __future__ import annotations

import time
from typing import Any, Mapping, Protocol

from .events import SCHEMA_VERSION


class EmotionPredictor(Protocol):
    """기존 및 외부 감정 모델이 맞춰야 하는 최소 예측 인터페이스."""

    def predict(self, input_data: Any) -> Mapping[str, Any]:
        ...


class EmotionModelAdapter:
    """각 모델의 예측 결과를 공통 perception 이벤트 형식으로 감싼다."""

    def __init__(
        self,
        predictor: EmotionPredictor,
        source: str,
        label_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.predictor = predictor
        self.source = source
        # 외부 모델의 고유 라벨을 내부 라벨로 바꾸되 원본 모델 코드는 수정하지 않는다.
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
            # confidence를 따로 주지 않는 모델은 클래스별 점수에서 신뢰도를 구한다.
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
