"""Choose short facial reactions from event appraisal and pre-event Russell mood."""

import math
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer

from app_logging import log_event
from .russell_sectors import SECTORS, SECTOR_ANGLE, russell_face


@dataclass(frozen=True)
class Appraisal:
    # Outcome desirability, expressive arousal, and weight in the visible reaction.
    outcome: float
    arousal: float
    weight: float
    seconds: float
    priority: int = 1
    attribution: str = ""
    prospect: str = ""
    sudden: bool = False


EVENTS = {
    "pet": Appraisal(.56, -.42, .38, .50, attribution="help"),
    "pet_refused": Appraisal(-.52, .04, .65, .55, 2),
    "poke_start": Appraisal(.12, .70, .55, .22, 2, sudden=True),
    "poke_play": Appraisal(.44, .32, .40, .44, 2),
    "poke_discomfort": Appraisal(-.44, .12, .54, .48, 2),
    "tap": Appraisal(.47, .18, .39, .55),
    "drag_start": Appraisal(-.3, .73, .70, .36, 3, sudden=True),
    "drag_discomfort": Appraisal(-.56, .10, .55, .68, 3),
    "drag_repeated": Appraisal(-.68, .58, .54, .76, 3, attribution="blame"),
    "palm": Appraisal(.50, -.38, .43, .58, 2, attribution="help"),
    "ball_ready": Appraisal(.42, .37, .37, .58),
    "ball_kicked": Appraisal(.60, .67, .42, .80, 2),
    "ball_removed": Appraisal(-.40, -.33, .44, .64),
    "file_received": Appraisal(.59, -.06, .45, .82, 2, attribution="help"),
    "files_returned": Appraisal(-.60, -.30, .48, .76, 3),
    "fall_start": Appraisal(-.34, .8, .70, .22, 5, sudden=True),
    "fall_risk": Appraisal(-.65, .68, .62, .65, 5, prospect="threat"),
    "safe_landing": Appraisal(.52, -.40, .65, .73, 5, prospect="safe"),
    "greeting": Appraisal(.52, .14, .42, .94, 2, attribution="help"),
    "praised": Appraisal(.52, .28, .42, .78, 2, attribution="self_credit"),
    "good_news": Appraisal(.55, .20, .44, .80, 2),
    "game_win": Appraisal(.66, .58, .48, 1.06, 4),
    "game_earned_win": Appraisal(.69, .43, .51, 1.1, 4, attribution="self_credit"),
    "game_loss": Appraisal(-.55, -.21, .48, 1.02, 4),
    "game_draw": Appraisal(.37, -.18, .38, .74, 4),
    "game_disappointed": Appraisal(-.66, -.28, .58, 1.22, 4, prospect="missed_reward"),
    "self_play": Appraisal(.47, .43, .42, .63),
    "wake": Appraisal(.25, -.55, .58, .58),
    "wake_settle": Appraisal(.49, -.37, .55, .58),
}

_FACES = {
    name: (math.cos(math.radians(i * SECTOR_ANGLE)), math.sin(math.radians(i * SECTOR_ANGLE)))
    for i, (name, _) in enumerate(SECTORS)
}
_FACES["fear"] = (-.60, .75)


def choose_face(event, before, *, strength=1.0):
    """Gate by what happened, then rank eligible faces on the affect plane."""
    rule = EVENTS[event]
    if rule.sudden:
        return "scared"
    if rule.prospect == "safe":
        return "relieved"
    weight = min(1., rule.weight * strength)
    target = ((1 - weight) * before[0] + weight * rule.outcome,
              (1 - weight) * before[1] + weight * rule.arousal)
    if rule.prospect == "threat":
        candidates = ("anxious", "fear")
        # Threat severity also changes which expressions are plausible.
        if strength < .9:
            return "anxious"
        if strength >= 1.45:
            return "fear"
    elif rule.prospect == "missed_reward":
        candidates = ("hurt", "sad")
    elif event == "pet_refused":
        return "displeased"
    elif event == "wake":
        candidates = ("tired", "quiet", "serene")
    elif event in ("ball_ready", "ball_kicked", "self_play"):
        candidates = ("pleasant", "excited", "thrilled")
    elif rule.outcome < 0:
        candidates = ("displeased", "hurt", "sad", "distressed")
        if rule.attribution == "blame" and target[1] >= .38:
            return "angry"
    else:
        candidates = ("pleasant", "serene", "happy", "excited", "thrilled")
        if event in ("pet", "palm", "wake_settle", "tap", "greeting"):
            candidates += ("calm",)
        if rule.attribution == "self_credit":
            candidates += ("proud",)
    if rule.outcome > 0 and target[0] < 0 and event != "wake":
        candidates = ("calm", "serene", "pleasant")
    # Compare directions for ordinary faces. Use the authored coordinates of
    # reactions outside the ring to distinguish nearby fear and anger.
    radius = math.hypot(*target)
    if radius > 0:
        target = (target[0] / radius, target[1] / radius)
    ranked = sorted(candidates, key=lambda face: math.dist(target, _FACES[face]))
    best, second = ranked[:2]
    if (rule.outcome > 0 and best == russell_face(*before)
            and math.dist(target, _FACES[second]) - math.dist(target, _FACES[best]) < .30):
        return second
    return best


def reaction_mood(host):
    state = getattr(getattr(host, 'mood_system', None), 'russell', None)
    return (state.valence, state.arousal) if state is not None else (0., 0.)


def react(host, event, **options):
    reactions = getattr(host, 'reactions', None)
    if reactions is not None:
        return reactions.play(event, **options)
    return False


class Reactions(QObject):
    """One temporary face. A newer event owns its timeout and any follow-up."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        self.event = None
        self.source = None
        self._next = None
        self.threat = False

    def play(self, event, *, before=None, source=None, strength=1., follow=None, sustain=False):
        host = self.host
        if (host.rig_view is None or host._character_closing or not host.isVisible()
                or getattr(host, '_hand_throw_active', False)):
            return False
        rule = EVENTS[event]
        if self.event is not None and EVENTS[self.event].priority > rule.priority:
            return False
        source = source or event
        if sustain and self.source == source and self.event == event:
            self._timer.start(round(rule.seconds * 1000))
            return True
        before = before if before is not None else reaction_mood(host)
        face = choose_face(event, before, strength=strength)
        self.event, self.source = event, source
        self._next = (follow, before, strength) if follow else None
        host.sprite_animator.set_reaction_emotion(face, urgent=source == "fall")
        self._timer.start(round(rule.seconds * 1000))
        log_event('character.reaction', '사건에 따라 리액션 표정을 표시합니다.',
                  category='캐릭터 상태', event_name=event, source=source, emotion=face,
                  valence=before[0], arousal=before[1], outcome=rule.outcome,
                  attribution=rule.attribution, prospect=rule.prospect)
        return True

    def _advance(self):
        follow, source = self._next, self.source
        self.clear()
        if follow is not None:
            event, before, strength = follow
            self.play(event, before=before, strength=strength, source=source)

    def clear(self, source=None):
        if source is not None and source != self.source:
            return
        was_active = self.event is not None
        self._timer.stop()
        self.event = self.source = self._next = None
        if was_active and self.host.rig_view is not None:
            self.host.sprite_animator.set_mood_emotion("neutral")
            self.host.sprite_animator.set_reaction_emotion()

    def cancel(self):
        self.threat = False
        self.clear()

    def falling(self, distance, *, sudden=False):
        if distance < .38 or getattr(self.host, '_hand_throw_active', False):
            return
        strength = min(1.8, .65 + distance * .6)
        self.threat = self.threat or distance >= .65
        if self.source == "fall":
            if self.event == "fall_risk" and self._timer.remainingTime() < 250:
                self._timer.start(round(EVENTS["fall_risk"].seconds * 1000))
            return
        if sudden:
            self.play("fall_start", source="fall", strength=strength,
                      follow="fall_risk" if self.threat else None)
        elif self.threat:
            self.play("fall_risk", source="fall", strength=strength)

    def safe(self):
        was_threat = self.threat
        self.threat = False
        self.clear("fall")
        return was_threat and self.play("safe_landing")
