"""Both scissors poses pass the shared classifier and the game's stable input."""
from copy import deepcopy
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / 'medeapipe_capstone'))
from recognition import holistic_tracker as core
from character.rps_game import HandTracker, judge


def hand(pose='thumb-index', *, scale=1., angle=0., mirror=False):
    points = [
        (0, 0), (-18, -10), (-40, -23), (-65, -35), (-92, -47),
        (-25, -50), (-25, -85), (-25, -110), (-25, -135),
        (0, -55), (0, -80), (12, -70), (10, -45),
        (25, -50), (25, -75), (37, -65), (35, -40),
        (45, -40), (45, -65), (57, -55), (55, -30),
    ]
    if pose in ('index-only', 'index-middle', 'rock'):
        points[1:5] = [(-18, -10), (-32, -25), (-14, -44), (2, -38)]
    if pose in ('index-middle', 'paper'):
        points[9:13] = [(0, -55), (0, -90), (0, -115), (0, -145)]
    if pose in ('rock', 'thumb-only'):
        points[5:9] = [(-25, -50), (-25, -75), (-13, -65), (-15, -40)]
    if pose in ('paper', 'extra-ring'):
        points[13:17] = [(25, -50), (25, -85), (25, -110), (25, -130)]
    if pose in ('paper', 'extra-pinky'):
        points[17:21] = [(45, -40), (45, -70), (45, -95), (45, -115)]
    if pose == 'pinch':
        points[4] = (-25, -135)
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    records = []
    for name, (x, y) in zip(core.HAND_LANDMARK_NAMES, points):
        x = -x if mirror else x
        records.append({'name': name,
                        'pixel_x': 320 + scale * (x * cosine - y * sine),
                        'pixel_y': 240 + scale * (x * sine + y * cosine)})
    return records


@pytest.mark.parametrize('pose', ['thumb-index', 'index-middle'])
@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('scale', [.45, 1., 2.2])
@pytest.mark.parametrize('angle', [-25., 0., 25.])
def test_both_scissors_poses_allow_left_right_hands_size_and_tilt(pose, mirror, scale, angle):
    assert core.analyze_rps_hand_state(hand(pose, mirror=mirror, scale=scale, angle=angle))['state'] == 'SCISSORS'


@pytest.mark.parametrize('pose,expected', [
    ('index-only', 'NONE'), ('thumb-only', 'ROCK'), ('rock', 'ROCK'),
    ('paper', 'PAPER'), ('extra-ring', 'NONE'), ('extra-pinky', 'NONE'), ('pinch', 'NONE'),
])
def test_other_poses_do_not_turn_into_the_new_scissors_pose(pose, expected):
    assert core.analyze_rps_hand_state(hand(pose))['state'] == expected


@pytest.mark.parametrize('missing', core.HAND_LANDMARK_NAMES)
def test_incomplete_hand_cannot_confirm_thumb_index_scissors(missing):
    records = [record for record in hand() if record['name'] != missing]
    assert core.analyze_rps_hand_state(records)['state'] != 'SCISSORS'


@pytest.mark.parametrize('invalid', [float('nan'), float('inf')])
@pytest.mark.parametrize('landmark', ['THUMB_MCP', 'THUMB_IP', 'THUMB_TIP', 'PINKY_MCP'])
def test_invalid_thumb_or_palm_coordinates_cannot_confirm_the_new_pose(invalid, landmark):
    records = hand()
    core.records_by_name(records)[landmark]['pixel_x'] = invalid
    assert core.analyze_rps_hand_state(records)['state'] != 'SCISSORS'


def test_pose_analysis_preserves_the_source_landmarks_and_existing_finger_schema():
    records = hand()
    before = deepcopy(records)
    result = core.analyze_rps_hand_state(records)
    assert records == before
    assert result['extended_fingers'] == {'index': True, 'middle': False, 'ring': False, 'pinky': False}
    assert core.analyze_rps_hand_state([])['state'] == 'NONE'
    assert core.disabled_rps_state()['state'] == 'OFF'


@pytest.mark.parametrize('side', ['left', 'right'])
@pytest.mark.parametrize('pose', ['thumb-index', 'index-middle'])
def test_landmark_frame_builder_delivers_both_scissors_poses_to_the_real_game_tracker(side, pose):
    records = hand(pose, mirror=side == 'right')
    landmarks = SimpleNamespace(landmark=[SimpleNamespace(x=point['pixel_x'] / 640,
        y=point['pixel_y'] / 480, z=0.) for point in records])
    results = SimpleNamespace(face_landmarks=None, pose_landmarks=None,
        left_hand_landmarks=landmarks if side == 'left' else None,
        right_hand_landmarks=landmarks if side == 'right' else None)
    tracker = HandTracker('thumb-index-game', 100.)
    for index, stamp in enumerate((100., 100.25)):
        frame = core.build_frame_record(index, int(stamp * 1000), 640, 480, results, False, True)
        payload = {'rps_game': {'session': 'thumb-index-game', 'captured_at': stamp,
            'hands': {name: gesture['state'] for name, gesture in frame['hand_gestures'].items()}}}
        assert tracker.feed(payload, stamp)
    assert tracker.stable_hand(100.25) == 'SCISSORS'
    assert judge(tracker.stable_hand(100.25), 'PAPER') == '당신의 승리!'
    disabled = core.build_frame_record(3, 101000, 640, 480, results, False, False)
    assert all(gesture['state'] == 'OFF' for gesture in disabled['hand_gestures'].values())
