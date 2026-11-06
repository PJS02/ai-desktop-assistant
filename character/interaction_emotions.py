"""Appraise confirmed interactions independently of temporary facial playback.

OCC categories describe the event; the small doses below are application tuning,
not constants supplied by OCC or Russell's circumplex model.
"""
from collections import OrderedDict, deque
import math
import time

from .perception_affect import appraise_perception, state_labels, unit

from app_logging import log_event


SOURCES = {
    'pet': '쓰다듬기', 'pet_refused': '원치 않는 쓰다듬기',
    'poke_start': '볼 찌르기', 'poke_play': '볼 장난',
    'poke_discomfort': '반복되는 볼 찌르기', 'contact_ignored': '접촉 거절 무시',
    'palm': '손바닥으로 받치기', 'throw': '손으로 던지기',
    'fall_risk': '낙하 위험', 'safe_landing': '안전하게 착지',
    'impact': '강한 충돌',
    'ball_ready': '공놀이 준비', 'ball_kicked': '공 차기', 'ball_removed': '공놀이 중단',
    'file_received': '파일 전달받음', 'files_returned': '파일 반환 완료',
    'files_dropped': '거친 드래그로 파일 놓침', 'wake': '잠에서 깨어남',
}
FACE_SOURCES = {
    'happy': '사용자 웃음 감지', 'anger': '사용자 분노 표정 감지',
    'contempt': '사용자 경멸 표정 감지', 'disgust': '사용자 불쾌 표정 감지',
    'fear': '사용자 두려움 감지', 'sadness': '사용자 슬픔 감지', 'surprise': '사용자 놀람 감지',
}


def _number(value, lower=0., upper=1., default=0.):
    value = default if value is None else float(value)
    if not math.isfinite(value):
        raise ValueError('Interaction measurements must be finite')
    return max(lower, min(upper, value))


class InteractionEmotions:
    def __init__(self, mood):
        self.mood = mood
        self.seen = OrderedDict()
        self.exposure = {}
        self.contacts = {}
        self.fall = None
        self.claims = {}
        self.totals = {key.value: value for key, value in mood.occ_intensities.items()}
        self.perception_budget = deque()
        self.perception_states = set()
        self.perception_pending = {}

    def _sync_claims(self, resolved=None):
        # Track only the remaining contribution of each episode. Recovery must
        # not erase fear or hope that came from an unrelated event.
        for emotion in ('fear', 'hope'):
            total = self.mood.occ_intensities[self._key(emotion)]
            previous = max(0., self.totals[emotion] - (resolved or {}).get(emotion, 0.))
            if total < previous and previous > 0:
                for claim in self.claims.values():
                    claim[emotion] = claim.get(emotion, 0.) * total / previous
            self.totals[emotion] = total

    def _key(self, name):
        return next(key for key in self.mood.occ_intensities if key.value == name)

    def _dose(self, family, amount, now, *, continuous=False, elapsed=None):
        last, prior = self.exposure.get(family, (now - amount, 0.))
        idle = max(0., now - last - ((elapsed if elapsed is not None else amount) if continuous else 0.))
        prior *= math.exp(-idle / 20.)
        if continuous:
            dose = 8. * math.exp(-prior / 8.) * -math.expm1(-amount / 8.)
        else:
            dose = amount / (1. + .5 * prior)
        self.exposure[family] = now, prior + amount
        return dose

    def _distinct(self, event_id, event):
        if event_id is None:
            return True
        identity = str(event_id)
        if identity in self.seen:
            return False
        self.seen[identity] = None
        while len(self.seen) > 512:
            self.seen.popitem(last=False)
        return True

    def apply(self, event, *, event_id=None, source=None, **context):
        if event.startswith('user_'):
            return self._apply_perception(event[5:], event_id=event_id, source=source, **context)
        mood, now = self.mood, time.monotonic()
        before = (mood.russell.valence, mood.russell.arousal)
        result = {'before': before, 'reaction': event, 'applied': False, 'dose': 0.}
        for name in ('strength', 'elapsed', 'speed', 'distance'):
            if context.get(name) is not None:
                _number(context[name])
        if event in ('file_received', 'files_returned', 'files_dropped') and not context.get('success', True):
            return result
        if not self._distinct(event_id, event):
            result['duplicate'] = True
            log_event('mood.interaction.duplicate', '동일 사건의 감정 중복 반영을 생략합니다.',
                      category='캐릭터 상태', event_name=event, event_id=event_id)
            return result
        self._sync_claims()
        raw, recovery = {}, {}
        valence = arousal = 0.
        dose = _number(context.get('strength'), 0., 2., 1.)
        meaning, agency = '', 0.
        session = str(context.get('session', ''))
        claim = self.claims.get(session, {})

        if event in ('pet', 'pet_refused'):
            elapsed = _number(context.get('elapsed'), 0., 1., .15)
            speed = _number(context.get('speed'), 0., 2000., 140.)
            contact = self.contacts.get('pet')
            if contact is None or now - contact['last'] > 1.2:
                contact = {'last': now, 'elapsed': 0., 'refused': False, 'ignored': False}
                self.contacts['pet'] = contact
            contact['last'] = now
            refused = event == 'pet_refused' or mood.should_refuse_pet()
            if refused:
                contact['elapsed'] += elapsed
                result['reaction'] = 'pet_refused'
                if not contact['refused']:
                    contact['refused'] = True
                    raw = {'distress': .01}
                    meaning = '원하지 않는 접촉을 거절함'
                elif contact['elapsed'] >= .8 and not contact['ignored']:
                    contact['ignored'] = True
                    raw = {'distress': .01, 'anger': .02}
                    agency, meaning = -.6, '거절한 뒤에도 접촉이 지속됨'
                    result['reaction'] = 'contact_ignored'
                else:
                    result['reaction'] = None
                    return result
                dose = self._dose('refusal', 1., now)
            else:
                quality = math.exp(-((speed - 140.) / 180.) ** 2)
                dose = self._dose('pet', elapsed * quality, now, continuous=True, elapsed=elapsed)
                raw = {'joy': .02, 'gratitude': .01, 'satisfaction': .01}
                recovery = {'distress': .025, 'fear': .035}
                if mood.occ_intensities[self._key('distress')] > .3:
                    raw['joy'] *= .5
                agency, arousal = .6, -.02
                meaning = '편안한 접촉의 시간과 품질에 따라 위로와 친밀감을 누적'
                result['dose'] = elapsed * quality
        elif event == 'poke_start':
            dose = self._dose('poke', 1., now)
            arousal, meaning = .025, '갑작스러운 접촉에 각성도가 잠깐 상승'
        elif event in ('poke_play', 'poke_discomfort', 'contact_ignored'):
            dose = self._dose('poke', 1., now)
            if event == 'contact_ignored' or mood.should_refuse_pet():
                raw, agency = {'distress': .02, 'anger': .02}, -.6
                result['reaction'] = 'contact_ignored'
            elif event == 'poke_discomfort' or before[0] < -.24:
                raw = {'distress': .02}
                result['reaction'] = 'poke_discomfort'
            else:
                raw = {'joy': .015}
            arousal, meaning = .01, '현재 감정과 반복 접촉 여부로 장난과 불편함을 구분'
        elif event in ('throw', 'fall_risk'):
            risk = (_number(context.get('distance'), 0., 8., 1.) if event == 'fall_risk'
                    else _number(context.get('speed'), 0., 20., 3.) / 3.)
            if self.fall is None:
                self.fall = {'peak': 0., 'claim': 'fall:' + str(now)}
            session = self.fall['claim']
            severity = _number((risk - .38) / 1.5)
            previous = self.fall['peak']
            self.fall['peak'] = max(previous, severity)
            dose = max(0., severity - previous)
            raw, valence, arousal = {'fear': .10}, -.025, .08
            meaning = '아직 발생하지 않은 충돌 위험과 통제 불가능성을 평가'
            result['reaction'] = None if event == 'throw' else 'fall_risk'
        elif event == 'impact':
            if self.fall is None or self.fall.get('impact'):
                return result
            self.fall['impact'] = True
            raw, valence, arousal = {'distress': .025}, -.015, .02
            meaning = '예상했던 충돌이 실제로 발생해 고통을 느낌'
            result['reaction'] = None
        elif event == 'safe_landing':
            if self.fall is None:
                return result
            session = self.fall['claim']
            claim = self.claims.pop(session, {})
            impacted = self.fall.get('impact', False)
            self.fall = None
            owned_fear = min(claim.get('fear', 0.), mood.occ_intensities[self._key('fear')])
            if owned_fear <= 0:
                return result
            raw = {'fear': -owned_fear, 'relief': min(.06, owned_fear * .6)}
            if impacted:
                raw.pop('relief')
                result['reaction'] = None
                source = '충돌 후 멈춤'
            if context.get('rescued') and not impacted:
                raw['gratitude'] = min(.02, owned_fear * .2)
                agency = .8
            dose = self._dose('safety', 1., now)
            valence, arousal = (0., -.015) if impacted else (.005, -.05)
            meaning = ('충돌이 끝나 해당 사건의 두려움만 정리; 충돌의 고통은 유지'
                       if impacted else '해당 낙하에서 생긴 잔여 두려움을 해소하고 안전에 안도')
        elif event == 'palm':
            dose = self._dose('palm', 1., now)
            raw, agency, arousal = {'gratitude': .015, 'satisfaction': .01}, .6, -.015
            meaning = '안정적인 지지와 호의를 받음'
        elif event == 'ball_ready':
            raw, dose = {'hope': .015}, self._dose('ball_ready', 1., now)
            meaning = '곧 함께 놀 수 있다는 긍정적인 기대'
        elif event in ('ball_kicked', 'ball_removed', 'ball_cancel'):
            raw = {'hope': -claim.get('hope', 0.)}
            if event == 'ball_kicked':
                dose = self._dose('ball_play', 1., now)
                raw.update(joy=.035, satisfaction=.015)
                recovery = {'distress': .05, 'fear': .04, 'anger': .04}
                valence, arousal = .01, .02
                meaning = '실제 공 차기 성공과 놀이의 즐거움'
            elif event == 'ball_removed':
                dose = self._dose('ball_removed', 1., now)
                raw['distress'] = .02
                valence, arousal = -.005, -.01
                meaning = '진행 중이던 놀이가 끝나 기대가 무산됨'
            else:
                meaning = '종료한 공의 기대만 정리'
            self.claims.pop(session, None)
        elif event.startswith('game_'):
            if event == 'game_start':
                raw = {'hope': .008 if context.get('round') else .015}
                result['reaction'] = None
                meaning = '게임 결과에 대한 기대'
            else:
                raw = {'hope': -claim.get('hope', 0.)}
                self.claims.pop(session, None)
                if event in ('game_win', 'game_earned_win'):
                    raw.update(joy=.05, satisfaction=.025 if claim.get('hope', 0.) else 0.)
                    if context.get('earned'):
                        raw['pride'] = .025
                    else:
                        result['reaction'] = 'game_win'
                    valence, arousal = .015, .02
                elif event in ('game_loss', 'game_disappointed'):
                    raw['distress'] = .06 if event == 'game_disappointed' else .04
                    valence, arousal = -.01, -.005
                elif event == 'game_draw':
                    raw['joy'] = .005
                elif event != 'game_cancel':
                    raise ValueError('Unknown game event: ' + event)
                if context.get('round'):
                    dose *= .4
                elif context.get('final'):
                    dose *= .6
                meaning = '게임의 실제 결과와 사전 기대를 평가; 우연한 승패에 책임을 부여하지 않음'
        elif event in ('file_received', 'files_returned', 'files_dropped'):
            dose = self._dose('files', 1., now)
            if event == 'file_received':
                raw, agency = {'joy': .025, 'gratitude': .035}, .7
                meaning = '성공한 파일 전달 한 묶음을 받음'
            elif event == 'files_dropped' or context.get('forced'):
                raw, valence = {'distress': .025}, -.01
                result['reaction'] = 'files_dropped'
                meaning = '거친 다루기로 보관하던 파일을 놓침'
            else:
                raw = {'satisfaction': .015}
                meaning = '요청한 파일 반환 묶음을 정상적으로 완료'
        elif event == 'wake':
            dose = self._dose('wake', 1., now)
            arousal = min(.04, max(0., -before[1]))
            meaning = '수면에서 깨어나 각성도를 회복; 휴식 보상은 다시 지급하지 않음'
        elif event == 'wake_settle':
            return result
        else:
            raise ValueError('Unknown interaction event: ' + event)

        if dose <= 0:
            return result
        state = mood._capture_emotion_state()
        factor, factors = 1., []
        if mood.personality_system is not None:
            sign = sum((-v if k in ('distress', 'fear', 'anger', 'shame') else v)
                       for k, v in raw.items())
            factor, factors = mood.personality_system.get_event_weight_multiplier(
                valence=sign, self_attribution=.6 if context.get('earned') else 0.,
                agent_benevolence=agency, novelty=.7 if event in ('throw', 'poke_start') else 0.)
        applied_dose = dose * factor
        for name, amount in raw.items():
            key, current = self._key(name), mood.occ_intensities[self._key(name)]
            if amount > 0:
                # Exact integration of dI/dDose=(1-I)^1.5 is invariant to frame rate.
                remaining = max(0., 1. - current)
                mood.occ_intensities[key] = (1. - (remaining ** -.5 + amount * applied_dose / 2.) ** -2
                                             if remaining > 1e-12 else current)
            else:
                # An episode's outstanding expectation/fear is resolved once.
                mood.occ_intensities[key] = max(0., current + amount)
        for name, rate in recovery.items():
            key = self._key(name)
            mood.occ_intensities[key] *= math.exp(-rate * applied_dose)
        changes = {key.value: mood.occ_intensities[key] - value for key, value in state['occ'].items()
                   if abs(mood.occ_intensities[key] - value) > 1e-12}
        if not changes and not valence and not arousal:
            return result
        mood._event_valence_bias = max(-1., min(1., mood._event_valence_bias + valence * applied_dose))
        mood._event_arousal_bias = max(-1., min(1., mood._event_arousal_bias + arousal * applied_dose))
        continuous = event in ('pet', 'pet_refused')
        if continuous:
            mood._update_russell_from_occ()
        else:
            mood._apply_occ_to_mood()
        self._sync_claims({name: -amount for name, amount in raw.items() if amount < 0})
        changes = {key.value: mood.occ_intensities[key] - value for key, value in state['occ'].items()
                   if abs(mood.occ_intensities[key] - value) > 1e-12}
        if session and event in ('throw', 'fall_risk', 'ball_ready', 'game_start'):
            credits = self.claims.setdefault(session, {})
            for name in ('fear', 'hope'):
                credits[name] = credits.get(name, 0.) + max(0., changes.get(name, 0.))
            while len(self.claims) > 32:
                del self.claims[next(iter(self.claims))]
        if changes or valence or arousal:
            goodness = sum((-amount if name in ('distress', 'fear', 'anger', 'shame') else amount)
                           for name, amount in changes.items())
            category = 'positive' if goodness > 0 else 'negative' if goodness < 0 else 'neutral'
            mood._record_influence(
                source=source or SOURCES.get(event, event), category=category,
                base_weight=dose, adjusted_weight=applied_dose, personality_multiplier=factor,
                personality_factors=factors, before=before, before_occ=state['occ'],
                state_before=state, merge_window=.5 if continuous else 0., details=meaning,
                weight_applied=mood.personality_system is not None,
                event_input={'event': event, 'event_id': event_id, 'session': session,
                             'requested_occ': raw, 'actual_occ': changes, 'dose': dose,
                             **context})
            result['applied'] = True
        result['changes'] = changes
        return result

    def _apply_perception(self, signal, *, event_id=None, source=None, actor_state=None,
                          label=None, quality=1., maintenance=1., **context):
        mood, now = self.mood, time.monotonic()
        quality, maintenance = unit(quality), unit(maintenance)
        state = mood._capture_emotion_state()
        before = (mood.russell.valence, mood.russell.arousal)
        occ = {key.value: value for key, value in mood.occ_intensities.items()}
        actor = dict(actor_state or {})
        actor['manual_emotion'] = bool(actor.get('manual_emotion') or mood._manual_russell_override)
        appraisal = appraise_perception(signal, occ, before, actor, label=label)
        appraisal['state_labels'] = state_labels(
            occ, before, unit(actor.get('rest', 0.)), self.perception_states,
            self.perception_pending, now)
        result = {'before': before, 'reaction': None, 'applied': False, 'dose': 0.,
                  'accepted': appraisal['accepted'], 'appraisal': appraisal, 'changes': {}}
        if not self._distinct(event_id, 'user_' + signal):
            appraisal.update(accepted=False, reason='duplicate')
            result.update(accepted=False, duplicate=True)
            return result
        if not appraisal['accepted'] or quality <= 0 or maintenance <= 0:
            appraisal.update(accepted=False, reason=appraisal['reason'] or 'invalid_quality')
            result['accepted'] = False
            log_event('mood.perception.skipped', '사용자 인식 감정 반영 생략', category='사용자 인식',
                      event_name=signal, reason=appraisal['reason'] or 'invalid_quality', event_id=event_id)
            return result

        family = 'face' if signal == 'face' else 'gesture'
        repeat = self._dose('user_' + family, maintenance, now) / maintenance
        raw = appraisal['requested_occ']
        goodness = sum(-v if k in ('distress', 'fear', 'anger', 'shame') else v
                       for k, v in raw.items())
        factor, factors = 1., []
        if mood.personality_system is not None:
            factor, factors = mood.personality_system.get_event_weight_multiplier(
                valence=goodness, agent_benevolence=.6 if signal in
                ('heart', 'thumbs_up', 'greeting', 'ok', 'head_agree') else 0.,
                novelty=.2 if label == 'surprise' else 0.)
        factor = _number(factor, .25, 2., 1.)
        dose = quality * maintenance * repeat * factor * appraisal['multiplier']
        requested = {name: max(-.04, min(.04, value * dose)) for name, value in raw.items()}
        total = sum(abs(value) for value in requested.values())
        if total > .06:
            requested = {name: value * .06 / total for name, value in requested.items()}
        changes = {}
        for name, amount in requested.items():
            current = occ[name]
            if amount > 0:
                remaining = max(0., 1. - current)
                updated = (1. - (remaining ** -.5 + amount / 2.) ** -2
                           if remaining > 1e-12 else current)
                changes[name] = updated - current
            else:
                changes[name] = -min(-amount, current * .1)
        while self.perception_budget and now - self.perception_budget[0][0] >= 60:
            self.perception_budget.popleft()
        used = sum(item[2] for item in self.perception_budget)
        family_used = sum(item[2] for item in self.perception_budget if item[1] == family)
        amount = sum(abs(value) for value in changes.values())
        remaining = min(max(0., .25 - used),
                        max(0., (.06 if family == 'face' else .20) - family_used))
        scale = min(1., remaining / amount) if amount else 1.
        changes = {name: value * scale for name, value in changes.items()}
        arousal = max(-.02, min(.02, appraisal['arousal'] * dose))
        arousal_used = sum(item[3] for item in self.perception_budget)
        arousal = math.copysign(min(abs(arousal), max(0., .06 - arousal_used)), arousal)
        arousal = max(-1., min(1., mood._event_arousal_bias + arousal)) - mood._event_arousal_bias
        self._sync_claims()
        for name, delta in changes.items():
            mood.occ_intensities[self._key(name)] = max(0., min(1., occ[name] + delta))
        mood._event_arousal_bias = max(-1., min(1., mood._event_arousal_bias + arousal))
        actual_amount = sum(abs(value) for value in changes.values())
        if actual_amount or arousal:
            self.perception_budget.append((now, family, actual_amount, abs(arousal)))
            mood._apply_occ_to_mood()
            self._sync_claims()
        changes = {key: value for key, value in changes.items() if abs(value) > 1e-12}
        appraisal.update(expression_strength=unit(appraisal['strength'] * dose),
                         applied_occ=changes, budget_scale=scale, quality=quality,
                         personality_multiplier=factor, repetition_multiplier=repeat)
        result.update(reaction='user_' + signal, applied=bool(changes or arousal),
                      changes=changes, dose=dose)
        if result['applied']:
            source = source or {'heart': '하트 인식', 'thumbs_up': '엄지척 인식',
                'ok': 'OK 인식', 'greeting': '손 흔들기 인사', 'head_agree': '고개 끄덕임',
                'head_negative': '고개 좌우 흔들기', 'face': FACE_SOURCES.get(label, '사용자 표정 인식')}[signal]
            goodness = sum(-v if k in ('distress', 'fear', 'anger', 'shame') else v
                           for k, v in changes.items())
            mood._record_influence(
                source=source, category='positive' if goodness > 0 else 'negative' if goodness < 0 else 'neutral',
                base_weight=quality * maintenance, adjusted_weight=dose, personality_multiplier=factor,
                personality_factors=factors, before=before, before_occ=state['occ'], state_before=state,
                weight_applied=mood.personality_system is not None,
                details=(f'인식 신뢰도 {quality * 100:.0f}% · ' if signal == 'face' else '')
                        + ' · '.join(appraisal['interpretation']),
                event_input={'event': 'user_' + signal, 'event_id': event_id, 'label': label,
                    'quality': quality, 'profile_weights': appraisal['weights'],
                    'actor_state': actor, 'requested_occ': raw, 'actual_occ': changes,
                    'budget_scale': scale, 'repetition_multiplier': repeat,
                    'state_labels': appraisal['state_labels'], **context})
        return result
