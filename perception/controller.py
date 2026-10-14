from __future__ import annotations

from collections import deque
import math
import time
import json
from typing import Callable

from app_logging import log_event, log_throttled, new_trace_id

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
        on_greeting: Callable[[], None] | None = None,
        greeting_cooldown: float = 6.0,
        on_speech: Callable[[str], None] | None = None,
        on_speech_with_context: Callable[[str, dict], None] | None = None,
        on_dialogue_with_context: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.mood_system = mood_system
        self.on_dialogue = on_dialogue or (lambda _text: None)
        self.emotion_confidence = emotion_confidence
        self.emotion_cooldown = emotion_cooldown
        self.reaction_cooldown = reaction_cooldown
        self.max_event_age = max_event_age
        self.time_provider = time_provider
        self.on_greeting = on_greeting or (lambda: self.on_dialogue("안녕! 👋"))
        self.greeting_cooldown = greeting_cooldown
        self.on_speech = on_speech or (lambda _text: None)
        self.on_speech_with_context = on_speech_with_context
        self.on_dialogue_with_context = on_dialogue_with_context
        self.current_trace_id = None
        self._greeting_sources = {}
        self._last_greeting_at = -math.inf
        # 얼굴 감정은 프레임마다 흔들릴 수 있으므로 최근 결과를 모아 안정성을 확인한다.
        self._emotion_history: deque[str] = deque(maxlen=max(1, emotion_samples))
        self._last_emotion: str | None = None
        self._last_emotion_at = 0.0
        self._active_gestures: set[tuple[str, str | None, str]] = set()
        self._last_reaction_at: dict[str, float] = {}
        self._last_head_motion: str | None = None
        self._last_attention: str | None = None
        self._last_speech_key = None
        self._speech_keys = set()
        self._speech_key_history = deque()
        self._speech_suppressed = False
        self._speech_ignore_until = -math.inf
        self.last_event: PerceptionEvent | None = None

    def handle_payload(self, payload: dict) -> PerceptionEvent:
        event = parse_perception_event(payload)
        self.handle_event(event)
        return event

    def handle_event(self, event: PerceptionEvent) -> None:
        now = self.time_provider()
        self.current_trace_id = event.trace_id or new_trace_id('perception')
        # 송신기 지연이나 재연결 뒤 밀려온 과거 이벤트가 뒤늦게 반응하지 않도록 한다.
        if event.timestamp > 0 and now - event.timestamp > self.max_event_age:
            self._reject('event', 'stale', event, age=now - event.timestamp)
            return
        self.last_event = event
        self._handle_emotion(event, now)
        self._handle_gestures(event, now)
        self._handle_head_motion(event, now)
        self._handle_attention(event)
        self._handle_speech(event)
        self._handle_greeting(event, now)

    def _reject(self, kind, reason, event, **data):
        log_throttled('perception.rejected', '인식 결과 적용 생략',
                      category='사용자 인식', trace_id=event.speech_trace_id if kind == 'speech' else self.current_trace_id,
                      key=f'perception:{id(self)}:{event.source}:{kind}:{reason}',
                      kind=kind, reason=reason, source=event.source, **data)

    def _callback(self, callback, event, kind, *args):
        log_event('perception.reaction.requested', '인식 반응 요청',
                  category='사용자 인식', trace_id=self.current_trace_id,
                  kind=kind, source=event.source)
        try:
            if callback is self.on_dialogue and self.on_dialogue_with_context is not None:
                result = self.on_dialogue_with_context(*args, {'trace_id': self.current_trace_id,
                                                             'source': event.source, 'kind': kind})
            else:
                result = callback(*args)
        except Exception as exc:
            log_event('perception.reaction.failed', '인식 반응 처리 실패', category='오류', level='ERROR',
                      trace_id=self.current_trace_id, kind=kind, error=str(exc))
            raise
        log_event('perception.reaction.result', '인식 반응 전달 결과',
                  category='사용자 인식', trace_id=self.current_trace_id,
                  kind=kind, outcome='blocked' if result is False else
                  'shown' if result is True else 'callback_returned',
                  source=event.source)
        return result

    def _handle_emotion(self, event: PerceptionEvent, now: float) -> None:
        observation = event.emotion
        if observation is None or observation.confidence < self.emotion_confidence:
            self._emotion_history.clear()
            if observation is not None:
                self._reject('emotion', 'low_confidence', event,
                             label=observation.label, confidence=observation.confidence,
                             threshold=self.emotion_confidence)
            return
        if observation.label == "neutral":
            self._emotion_history.clear()
            self._reject('emotion', 'neutral', event)
            return

        self._emotion_history.append(observation.label)
        if len(self._emotion_history) < self._emotion_history.maxlen:
            self._reject('emotion', 'samples_pending', event,
                         samples=len(self._emotion_history), required=self._emotion_history.maxlen)
            return
        if len(set(self._emotion_history)) != 1:
            self._reject('emotion', 'unstable', event, samples=list(self._emotion_history))
            return
        # 동일 감정이 연속으로 확인된 경우에만 캐릭터 기분에 반영한다.
        if self._last_emotion == observation.label and now - self._last_emotion_at < self.emotion_cooldown:
            self._reject('emotion', 'cooldown', event, label=observation.label,
                         remaining=self.emotion_cooldown - (now - self._last_emotion_at))
            return

        if self.mood_system.on_external_emotion(observation.label, observation.confidence):
            self._last_emotion = observation.label
            self._last_emotion_at = now
            log_event('perception.emotion.applied', '외부 감정 반영', category='사용자 인식',
                      trace_id=self.current_trace_id, label=observation.label,
                      confidence=observation.confidence, source=event.source)
            print(
                f"[외부 감정 인식] {observation.label} "
                f"(신뢰도: {observation.confidence:.2f}, 출처: {event.source})"
            )
        else:
            self._reject('emotion', 'mood_rejected', event, label=observation.label)

    def _handle_gestures(self, event: PerceptionEvent, now: float) -> None:
        active = {(item.kind, item.side, item.label) for item in event.gestures}
        # 현재 프레임에서 새로 시작된 동작만 처리해 손을 든 동안 말풍선이 반복되지 않게 한다.
        for kind, side, label in active - self._active_gestures:
            reaction_key = f"{kind}:{side}:{label}"
            if now - self._last_reaction_at.get(reaction_key, 0.0) < self.reaction_cooldown:
                self._reject('gesture', 'cooldown', event, gesture=reaction_key)
                continue
            message = self._gesture_message(kind, label)
            if message is None:
                if kind != 'wave' and label not in ('hello', 'wave'):
                    self._reject('gesture', 'unmapped', event, gesture=reaction_key)
                continue
            # 실제 MoodSystem은 제스처 이름까지 XAI 판단 근거로 남기고,
            # 단순 테스트/외부 구현체는 기존 on_click 계약을 그대로 사용한다.
            self._record_positive_gesture(label)
            self._callback(self.on_dialogue, event, 'gesture', message)
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
            self._reject('head_motion', 'duplicate', event, label=label)
            return
        self._last_head_motion = label
        reaction_key = f"head:{label}"
        if now - self._last_reaction_at.get(reaction_key, 0.0) < self.reaction_cooldown:
            self._reject('head_motion', 'cooldown', event, label=label)
            return
        message = {
            "agree": "응, 그렇게 해보자!",
            "negative": "알겠어. 다른 방법을 생각해볼게.",
        }.get(label)
        if message:
            self._callback(self.on_dialogue, event, 'head_motion', message)
            self._last_reaction_at[reaction_key] = now
            print(f"[외부 고개 동작 인식] {label}")

    def _handle_attention(self, event: PerceptionEvent) -> None:
        attention = event.attention
        if attention == self._last_attention:
            # 자리를 비운 상태 자체가 아니라 상태가 바뀌는 순간만 처리한다.
            return
        previous = self._last_attention
        self._last_attention = attention
        log_event('perception.attention.changed', '사용자 주의 상태 변경',
                  category='사용자 인식', trace_id=self.current_trace_id,
                  previous=previous, current=attention, source=event.source)
        if attention == "away":
            self.mood_system.on_idle()
            print("[외부 상태 인식] 사용자가 자리를 비움")

    def _handle_speech(self, event: PerceptionEvent) -> bool:
        if event.speech is None or not event.speech_final:
            if event.speech is not None:
                self._reject('speech', 'not_final', event)
            return False
        # Session + sequence survives retransmission/out-of-order delivery while
        # allowing an intentional repetition and a restarted recognizer's seq 1.
        identity = (event.speech_id if event.speech_id is not None else
                    event.speech_recognized_at if event.speech_recognized_at is not None else
                    event.speech)
        speech_key = (event.source, event.speech_session,
                      json.dumps(identity, sort_keys=True, ensure_ascii=False))
        if speech_key in self._speech_keys:
            self._reject('speech', 'duplicate', event, speech_sequence=event.speech_id)
            return False
        self._last_speech_key = speech_key
        self._speech_keys.add(speech_key)
        self._speech_key_history.append(speech_key)
        if len(self._speech_key_history) > 256:
            self._speech_keys.discard(self._speech_key_history.popleft())
        now = self.time_provider()
        observed = event.speech_recognized_at
        # Consume suppressed event IDs too, so cached echoes cannot reappear on
        # later camera frames after playback stops. Speech has its own age: the
        # camera's fresh frame timestamp must not revive an old transcript.
        if self._speech_suppressed or now < self._speech_ignore_until:
            self._reject('speech', 'tts_suppressed', event, ignore_until=self._speech_ignore_until)
            return False
        if observed is not None and (
                now - observed > self.max_event_age or observed < self._speech_ignore_until):
            self._reject('speech', 'stale_or_playback_tail', event, recognized_at=observed)
            return False
        speech_trace_id = event.speech_trace_id or self.current_trace_id
        context = {'trace_id': speech_trace_id, 'speech_session': event.speech_session,
                   'speech_sequence': event.speech_id, 'speech_recognized_at': observed,
                   'source': event.source}
        log_event('perception.speech.accepted', '음성 대화 입력 전달', category='사용자 인식',
                  trace_id=speech_trace_id, text=event.speech,
                  speech_session=event.speech_session, speech_sequence=event.speech_id)
        print(f"[외부 음성 인식] {event.speech} (출처: {event.source})")
        if self.on_speech_with_context is not None:
            self.on_speech_with_context(event.speech, context)
        else:
            self.on_speech(event.speech)
        return True

    def set_speech_suppressed(self, speaking: bool) -> None:
        self._speech_suppressed = bool(speaking)
        # Acoustic tail and delayed final results are ignored after actual TTS.
        self._speech_ignore_until = self.time_provider() + 0.8
        log_event('perception.speech.suppression', '캐릭터 음성에 따른 입력 억제 변경',
                  category='사용자 인식', speaking=self._speech_suppressed,
                  ignore_until=self._speech_ignore_until)

    def _record_positive_gesture(self, label):
        if hasattr(self.mood_system, "on_positive_gesture"):
            self.mood_system.on_positive_gesture(label)
        else:
            self.mood_system.on_click()

    @staticmethod
    def _observation_time(value, fallback):
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else fallback

    def _handle_greeting(self, event, now):
        state = self._greeting_sources.setdefault(event.source, {'active': False})
        waving = any((item.kind == 'wave' and item.label == 'hello')
                     or item.label == 'wave' for item in event.gestures)
        newly_waving = waving and not state['active']
        state['active'] = waving
        if not newly_waving:
            return
        always = event.raw.get('always', {})
        wave = always.get('wave', {}) if isinstance(always, dict) else {}
        observed = wave.get('started_at') if isinstance(wave, dict) else None
        started_at = self._observation_time(observed, event.timestamp)
        if not 0 <= now - started_at <= self.max_event_age:
            self._reject('greeting', 'stale_wave', event, started_at=started_at)
            return
        # Detection is logged even if animation is suppressed by the cooldown.
        sides = sorted({item.side or 'unknown' for item in event.gestures
                        if item.kind == 'wave' or item.label == 'wave'})
        log_event('perception.wave.detected', '손 흔들기 감지', category='사용자 인식',
                  trace_id=self.current_trace_id, sides=sides, source=event.source)
        print(f"[외부 동작 인식] 손 흔들기 wave/hello ({', '.join(sides)}, 출처: {event.source})")
        if now - self._last_greeting_at < self.greeting_cooldown:
            self._reject('greeting', 'cooldown', event,
                         remaining=self.greeting_cooldown - (now - self._last_greeting_at))
            print("[사용자 인사] 재인사 대기 중: 손 흔들기는 감지했지만 반복 재생을 생략함")
            return
        self._last_greeting_at = now
        self._record_positive_gesture('greeting')
        self._callback(self.on_greeting, event, 'greeting')

    @staticmethod
    def _gesture_message(kind: str, label: str) -> str | None:
        return {
            "thumbs_up": "좋아! 👍",
            "heart": "나도 반가워! 💛",
            "ok": "확인했어! 👌",
        }.get(label)
