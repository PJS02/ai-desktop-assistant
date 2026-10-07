/* Cloudy directional motion. Coordinates: x right, y down; angles: degrees.
 * Art faces LEFT: a planted foot travels RIGHT relative to the travelling body.
 * This file is independent of the host project and has no rendering dependency.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudyMotion = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const TAU = Math.PI * 2;
  const DEG = 180 / Math.PI;
  const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
  const mix = (a, b, t) => a + (b - a) * t;
  const cycle = (t, duration) => ((t / duration) % 1 + 1) % 1;
  // One full left/right running stride. A duty factor below half leaves two
  // short flight intervals; speed follows the planted foot's linear travel.
  const runProfile = Object.freeze({duration: .8, stride: 56, stance: .34,
    lift: 38, fps: 60, frameCount: 48, speed: 56 / (.8 * .34)});
  // Valence/arousal positions are art-direction coordinates, not measurements.
  const emotions = {
    neutral:{label:'중립',valence:0,arousal:0},
    happy:{label:'기쁨',valence:.8,arousal:.45},
    excited:{label:'들뜸·흥분',valence:.6,arousal:.9},
    proud:{label:'의기양양',valence:.8,arousal:.7},
    relieved:{label:'만족·안도',valence:.8,arousal:-.2},
    calm:{label:'차분·평온',valence:.6,arousal:-.7},
    anxious:{label:'초조함',valence:-.4,arousal:.85},
    hurt:{label:'속상함',valence:-.7,arousal:.5},
    displeased:{label:'불만',valence:-.8,arousal:.1},
    distressed:{label:'괴로움',valence:-.9,arousal:.6},
    sad:{label:'슬픔',valence:-.8,arousal:-.3},
    depressed:{label:'우울함',valence:-.65,arousal:-.65},
    tired:{label:'지침',valence:-.35,arousal:-.9},
    angry:{label:'화남',valence:-.85,arousal:.85},
    scared:{label:'놀람',valence:0,arousal:.95}
  };
  const expressionKeys = [...Object.keys(emotions).filter(k=>k!=='neutral').map(k=>'expr'+k[0].toUpperCase()+k.slice(1)), 'exprTalk','exprThinking','exprSleep'];

  function smoothstep(x) {
    x = clamp(x);
    return x * x * (3 - 2 * x);
  }

  function smootherstep(x) {
    x = clamp(x);
    return x * x * x * (10 + x * (-15 + 6 * x));
  }

  // The approved side path first folds inward, then rolls that folded forearm.
  // Its projection is nonlinear: a uniform path clock rushes through the roll.
  // Reparameterize this same path by travelled joint angle instead. Include
  // the canonical shoulder travel (-2 to -20 degrees) so the shoulder also
  // eases smoothly where the forearm projection becomes nearly stationary.
  function sidePreparationBend(progress) {
    const flex = mix(8, 132, smoothstep(progress / .65)) / DEG;
    const plane = Math.PI * smoothstep((progress - .46) / .54);
    const angle = Math.atan2(Math.sin(flex) * Math.cos(plane), Math.cos(flex)) * DEG;
    return angle < 0 ? angle + 360 : angle;
  }

  function sidePreparationProgress(progress) {
    progress = clamp(progress);
    if (progress <= 1e-12) return 0;
    if (progress >= 1 - 1e-12) return 1;
    const target = 238 * smootherstep(progress);
    if (target <= 0) return 0;
    if (target >= 238) return 1;
    let lo = 0, hi = 1;
    // Solve the original projection directly, avoiding speed changes at table
    // knots. This precision also keeps infinitesimal transition samples stable.
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      const distance = sidePreparationBend(mid) - 8 + 18 * smoothstep(mid);
      if (distance < target) lo = mid;
      else hi = mid;
    }
    return (lo + hi) / 2;
  }

  /** Retimed preparation; the return traverses the identical path in reverse. */
  function sideWavePreparation(time) {
    const t = cycle(Number.isFinite(time) ? time : 0, 4.6) * 4.6;
    const timelineProgress = t < 1.32 ? clamp((t - .18) / 1.14)
      : t > 2.85 ? clamp((3.99 - t) / 1.14) : 1;
    const pathProgress = sidePreparationProgress(timelineProgress);
    return {timelineProgress, pathProgress, lift: smoothstep(pathProgress),
      roll: smoothstep((pathProgress - .46) / .54)};
  }

  /** Recover the actual bend-plane roll from the existing interpolated gesture. */
  function sideWaveRoll(gesture) {
    const lift = clamp(gesture);
    if (lift === 0 || lift === 1) return lift;
    const pathProgress = .5 - Math.sin(Math.asin(1 - 2 * lift) / 3);
    return smoothstep((pathProgress - .46) / .54);
  }

  /** One C1 gait cycle. Stance is 60%; swing is 40%. Stride is total travel. */
  function gait(phase, stride = 40, lift = 20) {
    const q = ((phase % 1) + 1) % 1;
    if (q < 0.6) {
      return {x: stride * (-0.5 + q / 0.6), y: 0, angle: 0, stance: true, phase: q};
    }
    const r = (q - 0.6) / 0.4;
    const r2 = r * r, r3 = r2 * r;
    // Hermite endpoints have the SAME velocity as the preceding/following stance.
    const x = stride * (0.5 - 3 * r2 + 2 * r3 + (0.4 / 0.6) * (r - 3 * r2 + 2 * r3));
    const arch = Math.sin(Math.PI * r) ** 2;
    return {
      x, y: -lift * arch,
      angle: 18 * Math.sin(TAU * r) * arch,
      stance: false, phase: q
    };
  }

  /** C1 run cycle: brief support, then a folded recovery with no foot snap. */
  function runGait(phase, stride = runProfile.stride, lift = runProfile.lift) {
    const q = ((phase % 1) + 1) % 1, support = runProfile.stance;
    if (q < support) {
      return {x: stride * (-.5 + q / support), y: 0, angle: 0, stance: true, phase: q};
    }
    const r = (q - support) / (1 - support), r2 = r * r, r3 = r2 * r;
    const arch = Math.sin(Math.PI * r) ** 2;
    return {
      x: stride * (.5 - 3 * r2 + 2 * r3 + (1 - support) / support * (r - 3 * r2 + 2 * r3)),
      y: -lift * arch, angle: 26 * Math.sin(TAU * r) * arch,
      stance: false, phase: q
    };
  }

  /**
   * Two-bone IK with a stable bend side. Angles are rotations of a DOWN-pointing
   * bone: positive degrees rotate clockwise on a y-down Canvas. Unreachable
   * requests are projected to the reachable annulus; the returned ankle is the
   * actual solved endpoint, so callers never attach a shoe to an impossible goal.
   */
  function solveIK(hip, foot, upper, lower, bend = 1) {
    if (!(upper > 0) || !(lower > 0)) throw new RangeError('Bone lengths must be positive');
    const dx = foot.x - hip.x, dy = foot.y - hip.y;
    const rawDistance = Math.hypot(dx, dy);
    const epsilon = Math.min(upper, lower) * 1e-6;
    const distance = clamp(rawDistance, Math.abs(upper - lower) + epsilon, upper + lower - epsilon);
    const ux = rawDistance > 1e-9 ? dx / rawDistance : 0;
    const uy = rawDistance > 1e-9 ? dy / rawDistance : 1;
    const along = (upper * upper - lower * lower + distance * distance) / (2 * distance);
    const across = Math.sqrt(Math.max(0, upper * upper - along * along)) * (bend < 0 ? -1 : 1);
    const knee = {x: hip.x + ux * along - uy * across, y: hip.y + uy * along + ux * across};
    const ankle = {x: hip.x + ux * distance, y: hip.y + uy * distance};
    const angle = (a, b) => Math.atan2(-(b.x - a.x), b.y - a.y) * DEG;
    const upperAngle = angle(hip, knee), lowerAngle = angle(knee, ankle);
    return {knee, ankle, angles: {upper: upperAngle, lower: lowerAngle}, upperAngle, lowerAngle};
  }

  /** Fast close, short hold, slower reopen. Both ends have zero velocity. */
  function blinkAt(time) {
    const t = cycle(time, 4.6) * 4.6 - 3.17;
    if (t < 0 || t >= 0.20) return 0;
    if (t < 0.07) return smoothstep(t / 0.07);
    if (t < 0.10) return 1;
    return 1 - smoothstep((t - 0.10) / 0.10);
  }

  /** Soft syllable openings, including short pauses between spoken phrases. */
  const speechProfiles={
    neutral:[3.7,1,1.9],happy:[4.1,.93,2.05],excited:[4.7,1,2.12],
    proud:[3.35,.75,1.85],relieved:[3.05,.68,1.78],calm:[2.6,.5,1.7],
    anxious:[4.25,.61,1.63],hurt:[3.15,.7,1.62],displeased:[3.4,.61,1.76],
    distressed:[3.85,.89,1.9],sad:[2.7,.58,1.65],depressed:[2.2,.42,1.48],
    tired:[2.1,.53,1.4],angry:[4.2,.94,1.95],scared:[4.4,.85,1.8]
  };
  function speechAt(time,emotion='neutral') {
    const t=cycle(time,2.8)*2.8;
    const [rate,amplitude,end]=Object.prototype.hasOwnProperty.call(speechProfiles,emotion)?speechProfiles[emotion]:speechProfiles.neutral;
    const envelope=smoothstep(t/.12)*(1-smoothstep((t-end)/.28));
    return amplitude*envelope*(.5-.5*Math.cos(TAU*rate*t))*(.84+.16*Math.sin(TAU*.7*t));
  }

  /** Layer a selected face over an action without changing its motion or cues. */
  function applyEmotion(actionPose, emotion) {
    const p = {...actionPose};
    // Auto and unknown choices retain the action's original face. Sleep remains
    // asleep; speaking and thinking are independent action cues, not faces.
    if (!Object.prototype.hasOwnProperty.call(emotions, emotion) || p.exprSleep > 0) return p;
    for (const key of expressionKeys) p[key] = 0;
    if (emotion!=='neutral') p['expr'+emotion[0].toUpperCase()+emotion.slice(1)] = 1;
    return p;
  }

  /** Speaking is independent of the action clock and only changes the mouth. */
  function applySpeech(actionPose, speaking, speechTime = 0) {
    const p = {...actionPose};
    if (speaking === undefined && !p.speaking) return p;
    const enabled = Boolean(speaking === undefined ? p.speaking : speaking) && !(p.exprSleep > 0);
    p.speaking = enabled ? 1 : 0;
    let emotion='neutral',weight=.5;
    for(const name of Object.keys(emotions)){const value=p['expr'+name[0].toUpperCase()+name.slice(1)]||0;if(value>weight){emotion=name;weight=value;}}
    p.mouthOpen = enabled ? speechAt(Number.isFinite(speechTime) ? speechTime : 0,emotion) : 0;
    return p;
  }

  /**
   * Clock-driven motion, sampled directly rather than played as sparse frames.
   * Optional walkAmount supports accelerating/decelerating under any expression.
   * It changes the stride and arm swing together; direction belongs to renderer.
   * Optional runAmount blends the separate running stride; run/run_<emotion>
   * default to a full run. Existing walk and action samples stay unchanged.
   * Optional emotion selects only the face; omitted/'auto' keeps action defaults.
   * Optional speaking/speechTime layers speech without restarting action motion.
   */
  function pose(state, time, options = {}) {
    if (!Number.isFinite(time)) time = 0;
    const walkingState = state === 'walk' || state.startsWith('walk_');
    const runningState = state === 'run' || state.startsWith('run_');
    const emotion = state.startsWith('walk_') ? state.slice(5) : state.startsWith('run_') ? state.slice(4) : state;
    const amount = clamp(options.walkAmount === undefined ? (walkingState ? 1 : 0) : options.walkAmount);
    const runAmount = clamp(options.runAmount === undefined ? (runningState ? 1 : 0) : options.runAmount);
    const breathe = TAU * time / 4.6;
    const s = Math.sin(breathe), c = Math.cos(breathe);
    const p = {
      bodyX: 0, bodyY: -0.9 * (1 - c), lean: 0.35 * s,
      headAngle: 0.8 * Math.sin(breathe - 0.3), blink: blinkAt(time),
      armNear: -2 + 1.2 * Math.sin(breathe - 0.5), elbowNear: 8, wristNear: 0.5 * s,
      armFar: 2 + 0.9 * Math.sin(breathe - 0.8), elbowFar: 6, wristFar: -0.4 * s,
      footNearX: 0, footNearY: 0, footFarX: 0, footFarY: 0,
      footNearAngle: 0, footFarAngle: 0,
      exprHappy:0,exprSad:0,exprAngry:0,exprScared:0,exprTalk:0,exprThinking:0,exprSleep:0,
      mouthOpen:0,speaking:0,thinkGesture:0,waveGesture:0,airborne:0,airArms:0,idleGesture:0,
      waveArmOffset:0,waveElbowOffset:0,waveWristOffset:0,waveSideGesture:0,waveForearmShorten:0
    };
    for(const key of expressionKeys)if(!(key in p))p[key]=0;
    // A narrow idle range keeps the frontal arms gently spread throughout the
    // breath. Fade this view-specific rest pose away during locomotion.
    if (state === 'idle') p.idleGesture = (.95 + .05 * Math.sin(TAU * time / 6.4 - .6)) * (1 - amount);
    switch (emotion) {
      case 'happy':
        p.exprHappy=1;
        p.headAngle = -2 + 1.0 * s;
        p.armNear = 16 + 5 * s; p.elbowNear = 28 + 5 * Math.sin(breathe - 0.4);
        p.wristNear = 3 * Math.sin(breathe - 0.8); p.armFar = -9 + 3 * s; p.elbowFar = 17;
        p.bodyY = -1.7 * (1 - c);
        break;
      case 'sad':
        p.exprSad=1;
        p.headAngle = 5 + 0.6 * s; p.lean = 1.5;
        p.armNear = -3; p.elbowNear = 4; p.armFar = 1; p.elbowFar = 4;
        break;
      case 'angry':
        p.exprAngry=1;
        p.headAngle = -2 + 0.4 * s; p.lean = -1;
        p.armNear = 8 + s; p.elbowNear = 24; p.armFar = -7; p.elbowFar = 20;
        break;
      case 'scared':
        p.exprScared=1;
        p.headAngle = -2 + 0.7 * Math.sin(2 * breathe);
        p.armNear = 24 + 1.1 * s; p.elbowNear = 58; p.wristNear = -9;
        p.armFar = -20 - 1.1 * s; p.elbowFar = 47; p.wristFar = 8;
        break;
      case 'talk':
        p.exprTalk=1;p.speaking=1;p.mouthOpen=speechAt(time);
        p.headAngle = 1.2 * s;
        p.armNear = 8 + 4 * s; p.elbowNear = 31 + 8 * Math.sin(breathe - 0.4);
        p.wristNear = 3 * Math.sin(breathe - 0.8);
        break;
      case 'thinking':
        p.exprThinking=1;p.thinkGesture=1;
        p.headAngle = -4 + 0.5 * s; p.armNear = 12; p.elbowNear = 100; p.wristNear = -5+1.5*s;
        break;
      case 'wave': {
        const restArm=p.armNear,restElbow=p.elbowNear,restWrist=p.wristNear;
        // Restore the original approved front wave. Only side-view offsets
        // add the body-side elbow / folded forearm treatment below.
        // These are projected drawing angles, not anatomical measurements.
        const t=cycle(time,4.6)*4.6;
        const lift=smoothstep((t-.18)/.62)*(1-smoothstep((t-2.85)/.72));
        const waving=smoothstep((t-.8)/.24)*(1-smoothstep((t-2.6)/.25));
        const phase=TAU*(t-.82)*1.8;
        const shoulderWave=waving*Math.sin(phase);
        const elbowWave=waving*Math.sin(phase-.28);
        const wristWave=waving*Math.sin(phase-.55);
        p.exprHappy=1;p.waveGesture=lift;
        // Keep the other frontal arm in the same relaxed diagonal as idle.
        // The renderer fades the near arm's rest spread by waveGesture only.
        p.idleGesture=(.95+.05*Math.sin(TAU*time/6.4-.6))*(1-amount);
        p.armNear=mix(p.armNear,-67+5*shoulderWave,lift);
        p.elbowNear=mix(p.elbowNear,-102+13*elbowWave,lift);
        p.wristNear=mix(p.wristNear,-4+16*wristWave,lift);
        // Keep the elbow beside the body, but wave with the entire forearm.
        // A shallower fold leaves the sleeve visibly long instead of bunching
        // it into a ball. The wrist follows the forearm with a small delay.
        const sidePreparation=sideWavePreparation(time);
        const sideProgress=sidePreparation.pathProgress;
        const sideLift=sidePreparation.lift;
        const sideWaving=smoothstep((t-1.32)/.24)*(1-smoothstep((t-2.6)/.25));
        const sidePhase=TAU*(t-1.56)*1.65;
        const sideShoulderWave=sideWaving*Math.sin(sidePhase);
        const sideForearmWave=sideWaving*Math.sin(sidePhase-.24);
        const sideWristWave=sideWaving*Math.sin(sidePhase-.55);
        const flexAngle=mix(restElbow,132+18*sideForearmWave,smoothstep(sideProgress/.65))*Math.PI/180;
        const bendPlane=Math.PI*smoothstep((sideProgress-.46)/.54);
        const along=Math.cos(flexAngle),across=Math.sin(flexAngle)*Math.cos(bendPlane);
        let projectedBend=Math.atan2(across,along)*DEG;
        if(projectedBend<0)projectedBend+=360;
        p.waveSideGesture=sideLift;
        p.waveArmOffset=mix(restArm,-20+1.5*sideShoulderWave,sideLift)-p.armNear;
        p.waveElbowOffset=projectedBend-p.elbowNear;
        p.waveForearmShorten=0;
        p.waveWristOffset=mix(restWrist,-4-8*sideWristWave,sideLift)-p.wristNear;
        p.lean+=lift*(-1.1+.35*shoulderWave);
        p.headAngle+=lift*(3.5+.65*waving*Math.sin(phase-.7));
        p.bodyY+=lift*(-1.25+.3*shoulderWave);
        break;
      }
      case 'sleep':
        p.exprSleep=1;
        p.headAngle = 6 + 0.8 * s; p.blink = 1;
        p.armNear = -4; p.elbowNear = 5; p.armFar = 3; p.elbowFar = 5;
        break;
      case 'hovering': {
        const f=TAU*time*2.6;
        p.exprScared=1;p.airborne=1;p.airArms=1;
        p.bodyY=-24+2*Math.sin(f*.5);p.lean=2*Math.sin(f*.5);
        p.armNear=-63+24*Math.sin(f);p.armFar=60-25*Math.sin(f+.85);
        p.elbowNear=28+15*Math.sin(f-.45);p.elbowFar=30+16*Math.sin(f+.4);
        p.wristNear=13*Math.sin(f-.8);p.wristFar=-13*Math.sin(f+.1);
        p.footNearX=-12+12*Math.sin(f+.4);p.footFarX=12-12*Math.sin(f+.4);
        p.footNearY=-39-12*Math.sin(f);p.footFarY=-39+12*Math.sin(f);
        p.footNearAngle=16*Math.sin(f-.5);p.footFarAngle=-16*Math.sin(f-.5);
        p.headAngle=2*Math.sin(f*.5-.3);
        break;
      }
      case 'jump': {
        // Complete repeatable demonstration: anticipation, rise, descent, settle.
        const q = cycle(time, 2.4);
        const bell = (a, b) => q > a && q < b ? Math.sin(Math.PI * (q - a) / (b - a)) ** 2 : 0;
        const flight=bell(.15,.70),height=62*flight,tuck=15*bell(.23,.55),crouch=bell(0,.18),landing=bell(.68,.88);
        p.airborne=flight;p.airArms=1;p.exprHappy=1;
        p.bodyY=12*crouch-height+10*landing;p.lean=3*crouch-3*flight+2*landing;
        p.footNearY=-height-tuck;p.footFarY=-height-tuck*.75;
        p.footNearX=-8*flight;p.footFarX=8*flight;
        p.footNearAngle=18*bell(.22,.52);p.footFarAngle=-15*bell(.27,.61);
        p.armNear=8*crouch-128*flight-10*landing;p.armFar=-8*crouch+123*flight+10*landing;
        p.elbowNear=12+30*flight+12*landing;p.elbowFar=10+25*flight+12*landing;
        p.wristNear=-12*flight;p.wristFar=12*flight;
        p.headAngle=3*crouch-5*flight+3*landing;
        p.blink *= 1-smoothstep(landing/.08);
        break;
      }
      case 'fall': {
        const f=TAU*time*3.25;
        p.exprScared=1;p.airborne=1;p.airArms=1;
        p.bodyY=-29+4*Math.sin(TAU*time/1.8);p.lean=3.5*Math.sin(f*.5);
        p.armNear=-92+29*Math.sin(f);p.armFar=88-28*Math.sin(f+1.2);
        p.elbowNear=30+21*Math.sin(f-.6);p.elbowFar=32+20*Math.sin(f+.6);
        p.wristNear=19*Math.sin(f-1);p.wristFar=-19*Math.sin(f+.2);
        p.footNearX=-16+16*Math.sin(f+.3);p.footFarX=16-16*Math.sin(f+.3);
        p.footNearY=-44-15*Math.sin(f);p.footFarY=-44+15*Math.sin(f);
        p.footNearAngle=23*Math.sin(f-.5);p.footFarAngle=-23*Math.sin(f-.5);
        p.headAngle=3*Math.sin(f*.5-.3);
        break;
      }
      case 'land': {
        const t = cycle(time, 1.6) * 1.6;
        const compress = t < 0.65 ? Math.sin(Math.PI * t / 0.65) ** 2 : 0;
        p.bodyY = 7 * compress; p.armNear = 4 + 8 * compress; p.armFar = -4 - 8 * compress;
        p.elbowNear = 10 + 8 * compress; p.elbowFar = 8 + 7 * compress;
        p.headAngle = 1.5 * compress;
        p.blink*=1-smoothstep(compress/.08);
        break;
      }
    }
    if (amount > 0) {
      const phase = time / 1.2;
      const a = TAU * phase;
      const stride = emotion === 'sad' ? 30 : 40;
      const lift = emotion === 'happy' ? 22 : 18;
      const near = gait(phase, stride, lift), far = gait(phase + 0.5, stride, lift);
      p.footNearX = mix(p.footNearX, near.x, amount);
      p.footNearY = mix(p.footNearY, near.y, amount);
      p.footFarX = mix(p.footFarX, far.x, amount);
      p.footFarY = mix(p.footFarY, far.y, amount);
      p.footNearAngle = mix(p.footNearAngle, near.angle, amount);
      p.footFarAngle = mix(p.footFarAngle, far.angle, amount);
      p.bodyY = mix(p.bodyY, -1.6 + 1.4 * Math.cos(2 * a), amount);
      p.bodyX = mix(p.bodyX, 0, amount);
      p.lean = mix(p.lean, -1.5 + 0.45 * Math.sin(a), amount);
      p.headAngle = mix(p.headAngle, 0.55 * Math.sin(a - 0.4), amount * 0.7);
      // Arms counter the legs, with elbows/wrists following a little later.
      p.armNear = mix(p.armNear, 12 * Math.sin(a - 0.10), amount);
      p.armFar = mix(p.armFar, -12 * Math.sin(a - 0.10), amount);
      p.elbowNear = mix(p.elbowNear, 10 + 5 * (1 - Math.cos(a - 0.25)), amount);
      p.elbowFar = mix(p.elbowFar, 10 + 5 * (1 + Math.cos(a - 0.25)), amount);
      p.wristNear = mix(p.wristNear, 2.2 * Math.sin(a - 0.35), amount);
      p.wristFar = mix(p.wristFar, -2.2 * Math.sin(a - 0.35), amount);
      p.waveArmOffset *= 1 - amount;
      p.waveElbowOffset *= 1 - amount;
      p.waveWristOffset *= 1 - amount;
      p.waveSideGesture *= 1 - amount;
      p.waveForearmShorten *= 1 - amount;
    }
    if (runAmount > 0) {
      const phase = time / runProfile.duration, q = cycle(time, runProfile.duration), a = TAU * phase;
      const near = runGait(phase), far = runGait(phase + .5);
      // Lift the feet WITH the pelvis in flight. A pelvis-only hop stretches
      // the short painted legs and makes the hidden hip correction do the work.
      const half = q % .5, flight = half > runProfile.stance
        ? Math.sin(Math.PI * (half - runProfile.stance) / (.5 - runProfile.stance)) ** 2 : 0;
      const flightLift = 12 * flight;
      p.footNearX = mix(p.footNearX, near.x, runAmount);
      p.footNearY = mix(p.footNearY, near.y - flightLift, runAmount);
      p.footFarX = mix(p.footFarX, far.x, runAmount);
      p.footFarY = mix(p.footFarY, far.y - flightLift, runAmount);
      p.footNearAngle = mix(p.footNearAngle, near.angle, runAmount);
      p.footFarAngle = mix(p.footFarAngle, far.angle, runAmount);
      p.bodyY = mix(p.bodyY, 3 - 6 * Math.sin(a) ** 2 - flightLift, runAmount);
      p.bodyX = mix(p.bodyX, 0, runAmount);
      const lean = -16.5 + .45 * Math.sin(a);
      p.lean = mix(p.lean, lean, runAmount);
      p.headAngle = mix(p.headAngle, 5 + .7 * Math.sin(a - .3), runAmount);
      // The arm opposite the forward leg leads, with a bent elbow and a small
      // delayed wrist response. Leave airArms off to retain frontal arm depth.
      // Shift the swing behind the shoulders and widen its rear reach. The far
      // forearm folds more tightly so its hidden elbow never reads as straight.
      p.armNear = mix(p.armNear, -14 - 34 * Math.cos(a - .16), runAmount);
      p.armFar = mix(p.armFar, -14 + 34 * Math.cos(a - .16), runAmount);
      p.elbowNear = mix(p.elbowNear, 85 + 10 * Math.sin(a - .35), runAmount);
      p.elbowFar = mix(p.elbowFar, 105 - 8 * Math.sin(a - .35), runAmount);
      p.wristNear = mix(p.wristNear, -4 + 4 * Math.sin(a - .5), runAmount);
      p.wristFar = mix(p.wristFar, -4 - 4 * Math.sin(a - .5), runAmount);
      p.airborne = mix(p.airborne, flight, runAmount);
      p.airArms *= 1 - runAmount;
      for (const key of ['idleGesture', 'thinkGesture', 'waveGesture', 'waveArmOffset',
        'waveElbowOffset', 'waveWristOffset', 'waveSideGesture', 'waveForearmShorten']) p[key] *= 1 - runAmount;
      // Only new run samples carry these channels. The renderer projects the
      // forward tilt for each view without changing historical action poses.
      p.runGesture = runAmount;
      p.runLean = lean * runAmount;
    }
    p.blink = clamp(p.blink);
    // Repeated air actions need extra headroom. A composed sequence may keep
    // its own fixed framing independently of the arms' front/back depth.
    p.framingZoom = 1 - .14 * p.airArms;
    return applySpeech(applyEmotion(p, options.emotion), options.speaking,
      options.speechTime === undefined ? time : options.speechTime);
  }

  /**
   * Critically damped tracking of a moving target, integrated analytically.
   * Tracking target velocity avoids persistent lag/sliding in a steady stance.
   * Retargeting keeps the actual position AND velocity, including interruptions.
   */
  class PoseTransition {
    constructor(initial = {}) {
      this.values = {...initial};
      this.velocity = Object.fromEntries(Object.keys(initial).map(k => [k, 0]));
      this.target = {...initial};
      this.previousTarget = {...initial};
    }
    withRunRest(target) {
      const next = {...target};
      // Historical poses deliberately omit new channels. Once a transition
      // has used them, an absent channel means returning to its zero rest.
      for (const key of ['runGesture', 'runLean']) {
        if (key in this.values && !(key in next)) next[key] = 0;
      }
      return next;
    }
    retarget(target) {
      this.target = this.withRunRest(target);
      // A state change is a position goal, not a fictitious one-frame velocity.
      this.previousTarget = {...this.target};
      for (const [key, value] of Object.entries(this.target)) {
        if (!(key in this.values)) { this.values[key] = key === 'runGesture' || key === 'runLean' ? 0 : value; this.velocity[key] = 0; }
      }
      return this;
    }
    step(target, dt) {
      if (typeof target === 'number' && dt === undefined) { dt = target; target = this.target; }
      target = target || this.target;
      target = this.withRunRest(target);
      this.target = {...target};
      if (!(dt > 0) || !Number.isFinite(dt)) return {...this.values};
      for (const [key, goal] of Object.entries(target)) {
        if (!Number.isFinite(goal)) continue;
        if (!(key in this.values)) { this.values[key] = key === 'runGesture' || key === 'runLean' ? 0 : goal; this.velocity[key] = 0; }
        const previous = this.previousTarget[key] === undefined ? goal : this.previousTarget[key];
        const goalVelocity = (goal - previous) / dt;
        const omega = key === 'blink' ? 78 : key === 'mouthOpen' ? 65 : key.startsWith('foot') ? 36 : 24;
        const error = this.values[key] - previous;
        const relativeVelocity = this.velocity[key] - goalVelocity;
        const c = relativeVelocity + omega * error;
        const decay = Math.exp(-omega * dt);
        this.values[key] = goal + (error + c * dt) * decay;
        this.velocity[key] = goalVelocity + (relativeVelocity - omega * c * dt) * decay;
        if ((key==='blink'||key==='mouthOpen'||key==='speaking'||key==='thinkGesture'||key==='waveGesture'||key==='waveSideGesture'||key==='waveForearmShorten'||key==='airborne'||key==='airArms'||key==='idleGesture'||key==='runGesture'||key.startsWith('expr')) && (this.values[key] < 0 || this.values[key] > 1)) {
          this.values[key] = clamp(this.values[key]); this.velocity[key] = 0;
        }
      }
      this.previousTarget = {...target};
      return {...this.values};
    }
  }

  /**
   * Smooth skinning for a 3-joint arm or 4-joint leg. The fourth point is a toe;
   * source pixels below the ankle follow the ankle-to-toe frame, so the shoe can
   * stay level while the calf bends. Unlike separate rectangles, the shared mesh
   * remains connected through its joints. Width is preserved while bone length
   * follows the posed chain. No allocation or mutation of the joint arrays.
   */
  function deformPoint(point, restJoints, posedJoints, normalScale) {
    const count = restJoints.length;
    if (count !== posedJoints.length || count < 2) throw new RangeError('Matching joint chains are required');
    const bones = [];
    for (let i = 0; i < count - 1; i++) {
      const start = restJoints[i], end = restJoints[i + 1];
      const dx = end.x - start.x, dy = end.y - start.y;
      const length = Math.max(1e-6, Math.hypot(dx, dy));
      const posedStart = posedJoints[i], posedEnd = posedJoints[i + 1];
      const pdx = posedEnd.x - posedStart.x, pdy = posedEnd.y - posedStart.y;
      const posedLength = Math.max(1e-6, Math.hypot(pdx, pdy));
      bones.push({start, length, x: dx / length, y: dy / length, posedStart,
        px: pdx / posedLength, py: pdy / posedLength, scale: posedLength / length});
    }
    const transform = i => {
      const b = bones[i], dx = point.x - b.start.x, dy = point.y - b.start.y;
      const axial = dx * b.x + dy * b.y;
      const along = axial * b.scale;
      // Girth affects only distance across the bone, leaving its length and
      // joint positions intact. Omitting the callback preserves the old map.
      const normal = (-dx * b.y + dy * b.x) * (normalScale ? normalScale(i, axial / b.length) : 1);
      return {x: b.posedStart.x + along * b.px - normal * b.py,
        y: b.posedStart.y + along * b.py + normal * b.px};
    };
    // Smooth signed joint planes avoid the discontinuous "nearest bone" switch
    // on a bent source limb. Every triangle vertex uses the same continuous map.
    let result = transform(0);
    for (let joint = 1; joint < bones.length; joint++) {
      const previous = bones[joint - 1], next = bones[joint], center = restJoints[joint];
      let bx = previous.x + next.x, by = previous.y + next.y;
      const bisectorLength = Math.hypot(bx, by);
      if (bisectorLength < 1e-6) { bx = previous.x; by = previous.y; }
      else { bx /= bisectorLength; by /= bisectorLength; }
      let axial = (point.x - center.x) * bx + (point.y - center.y) * by;
      let radius = Math.min(previous.length, next.length) * 0.26;
      let weight = smoothstep((axial + radius) / (2 * Math.max(radius, 1e-6)));
      if (count === 4 && joint === 2) {
        // Finish at the ankle plane: source shoe pixels below it stay rigid.
        axial = (point.x - center.x) * previous.x + (point.y - center.y) * previous.y;
        radius = Math.min(previous.length * 0.25, next.length * 0.45);
        weight = smoothstep((axial + radius) / Math.max(radius, 1e-6));
      }
      if (weight > 0) {
        const q = transform(joint);
        result = {x: mix(result.x, q.x, weight), y: mix(result.y, q.y, weight)};
      }
    }
    return result;
  }

  return {smoothstep, sideWavePreparation, sideWaveRoll, gait, runGait, runProfile, solveIK, pose, applyEmotion, applySpeech, blinkAt, speechAt, PoseTransition, deformPoint, emotions, expressionKeys};
});
