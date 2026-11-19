"""Appraise confirmed interactions independently of temporary facial playback.

OCC categories describe the event; the small doses below are application tuning,
not constants supplied by OCC or Russell's circumplex model.
"""
from collections import OrderedDict, deque
import math
import time

from .perception_affect import appraise_perception, state_labels, unit
from .russell_sectors import LOW_MOOD_EMOTIONS, MOOD_REFERENCES

from app_logging import log_event


OCC_RESPONSE_GAIN = 1.15
FALL_EMOTION_MIN_HEIGHT = .34


SOURCES = {
    'pet': '쓰다듬기', 'pet_refused': '원치 않는 쓰다듬기',
    'poke_start': '볼 찌르기', 'poke_play': '볼 장난',
    'poke_discomfort': '반복되는 볼 찌르기', 'contact_ignored': '접촉 거절 무시',
    'palm': '손바닥으로 받치기', 'throw': '손으로 던지기',
    'fall_risk': '낙하 위험', 'safe_landing': '안전하게 착지',
    'impact': '강한 충돌',
    'ball_ready': '공놀이 준비', 'ball_kicked': '공 차기', 'ball_removed': '공놀이 중단',
    'ball_cancel': '공놀이 취소',
    'file_received': '파일 전달받음', 'files_returned': '파일 반환 완료',
    'files_dropped': '거친 드래그로 파일 놓침', 'wake': '잠에서 깨어남',
    'drag_start': '갑자기 들림', 'drag_held': '잡힌 상태가 이어짐',
    'drag_shake': '반복적인 캐릭터 흔들기',
    'high_five_ready': '하이파이브 기대', 'high_five': '하이파이브 접촉',
    'high_five_refused': '하이파이브 거부', 'high_five_cancel': '하이파이브 취소',
    'hide_ready': '숨바꼭질 기대', 'hide_found': '숨바꼭질에서 발견됨',
    'hide_cancel': '숨바꼭질 취소',
    'window_covered': '창으로 행동이 가려짐', 'window_escaped': '창 뒤에서 벗어남',
    'window_revealed': '가리던 창에서 다시 드러남', 'window_cancel': '창 가림 종료',
    'game_start': '게임 시작', 'game_win': '게임 승리', 'game_earned_win': '게임 승리',
    'game_loss': '게임 패배', 'game_disappointed': '게임 역전패',
    'game_draw': '게임 무승부', 'game_cancel': '게임 종료',
    'tap': '캐릭터 클릭',
}
EXTERNAL_GAME_SOURCES = {'win': '외부 게임 승리', 'loss': '외부 게임 패배',
                         'draw': '외부 게임 무승부', 'score': '외부 게임 득점'}
FACE_SOURCES = {
    'happy': '사용자 웃음 감지', 'anger': '사용자 분노 표정 감지',
    'contempt': '사용자 경멸 표정 감지', 'disgust': '사용자 불쾌 표정 감지',
    'fear': '사용자 두려움 감지', 'sadness': '사용자 슬픔 감지', 'surprise': '사용자 놀람 감지',
}
GESTURE_SOURCES = {
    'heart': '하트 인식', 'thumbs_up': '엄지척 인식', 'ok': 'OK 인식',
    'greeting': '손 흔들기 인사', 'head_agree': '고개 끄덕임', 'head_negative': '고개 좌우 흔들기',
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
            dose = amount / (1. + .4 * prior)
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
        mood = self.mood
        now = mood.emotion_time(time.monotonic())
        before = (mood.russell.valence, mood.russell.arousal)
        result = {'before': before, 'reaction': None, 'applied': False, 'dose': 0.}
        for name in ('strength', 'elapsed', 'speed', 'distance', 'control', 'impact_speed', 'contact_at', 'quality'):
            if context.get(name) is not None:
                _number(context[name])
        if event in ('file_received', 'files_returned', 'files_dropped') and not context.get('success', True):
            return result
        if event in ('high_five', 'hide_found') and _number(context.get('quality'), default=1.) <= 0:
            return result
        if not self._distinct(event_id, event):
            result['duplicate'] = True
            log_event('mood.interaction.duplicate', '동일 사건의 감정 중복 반영을 생략합니다.',
                      category='캐릭터 상태', event_name=event, event_id=event_id)
            return result
        self._sync_claims()
        result['reaction'] = event
        mood_name = mood.get_display_emotion()
        mood_valence, mood_arousal = MOOD_REFERENCES[mood_name]
        has_distress = mood.occ_intensities[self._key('distress')] >= .25
        raw, recovery = {}, {}
        valence = arousal = 0.
        dose = _number(context.get('strength'), 0., 2., 1.)
        meaning, agency = '', 0.
        session = str(context.get('session', ''))
        claim = self.claims.get(session, {})
        surprise = risk = 0.

        unwanted_contact = event == 'high_five_refused' or (
            event in ('tap', 'high_five_ready', 'high_five') and mood.refuses_brief_contact()
        )
        if unwanted_contact:
            if event == 'high_five_ready':
                result['reaction'] = None
                return result

            raw = {'distress': .03, 'anger': .02}
            weight = 1.
            if event == 'tap':
                source = source or '원치 않는 클릭'
                dose = self._dose('tap', weight, now)
            else:
                result['reaction'] = 'high_five_refused'
                raw['hope'] = -claim.get('hope', 0.)
                self.claims.pop(session, None)
                weight = _number(context.get('quality'), default=1.)
                source = source or SOURCES['high_five_refused']
                dose = self._dose('high_five', weight, now)
            agency, valence, arousal = -.45, -.01, .025
            meaning = '분노가 높은 상태에서 접촉을 불편하게 받아들임'
        elif event == 'tap':
            dose = self._dose('tap', 1., now)
            engagement = _number(.65 + mood_valence * .35 + mood_arousal * .15)
            context['goal_relevance'] = engagement
            raw, agency = {'joy': .04 * engagement, 'gratitude': .015}, .45
            meaning = '짧고 분명한 접촉을 직전 기분에 따라 평가'
            if (mood_name in LOW_MOOD_EMOTIONS or has_distress
                    or mood.occ_intensities[self._key('fear')] >= .30):
                source = source or '캐릭터 클릭 (위로)'
                recovery = {'distress': .025, 'fear': .018}
                arousal = -.008
        elif event in ('pet', 'pet_refused'):
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
                elif contact['elapsed'] >= .7 and not contact['ignored']:
                    contact['ignored'] = True
                    raw = {'distress': .01, 'anger': .02}
                    agency, meaning = -.6, '거절한 뒤에도 접촉이 지속됨'
                    result['reaction'] = 'contact_ignored'
                else:
                    result['reaction'] = None
                    return result
                dose = self._dose('refusal', 1., now)
            else:
                quality = math.exp(-((speed - 140.) / 200.) ** 2)
                dose = self._dose('pet', elapsed * quality, now, continuous=True, elapsed=elapsed)
                raw = {'joy': .02, 'gratitude': .01, 'satisfaction': .01}
                recovery = {'distress': .025, 'fear': .035}
                if has_distress:
                    raw['joy'] *= .5
                agency, arousal = .6, -.02
                meaning = '편안한 접촉의 시간과 품질에 따라 위로와 친밀감을 누적'
                result['dose'] = elapsed * quality
        elif event == 'poke_start':
            dose = self._dose('poke', 1., now)
            familiar = context.get('familiar', False) and not mood.should_refuse_pet()
            surprise = .45 if familiar else 1.
            arousal, meaning = .025 * surprise, '접촉의 갑작스러움에 따라 각성 변화'
            if familiar and mood_valence > .1:
                raw['joy'] = .012 * min(1., mood_valence + .3)
        elif event in ('poke_play', 'poke_discomfort', 'contact_ignored'):
            dose = self._dose('poke', 1., now)
            if event == 'contact_ignored' or mood.should_refuse_pet():
                raw, agency = {'distress': .02, 'anger': .02}, -.6
                result['reaction'] = 'contact_ignored'
            elif event == 'poke_discomfort' or mood_name in LOW_MOOD_EMOTIONS or has_distress:
                raw = {'distress': .02}
                result['reaction'] = 'poke_discomfort'
            else:
                raw = {'joy': .015}
            arousal, meaning = .01, '현재 감정과 반복 접촉 여부로 장난과 불편함을 구분'
        elif event in ('drag_start', 'drag_held', 'drag_shake'):
            if event == 'drag_start':
                speed = _number(context.get('speed'), 0., 20.)
                dose = _number((speed - 1.3) / 4.)
                surprise = dose
            elif event == 'drag_held':
                dose = .45
            else:
                dose, surprise = 1., .7
            dose = self._dose('drag', dose, now) if dose else 0.
            raw = {'distress': .04 if event == 'drag_shake' else .022}
            arousal = .025 + .035 * surprise
            meaning = '이동 속도와 제어를 잃은 시간 또는 실제 반복 흔들림'
        elif event in ('throw', 'fall_risk'):
            height = (_number(context.get('distance'), 0., 8., 1.) if event == 'fall_risk'
                      else _number(context.get('speed'), 0., 20., 3.) / 3.)
            if self.fall is None:
                self.fall = {'peak': 0., 'claim': 'fall:' + str(now)}
            session = self.fall['claim']
            control = _number(context.get('control'))
            risk = _number((height - FALL_EMOTION_MIN_HEIGHT) / 1.5) * (1. - .65 * control)
            previous = self.fall['peak']
            self.fall['peak'] = max(previous, risk)
            dose = max(0., risk - previous)
            surprise = min(1., dose * 2.) if event == 'throw' or context.get('sudden') else 0.
            raw, valence, arousal = {'fear': .10}, -.025, .08
            meaning = '아직 발생하지 않은 충돌 위험과 통제 불가능성을 평가'
        elif event == 'impact':
            if self.fall is None:
                self.fall = {'peak': 0., 'claim': 'fall:' + str(now)}
            speed = _number(context.get('impact_speed'), 0., 180., 36.)
            severity = _number(speed / 36.)
            peak = self.fall.get('impact', 0.)
            contact_at = context.get('contact_at')
            if contact_at is None:
                dose = max(0., severity - peak)
            else:
                # Two axes of the same corner can register in adjacent physics steps.
                started, contact_peak, count = self.fall.get('contact', (-math.inf, 0., 0))
                if contact_at < started:
                    return result
                if contact_at - started > .08:
                    started, contact_peak, count = contact_at, 0., count + 1
                dose = max(0., severity - contact_peak) * .65 ** (count - 1)
                self.fall['contact'] = (started, max(severity, contact_peak), count)
            self.fall['impact'] = max(peak, severity)
            used = self.fall.get('impact_dose', 0.)
            dose = min(dose, max(0., 1.6 - used))
            self.fall['impact_dose'] = used + dose
            surprise = severity
            raw, valence, arousal = {'distress': .025}, -.015, .02
            meaning = '실제 접촉별 충격을 평가하고 같은 충돌의 중복과 연속 충격의 누적을 제한'
        elif event == 'safe_landing':
            if self.fall is None:
                return result
            session = self.fall['claim']
            claim = self.claims.pop(session, {})
            impacted = bool(self.fall.get('impact'))
            self.fall = None
            owned_fear = min(claim.get('fear', 0.), mood.occ_intensities[self._key('fear')])
            if owned_fear <= 0:
                result['reaction'] = None
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
        elif event in ('high_five_ready', 'hide_ready', 'ball_ready'):
            engagement = _number(.65 + mood_valence * .35 + mood_arousal * .15)
            amount = .015 if event == 'ball_ready' else .02
            raw, dose = {'hope': amount * engagement}, self._dose(event, 1., now)
            meaning = '확인된 놀이 기회와 현재의 참여 의욕'
        elif event in ('high_five', 'hide_found', 'high_five_cancel', 'hide_cancel'):
            owned_hope = claim.get('hope', 0.)
            raw = {'hope': -owned_hope}
            self.claims.pop(session, None)
            if event.endswith('_cancel'):
                result['reaction'] = None
                meaning = '진행을 멈춘 놀이의 기대만 정리'
            else:
                confidence = _number(context.get('quality'), default=1.)
                engagement = _number(.60 + mood_valence * .35 + mood_arousal * .15)
                dose = self._dose(event, confidence, now)
                raw.update(joy=.04 * engagement, satisfaction=min(.025, owned_hope * .8),
                           gratitude=.03 * engagement * (.65 if event == 'high_five' else .3))
                recovery = {'fear': .025, 'distress': .022} if event == 'high_five' else {}
                agency = .65 if event == 'high_five' else .3
                arousal = .02 * engagement - .035 * mood.occ_intensities[self._key('fear')]
                meaning = '실제로 확인된 놀이 결과와 호의, 기대 및 직전 긴장'
        elif event in ('window_covered', 'window_escaped', 'window_revealed', 'window_cancel'):
            if event == 'window_covered':
                risk = _number(context.get('strength'), default=.6) * .45
                raw, arousal = {'fear': .10 * risk}, .025 * risk
                meaning = '가려진 상태가 지속되어 움직임과 지지의 불확실성이 생김'
            else:
                owned_fear = min(claim.get('fear', 0.), mood.occ_intensities[self._key('fear')])
                raw = {'fear': -owned_fear}
                self.claims.pop(session, None)
                if event in ('window_escaped', 'window_revealed'):
                    raw['relief'] = min(.06, owned_fear * .6)
                    arousal = -.03 * min(1., owned_fear / .04)
                    if event == 'window_escaped':
                        raw['satisfaction'] = .012
                        meaning = '탈출을 완료해 안전과 제어를 되찾음'
                    else:
                        meaning = '가리던 창이 없어지거나 비켜나 다시 드러남'
                else:
                    result['reaction'] = None
                    meaning = '가림이 중단되어 해당 위험 기여분만 정리'
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
                result['reaction'] = None
                meaning = '종료한 공의 기대만 정리'
            self.claims.pop(session, None)
        elif event == 'game_external_result':
            outcome = context.get('outcome')
            if outcome not in EXTERNAL_GAME_SOURCES:
                raise ValueError('Unknown external game outcome')
            quality = _number(context.get('quality'), default=1.)
            engagement = _number(.7 + mood_valence * .18 + mood_arousal * .12)
            family = 'external_game_score' if outcome == 'score' else 'external_game_result'
            dose = self._dose(family, quality * engagement, now)
            source = source or EXTERNAL_GAME_SOURCES[outcome]
            if outcome == 'win':
                raw, valence, arousal = {'joy': .05}, .02, .024
            elif outcome == 'loss':
                raw, valence, arousal = {'distress': .044}, -.018, .012 * mood_arousal
            elif outcome == 'score':
                raw, valence, arousal = {'joy': .026}, .01, .018
            else:
                raw, arousal = {'joy': .007}, -.008
            meaning = '사용자의 게임 화면에 확인된 결과를 관전 중인 캐릭터의 관점으로 평가'
        elif event.startswith('game_'):
            if event == 'game_start':
                engagement = _number(.7 + mood_valence * .3 + mood_arousal * .18)
                raw = {'hope': (.008 if context.get('round') else .015) * engagement}
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
                elif event == 'game_cancel':
                    result['reaction'] = None
                else:
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
                source = source or SOURCES['files_dropped']
                meaning = '거친 다루기로 보관하던 파일을 놓침'
            else:
                raw = {'satisfaction': .015}
                meaning = '요청한 파일 반환 묶음을 정상적으로 완료'
        elif event == 'wake':
            dose = self._dose('wake', 1., now)
            arousal = min(.04, max(0., -before[1]))
            meaning = '수면에서 깨어나 흥분도를 회복; 휴식 보상은 다시 지급하지 않음'
        elif event == 'wake_settle':
            return result
        else:
            raise ValueError('Unknown interaction event: ' + event)

        if dose <= 0 and not any(amount < 0 for amount in raw.values()):
            return result
        state = mood._capture_emotion_state()
        factor, factors = 1., []
        negative = ('distress', 'fear', 'anger', 'shame')
        weights = {}
        if mood.personality_system is not None:
            signs = {(-1 if name in negative else 1) for name, amount in raw.items() if amount > 0}
            for sign in sorted(signs or {0}):
                weights[sign], labels = mood.personality_system.get_event_weight_multiplier(
                    valence=sign, self_attribution=.6 if sign > 0 and context.get('earned') else 0.,
                    agent_benevolence=agency if agency * sign > 0 else 0., novelty=surprise)
                factors.extend(label for label in labels if label not in factors)
            factor = sum(weights.values()) / len(weights)
        applied_dose = dose * factor
        increases = {name: amount * dose * OCC_RESPONSE_GAIN * weights.get(-1 if name in negative else 1, 1.)
                     for name, amount in raw.items() if amount > 0}
        physical_risk = event in ('throw', 'fall_risk')
        increases = {name: min(.10 if name == 'fear' and physical_risk else
                               .06 if name == 'relief' else .05, amount)
                     for name, amount in increases.items()}
        total = sum(increases.values())
        limit = .12 if physical_risk else .09
        scale = min(1., limit / total) if total else 1.
        for name, amount in raw.items():
            key, current = self._key(name), mood.occ_intensities[self._key(name)]
            if amount > 0:
                # Exact integration of dI/dDose=(1-I)^1.5 is invariant to frame rate.
                remaining = max(0., 1. - current)
                added = increases[name] * scale
                mood.occ_intensities[key] = (1. - (remaining ** -.5 + added / 2.) ** -2
                                             if remaining > 1e-12 else current)
            else:
                # An episode's outstanding expectation/fear is resolved once.
                mood.occ_intensities[key] = max(0., current + amount)
        for name, rate in recovery.items():
            key = self._key(name)
            mood.occ_intensities[key] *= math.exp(-rate * applied_dose * OCC_RESPONSE_GAIN)
        mood._event_valence_bias = max(-1., min(1., mood._event_valence_bias + valence * applied_dose))
        mood._event_arousal_bias = max(-1., min(1., mood._event_arousal_bias + arousal * applied_dose))
        if (mood.occ_intensities == state['occ'] and
                (mood._event_valence_bias, mood._event_arousal_bias) == state['bias']):
            return result
        continuous = event in ('pet', 'pet_refused')
        if continuous:
            mood._update_russell_from_occ()
        else:
            mood._apply_occ_to_mood()
        self._sync_claims({name: -amount for name, amount in raw.items() if amount < 0})
        result.update(mood._event_changes(state), risk=risk, surprise=surprise)
        changes = result['changes']
        if session and event in ('throw', 'fall_risk', 'ball_ready', 'game_start', 'high_five_ready',
                                 'hide_ready', 'window_covered'):
            credits = self.claims.setdefault(session, {})
            for name in ('fear', 'hope'):
                credits[name] = credits.get(name, 0.) + max(0., changes.get(name, 0.))
            while len(self.claims) > 32:
                del self.claims[next(iter(self.claims))]
        if result['applied']:
            goodness = sum((-amount if name in negative else amount) for name, amount in changes.items())
            category = 'positive' if goodness > 0 else 'negative' if goodness < 0 else 'neutral'
            mood._record_influence(
                source=source or SOURCES.get(event, event), category=category,
                base_weight=dose, adjusted_weight=applied_dose, personality_multiplier=factor,
                personality_factors=factors, before=before, before_occ=state['occ'],
                state_before=state, merge_window=.5 if continuous else 0., details=meaning,
                weight_applied=mood.personality_system is not None,
                event_input={'event': event, 'event_id': event_id, 'session': session,
                             'requested_occ': raw, 'actual_occ': changes, 'dose': dose,
                             'bias_change': result['bias_change'],
                             'arousal_change': result['bias_change'][1] if not changes else 0.,
                             **context})
        return result

    def _apply_perception(self, signal, *, event_id=None, source=None, actor_state=None,
                          label=None, quality=1., maintenance=1., **context):
        mood = self.mood
        now = mood.emotion_time(time.monotonic())
        quality, maintenance = unit(quality), unit(maintenance)
        state = mood._capture_emotion_state()
        before = (mood.russell.valence, mood.russell.arousal)
        occ = {key.value: value for key, value in mood.occ_intensities.items()}
        actor = dict(actor_state or {})
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
        requested = {name: max(-.04, min(.04, value * dose * OCC_RESPONSE_GAIN)) for name, value in raw.items()}
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
        appraisal.update(applied_occ=changes, budget_scale=scale, quality=quality,
                         applied_arousal=arousal,
                         personality_multiplier=factor, repetition_multiplier=repeat)
        result.update(mood._event_changes(state), reaction='user_' + signal, dose=dose,
                      surprise=quality if signal == 'face' and label == 'surprise' else 0.)
        if not result['applied']:
            limited = (amount > 0 and scale == 0 or
                       appraisal['arousal'] * dose != 0 and arousal_used >= .06)
            appraisal['reason'] = 'budget_exhausted' if limited else 'no_change'
        if result['applied']:
            source = source or (FACE_SOURCES.get(label, '사용자 표정 인식') if signal == 'face'
                                else GESTURE_SOURCES[signal])
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
                    'arousal_change': arousal, 'maintenance': maintenance,
                    'budget_scale': scale, 'repetition_multiplier': repeat,
                    'state_labels': appraisal['state_labels'], **context})
        return result
