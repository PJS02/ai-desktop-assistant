from __future__ import annotations

from collections import deque
import time
from typing import Callable

from .events import PerceptionEvent, parse_perception_event


class PerceptionController:
    """공통 인식 이벤트를 중복과 노이즈가 제거된 캐릭터 반응으로 바꾼다."""

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
        # 얼굴 감정은 프레임마다 흔들릴 수 있으므로 최근 결과를 모아 안정성을 확인한다.
        self._emotion_history: deque[str] = deque(maxlen=max(1, emotion_samples))
        self._last_emotion: str | None = None
        self._last_emotion_at = 0.0
        self._active_gestures: set[tuple[str, str | None, str]] = set()
        self._last_reaction_at: dict[str, float] = {}
        self._last_head_motion: str | None = None
        self._last_attention: str | None = None
        self._last_speech_key = None
        self.last_event: PerceptionEvent | None = None

    def handle_payload(self, payload: dict) -> PerceptionEvent:
        event = parse_perception_event(payload)
        self.handle_event(event)
        return event

    def handle_event(self, event: PerceptionEvent) -> None:
        now = self.time_provider()
        # 송신기 지연이나 재연결 뒤 밀려온 과거 이벤트가 뒤늦게 반응하지 않도록 한다.
        if event.timestamp > 0 and now - event.timestamp > self.max_event_age:
            return
        self.last_event = event
        self._handle_emotion(event, now)
        self._handle_gestures(event, now)
        self._handle_head_motion(event, now)
        self._handle_attention(event)
        self._handle_speech(event)

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
        # 동일 감정이 연속으로 확인된 경우에만 캐릭터 기분에 반영한다.
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
        # 현재 프레임에서 새로 시작된 동작만 처리해 손을 든 동안 말풍선이 반복되지 않게 한다.
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
            # 여러 프레임에 유지되는 동일한 고개 동작은 한 번만 반응한다.
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
            # 자리를 비운 상태 자체가 아니라 상태가 바뀌는 순간만 처리한다.
            return
        self._last_attention = attention
        if attention == "away":
            self.mood_system.on_idle()
            print("[외부 상태 인식] 사용자가 자리를 비움")

    def _handle_speech(self, event: PerceptionEvent) -> None:
        if event.speech is None:
            return
        # 발화 순번이 있으면 같은 문장을 다시 말해도 새로운 음성으로 처리한다.
        identity = event.speech_id if event.speech_id is not None else event.speech
        speech_key = (event.source, identity)
        if speech_key == self._last_speech_key:
            return
        self._last_speech_key = speech_key
        print(f"[외부 음성 인식] {event.speech} (출처: {event.source})")

    @staticmethod
    def _gesture_message(kind: str, label: str) -> str | None:
        if kind == "wave" and label == "hello":
            return "안녕! 👋"
        return {
            "thumbs_up": "좋아! 👍",
            "heart": "나도 반가워! 💛",
            "ok": "확인했어! 👌",
        }.get(label)
