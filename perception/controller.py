from __future__ import annotations

from collections import deque
import time
from typing import Callable

from .events import PerceptionEvent, parse_perception_event


class PerceptionController:
    """Turns canonical perception events into character-safe reactions."""

    def __init__(
        self,
        mood_system,
        on_dialogue: Callable[[str], None] | None = None,
        emotion_confidence: float = 0.55,
        emotion_samples: int = 3,
        emotion_cooldown: float = 4.0,
        reaction_cooldown: float = 3.0,
        max_event_age: float = 5.0,
        time_provider: Callable[[], float] = time.time,
    ) -> None:
        self.mood_system = mood_system
        self.on_dialogue = on_dialogue or (lambda _text: None)
        self.emotion_confidence = emotion_confidence
        self.emotion_cooldown = emotion_cooldown
        self.reaction_cooldown = reaction_cooldown
        self.max_event_age = max_event_age
        self.time_provider = time_provider
        self._emotion_history: deque[str] = deque(maxlen=max(1, emotion_samples))
        self._last_emotion: str | None = None
        self._last_emotion_at = 0.0
        self._active_gestures: set[tuple[str, str | None, str]] = set()
        self._last_reaction_at: dict[str, float] = {}
        self._last_head_motion: str | None = None
        self._last_attention: str | None = None
        self.last_event: PerceptionEvent | None = None

    def handle_payload(self, payload: dict) -> PerceptionEvent:
        event = parse_perception_event(payload)
        self.handle_event(event)
        return event

    def handle_event(self, event: PerceptionEvent) -> None:
        now = self.time_provider()
        if event.timestamp > 0 and now - event.timestamp > self.max_event_age:
            return
        self.last_event = event
        self._handle_emotion(event, now)
        self._handle_gestures(event, now)
        self._handle_head_motion(event, now)
        self._handle_attention(event)

    def _handle_emotion(self, event: PerceptionEvent, now: float) -> None:
        observation = event.emotion
        if observation is None or observation.confidence < self.emotion_confidence:
            self._emotion_history.clear()
            return
        if observation.label == "neutral":
            self._emotion_history.clear()
            return

        self._emotion_history.append(observation.label)
        if len(self._emotion_history) < self._emotion_history.maxlen:
            return
        if len(set(self._emotion_history)) != 1:
            return
        if self._last_emotion == observation.label and now - self._last_emotion_at < self.emotion_cooldown:
            return

        if self.mood_system.on_external_emotion(observation.label, observation.confidence):
            self._last_emotion = observation.label
            self._last_emotion_at = now
            print(
                f"[외부 감정 인식] {observation.label} "
                f"(신뢰도: {observation.confidence:.2f}, 출처: {event.source})"
            )

    def _handle_gestures(self, event: PerceptionEvent, now: float) -> None:
        active = {(item.kind, item.side, item.label) for item in event.gestures}
        for kind, side, label in active - self._active_gestures:
            reaction_key = f"{kind}:{side}:{label}"
            if now - self._last_reaction_at.get(reaction_key, 0.0) < self.reaction_cooldown:
                continue
            message = self._gesture_message(kind, label)
            if message is None:
                continue
            self.mood_system.on_click()
            self.on_dialogue(message)
            self._last_reaction_at[reaction_key] = now
            print(f"[외부 동작 인식] {kind}/{label} ({side or 'unknown'})")
        self._active_gestures = active

    def _handle_head_motion(self, event: PerceptionEvent, now: float) -> None:
        label = event.head_motion
        if label is None:
            self._last_head_motion = None
            return
        if label == self._last_head_motion:
            return
        self._last_head_motion = label
        reaction_key = f"head:{label}"
        if now - self._last_reaction_at.get(reaction_key, 0.0) < self.reaction_cooldown:
            return
        message = {
            "agree": "응, 그렇게 해보자!",
            "negative": "알겠어. 다른 방법을 생각해볼게.",
        }.get(label)
        if message:
            self.on_dialogue(message)
            self._last_reaction_at[reaction_key] = now
            print(f"[외부 고개 동작 인식] {label}")

    def _handle_attention(self, event: PerceptionEvent) -> None:
        attention = event.attention
        if attention == self._last_attention:
            return
        self._last_attention = attention
        if attention == "away":
            self.mood_system.on_idle()
            print("[외부 상태 인식] 사용자가 자리를 비움")

    @staticmethod
    def _gesture_message(kind: str, label: str) -> str | None:
        if kind == "wave" and label == "hello":
            return "안녕! 👋"
        return {
            "thumbs_up": "좋아! 👍",
            "heart": "나도 반가워! 💛",
            "ok": "확인했어! 👌",
        }.get(label)
