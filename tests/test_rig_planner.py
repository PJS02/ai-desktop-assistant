"""Math/transport parity without a browser, GL context, or host integration."""
from array import array
import hashlib
import json
import time

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QImage
from PIL import Image

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
    effects = node.effect_recipes()
    assert not any(name.startswith('fx_tear') for name in effects)
    for source in RIG_SOURCES:
        expected = hashlib.sha256((node.rig_root / source).read_bytes()).hexdigest()
        assert qt.source_hashes[source] == node.source_hashes[source] == expected


@pytest.mark.parametrize('action', ('jump', 'fall'))
def test_host_jump_has_no_panic_flapping_or_second_jump_trajectory(planners, action):
    qt, node = planners
    near_angles = []
    for time_step in range(121):
        stamp = time_step / 60
        state = {'action': action, 'time': stamp, 'externalPhysics': True,
                 'jumpActive': True, 'emotion': 'happy'}
        frame = node.sample(state)
        _assert_close(frame, qt.sample(state))
        rest = node.sample({'action': 'idle', 'time': stamp, 'emotion': 'happy'})
        # Qt moves the entire host; the rig must not pin feet to a separate
        # authored trajectory or alternate raised panic arms while descending.
        assert frame['pose']['bodyY'] == rest['pose']['bodyY']
        assert frame['pose']['footNearY'] == frame['pose']['footFarY'] == 0
        assert frame['pose']['idleGesture'] >= .9
        assert frame['pose']['airArms'] == 0
        assert frame['pose']['framingZoom'] == 1
        near_angles.append(frame['pose']['armNear'])
    assert max(near_angles) - min(near_angles) < 3


def test_host_landing_keeps_relaxed_arms_through_smooth_transitions(planners):
    qt, node = planners
    for action, active in [('idle', False), ('jump', True), ('fall', True),
                           ('land', False), ('idle', False)]:
        for step in range(100):
            state = {'action': action, 'time': step / 60, 'emotion': 'neutral',
                     'externalPhysics': True, 'jumpActive': active, 'smooth': True, 'dt': 1 / 60}
            frame = node.sample(state)
            _assert_close(frame, qt.sample(state))
            if action != 'idle' or step > 60:
                assert frame['pose']['idleGesture'] > .85
                assert frame['pose']['airArms'] < .01


@pytest.mark.parametrize('yaw', YAWS)
def test_controlled_jump_and_landing_geometry_matches_both_engines(planners, yaw):
    qt, node = planners
    for action in ('jump', 'fall', 'land'):
        _assert_plan_parity(qt, node, {'action': action, 'time': .3, 'yaw': yaw,
                                     'externalPhysics': True, 'jumpActive': action != 'land'})


def test_source_rectangle_reuses_existing_uvs_and_face_geometry(planners):
    qt, _ = planners
    result = qt._evaluate("""
      (function(){
        var meshes=[],gl={bufferData:function(_,data){meshes.push(Array.from(data));}};
        ['uniform1f','uniform3f','uniform2f','activeTexture','bindTexture','bindBuffer',
         'enableVertexAttribArray','vertexAttribPointer','drawArrays'].forEach(function(name){gl[name]=function(){};});
        var recorder={gl:gl,parts:{art:{bbox:[20,30,100,150]}},textures:{art:{}},viewZoom:1};
        var map=function(p){return {x:p.x+.006*(p.y-30)*(p.y-30),
          y:p.y+.005*(p.x-20)*(p.x-20)};};
        CloudyRenderer.prototype.mesh.call(recorder,'art',map,1,5,7);
        CloudyRenderer.prototype.mesh.call(recorder,'art',map,1,5,7,
          null,0,null,null,null,[44,67,38,53]);
        return JSON.stringify(meshes);
      })()
    """, 'source-rectangle-geometry')
    full, cropped = json.loads(result.toString())
    original = [[full[offset + i:offset + i + 4] for i in (0, 4, 8)]
                for offset in range(0, len(full), 12)]
    vertices = [cropped[offset:offset + 4] for offset in range(0, len(cropped), 4)]
    assert vertices
    for x, y, u, v in vertices:
        assert .24 - 1e-6 <= u <= .62 + 1e-6
        assert 37 / 150 - 1e-6 <= v <= .6 + 1e-6
        found = False
        for a, b, c in original:
            denominator = ((b[3] - c[3]) * (a[2] - c[2])
                           + (c[2] - b[2]) * (a[3] - c[3]))
            wa = ((b[3] - c[3]) * (u - c[2]) + (c[2] - b[2]) * (v - c[3])) / denominator
            wb = ((c[3] - a[3]) * (u - c[2]) + (a[2] - c[2]) * (v - c[3])) / denominator
            wc = 1 - wa - wb
            if min(wa, wb, wc) >= -1e-5:
                expected = (wa * a[0] + wb * b[0] + wc * c[0],
                            wa * a[1] + wb * b[1] + wc * c[1])
                if (x, y) == pytest.approx(expected, rel=0, abs=1e-4):
                    found = True
                    break
        assert found, 'A cut vertex moved away from its original face triangle'
    area = 0
    for offset in range(0, len(vertices), 3):
        a, b, c = vertices[offset:offset + 3]
        area += abs((b[2] - a[2]) * (c[3] - a[3])
                    - (c[2] - a[2]) * (b[3] - a[3])) / 2
    assert area == pytest.approx(38 / 100 * 53 / 150, rel=0, abs=1e-6)


@pytest.mark.parametrize('emotion,below_lip', (('happy', 253), ('distressed', 247)))
@pytest.mark.parametrize('speaking', (False, True))
def test_right_jaw_cleanup_keeps_the_authored_lip_and_its_white_rim(planners, emotion, below_lip, speaking):
    qt, _ = planners
    expression = 'expr' + emotion.capitalize()
    setup = json.dumps({'expression': expression, 'speaking': speaking, 'emotion': emotion})
    result = qt._evaluate("""
      (function(config){
        var calls=[],renderer={parts:CLOUDY_PARTS,textures:{},viewZoom:1,
          bodyPoint:function(p){return p;},mesh:function(name,map,alpha,cols,rows,
          replacement,amount,base,blend,clip,rect){calls.push({name:name,rect:rect||null});}};
        Object.keys(CLOUDY_PARTS).forEach(function(name){renderer.textures[name]={};});
        var pose={lean:0,headAngle:0,blink:0,mouthOpen:.7,speaking:config.speaking?1:0};
        pose[config.expression]=1;
        var prior=CloudyEmotionFX;CloudyEmotionFX=null;
        try{CloudyRenderer.prototype.face.call(renderer,CloudyRig.views[6],pose,1,.76);}
        finally{CloudyEmotionFX=prior;}
        return JSON.stringify(calls);
      })(CONFIG)
    """.replace('CONFIG', setup), 'right-jaw-lip-coverage')
    calls = json.loads(result.toString())
    base = 'right_00_espeech_happy' if emotion == 'happy' and speaking else 'right_00_russell_' + emotion
    if emotion == 'distressed' and speaking:
        assert not any(call['rect'] for call in calls)
        return
    normal = 'right_00_russell_talk_' + emotion
    original_regions = [call['rect'] for call in calls if call['name'] == base and call['rect']]
    replacement_regions = [call['rect'] for call in calls if call['name'] == normal and call['rect']]
    assert len(original_regions) == len(replacement_regions) == 2
    # Bounds include the pink lip, original white outline and alpha sampling
    # gutter. Every part of that rectangle keeps the original material.
    lip = (237, 230, 263, 252) if emotion == 'happy' else (236, 229, 263, 246)
    def intersects(rect, bounds):
        x, y, width, height = rect
        return x < bounds[2] and x + width > bounds[0] and y < bounds[3] and y + height > bounds[1]
    assert not any(intersects(rect, lip) for rect in replacement_regions)
    assert any(rect[1] == below_lip for rect in replacement_regions)
    assert sum(rect[2] * rect[3] for rect in original_regions + replacement_regions) == 286 * 309


def test_all_painted_tear_frames_are_real_alpha_pngs_loaded_identically_by_qt(planners):
    qt, node = planners
    expected = {f'fx_tear_{direction}_{eye}_{stage}'
                for direction in ('front', 'left', 'right')
                for eye in (0, 1) for stage in range(6)}
    actual = {name for name, part in node.parts.items() if part.get('drawnTearFrame')}
    assert actual == expected
    pixels_seen = set()
    for name in sorted(expected):
        part = node.texture_metadata(name)
        assert part == qt.texture_metadata(name)
        assert part['size'] == [256, 512]
        assert part['bbox'][2] / part['size'][0] == pytest.approx(
            part['bbox'][3] / part['size'][1], abs=1e-12)
        assert part['file'].split('?')[0].endswith('.png')
        path = node.rig_root / part['file'].split('?')[0]
        assert path.is_file()
        with Image.open(path) as bitmap:
            assert bitmap.format == 'PNG'
            assert bitmap.mode == 'RGBA'
            assert list(bitmap.size) == part['size']
            alpha = bitmap.getchannel('A')
            assert alpha.getextrema()[0] == 0
            assert alpha.getextrema()[1] > 128
            assert alpha.histogram()[0] > bitmap.width * bitmap.height / 2
            raw = bitmap.tobytes()
        image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
        assert not image.isNull()
        pointer = image.constBits()
        pointer.setsize(image.sizeInBytes())
        assert bytes(pointer) == raw
        pixels_seen.add(hashlib.sha256(raw).digest())
    # Thirty-six authored cells remain separate images rather than aliases to
    # a single stretched tear picture.
    assert len(pixels_seen) == 36


@pytest.mark.parametrize('yaw', YAWS)
@pytest.mark.parametrize('emotion', ('sad', 'hurt'))
def test_crying_draws_registered_png_frames_with_original_math_parity(planners, yaw, emotion):
    qt, node = planners
    state = {'action': 'idle', 'time': 2.4, 'yaw': yaw, 'emotion': emotion,
             'blink': 0, 'speaking': True, 'speechTime': .6, 'companion': False}
    _assert_plan_parity(qt, node, state)
    plan = node.plan(state)
    names = set(plan['requiredTextures'])
    tears = {name for name in names if name.startswith('fx_tear')}
    assert tears
    assert all(node.texture_metadata(name).get('drawnTearFrame') for name in tears)
    assert not tears & node.effect_recipes().keys()


def test_painted_tear_cycle_changes_images_without_stretching_their_mesh(planners):
    qt, _ = planners
    # Hold the face mapping fixed while time advances through every painted
    # phase. Breathing/head movement belongs to the existing face rig and is
    # intentionally excluded from this test of the tear's own deformation.
    result = qt._evaluate("""
      (function(){
        var rows=[];
        ['front','left','right'].forEach(function(direction){
          for(var step=1;step<100;step++){
            var t=step/100*4.3;
            var recorder={parts:CLOUDY_PARTS,mesh:function(name,map,alpha){
              if(name.indexOf('fx_tear_')!==0)return;
              var p=this.parts[name],b=p.bbox;
              rows.push({name:name,alpha:alpha,bbox:b,
                corners:[[b[0],b[1]],[b[0]+b[2],b[1]],
                         [b[0],b[1]+b[3]],[b[0]+b[2],b[1]+b[3]]]
                  .map(function(v){return map({x:v[0],y:v[1]});})});
            }};
            CloudyEmotionFX.draw(recorder,{prefix:direction,head:[0]},
              {exprSad:1},t,function(p){return p;},1);
          }
        });
        return JSON.stringify(rows);
      })()
    """, 'painted-tear-mesh-invariance')
    rows = json.loads(result.toString())
    assert rows
    seen = set()
    for row in rows:
        seen.add(row['name'])
        x, y, width, height = row['bbox']
        assert row['corners'] == [{'x': x, 'y': y}, {'x': x + width, 'y': y},
                                  {'x': x, 'y': y + height},
                                  {'x': x + width, 'y': y + height}]
        assert 0 <= row['alpha'] <= 1
    assert len(seen) == 36


def test_gathered_eye_pools_stay_visible_across_the_cycle_wrap(planners):
    qt, _ = planners
    result = qt._evaluate("""
      (function(){
        var rows=[];
        [4.3,4.77,6.8].forEach(function(period){
          [0,.43].forEach(function(offset){
            for(var step=0;step<=200;step++){
              var sample=CloudyEmotionFX.samplePaintedTear(step/100*period,period,offset);
              rows.push(sample);
            }
          });
        });
        return JSON.stringify(rows);
      })()
    """, 'gathered-pool-cycle-wrap')
    rows = json.loads(result.toString())
    assert rows
    assert any(row['frame'] == 5 and row['nextFrame'] == 0 for row in rows)
    for row in rows:
        assert row['alpha'] == 1
        assert 0 <= row['mix'] <= 1
        assert 0 <= row['frame'] < 6 and 0 <= row['nextFrame'] < 6
        # The outgoing and incoming separately painted pools are never
        # jointly faded away at the reset boundary.
        assert (1 - row['mix']) * row['alpha'] + row['mix'] * row['alpha'] == pytest.approx(1)


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
