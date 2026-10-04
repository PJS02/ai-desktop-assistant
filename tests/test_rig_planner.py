"""Math/transport parity without a browser, GL context, or host integration."""
from array import array
import hashlib
import time

import pytest
from PyQt6.QtCore import QCoreApplication

from character.rig_planner import RigPlanner, RIG_SOURCES
from character.rig_v8 import NodeRigPlanner


YAWS = (-65, 0, 65)
ACTIONS = ('idle', 'walk', 'wave', 'thinking', 'sleep', 'hovering', 'jump', 'fall', 'land')
EMOTIONS = ('neutral', 'happy', 'excited', 'proud', 'relieved', 'calm', 'anxious',
            'hurt', 'displeased', 'distressed', 'sad', 'depressed', 'tired', 'angry', 'scared')


@pytest.fixture(scope='module')
def planners():
    app = QCoreApplication.instance() or QCoreApplication([])
    qt = RigPlanner()
    node = NodeRigPlanner()
    yield qt, node
    node.close()
    qt.engine.collectGarbage()
    # Keep the application alive until both engines have finished.
    assert app is QCoreApplication.instance()


def _assert_close(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _assert_close(actual[key], expected[key])
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            _assert_close(a, b)
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        assert actual == pytest.approx(expected, rel=0, abs=1e-10)
    else:
        assert actual == expected


def _assert_plan_parity(qt, node, state):
    before, after = qt.plan(state), node.plan(state)
    _assert_close({key: value for key, value in before.items() if key != 'commands'},
                  {key: value for key, value in after.items() if key != 'commands'})
    assert len(before['commands']) == len(after['commands'])
    floats = 0
    for original, native in zip(before['commands'], after['commands']):
        encoded = array('f', original['vertices']).tobytes()
        assert bytes(native['vertexBytes']) == encoded
        assert len(encoded) == native['vertexCount'] * native['stride'] * 4
        _assert_close({key: value for key, value in original.items() if key != 'vertices'},
                      {key: value for key, value in native.items() if key != 'vertexBytes'})
        floats += len(original['vertices'])
    assert floats > 0
    assert all(node.texture_metadata(name) for name in after['requiredTextures'])
    return floats


@pytest.mark.parametrize('yaw', YAWS)
@pytest.mark.parametrize('action', ACTIONS)
def test_original_meshes_and_materials_match_for_actions(planners, yaw, action):
    qt, node = planners
    action_times = {'wave': .76, 'jump': 1.02, 'land': .18}
    _assert_plan_parity(qt, node, {'action': action, 'time': action_times.get(action, .63),
                                 'yaw': yaw, 'companion': False})


@pytest.mark.parametrize('yaw', YAWS)
@pytest.mark.parametrize('emotion', EMOTIONS)
@pytest.mark.parametrize('speaking', (False, True))
def test_original_emotion_and_speech_plans_match(planners, yaw, emotion, speaking):
    qt, node = planners
    _assert_plan_parity(qt, node, {'action': 'idle', 'time': .76, 'yaw': yaw,
                                 'emotion': emotion, 'speaking': speaking,
                                 'speechTime': .41, 'blink': .65, 'companion': False})


@pytest.mark.parametrize('action', ('idle', 'jump', 'fall', 'hovering'))
def test_external_root_height_requires_explicit_flag(planners, action):
    qt, node = planners
    state = {'action': action, 'time': 1.02, 'yaw': 0}
    original = node.sample(state)
    assert original['externalRootHeightAdjustment'] == 0
    assert original['pose'] == original['originalPose']
    override = node.sample({**state, 'externalPhysics': True})
    _assert_close(override, qt.sample({**state, 'externalPhysics': True}))
    expected_adjustment = {'idle': 0, 'jump': 62 * original['pose']['airborne'],
                           'fall': 29, 'hovering': 24}[action]
    assert override['externalRootHeightAdjustment'] == pytest.approx(expected_adjustment)
    assert override['pose']['bodyY'] == pytest.approx(original['pose']['bodyY'] + expected_adjustment)
    for key, value in original['pose'].items():
        if key != 'bodyY':
            assert override['pose'][key] == value


def test_original_effect_recipes_and_source_identities_match(planners):
    qt, node = planners
    _assert_close(qt.effect_recipes(), node.effect_recipes())
    assert qt.effect_metadata() == node.effect_metadata()
    assert len(node.effect_recipes()) == 20
    for source in RIG_SOURCES:
        expected = hashlib.sha256((node.rig_root / source).read_bytes()).hexdigest()
        assert qt.source_hashes[source] == node.source_hashes[source] == expected


def test_planning_preserves_every_original_source_and_image_byte(planners):
    _, node = planners
    paths = {node.rig_root / relative for relative in RIG_SOURCES}
    paths.update(node.rig_root / part['file'].split('?')[0] for part in node.parts.values())
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
    for yaw in YAWS:
        node.plan({'action': 'wave', 'yaw': yaw, 'time': 1.25, 'emotion': 'anxious',
                   'speaking': True, 'speechTime': .6})
    after = {path: hashlib.sha256(path.read_bytes()).digest() for path in paths}
    assert before == after


def test_worker_uses_configured_heap_limit_and_stays_usable(planners):
    _, node = planners
    assert '--max-old-space-size=64' in node.process.args
    assert '--max-semi-space-size=4' in node.process.args
    for index in range(45):
        node.plan({'action': 'wave', 'yaw': YAWS[index % 3], 'time': index / 30,
                   'emotion': EMOTIONS[index % len(EMOTIONS)],
                   'speaking': bool(index % 2), 'speechTime': index / 30})
    stats = node.stats()
    assert stats['heapUsed'] > 0 and stats['rss'] > 0
    assert node.process.poll() is None


def test_close_stops_worker_and_reader_and_rejects_reuse():
    node = NodeRigPlanner()
    node.plan({'action': 'idle', 'time': .2})
    node.close()
    node.close()
    assert node.process.poll() is not None
    assert not node._reader.is_alive()
    assert node.process.stdin.closed and node.process.stdout.closed
    with pytest.raises(RuntimeError, match='closed'):
        node.plan({'action': 'idle'})


def test_worker_crash_is_reported_and_cleanup_is_safe():
    node = NodeRigPlanner()
    node.process.kill()
    node.process.wait(timeout=2)
    started = time.perf_counter()
    try:
        with pytest.raises(RuntimeError):
            node.plan({'action': 'idle'})
    finally:
        node.close()
    assert time.perf_counter() - started < 6
    assert not node._reader.is_alive()


def test_request_timeout_cannot_feed_a_late_plan_to_the_next_state():
    node = NodeRigPlanner()
    try:
        with pytest.raises(RuntimeError, match='respond'):
            node._request({'op': 'plan', 'state': {'action': 'wave', 'yaw': -65, 'time': .76}},
                          timeout=0)
        assert node._closed
        assert node.process.poll() is not None
        with pytest.raises(RuntimeError, match='closed'):
            node.sample({'action': 'walk', 'time': .12})
    finally:
        node.close()
