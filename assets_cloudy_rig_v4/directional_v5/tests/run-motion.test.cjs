'use strict';

// Run from the repository root:
// node --test assets_cloudy_rig_v4/directional_v5/tests/run-motion.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../motion.js');

const motionKeys = [
  'bodyX', 'bodyY', 'lean', 'headAngle',
  'armNear', 'elbowNear', 'wristNear', 'armFar', 'elbowFar', 'wristFar',
  'footNearX', 'footNearY', 'footNearAngle',
  'footFarX', 'footFarY', 'footFarAngle', 'airborne'
];

function close(actual, expected, message, tolerance = 1e-9) {
  assert.ok(Number.isFinite(actual), `${message}: ${actual} must be finite`);
  assert.ok(Math.abs(actual - expected) <= tolerance,
    `${message}: expected ${expected}, received ${actual}`);
}

test('run profile describes its complete 60 fps cycle and stance travel speed', () => {
  assert.equal(M.runProfile.duration, .8);
  assert.equal(M.runProfile.stride, 56);
  assert.equal(M.runProfile.stance, .34);
  assert.equal(M.runProfile.lift, 38);
  assert.equal(M.runProfile.fps, 60);
  assert.equal(M.runProfile.frameCount, 48);
  close(M.runProfile.frameCount / M.runProfile.fps, M.runProfile.duration, 'sheet duration');
  close(M.runProfile.speed, 56 / (.8 * .34), 'stance speed');
});

test('run feet have a shorter grounded stance, a lifted swing, and normalized phases', () => {
  const {stride, lift, stance} = M.runProfile;
  for (const phase of [0, .05, .17, stance - 1e-6]) {
    const foot = M.runGait(phase);
    assert.equal(foot.stance, true, `stance at ${phase}`);
    close(foot.x, stride * (-.5 + phase / stance), `stance x at ${phase}`);
    close(foot.y, 0, `planted y at ${phase}`);
    close(foot.angle, 0, `planted shoe angle at ${phase}`);
  }
  const apex = M.runGait(stance + (1 - stance) / 2);
  assert.equal(apex.stance, false);
  close(apex.y, -lift, 'swing clearance');
  for (const phase of [-2.23, -.01, 0, .42, 1, 7.81]) {
    const a = M.runGait(phase), b = M.runGait(phase + 3);
    for (const key of ['x', 'y', 'angle', 'phase']) close(a[key], b[key], `${key} wraps at ${phase}`);
    assert.equal(a.stance, b.stance);
    assert.ok(a.phase >= 0 && a.phase < 1);
  }
});

test('running joins the ground and wraps the loop with continuous positions and velocities', () => {
  const epsilon = 1e-7;
  for (const join of [M.runProfile.stance, 1]) {
    const before = M.runGait(join - epsilon), at = M.runGait(join), after = M.runGait(join + epsilon);
    for (const key of ['x', 'y', 'angle']) {
      close(before[key], at[key], `${key} before join ${join}`, 3e-5);
      close(after[key], at[key], `${key} after join ${join}`, 3e-5);
      const leftVelocity = (at[key] - before[key]) / epsilon;
      const rightVelocity = (after[key] - at[key]) / epsilon;
      close(leftVelocity, rightVelocity, `${key} velocity at ${join}`, .002);
    }
    close((after.x - before.x) / (2 * epsilon),
      M.runProfile.stride / M.runProfile.stance, `ground velocity at ${join}`, .002);
  }
});

test('run travel speed cancels the planted-foot motion over a real time interval', () => {
  const start = .05, end = .25, {duration, speed} = M.runProfile;
  const a = M.runGait(start), b = M.runGait(end);
  const travelled = speed * (end - start) * duration;
  close(b.x - a.x - travelled, 0, 'world-space planted foot displacement');
});

test('the run has two actual flight windows while each stance shoe stays grounded', () => {
  const duration = M.runProfile.duration;
  for (const phase of [.1, .2]) {
    const p = M.pose('run', phase * duration);
    close(p.footNearY, 0, `near shoe on ground at ${phase}`);
    close(p.airborne, 0, `grounded body at ${phase}`);
    assert.ok(p.footFarY < 0, 'opposite foot swings above ground');
  }
  for (const phase of [.6, .7]) {
    const p = M.pose('run', phase * duration);
    close(p.footFarY, 0, `far shoe on ground at ${phase}`);
    close(p.airborne, 0, `grounded body at ${phase}`);
    assert.ok(p.footNearY < 0);
  }
  for (const phase of [.42, .92]) {
    const p = M.pose('run', phase * duration);
    assert.ok(p.airborne > 0, `flight cue at ${phase}`);
    assert.ok(p.footNearY < 0 && p.footFarY < 0, `both shoes clear ground at ${phase}`);
    close(p.airArms, 0, 'running preserves arm projection');
    close(p.framingZoom, 1, 'running uses a fixed full-size framing');
  }
});

test('running repeats its body, head and limb cycle without carrying the breathing clock', () => {
  for (const time of [0, .057, .153, .336, .591, .792]) {
    const a = M.pose('run', time), b = M.pose('run', time + M.runProfile.duration);
    assert.deepEqual(Object.keys(a).sort(), Object.keys(b).sort());
    for (const key of Object.keys(a)) {
      if (['blink', 'mouthOpen', 'speaking'].includes(key)) continue;
      close(a[key], b[key], `${key} repeats at ${time}`, 1e-8);
    }
  }
});

test('runAmount suppresses or blends the running action without activating walking', () => {
  const time = .336;
  const stopped = M.pose('run', time, {runAmount: 0});
  const half = M.pose('run', time, {runAmount: .5});
  const full = M.pose('run', time);
  for (const suffix of ['Near', 'Far']) {
    for (const field of ['X', 'Y', 'Angle']) close(stopped[`foot${suffix}${field}`], 0, `stopped ${suffix} ${field}`);
  }
  close(stopped.airborne, 0, 'suppressed flight');
  close(stopped.runGesture || 0, 0, 'suppressed run projection');
  assert.ok(full.runGesture > 0, 'full running enables its arm projection');
  for (const key of motionKeys) close(half[key], (stopped[key] + full[key]) / 2, `half run ${key}`);
});

test('face and speech layers preserve the sampled run motion', () => {
  const time = .336, base = M.pose('run', time);
  for (const emotion of ['happy', 'sad', 'angry', 'scared']) {
    const p = M.pose('run', time, {emotion});
    const expression = 'expr' + emotion[0].toUpperCase() + emotion.slice(1);
    assert.equal(p[expression], 1);
    for (const key of motionKeys) close(p[key], base[key], `${emotion} leaves ${key} intact`);
    const speaking = M.pose('run', time, {emotion, speaking: true, speechTime: .2});
    assert.equal(speaking.speaking, 1);
    assert.ok(speaking.mouthOpen > 0 && speaking.mouthOpen <= 1);
    assert.equal(speaking[expression], 1);
    for (const key of motionKeys) close(speaking[key], p[key], `speech leaves ${key} intact`);
    const named = M.pose(`run_${emotion}`, time);
    assert.equal(named[expression], 1, `named run ${emotion}`);
    for (const key of ['footNearX', 'footNearY', 'footFarX', 'footFarY'])
      close(named[key], base[key], `named ${emotion} leaves ${key} intact`);
  }
});

test('every frame and interpolated sample has finite values and a valid solved leg chain', () => {
  for (let frame = 0; frame <= 960; frame++) {
    const time = frame / 600;
    const p = M.pose('run', time);
    for (const [key, value] of Object.entries(p)) assert.ok(Number.isFinite(value), `${key} at ${time}`);
    for (const suffix of ['Near', 'Far']) {
      assert.ok(p[`foot${suffix}Y`] <= 1e-9, 'feet stay on or above ground');
      const hip = {x: 190 + p.bodyX, y: 357 + p.bodyY};
      const goal = {x: 190 + p[`foot${suffix}X`], y: 488 + p[`foot${suffix}Y`]};
      const solved = M.solveIK(hip, goal, 68, 67, 1);
      for (const joint of [solved.knee, solved.ankle]) {
        assert.ok(Number.isFinite(joint.x) && Number.isFinite(joint.y));
      }
      close(Math.hypot(solved.knee.x - hip.x, solved.knee.y - hip.y), 68, 'upper leg length', 1e-7);
      close(Math.hypot(solved.ankle.x - solved.knee.x, solved.ankle.y - solved.knee.y), 67, 'lower leg length', 1e-7);
    }
  }
});

test('direct API transitions fade running channels in and retire them on idle', () => {
  const idle = M.pose('idle', .336), running = M.pose('run', .336);
  const transition = new M.PoseTransition(idle).retarget(running);
  assert.equal(transition.values.runGesture, 0);
  assert.equal(transition.values.runLean, 0);
  for (let frame = 0; frame < 180; frame++) transition.step(running, 1 / 60);
  close(transition.values.runGesture, 1, 'run reached');
  for (const useRetarget of [false, true]) {
    const leaving = new M.PoseTransition(running);
    if (useRetarget) leaving.retarget(idle);
    for (let frame = 0; frame < 180; frame++) leaving.step(useRetarget ? 1 / 60 : idle, useRetarget ? undefined : 1 / 60);
    close(leaving.values.runGesture, 0, 'running gesture retired');
    close(leaving.values.runLean, 0, 'running tilt retired');
    close(leaving.values.lean, idle.lean, 'idle tilt restored');
  }
});

// Recorded before the run implementation, rather than recomputed from a second
// copy of the walk algorithm. These protect the existing motion output.
const walkGolden = [
  {state: 'walk', headAngle: .4406044750924231, footNearX: 2.9444444444444517,
    footFarX: -7.9177312403549465, footFarY: -15.919576488661132},
  {state: 'walk_happy', headAngle: -.06164816939819251, footNearX: 2.9444444444444517,
    footFarX: -7.9177312403549465, footFarY: -19.45726015280805},
  {state: 'walk_sad', headAngle: 1.9741910682426678, footNearX: 2.208333333333339,
    footFarX: -5.93829843026621, footFarY: -15.919576488661132}
];
const sharedWalkGolden = {
  bodyX: 0, bodyY: -2.1289771015458543, lean: -1.1264944717070846,
  armNear: 10.578567368991875, elbowNear: 16.675289193381456, wristNear: 2.136069027256615,
  armFar: -10.578567368991875, elbowFar: 13.324710806618544, wristFar: -2.136069027256615,
  footNearY: 0, footNearAngle: 0, footFarAngle: -10.179598101863062
};

test('existing neutral, happy and sad walking samples retain their pre-run output', () => {
  for (const {state, ...expected} of walkGolden) {
    const p = M.pose(state, .413);
    for (const [key, value] of Object.entries({...sharedWalkGolden, ...expected})) close(p[key], value, `${state} ${key}`);
    close(p.runGesture || 0, 0, `${state} has no running gesture`);
  }
});
