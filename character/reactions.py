"""Display short emotional reactions using the appraisal that changed the mood."""

from collections import deque
import math
import time

from PyQt6.QtCore import QObject, QTimer

from app_logging import log_event, log_throttled
from .russell_sectors import SECTORS, SECTOR_ANGLE, russell_face


_FACES = {
    name: (math.cos(math.radians(index * SECTOR_ANGLE)),
           math.sin(math.radians(index * SECTOR_ANGLE)))
    for index, (name, _) in enumerate(SECTORS)
}
_FACES.update(fear=(-.60, .75), angry=(-.85, .85), scared=(0., .95))
_CONCERN = {'neutral', 'anxious', 'fear', 'scared', 'distressed', 'hurt', 'displeased'}
_PHYSICAL_EVENTS = {'throw', 'fall_risk', 'impact', 'safe_landing', 'drag_shake'}
_DIRECT_INTERACTIONS = {'tap', 'pet', 'pet_refused', 'poke_start', 'poke_play', 'poke_discomfort',
                        'contact_ignored', 'palm', 'drag_start', 'drag_held', 'high_five',
                        'files_returned', 'files_dropped'}


def _strength(result):
    return min(1., max(sum(abs(value) for value in result.get('changes', {}).values()),
                       math.hypot(*result.get('bias_change', (0., 0.)))) / .04)


def choose_face(result, before, *, current=None):
    """Combine the applied change, evidence and current Russell direction."""
    strength = _strength(result)
    if strength < .10:
        return None
    changes = result.get('changes', {})
    _, arousal = result.get('bias_change', (0., 0.))
    delta = result.get('target_change', (0., 0.))
    radius = math.hypot(*delta)
    distance = .20 + .25 * strength
    target = tuple(value + distance * movement / radius for value, movement in zip(before, delta)) if radius else before
    radius = math.hypot(*target)

    gain = min(1., sum(max(0., changes.get(name, 0.)) for name in
                       ('joy', 'gratitude', 'pride', 'hope', 'satisfaction')) / .04)
    loss = min(1., sum(max(0., changes.get(name, 0.)) for name in
                       ('distress', 'anger', 'shame')) / .035)
    comfort = min(1., (max(0., changes.get('relief', 0.)) + max(0., -arousal)
                      + sum(max(0., -changes.get(name, 0.)) for name in
                            ('fear', 'distress', 'anger'))) / .045)
    risk = result.get('risk', 0.)
    threat = max(risk, min(1., max(0., changes.get('fear', 0.)) / .045))
    surprise = min(result.get('surprise', 0.), max(0., arousal) / .025)
    support = dict.fromkeys(_FACES, 0.)
    support.update(
        pleasant=gain, happy=gain, excited=gain, thrilled=gain * .7,
        serene=max(gain * .8, comfort), calm=max(gain * .55, comfort),
        relieved=comfort, quiet=max(loss * .45, comfort * .7), tired=comfort * .4,
        sad=loss, depressed=loss * .7, hurt=loss, distressed=max(loss, threat * .5),
        displeased=loss, anxious=threat * (1. - .45 * risk), fear=threat * (.55 + .45 * risk),
        scared=surprise, angry=min(1., max(0., changes.get('anger', 0.)) / .02),
        proud=min(1., max(0., changes.get('pride', 0.)) / .025),
    )
    special = {'scared', 'fear', 'angry', 'proud'}
    candidates = ['neutral', *(face for face in _FACES if face not in special or support[face] > .10)]
    if changes.get('relief', 0.) <= 0:
        candidates.remove('relieved')
    if strength < .30 and before[1] < .35:
        candidates = [face for face in candidates if face not in {'thrilled', 'excited'}]
    if not changes and arousal > 0 and not surprise:
        candidates = ['neutral', 'quiet', 'calm', 'serene', 'tired']
        for face in candidates[1:]:
            support[face] = .55
    base = current if current == 'neutral' or current in _FACES else russell_face(*before)
    if base not in candidates:
        candidates.append(base)
    if risk >= .45 and strength >= .45:
        candidates = [face for face in candidates if face in _CONCERN]

    def score(face):
        if face == 'neutral':
            return .62 - .22 * strength
        x, y = _FACES[face]
        direction = (1. + (x * target[0] + y * target[1]) / (math.hypot(x, y) * radius)) / 2 if radius else .5
        continuity = 1. if face == base else 0.
        if not continuity and base in _FACES:
            bx, by = _FACES[base]
            continuity = .5 if (x * bx + y * by) / (math.hypot(x, y) * math.hypot(bx, by)) >= .92 else 0.
        return .6 * direction + .3 * support[face] + .1 * continuity

    best = max(candidates, key=lambda face: (score(face), face == base))
    return base if base in candidates and score(best) - score(base) < .06 else best


def reaction_mood(host):
    state = getattr(getattr(host, 'mood_system', None), 'russell', None)
    return (state.valence, state.arousal) if state is not None else (0., 0.)


def react(host, event, result, **options):
    reactions = getattr(host, 'reactions', None)
    if (reactions is not None and isinstance(result, dict) and result.get('applied')
            and (face_event := result.get('reaction', event)) is not None):
        return reactions.play(face_event, result=result, **options)
    return False


def experience(host, event, *, source=None, event_id=None, reaction=True,
               reaction_source=None, sustain=False, **context):
    """Commit the event once and use the committed changes for its expression."""
    handler = getattr(getattr(host, 'mood_system', None), 'on_interaction', None)
    if getattr(host, '_character_closing', False) or handler is None:
        return {'applied': False, 'reaction': None}
    result = handler(event, source=source, event_id=event_id, **context)
    if not isinstance(result, dict):
        return {'applied': False, 'reaction': None}
    if reaction:
        react(host, event, result, source=reaction_source, sustain=sustain)
    return result


class Reactions(QObject):
    """Own one temporary face, using a short window for continuous input."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)
        self.event = self.source = self.face = None
        self.priority = 0
        self._shown_at = 0.
        self._sample_key = None
        self._samples = deque()

    def _recent(self, key, result, now):
        if self._sample_key != key:
            self._samples.clear()
            self._sample_key = key
        self._samples.append((now, result))
        while self._samples and now - self._samples[0][0] > .45:
            self._samples.popleft()
        changes = {}
        valence = arousal = target_v = target_a = 0.
        for _, sample in self._samples:
            for name, change in sample['changes'].items():
                changes[name] = changes.get(name, 0.) + change
            dv, da = sample['bias_change']
            valence += dv
            arousal += da
            dv, da = sample['target_change']
            target_v += dv
            target_a += da
        return {**result, 'changes': changes, 'bias_change': (valence, arousal),
                'target_change': (target_v, target_a)}

    def play(self, event, *, result, source=None, sustain=False):
        host = self.host
        appraisal = result.get('appraisal') or {}
        source = source or ('perception' if appraisal else event)
        priority = appraisal.get('priority', 2)
        if event in _PHYSICAL_EVENTS:
            priority = 5
        elif event.startswith('game_') and event != 'game_start':
            priority = 4
        elif event in _DIRECT_INTERACTIONS:
            priority = 3
        now = time.monotonic()
        if sustain:
            result = self._recent((source, event), result, now)
        strength = _strength(result)
        animator = host.sprite_animator
        before = reaction_mood(host)
        face = choose_face(result, before, current=getattr(animator, 'current_emotion', None))
        if face is None:
            return False
        urgent = source == 'fall' or event in {'impact', 'safe_landing'}
        blocked = (
            'no_rig' if host.rig_view is None else
            'hidden' if host._character_closing or not host.isVisible() else
            'sleeping' if getattr(host, 'current_action', None) == 'sleep' else
            'perception_policy' if not appraisal.get('reaction_allowed', True) else
            'manual_face' if getattr(animator, '_emotion_override', None) and not urgent else
            'higher_priority' if self.priority > priority else
            'same_face' if self.event is None and face == getattr(animator, 'current_emotion', None) else None
        )
        if blocked:
            log_throttled('character.reaction.skipped', '리액션 표정 표시 보류', category='캐릭터 상태',
                          key=f'reaction:{event}:{blocked}', interval=.5,
                          event_name=event, emotion=face, displayed_emotion=(
                              'sleep' if blocked == 'sleeping' else getattr(animator, 'current_emotion', None)),
                          reason=blocked)
            return False

        seconds = .45 + .65 * strength
        if face == 'scared':
            seconds = .18 + .17 * strength
        if self.source == source and self.event == event:
            if face == self.face or (sustain and not urgent and now - self._shown_at < .30):
                self._timer.start(round(seconds * 1000))
                return animator.current_emotion == self.face
        self.event, self.source, self.face = event, source, face
        self.priority, self._shown_at = priority, now
        animator.set_reaction_emotion(face, urgent=urgent)
        self._timer.start(round(seconds * 1000))
        shown = animator.current_emotion
        if shown == face:
            log_event('character.reaction', '사건에 따라 리액션 표정을 표시합니다.',
                      category='캐릭터 상태', event_name=event, source=source, emotion=face,
                      displayed_emotion=shown, valence=before[0], arousal=before[1],
                      actual_occ=result['changes'], actual_bias=result['bias_change'])
        else:
            log_throttled('character.reaction.skipped', '동작 표정이 리액션보다 우선합니다.',
                          category='캐릭터 상태', key=f'reaction:{event}:motion', interval=.5,
                          event_name=event, emotion=face, displayed_emotion=shown, reason='motion_face')
        return shown == face

    def clear(self, source=None):
        if source is None or self._sample_key and self._sample_key[0] == source:
            self._sample_key = None
            self._samples.clear()
        if source is not None and source != self.source:
            return
        was_active = self.event is not None
        self._timer.stop()
        self.event = self.source = self.face = None
        self.priority = 0
        if was_active and self.host.rig_view is not None:
            mood = self.host.mood_system
            self.host.sprite_animator.set_mood_emotion(mood.decide_emotion()['emotion'])
            self.host.sprite_animator.set_reaction_emotion()

    def cancel(self):
        self.clear()

    def falling(self, distance, *, sudden=False):
        if distance < .38:
            return
        result = experience(self.host, 'fall_risk', distance=distance, sudden=sudden,
                            reaction_source='fall', sustain=True)
        if (not result.get('applied') and self.source == 'fall'
                and self._timer.remainingTime() < 250):
            self._timer.start(400)

    def safe(self, *, rescued=False):
        self.clear('fall')
        result = experience(self.host, 'safe_landing', rescued=rescued, reaction_source='fall')
        return result.get('applied', False)
