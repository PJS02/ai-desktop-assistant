from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Mapping


SCHEMA_VERSION = 1

_INACTIVE_LABELS = {
    "",
    "-",
    "none",
    "null",
    "wait",
    "waiting",
    "unknown",
    "recognition_waiting",
    "searching_face",
}

_EMOTION_ALIASES = {
    "angry": "anger",
    "anger": "anger",
    "contempt": "contempt",
    "disgust": "disgust",
    "fear": "fear",
    "happy": "happy",
    "happiness": "happy",
    "joy": "happy",
    "sad": "sadness",
    "sadness": "sadness",
    "surprised": "surprise",
    "surprise": "surprise",
    "neutral": "neutral",
}


@dataclass(frozen=True)
class EmotionObservation:
    label: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GestureObservation:
    kind: str
    label: str
    side: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class PerceptionEvent:
    source: str
    timestamp: float
    emotion: EmotionObservation | None = None
    gestures: tuple[GestureObservation, ...] = ()
    head_motion: str | None = None
    attention: str | None = None
    speech: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def _canonical_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if label in _INACTIVE_LABELS:
        return None
    return label


def _canonical_emotion(value: Any) -> str | None:
    label = _canonical_label(value)
    if label is None:
        return None
    return _EMOTION_ALIASES.get(label, label)


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _normalise_scores(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    scores: dict[str, float] = {}
    for raw_label, raw_score in value.items():
        label = _canonical_emotion(raw_label)
        if label is not None:
            scores[label] = _clamp_confidence(raw_score)
    return scores


def _parse_emotion(value: Any) -> EmotionObservation | None:
    if not isinstance(value, Mapping):
        return None
    label = _canonical_emotion(value.get("label"))
    if label is None:
        return None
    scores = _normalise_scores(value.get("scores"))
    confidence = value.get("confidence")
    if confidence is None:
        confidence = scores.get(label, max(scores.values(), default=0.0))
    return EmotionObservation(
        label=label,
        confidence=_clamp_confidence(confidence),
        scores=scores,
    )


def _parse_gesture_item(value: Any, default_kind: str = "motion") -> GestureObservation | None:
    if isinstance(value, str):
        label = _canonical_label(value)
        return GestureObservation(default_kind, label) if label else None
    if not isinstance(value, Mapping):
        return None
    label = _canonical_label(value.get("label") or value.get("value"))
    if label is None:
        return None
    kind = _canonical_label(value.get("kind")) or default_kind
    side = _canonical_label(value.get("side"))
    confidence_value = value.get("confidence")
    confidence = None if confidence_value is None else _clamp_confidence(confidence_value)
    return GestureObservation(kind=kind, label=label, side=side, confidence=confidence)


def _parse_native_event(payload: Mapping[str, Any]) -> PerceptionEvent:
    gestures: list[GestureObservation] = []
    raw_motions = payload.get("motions", payload.get("motion", []))
    if isinstance(raw_motions, (str, Mapping)):
        raw_motions = [raw_motions]
    if isinstance(raw_motions, list):
        for item in raw_motions:
            gesture = _parse_gesture_item(item)
            if gesture is not None:
                gestures.append(gesture)

    return PerceptionEvent(
        source=str(payload.get("source") or "external"),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        emotion=_parse_emotion(payload.get("emotion")),
        gestures=tuple(gestures),
        head_motion=_canonical_label(payload.get("head_motion")),
        attention=_canonical_label(payload.get("attention")),
        speech=_parse_speech(payload.get("speech")),
        raw=dict(payload),
    )


def _parse_legacy_recognition_state(payload: Mapping[str, Any]) -> PerceptionEvent:
    always = payload.get("always")
    always = always if isinstance(always, Mapping) else {}
    gestures: list[GestureObservation] = []

    for key, kind in (("wave", "wave"), ("hand_gesture", "hand_gesture")):
        group = always.get(key)
        if not isinstance(group, Mapping):
            continue
        for side in ("left", "right"):
            label = _canonical_label(group.get(side))
            if label is not None:
                gestures.append(GestureObservation(kind=kind, label=label, side=side))

    head = always.get("head")
    head_motion = None
    if isinstance(head, Mapping):
        head_motion = _canonical_label(head.get("value") or head.get("overlay"))

    attention_group = always.get("attention")
    attention = None
    if isinstance(attention_group, Mapping):
        attention = _canonical_label(
            attention_group.get("value") or attention_group.get("overlay")
        )

    speech_group = payload.get("speech")
    speech = None
    if isinstance(speech_group, Mapping):
        speech = _parse_speech(speech_group.get("latest_text"))

    return PerceptionEvent(
        source=str(payload.get("source") or "mediapipe_capstone"),
        timestamp=_parse_timestamp(payload.get("timestamp")),
        emotion=_parse_emotion(always.get("emotion")),
        gestures=tuple(gestures),
        head_motion=head_motion,
        attention=attention,
        speech=speech,
        raw=dict(payload),
    )


def _parse_timestamp(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return time.time()


def _parse_speech(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_perception_event(payload: Mapping[str, Any]) -> PerceptionEvent:
    """Convert supported model output payloads into one canonical event."""
    if not isinstance(payload, Mapping):
        raise ValueError("perception payload must be a JSON object")

    event_type = _canonical_label(payload.get("type"))
    if event_type == "recognition_state":
        return _parse_legacy_recognition_state(payload)
    if event_type in {"perception", "perception_event"}:
        version = payload.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported perception schema version: {version}")
        return _parse_native_event(payload)
    raise ValueError(f"unsupported perception event type: {payload.get('type')!r}")
