"""Host jump arms rise, then return to the normal outward rest shape."""
import math

import pytest
from PyQt6.QtWidgets import QApplication

from character.rig_planner import RigPlanner
from character.rig_v8 import NodeRigPlanner


ARM_CHANNELS = ('armNear', 'armFar', 'elbowNear', 'elbowFar', 'wristNear', 'wristFar',
                'idleGesture', 'airArms')
ARM_GESTURES = ('thinkGesture', 'waveGesture', 'waveSideGesture', 'waveArmOffset',
                'waveElbowOffset', 'waveWristOffset', 'waveForearmShorten')
YAWS = (-65, -21.01, -21, 0, 21, 21.01, 65)


@pytest.fixture(scope='module')
def arm_planners():
    app = QApplication.instance() or QApplication([])
    qt, node = RigPlanner(), NodeRigPlanner()
    yield qt, node
    node.close()
    qt.engine.collectGarbage()
    assert app is QApplication.instance()


def sample_both(planners, state):
    qt, node = planners
    actual, expected = node.sample(state), qt.sample(state)
    assert actual['pose'] == pytest.approx(expected['pose'], abs=1e-10)
    assert actual['originalPose'] == pytest.approx(expected['originalPose'], abs=1e-10)
    assert actual['externalRootHeightAdjustment'] == pytest.approx(expected['externalRootHeightAdjustment'])
    return actual


def flight_state(phase, time=.8, yaw=0):
    return {'action': 'fall', 'time': time, 'yaw': yaw, 'externalPhysics': True,
            'jumpActive': True, 'jumpPhase': phase, 'authoredJump': True}


def projected_hands(pose, yaw=0):
    """Wrist endpoints submitted by the renderer, relative to each shoulder."""
    frontal = abs(yaw) <= 21
    orientation = -1 if yaw > 21 else 1
    hands = []
    for side, spread, elbow_extra, sign in [('Near', 29, 5, 1), ('Far', 33, 7, -1)]:
        arm, bend = pose['arm' + side], pose['elbow' + side]
        if frontal:
            arm -= spread * pose['idleGesture']
            bend += elbow_extra * pose['idleGesture']
            shoulder = arm + pose['lean'] if side == 'Near' else (2 * pose['airArms'] - 1) * arm + pose['lean']
            forearm = shoulder + sign * bend
        else:
            shoulder = orientation * arm + pose['lean']
            forearm = shoulder + orientation * bend
        hands.append((-38 * math.sin(math.radians(shoulder)) - 46 * math.sin(math.radians(forearm)),
                      38 * math.cos(math.radians(shoulder)) + 46 * math.cos(math.radians(forearm))))
    return hands


def assert_outward_front_hands(pose):
    near, far = projected_hands(pose)
    assert near[0] > 25 and far[0] < -25


def assert_normal_spread(pose):
    assert pose['idleGesture'] >= .9 and pose['airArms'] == 0
    assert_outward_front_hands(pose)
    assert all(55 < hand[1] < 82 for hand in projected_hands(pose))


@pytest.mark.parametrize('yaw', YAWS)
@pytest.mark.parametrize('phase', [.15, .70])
def test_takeoff_and_end_of_descent_match_normal_idle_arms(arm_planners, phase, yaw):
    pose = sample_both(arm_planners, flight_state(phase, yaw=yaw))['pose']
    rest = sample_both(arm_planners, {'action': 'idle', 'time': .8, 'yaw': yaw})['pose']
    for channel in ARM_CHANNELS:
        assert pose[channel] == rest[channel]
    expected = {**rest, 'lean': pose['lean']}
    for actual_hand, rest_hand in zip(projected_hands(pose, yaw), projected_hands(expected, yaw)):
        assert math.dist(actual_hand, rest_hand) < 1e-8
    if abs(yaw) <= 21:
        assert_normal_spread(pose)


@pytest.mark.parametrize('yaw', YAWS)
def test_apex_retains_original_raised_animated_pose(arm_planners, yaw):
    frame = sample_both(arm_planners, flight_state(.425, yaw=yaw))
    for channel in ARM_CHANNELS:
        assert frame['pose'][channel] == frame['originalPose'][channel]
    assert frame['pose']['armNear'] < -100 and frame['pose']['armFar'] > 100
    if abs(yaw) <= 21:
        assert all(hand[1] < 0 for hand in projected_hands(frame['pose'], yaw))


@pytest.mark.parametrize('yaw', YAWS)
def test_full_hand_path_rises_then_descends_continuously_to_rest(arm_planners, yaw):
    frames = [sample_both(arm_planners, flight_state(.15 + .55 * step / 110, yaw=yaw))['pose']
              for step in range(111)]
    hands = [projected_hands(pose, yaw) for pose in frames]
    # Numeric armFar changes convention at the endpoints; the visible geometry
    # must stay continuous in both coordinates, including the last descent frame.
    for before, after in zip(hands, hands[1:]):
        assert all(math.dist(a, b) < 9 for a, b in zip(before, after))
    assert frames[0]['armNear'] - frames[55]['armNear'] > 100
    assert frames[-1]['armNear'] - frames[55]['armNear'] > 100
    for side in range(2):
        assert math.dist(hands[0][side], hands[-1][side]) < 1
    if abs(yaw) <= 21:
        assert all(pair[0][0] > 25 and pair[1][0] < -25 for pair in hands)
        for side in range(2):
            assert hands[0][side][1] - hands[55][side][1] > 85
            assert hands[-1][side][1] - hands[55][side][1] > 85


@pytest.mark.parametrize('phase', [.15, .19, .425, .68, .70])
def test_arm_override_preserves_authored_root_feet_and_other_channels(arm_planners, phase):
    frame = sample_both(arm_planners, {**flight_state(phase), 'emotion': 'sad'})
    raw, pose = frame['originalPose'], frame['pose']
    height = 62 * raw['airborne']
    assert frame['externalRootHeightAdjustment'] == pytest.approx(height)
    for channel, original in raw.items():
        if channel in ARM_CHANNELS + ARM_GESTURES or channel == 'framingZoom':
            continue
        expected = original + height if channel in {'bodyY', 'footNearY', 'footFarY'} else original
        assert pose[channel] == pytest.approx(expected)


@pytest.mark.parametrize('stamp', [0, .12, .24, .40, .65, 1.5])
def test_landing_keeps_normal_spread_while_body_compresses(arm_planners, stamp):
    frame = sample_both(arm_planners, {'action': 'land', 'time': stamp,
                                     'externalPhysics': True, 'authoredJump': True})
    assert_normal_spread(frame['pose'])
    rest = sample_both(arm_planners, {'action': 'idle', 'time': stamp})['pose']
    for channel in ARM_CHANNELS:
        assert frame['pose'][channel] == rest[channel]
    for channel, original in frame['originalPose'].items():
        if channel not in ARM_CHANNELS + ARM_GESTURES and channel != 'framingZoom':
            assert frame['pose'][channel] == original


def test_rest_endpoint_breathing_uses_host_time_instead_of_physics_phase(arm_planners):
    first = sample_both(arm_planners, flight_state(.15, time=.2))['pose']
    late = sample_both(arm_planners, flight_state(.70, time=.2))['pose']
    breathing = sample_both(arm_planners, flight_state(.70, time=1.2))['pose']
    for channel in ARM_CHANNELS:
        assert first[channel] == late[channel]
    assert breathing['armNear'] != late['armNear']
    assert abs(breathing['armNear'] - late['armNear']) < 3


@pytest.mark.parametrize('prior_action', ['idle', 'walk', 'thinking', 'wave'])
def test_smoothed_previous_gesture_jump_landing_idle_has_motion_without_collapse(arm_planners, prior_action):
    for step in range(90):
        sample_both(arm_planners, {'action': prior_action, 'time': step / 60,
                                   'externalPhysics': True, 'smooth': True, 'dt': 1 / 60})
    states = [flight_state(.15 + .55 * step / 110, time=step / 60) for step in range(111)]
    states += [{'action': 'land', 'time': step / 60, 'authoredJump': True} for step in range(30)]
    states += [{'action': 'idle', 'time': step / 60} for step in range(30)]
    previous, near_angles = None, []
    for state in states:
        pose = sample_both(arm_planners, {**state, 'externalPhysics': True,
                                        'smooth': True, 'dt': 1 / 60})['pose']
        assert_outward_front_hands(pose)
        assert all(pose[channel] == 0 for channel in ARM_GESTURES)
        if state['action'] in {'land', 'idle'} or state.get('jumpPhase') in {.15, .70}:
            assert_normal_spread(pose)
        near_angles.append(pose['armNear'])
        hands = projected_hands(pose)
        if previous is not None:
            assert all(math.dist(before, after) < 9 for before, after in zip(previous, hands))
        previous = hands
    assert max(near_angles) - min(near_angles) > 100


def test_walk_blend_option_cannot_collapse_rest_endpoint(arm_planners):
    frame = sample_both(arm_planners, {**flight_state(.15), 'walkAmount': 1})
    assert_normal_spread(frame['pose'])


@pytest.mark.parametrize('phase', [.15, .425, .70])
def test_standalone_authored_jump_keeps_original_motion(arm_planners, phase):
    frame = sample_both(arm_planners, {'action': 'jump', 'time': phase * 2.4})
    assert frame['pose'] == frame['originalPose']
    assert frame['pose']['idleGesture'] == 0 and frame['pose']['airArms'] == 1
    if phase == .425:
        assert frame['pose']['armNear'] < -100 and frame['pose']['armFar'] > 100


@pytest.mark.parametrize('action', ['fall', 'hovering', 'wave', 'thinking', 'idle'])
def test_uncontrolled_fall_and_other_gestures_keep_original_arms(arm_planners, action):
    frame = sample_both(arm_planners, {'action': action, 'time': .8, 'externalPhysics': True})
    for channel in ARM_CHANNELS + ARM_GESTURES:
        assert frame['pose'][channel] == frame['originalPose'][channel]
