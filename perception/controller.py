from __future__ import annotations

from collections import OrderedDict, deque
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
        emotion_cooldown: float = 8.0,
        reaction_cooldown: float = 3.0,
        max_event_age: float = 5.0,
        time_provider: Callable[[], float] = time.time,
        on_greeting: Callable[[], None] | None = None,
        greeting_cooldown: float = 6.0,
        on_speech: Callable[[str], None] | None = None,
        on_speech_with_context: Callable[[str, dict], None] | None = None,
        on_dialogue_with_context: Callable[[str, dict], None] | None = None,
        on_affect: Callable[..., dict] | None = None,
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
        self.on_affect = on_affect
        self.current_trace_id = None
        self._last_greeting_at = -math.inf
        self.emotion_samples = max(3, emotion_samples)
        self._last_emotion_at = -math.inf
        self._observations = OrderedDict()
        self._retired_sessions = deque(maxlen=64)
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
        if not math.isfinite(event.timestamp) or not -.5 <= now - event.timestamp <= self.max_event_age:
            self._reject('event', 'stale', event, age=now - event.timestamp)
            return
        self.last_event = event
        fields = event.present_fields
        if fields is None:
            fields = {'emotion', 'gestures', 'head_motion', 'attention', 'speech'}
        if 'speech' in fields:
            self._handle_speech(event)
        if event.camera_status in ('off', 'error', 'disconnected'):
            if event.session is not None and (event.source, event.session) not in self._retired_sessions:
                self._retired_sessions.append((event.source, event.session))
            self.reset_observations(event.source)
            return
        if not fields.intersection({'emotion', 'gestures', 'head_motion', 'attention'}):
            return
        state = self._source_state(event)
        if state is None:
            return
        direct = False
        if 'gestures' in fields and self._fresh(state, 'gestures', event):
            direct = self._handle_gestures(event, now, state)
        if 'head_motion' in fields and self._fresh(state, 'head', event):
            direct = self._handle_head_motion(event, now, state) or direct
        if 'attention' in fields and self._fresh(state, 'attention', event):
            self._handle_attention(event, state)
        if 'emotion' in fields:
            self._handle_emotion(event, now, state, .25 if direct else 1.)

    def reset_observations(self, source=None):
        if source is None:
            self._observations.clear()
        else:
            self._observations.pop(source, None)

    def reset_connection(self, client):
        for source, state in list(self._observations.items()):
            if state.get('client') == client:
                self._observations.pop(source)

    def _source_state(self, event):
        key = (event.source, event.session)
        if key in self._retired_sessions:
            self._reject('event', 'retired_session', event)
            return None
        state = self._observations.get(event.source)
        if state is not None and state['session'] != event.session:
            self._retired_sessions.append((event.source, state['session']))
            state = None
        if state is None:
            state = {'session': event.session, 'cursors': {}, 'face': None,
                     'face_applied': None, 'model': None, 'episodes': {},
                     'model_at': -math.inf, 'cooldowns': {}, 'presence': None, 'attention': None}
            self._observations[event.source] = state
        if event.timestamp >= state.get('client_at', -math.inf):
            state['client'], state['client_at'] = event.raw.get('_perception_client'), event.timestamp
        self._observations.move_to_end(event.source)
        while len(self._observations) > 16:
            self._observations.popitem(last=False)
        return state

    def _fresh(self, state, channel, event, observation=None):
        observed = (observation.observed_at if observation is not None else event.observed_at)
        observed = event.timestamp if observed is None else observed
        identity = observation.observation_id if observation is not None else event.observation_id
        if observation is not None and identity is None:
            self._reject(channel, 'missing_inference_id', event)
            return False
        identity = observed if identity is None else identity
        now = self.time_provider()
        if not math.isfinite(observed) or not -.5 <= now - observed <= self.max_event_age:
            self._reject(channel, 'stale_observation', event)
            return False
        previous = state['cursors'].get(channel)
        if previous is not None:
            stamp, token = previous
            if (identity == token or observed < stamp
                    or isinstance(identity, (int, float)) and isinstance(token, (int, float))
                    and identity <= token):
                self._reject(channel, 'duplicate_or_out_of_order', event)
                return False
        state['cursors'][channel] = observed, identity
        return True

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

    def _handle_emotion(self, event, now, state, scale=1.):
        observation = event.emotion
        if observation is None:
            if self._fresh(state, 'face_missing', event):
                state['face'] = state['face_applied'] = None
            return
        if observation.observation_id is None:
            state['face'] = state['face_applied'] = None
            self._reject('face', 'missing_inference_id', event)
            return
        observed = observation.observed_at if observation.observed_at is not None else event.timestamp
        if not -.5 <= now - observed <= self.max_event_age:
            self._reject('face', 'stale_observation', event)
            return
        if observation.model != state['model']:
            latest = state['cursors'].get('face', (-math.inf, None))[0]
            if observed < max(state['model_at'], latest):
                self._reject('face', 'old_model_observation', event)
                return
            state['model_at'] = observed
            state['model'] = observation.model
            state['face'] = state['face_applied'] = None
            state['cursors'].pop('face', None)
        if not self._fresh(state, 'face', event, observation):
            return
        if observation.confidence < self.emotion_confidence or observation.label == 'neutral':
            state['face'] = state['face_applied'] = None
            self._reject('face', 'neutral' if observation.label == 'neutral' else 'low_confidence',
                         event, label=observation.label, confidence=observation.confidence)
            return
        observed = observation.observed_at if observation.observed_at is not None else event.timestamp
        face = state['face']
        if face is None or face['label'] != observation.label or observed - face['last'] > 1.5:
            face = {'label': observation.label, 'since': observed, 'last': observed, 'samples': 0}
            state['face'] = face
            state['face_applied'] = None
        face['last'], face['samples'] = observed, face['samples'] + 1
        if face['samples'] < self.emotion_samples or observed - face['since'] < 1.:
            return
        if now - self._last_emotion_at < self.emotion_cooldown:
            self._reject('emotion', 'cooldown', event, label=observation.label)
            return
        maintenance = .25 if state['face_applied'] == observation.label else 1.
        self._last_emotion_at = now
        state['face_applied'] = observation.label
        self._affect(event, 'face', label=observation.label, quality=observation.confidence,
                     maintenance=maintenance * scale, observation=observation)

    def _handle_gestures(self, event, now, state):
        active = {item.label for item in event.gestures if item.label in ('heart', 'thumbs_up', 'ok')}
        waving = any((item.kind == 'wave' and item.label == 'hello') or item.label == 'wave'
                     for item in event.gestures)
        if waving:
            always = event.raw.get('always', {})
            wave = always.get('wave', {}) if isinstance(always, dict) else {}
            started = wave.get('started_at') if isinstance(wave, dict) else None
            started = self._observation_time(started, event.observed_at or event.timestamp)
            if -.5 <= now - started <= self.max_event_age:
                active.add('greeting')
            else:
                self._reject('greeting', 'stale_wave', event, started_at=started)
        return self._episodes(event, now, state, 'hand', active)

    def _handle_head_motion(self, event, now, state):
        active = {'head_' + event.head_motion} if event.head_motion in ('agree', 'negative') else set()
        return self._episodes(event, now, state, 'head', active)

    def _episodes(self, event, now, state, family, active):
        observed = event.observed_at if event.observed_at is not None else event.timestamp
        episodes, accepted = state['episodes'], False
        for key, episode in list(episodes.items()):
            if key[0] != family:
                continue
            if key[1] not in active:
                if episode['missing'] is None or observed - episode.get('missing_last', observed) > 1.5:
                    episode['missing'] = observed
                episode['missing_last'] = observed
                if not episode['latched'] or observed - episode['missing'] >= .4:
                    episodes.pop(key)
        for signal in sorted(active):
            key = family, signal
            episode = episodes.get(key)
            if episode is not None and episode['missing'] is not None:
                if not episode['latched']:
                    episode = None
                else:
                    episode['missing'] = None
            if episode is None:
                episode = {'since': observed, 'last': observed, 'samples': 0,
                           'latched': False, 'missing': None}
                episodes[key] = episode
            if observed - episode['last'] > 1.5:
                # Tracking gaps do not prove release; require explicit absence to rearm.
                if not episode['latched']:
                    episode['since'], episode['samples'] = observed, 0
            episode['last'], episode['samples'] = observed, episode['samples'] + 1
            if episode['latched']:
                continue
            if signal != 'greeting' and (episode['samples'] < 2 or observed - episode['since'] < .25):
                continue
            episode['latched'] = True
            if signal == 'greeting':
                sides = sorted({item.side or 'unknown' for item in event.gestures
                                if item.kind == 'wave' or item.label == 'wave'})
                log_event('perception.wave.detected', '손 흔들기 감지', category='사용자 인식',
                          trace_id=self.current_trace_id, sides=sides, source=event.source)
                print(f"[외부 동작 인식] 손 흔들기 wave/hello ({', '.join(sides)}, 출처: {event.source})")
            last = self._last_greeting_at if signal == 'greeting' else state['cooldowns'].get(signal, -math.inf)
            cooldown = self.greeting_cooldown if signal == 'greeting' else self.reaction_cooldown
            if now - last < cooldown:
                self._reject(signal, 'cooldown', event)
                if signal == 'greeting':
                    print('[사용자 인사] 재인사 대기 중: 반복 재생을 생략함')
                continue
            state['cooldowns'][signal] = now
            if signal == 'greeting':
                self._last_greeting_at = now
            confidences = [item.confidence for item in event.gestures
                           if item.label == signal and item.confidence is not None]
            result = self._affect(event, signal, quality=min(confidences, default=1.))
            accepted = result.get('accepted', False) or accepted
            if signal == 'greeting' and result.get('accepted'):
                self._callback(self.on_greeting, event, 'greeting')
        return accepted

    def _handle_attention(self, event, state):
        observed = event.observed_at if event.observed_at is not None else event.timestamp
        attention = event.attention if event.attention in ('screen', 'away') else None
        previous = state['attention']
        if previous is None or previous['value'] != attention or observed - previous['last'] > 1.5:
            previous = {'value': attention, 'since': observed, 'last': observed}
            state['attention'] = previous
        previous['last'] = observed
        if attention is None:
            if state['presence'] is not None:
                log_event('perception.attention.changed', '사용자 관측 상태 불명',
                          category='사용자 인식', trace_id=self.current_trace_id,
                          previous=state['presence'], current=None, source=event.source)
            state['presence'] = None
            return
        if observed - previous['since'] < (5. if attention == 'away' else 1.):
            return
        if state['presence'] != attention:
            log_event('perception.attention.changed', '사용자 주의 상태 변경',
                      category='사용자 인식', trace_id=self.current_trace_id,
                      previous=state['presence'], current=attention, source=event.source)
            state['presence'] = attention
        # Existing character-idle pressure owns absence; no second OCC penalty.

    def _affect(self, event, signal, *, label=None, quality=1., maintenance=1., observation=None):
        identity = observation.observation_id if observation is not None else event.observation_id
        identity = event.timestamp if identity is None else identity
        model = observation.model if observation is not None else ''
        event_id = f'{event.source}:{event.session}:{model}:{identity}:{signal}:{label or ""}'
        context = {'event_id': event_id, 'label': label, 'quality': quality,
                   'maintenance': maintenance,
                   'perception_context': {'source': event.source, 'session': event.session,
                                          'observed_at': (observation.observed_at if observation is not None
                                                          else event.observed_at) or event.timestamp,
                                          'trace_id': self.current_trace_id}}
        handler = self.on_affect or getattr(self.mood_system, 'on_interaction', None)
        if handler is not None:
            result = handler('user_' + signal, **context)
        # Compatibility for lightweight consumers without an OCC implementation.
        elif signal == 'face':
            accepted = self.mood_system.on_external_emotion(label, quality)
            result = {'accepted': accepted}
        elif signal.startswith('head_'):
            result = {'accepted': False}
        else:
            self.mood_system.on_click()
            result = {'accepted': True}
        if not isinstance(result, dict):
            result = {'accepted': bool(result)}
        log_event('perception.affect.result', '인식 감정 처리 결과', category='사용자 인식',
                  trace_id=self.current_trace_id, event_id=event_id, signal=signal, label=label,
                  source=event.source, quality=quality, maintenance=maintenance,
                  outcome='accepted' if result.get('accepted') else 'blocked',
                  reason=result.get('appraisal', {}).get('reason'),
                  applied=bool(result.get('applied')), occ_changes=result.get('changes', {}),
                  arousal_change=result.get('appraisal', {}).get('applied_arousal', 0.))
        return result

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
                not -.5 <= now - observed <= self.max_event_age or observed < self._speech_ignore_until):
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

    @staticmethod
    def _observation_time(value, fallback):
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else fallback
