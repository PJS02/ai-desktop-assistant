"""Support relaxed hands and launch the real ball from a confirmed hand swing."""
from dataclasses import replace
import math
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QEvent, QPoint, QRect, Qt
from PyQt6.QtWidgets import QApplication

from character.sandbox_manager import BallWidget
from hand_overlay.interaction_host import CharacterHandActions
from hand_overlay.interactions import Box, DisplayedHand, HandInteractionEngine


def pose(point=(150., 210.), *, support=False, facing=1, tilt=0., relaxed=False):
    points = [(0., .8, 0.)] * 21
    points[1:5] = [(-.3, .4, 0.), (-.5, .1, 0.), (-.6, -.1, 0.), (-.6, -.3, 0.)]
    for base, x in ((5, -.3), (9, -.1), (13, .1), (17, .3)):
        points[base:base + 4] = [(x, 0., 0.), (x, -.25, 0.), (x, -.5, 0.), (x, -.75, 0.)]
    if support:
        if relaxed:
            points[4] = (-.27, -.02, 0.)  # Tucked thumb and one flexed finger.
            points[20] = (.3, .5, 0.)
        angle = math.radians(90 + tilt)
        points = [(facing * (x * math.cos(angle) - y * math.sin(angle)),
                   x * math.sin(angle) + y * math.cos(angle), z) for x, y, z in points]
    else:
        points[7], points[8], points[4] = (-.1, -.45, 0.), (.1, -.6, 0.), (-.05, -.6, 0.)
    hand = DisplayedHand(1, tuple((x * 60, y * 60) for x, y, _ in points), tuple(points))
    anchor = hand.palm if support else hand.pinch_point
    dx, dy = point[0] - anchor[0], point[1] - anchor[1]
    return replace(hand, points=tuple((x + dx, y + dy) for x, y in hand.points))


class Actions:
    def __init__(self, ball=False):
        self.calls = []
        self.ball = Box(130, 190, 40, 40) if ball else None

    def available(self): return True
    def hold_valid(self, mode): return True
    def body_rect(self): return Box(100, 100, 100, 200)
    def ball_rect(self): return self.ball
    def begin_hold(self, mode, point):
        self.calls.append(('begin', mode, point))
        return True
    def move_hold(self, mode, point): self.calls.append(('move', mode, point))
    def end_hold(self, reason, velocity): self.calls.append(('end', reason, velocity))
    def pet(self, *args): self.calls.append(('pet',))
    def poke(self, *args): self.calls.append(('poke',))


def feed(engine, hand, now, token=None):
    engine.update(() if hand is None else (hand,), now, now if token is None else token)


def acquire(engine, hand):
    for now in (1., 1.07, 1.14, 1.21):
        feed(engine, hand, now)


@pytest.mark.parametrize('facing', [-1, 1])
@pytest.mark.parametrize('tilt,relaxed', [(0., True), (45., False), (45., True)])
def test_support_accepts_both_sides_with_tilt_tucked_thumb_and_one_flexed_finger(facing, tilt, relaxed):
    hand = pose((150, 310), support=True, facing=facing, tilt=tilt, relaxed=relaxed)
    actions = Actions()
    engine = HandInteractionEngine(actions)
    acquire(engine, hand)
    assert engine.active == ('palm', 1)


def test_support_accepts_edge_contact_at_feet_without_requiring_center_overlap():
    hand = pose((150, 310), support=True)
    left, right = hand.support_span
    hand = pose((150 + (right - left) / 2 + 16, 310), support=True)
    engine = HandInteractionEngine(Actions())
    acquire(engine, hand)
    assert engine.active == ('palm', 1)


def test_support_tolerates_one_bad_pose_then_releases_after_confirmed_loss():
    actions = Actions()
    engine = HandInteractionEngine(actions)
    supporting = pose((150, 310), support=True)
    acquire(engine, supporting)
    unsupported = pose()
    feed(engine, unsupported, 1.25)
    assert engine.active == ('palm', 1)
    feed(engine, supporting, 1.30)
    assert actions.calls[-1] == ('move', 'palm', supporting.palm)
    for now in (1.35, 1.42, 1.55):
        feed(engine, unsupported, now)
    assert engine.active is None
    assert actions.calls[-1] == ('end', 'palm_closed', (0., 0.))


def test_support_still_requires_a_hand_below_the_feet_and_fresh_observations():
    for hand in (pose(), pose((150, 150), support=True)):
        engine = HandInteractionEngine(Actions())
        acquire(engine, hand)
        assert engine.active != ('palm', 1)
    engine = HandInteractionEngine(Actions())
    for now in (1., 1.1, 1.2, 1.3):
        feed(engine, pose((150, 310), support=True), now, token='frozen')
    assert engine.active is None


@pytest.mark.parametrize('step', [(80., -40.), (-80., -40.), (0., -80.), (80., 0.), (0., 80.)])
def test_fast_ball_swing_automatically_throws_in_the_measured_direction(step):
    actions = Actions(ball=True)
    engine = HandInteractionEngine(actions)
    acquire(engine, pose())
    assert engine.active == ('ball', 1)
    for index, now in enumerate((1.26, 1.31), 1):
        feed(engine, pose((150 + step[0] * index, 210 + step[1] * index)), now)
    assert engine.active is None
    event, reason, velocity = actions.calls[-1]
    assert (event, reason) == ('end', 'thrown')
    assert velocity == pytest.approx(tuple(value / .05 for value in step))


def test_slow_ball_motion_keeps_holding_and_a_reversed_spike_cannot_throw():
    actions = Actions(ball=True)
    engine = HandInteractionEngine(actions)
    acquire(engine, pose())
    for index in range(1, 6):
        feed(engine, pose((150 + index * 10, 210)), 1.21 + index * .05)
    feed(engine, pose((280, 210)), 1.51)
    feed(engine, pose((200, 210)), 1.56)
    assert engine.active == ('ball', 1)
    assert not [call for call in actions.calls if call[0] == 'end']


def test_repeated_packet_and_tracking_loss_cannot_complete_a_ball_throw():
    actions = Actions(ball=True)
    engine = HandInteractionEngine(actions)
    acquire(engine, pose())
    feed(engine, pose((230, 170)), 1.26, token='last-fresh')
    feed(engine, pose((310, 130)), 1.31, token='last-fresh')
    assert engine.active == ('ball', 1)
    feed(engine, None, 1.4)
    feed(engine, None, 2.1)
    assert actions.calls[-1] == ('end', 'tracking_lost', (0., 0.))


@pytest.fixture
def sandbox_ball():
    app = QApplication.instance() or QApplication([])
    character = SimpleNamespace(contact_feedback=Mock(), x=lambda: 100, y=lambda: 100,
        pos=lambda: QPoint(100, 100), _physics_body_rect=lambda: QRect(0, 0, 100, 200),
        _character_closing=False, isVisible=lambda: True, _manual_control_active=lambda: False,
        is_dragging=False, _mark_character_interaction=Mock())
    manager = SimpleNamespace(character_widget=character, screen_center_x=960,
        screen_left=0, screen_right=1920, screen_top=0, screen_bottom=1080,
        update_character_chase=Mock(), can_interact_with_ball=lambda ball: False)
    ball = BallWidget(manager)
    manager.ball = ball
    character.sandbox_manager = manager
    ball.physics_timer.stop()
    ball.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    ball.move(600, 400)
    ball.show()
    yield ball, CharacterHandActions(character)
    ball.hide()
    ball.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_swing_reaches_real_ball_physics_and_continues_upward_after_release(sandbox_ball):
    ball, actions = sandbox_ball
    engine = HandInteractionEngine(actions)
    acquire(engine, pose((622, 422)))
    assert engine.active == ('ball', 1) and ball.is_dragging
    feed(engine, pose((702, 382)), 1.26)
    feed(engine, pose((782, 342)), 1.31)
    assert engine.active is None and not ball.is_dragging
    assert (ball.x_velocity, ball.y_velocity) == pytest.approx((1600 * .016, -800 * .016))
    start = ball.pos()
    ball._update_physics()
    assert ball.x() > start.x() and ball.y() < start.y()


@pytest.mark.parametrize('reason', ['tracking_lost', 'disabled', 'mirror_changed'])
def test_cancelled_ball_hold_never_launches_with_a_stale_velocity(sandbox_ball, reason):
    ball, actions = sandbox_ball
    actions.begin_hold('ball', (622, 422))
    actions.end_hold(reason, (1600., -800.))
    assert not ball.is_dragging
    assert ball.x_velocity == ball.y_velocity == 0.
