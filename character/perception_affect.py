"""State-dependent appraisal of confirmed observations; no second mood store.

The numbers are application tuning, not calibrated probabilities or OCC constants.
"""
import math

from .russell_sectors import SECTORS, SECTOR_ANGLE


POSITIVE_SIGNALS = {'heart': 1., 'thumbs_up': .8, 'greeting': .7,
                    'ok': .45, 'head_agree': .35}
PROFILE_NAMES = {'normal': '호의 수용', 'fear': '안정과 위로',
                 'guard': '조심스러운 수용', 'down': '낮은 활력에서의 위로'}
POSITIVE_PROFILES = {
    'normal': {'joy': .030, 'gratitude': .015},
    'fear': {'fear': -.020, 'relief': .015},
    'guard': {'anger': -.005, 'gratitude': .005},
    'down': {'distress': -.020, 'gratitude': .015, 'joy': .005},
}
DECLINE_PROFILES = {
    'normal': {'distress': .005},
    'fear': {'fear': .004, 'distress': .002},
    'guard': {'distress': .003},
    'down': {'distress': .002},
}
NEGATIVE_FACES = {
    'sadness': {'distress': .008},
    'anger': {'distress': .006}, 'disgust': {'distress': .006},
    'contempt': {'distress': .006},
    'fear': {'fear': .004, 'distress': .004},
}
PALETTES = {
    'positive': {
        'normal': ('pleasant', 'happy', 'excited', 'serene'),
        'fear': ('calm', 'relieved', 'serene'),
        'guard': ('quiet', 'displeased', 'calm'),
        'down': ('quiet', 'calm', 'serene'),
    },
    'concern': {
        'normal': ('quiet', 'hurt', 'calm'), 'fear': ('anxious', 'fear', 'quiet'),
        'guard': ('displeased', 'quiet'), 'down': ('quiet', 'sad', 'calm'),
    },
}
TARGETS = {'normal': (.55, .20), 'fear': (.25, -.35),
           'guard': (-.15, -.10), 'down': (.20, -.30)}
FACE_COORDINATES = {
    name: (math.cos(math.radians(index * SECTOR_ANGLE)),
           math.sin(math.radians(index * SECTOR_ANGLE)))
    for index, (name, _) in enumerate(SECTORS)
}
FACE_COORDINATES['fear'] = (-.6, .75)


def unit(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Perception measurements must be finite')
    return max(0., min(1., value))


def profile_weights(occ, before):
    valence, arousal = before
    fear, guard = unit(occ.get('fear', 0)), unit(occ.get('anger', 0))
    down = max(unit(occ.get('distress', 0)), max(0., -valence)) * unit((.1 - arousal) / .5)
    total = fear + guard + down
    divisor = max(1., total)
    return {'normal': max(0., 1. - total) / divisor, 'fear': fear / divisor,
            'guard': guard / divisor, 'down': down / divisor}


def mix_profiles(profiles, weights):
    result = {}
    for profile, weight in weights.items():
        for emotion, amount in profiles[profile].items():
            result[emotion] = result.get(emotion, 0.) + weight * amount
    return {key: value for key, value in result.items() if abs(value) > 1e-12}


def state_labels(occ, before, rest, active, pending, now):
    """Hysteretic labels explain continuous appraisal, rather than replacing it."""
    valence, arousal = before
    down = max(occ.get('distress', 0.), max(0., -valence)) * unit((.1 - arousal) / .5)
    fear, anger = occ.get('fear', 0.), occ.get('anger', 0.)
    conditions = {
        'fear': (fear >= .4, fear > .3),
        'guard': (anger >= .4, anger > .3),
        'down': (down >= .35, down > .25),
        'bright': (valence >= .2, valence > .1),
        'tired': (rest >= .65, rest > .45),
        'contact_refusal': (anger >= .65 and valence <= -.4,
                            anger > .5 and valence < -.25),
    }
    for name, (enter, remain) in conditions.items():
        update_label(name, enter, remain, active, pending, now)
    return sorted(active)


def update_label(name, enter, remain, active, pending, now):
    current = name in active
    desired = remain if current else enter
    if desired == current:
        pending.pop(name, None)
    elif now - pending.setdefault(name, now) >= (1. if current else .3):
        active.discard(name) if current else active.add(name)
        pending.pop(name, None)
    return name in active


def appraise_perception(signal, occ, before, actor=None, *, label=None):
    actor = dict(actor or {})
    weights = profile_weights(occ, before)
    result = {'signal': signal, 'label': label, 'weights': weights, 'before': before,
              'actor': actor, 'requested_occ': {}, 'arousal': 0., 'multiplier': 1.,
              'accepted': False, 'reason': None, 'reset_idle': False, 'wake': False,
              'style': 'positive', 'priority': 1 if signal == 'face' else 2,
              'seconds': .6 if signal == 'face' else .9, 'strength': 1.,
              'reaction_allowed': not actor.get('manual_face', False)}
    if actor.get('closing') or actor.get('physical') or actor.get('manual_emotion'):
        result['reason'] = ('closing' if actor.get('closing') else 'physical_owner'
                            if actor.get('physical') else 'manual_emotion')
        return result
    if actor.get('game'):
        if signal != 'face':
            result['reason'] = 'game_owner'
            return result
        result['multiplier'] = .25
        result['reaction_allowed'] = False
    if actor.get('sleeping'):
        if signal != 'greeting' or actor.get('manual_motion'):
            result['reason'] = 'sleeping'
            return result
        result['wake'] = True
        result['arousal'] = min(.02, max(0., -before[1]))
    if signal.startswith('head_') and not actor.get('recent_dialogue'):
        result['reason'] = 'no_dialogue_context'
        return result

    if signal in POSITIVE_SIGNALS or signal == 'face' and label == 'happy':
        strength = POSITIVE_SIGNALS.get(signal, .25)
        result['strength'] = strength
        raw = mix_profiles(POSITIVE_PROFILES, weights)
        if signal in ('ok', 'head_agree'):
            raw['satisfaction'] = raw.get('satisfaction', 0.) + raw.pop('joy', 0.)
        if signal == 'face':
            raw.pop('gratitude', None)
        raw = {key: amount * strength for key, amount in raw.items()}
    elif signal == 'head_negative':
        result['style'] = 'concern'
        raw = mix_profiles(DECLINE_PROFILES, weights)
    elif signal == 'face' and label in NEGATIVE_FACES:
        result['style'] = 'concern'
        base = NEGATIVE_FACES[label]
        profiles = {'normal': base,
                    'fear': {**base, 'fear': base.get('fear', 0.) + .25 * sum(base.values())},
                    'guard': {key: value * .5 for key, value in base.items()},
                    'down': {key: value * .5 for key, value in base.items()}}
        raw = mix_profiles(profiles, weights)
    elif signal == 'face' and label == 'surprise':
        result['style'] = 'concern'
        result['arousal'] = .01 * (1. + .3 * weights['fear'] - .3 * weights['down'])
        raw = {}
    else:
        result['reason'] = 'neutral' if label == 'neutral' else 'unmapped'
        return result

    if unit(actor.get('rest', 0.)) >= .65:
        result['multiplier'] *= .7
    result.update(accepted=True, requested_occ=raw, reset_idle=signal != 'face')
    result['interpretation'] = {PROFILE_NAMES[name]: round(weight, 4)
                                for name, weight in weights.items() if weight > 1e-6}
    return result


def choose_perception_face(appraisal, before=None):
    weights = appraisal['weights']
    palettes = PALETTES[appraisal['style']]
    highest = max(weights.values())
    profiles = [name for name, value in weights.items() if highest - value <= .15]
    candidates = sorted({face for name in profiles for face in palettes[name]})
    direction = tuple(sum(weights[name] * TARGETS[name][axis] for name in weights)
                      for axis in (0, 1))
    before = before if before is not None else appraisal['before']
    blend = .1 + .3 * unit(appraisal.get('expression_strength', appraisal['strength']))
    target = tuple((1 - blend) * old + blend * new for old, new in zip(before, direction))
    radius = math.hypot(*target)
    if radius:
        target = tuple(value / radius for value in target)
    def score(face):
        support = sum(weights[name] for name in profiles if face in palettes[name])
        return math.dist(target, FACE_COORDINATES[face]) - .2 * support
    return min(candidates, key=score)
