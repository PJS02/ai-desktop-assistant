'use strict';
(function (root) {
  const {pose: motionPose, smoothstep: ease} = root.CloudyMotion;
  const forwardImpact = .82;
  const backwardImpact = .9;
  const radians = Math.PI / 180;
  const mix = (a, b, t) => a + (b - a) * t;
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

  function pulse(t, start, end) {
    return Math.sin(Math.PI * clamp((t - start) / (end - start), 0, 1)) ** 2;
  }

  const forward = {
    label: '앞으로 꽈당',
    duration: 2.4,
    once: true,
    fall(t) {
      const fall = clamp((t - .27) / (forwardImpact - .27), 0, 1);
      const rock = pulse(t, .03, .38);
      const bounce = pulse(t, forwardImpact, 1.13);
      return {
        angle: 87 * fall ** 1.8 - 8 * rock - 8 * bounce - 2 * ease((t - forwardImpact) / .34),
        shift: mix(-48, 6, ease((t - .17) / .75)),
        lift: 6 * pulse(t, .33, forwardImpact) + 9 * bounce,
        impactTime: forwardImpact,
        impactOffset: 111
      };
    },
    body(p, t, side) {
      const sign = side || 1;
      const stumble = pulse(t, .02, .55);
      const reach = pulse(t, .3, forwardImpact);
      const tuck = ease((t - .44) / .44);
      const release = ease((t - .76) / .39);
      const rebound = pulse(t, forwardImpact, 1.15);
      const flail = ease((t - .06) / .26);
      const arms = Math.sin((t - .06) * 14) * pulse(t, .06, .51);
      p.bodyY += 8 * stumble + 34 * tuck - 5 * rebound;
      p.lean = sign * (-4 * stumble - 6 * reach + 3 * release);
      p.headAngle = sign * (8 * stumble - 11 * reach - 5 * release + 9 * rebound);
      p.idleGesture *= 1 - flail;
      p.airArms = flail;
      p.armNear = mix(p.armNear, side ? 76 + 34 * reach - 44 * release + 18 * arms : -82 - 24 * reach + 53 * release - 18 * arms, flail);
      p.armFar = mix(p.armFar, side ? -58 + 49 * reach + 80 * release + 19 * arms : 84 - 42 * reach - 59 * release + 19 * arms, flail);
      p.elbowNear = mix(p.elbowNear, side ? 24 + 50 * release : -12 - 15 * reach + 66 * release, flail);
      p.elbowFar = mix(p.elbowFar, 19 + 42 * release, flail);
      p.wristNear = mix(p.wristNear, -9 * reach + 11 * rebound, flail);
      p.wristFar = mix(p.wristFar, 12 * stumble, flail);
      p.footNearX = (side ? -24 : 17) * stumble + 14 * tuck;
      p.footFarX = (side ? 18 : -10) * stumble - 15 * tuck;
      p.footNearY -= 29 * stumble + 45 * tuck + 10 * rebound;
      p.footFarY -= 10 * stumble + 11 * tuck + 6 * rebound;
      p.footNearAngle += (side ? 1 : -1) * (22 * stumble + 18 * tuck);
      p.footFarAngle -= 15 * stumble + 11 * tuck;
      p.exprScared = ease((t - .09) / .19) * (1 - ease((t - .8) / .21));
      p.exprQuiet = ease((t - .91) / .29);
      p.blink = Math.max(p.blink, ease((t - .76) / .07) * (1 - ease((t - .94) / .2)));
    }
  };

  const forwardRecovery = [
    {
      time: .28, angle: 78, shift: 6, handPlant: .85,
      pose: side => ({
        bodyY: 42, lean: -3 * (side || 1), headAngle: -15 * (side || 1),
        armNear: side ? 29 : -32, armFar: side ? 46 : 40,
        elbowNear: side ? 64 : -58, elbowFar: side ? 51 : 47,
        wristNear: side ? 47 : -43, wristFar: side === -1 ? 26 : side ? 32 : -13,
        footNearX: side ? 2 : 15, footFarX: -12,
        footNearY: -42, footFarY: -11, footNearAngle: side ? 18 : -18, footFarAngle: -11,
        airArms: 1, idleGesture: 0, exprQuiet: 1
      })
    },
    {
      time: .62, angle: 58, shift: -5, handPlant: 1,
      pose: side => ({
        bodyY: side ? 87 : 77, lean: 2 * (side || 1), headAngle: -16 * (side || 1),
        armNear: side ? 55 : -54, armFar: side ? 53 : 16,
        elbowNear: side ? 13 : -16, elbowFar: side ? 17 : 50,
        wristNear: side ? 54 : -52, wristFar: side === -1 ? 22 : side ? 26 : -23,
        footNearX: side ? -34 : 15, footFarX: side ? 23 : -17,
        footNearY: -35, footFarY: -14, footNearAngle: side ? 38 : -34, footFarAngle: side ? 21 : -24,
        airArms: 1, idleGesture: 0, exprQuiet: 1
      })
    },
    {
      time: 1.02, angle: 25, shift: -2, footPlant: 1,
      pose: side => ({
        bodyY: 68, lean: 4 * (side || 1), headAngle: -11 * (side || 1),
        armNear: side ? 24 : -22, armFar: side ? 34 : 24,
        elbowNear: side ? 26 : -17, elbowFar: 37,
        wristNear: side ? 14 : -19, wristFar: side ? 10 : -7,
        footNearX: side ? -13 : 8, footFarX: side ? 12 : -10,
        footNearY: 0, footFarY: -9, footNearAngle: side ? 25 : -25, footFarAngle: side ? 21 : -20,
        airArms: .9, idleGesture: 0, exprQuiet: 1
      })
    },
    {
      time: 1.42, angle: 7, shift: 18, footPlant: 1,
      pose: side => ({
        bodyY: 24, lean: 2 * (side || 1), headAngle: -6 * (side || 1),
        armNear: side ? 9 : -18, armFar: side ? -8 : 8,
        elbowNear: 12, elbowFar: 19, wristNear: 3, wristFar: -3,
        footNearX: side ? -5 : 3, footFarX: side ? 6 : -3,
        footNearAngle: side ? 6 : -6, footFarAngle: side ? 6 : -6,
        airArms: .4, idleGesture: 0, exprRelieved: .75
      })
    },
    {time: 1.92, angle: 0, shift: 19, footPlant: 1}
  ];

  const backwardRecovery = [
    {
      time: .27, angle: -67, shift: -10,
      pose: side => ({
        bodyY: 68, lean: 4 * (side || 1), headAngle: 22 * (side || 1),
        armNear: side ? 37 : -47, armFar: side ? 30 : 41, elbowNear: 45, elbowFar: 44,
        wristNear: 8, wristFar: -4,
        footNearX: side ? -30 : 13, footFarX: side ? -20 : -9,
        footNearY: -64, footFarY: -42, footNearAngle: side ? -34 : 27, footFarAngle: side ? -27 : 23,
        airArms: 1, idleGesture: 0, exprQuiet: 1
      })
    },
    {
      time: .65, angle: -22, shift: 4,
      pose: side => ({
        bodyY: 125, lean: 4 * (side || 1), headAngle: 14 * (side || 1),
        armNear: side ? -33 : -23, armFar: side ? 45 : 25,
        elbowNear: 18, elbowFar: 34, wristNear: side ? -28 : 14, wristFar: 9,
        footNearX: side ? -57 : 23, footFarX: side ? -42 : -19,
        footNearY: -24, footFarY: -15, footNearAngle: side ? -22 : 22, footFarAngle: side ? -20 : 20,
        airArms: 1, idleGesture: 0, exprQuiet: 1
      })
    },
    {
      time: 1.02, angle: 12, shift: -8, footPlant: 1,
      pose: side => ({
        bodyY: 79, lean: 2 * (side || 1), headAngle: -9 * (side || 1),
        armNear: side ? 53 : -49, armFar: side ? 50 : 44,
        elbowNear: 25, elbowFar: 24, wristNear: -7, wristFar: 5,
        footNearX: side ? -30 : 11, footFarX: side ? -19 : -11,
        footNearY: 0, footFarY: -5, footNearAngle: side ? 12 : -12, footFarAngle: side ? 12 : -12,
        airArms: .95, idleGesture: 0, exprQuiet: .75
      })
    },
    {
      time: 1.48, angle: 5, shift: -15, footPlant: 1,
      pose: side => ({
        bodyY: 22, lean: 1 * (side || 1), headAngle: -5 * (side || 1),
        armNear: side ? 14 : -19, armFar: side ? 9 : 15,
        elbowNear: 19, elbowFar: 20, wristNear: 1, wristFar: 4,
        footNearX: side ? -7 : 3, footFarX: side ? -4 : -3,
        footNearAngle: side ? 5 : -5, footFarAngle: side ? 5 : -5,
        airArms: .4, idleGesture: 0, exprRelieved: .75
      })
    },
    {time: 1.97, angle: 0, shift: -17, footPlant: 1}
  ];

  function recoveringFall(fall, start, stages) {
    const standing = stages.at(-1);
    function segment(time, initial) {
      let from = initial;
      for (const to of stages) {
        if (time <= to.time) return [from, to, ease((time - from.time) / (to.time - from.time))];
        from = to;
      }
      return [standing, standing, 1];
    }
    return {
      label: fall.label,
      duration: Math.round((start + standing.time + .2) * 100) / 100,
      once: true,
      sample(t, side) {
        const fallTime = Math.min(t, start);
        const fallen = motionPose('idle', fallTime * 4.6 / fall.duration);
        fall.body(fallen, fallTime, side);
        if (t <= start) return fallen;
        const idle = motionPose('idle', 0);
        const initial = {time: 0, pose: () => fallen};
        const [from, to, amount] = segment(t - start, initial);
        const a = {...idle, ...from.pose?.(side)};
        const b = {...idle, ...to.pose?.(side)};
        return Object.fromEntries(Object.keys(idle).map(key => [key, mix(a[key], b[key], amount)]));
      },
      fall(t, cfg) {
        const base = fall.fall(Math.min(t, start), cfg);
        if (t <= start) return base;
        const [from, to, amount] = segment(t - start, {time: 0, ...base});
        return {
          ...base,
          angle: mix(from.angle, to.angle, amount),
          shift: mix(from.shift, to.shift, amount),
          handPlant: mix(from.handPlant ?? 0, to.handPlant ?? 0, amount),
          footPlant: mix(from.footPlant ?? 0, to.footPlant ?? 0, amount),
          standingShift: standing.shift
        };
      }
    };
  }

  const backward = {
    label: '뒤로 꽈당',
    duration: 2.6,
    once: true,
    fall(t, cfg) {
      const fall = clamp((t - .18) / (backwardImpact - .18), 0, 1);
      const rock = pulse(t, .02, .26);
      const bounce = pulse(t, backwardImpact, 1.21);
      // Each side has a different hair silhouette where the back meets the floor.
      const restingAngle = cfg.prefix === 'left' ? 70 : cfg.prefix === 'right' ? 74 : 87;
      return {
        angle: 5 * rock - (restingAngle + 3) * fall ** 1.55
          + 5.5 * bounce + 3 * ease((t - backwardImpact) / .38),
        shift: mix(48, -9, ease((t - .16) / .81)),
        lift: 3 * pulse(t, .44, backwardImpact) + 7 * bounce,
        impactTime: backwardImpact,
        impactOffset: -100
      };
    },
    body(p, t, side) {
      const sign = side || 1;
      const slip = pulse(t, .02, .55);
      const sit = ease((t - .25) / .46);
      const reach = pulse(t, .13, .85);
      const kick = pulse(t, .43, 1.02);
      const settle = ease((t - .85) / .46);
      const rebound = pulse(t, backwardImpact, 1.22);
      const arms = ease((t - .07) / .24);
      p.bodyY += 6 * slip + 45 * sit - 8 * rebound;
      p.lean = sign * (5 * slip - 7 * kick + (side ? 3 : 6) * settle);
      p.headAngle = sign * (-8 * slip + 17 * kick + 10 * settle - 11 * rebound);
      p.idleGesture *= 1 - arms;
      p.airArms = arms;
      p.armNear = mix(p.armNear, side ? 51 + 63 * reach - 74 * settle : -51 - 54 * reach + 26 * settle, arms);
      p.armFar = mix(p.armFar, side ? 48 + 51 * kick - 71 * settle : 52 + 43 * reach - 23 * settle, arms);
      p.elbowNear = mix(p.elbowNear, side ? 22 + 38 * settle : 13 + 38 * settle, arms);
      p.elbowFar = mix(p.elbowFar, 28 + 25 * settle, arms);
      p.wristNear = mix(p.wristNear, 8 * kick - 9 * settle, arms);
      p.wristFar = mix(p.wristFar, -9 * slip, arms);
      p.footNearX = (side ? -36 : 25) * slip + (side ? -24 : 11) * sit;
      p.footFarX = (side ? -15 : -16) * slip + (side ? -11 : -17) * sit + (side ? 12 : 10) * settle;
      p.footNearY -= 17 * slip + 40 * sit + 23 * kick + 7 * rebound;
      p.footFarY -= 10 * slip + 17 * sit + 17 * kick + 7 * rebound;
      p.footNearAngle += (side ? -1 : 1) * (24 * slip + 20 * kick + 9 * sit);
      p.footFarAngle += (side ? -1 : 1) * (9 * slip + 19 * kick + 8 * sit);
      p.exprScared = ease((t - .08) / .19) * (1 - ease((t - .87) / .25));
      p.exprQuiet = ease((t - 1.02) / .28);
      p.blink = Math.max(p.blink, ease((t - .81) / .08) * (1 - ease((t - 1.04) / .19)));
    }
  };

  function contour(image, [x, y, width, height]) {
    // Sample the painted silhouette so transparent margins cannot lift the rig.
    const size = 32;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(image, 0, 0, size, size);
    const {data} = ctx.getImageData(0, 0, size, size);
    const solid = (column, row) => data[(row * size + column) * 4 + 3] > 96;
    const points = [];
    const add = (column, row) => points.push({
      x: x + (column + .5) / size * width,
      y: y + (row + .5) / size * height
    });
    for (let line = 0; line < size; line++) {
      for (let edge = 0; edge < size; edge++) {
        if (solid(edge, line)) { add(edge, line); break; }
      }
      for (let edge = size - 1; edge >= 0; edge--) {
        if (solid(edge, line)) { add(edge, line); break; }
      }
      for (let edge = 0; edge < size; edge++) {
        if (solid(line, edge)) { add(line, edge); break; }
      }
      for (let edge = size - 1; edge >= 0; edge--) {
        if (solid(line, edge)) { add(line, edge); break; }
      }
    }
    return points;
  }

  function layout(cfg, t, fall, meshes, outlineFor) {
    const sign = cfg.prefix === 'left' ? -1 : 1;
    const {angle: rotation, shift, lift, impactTime, impactOffset, footPlant, handPlant, standingShift} = fall(t, cfg);
    const angle = sign * rotation * radians;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const rotate = ({x, y}) => ({
      x: (x - 180) * cos - (y - 286) * sin,
      y: (x - 180) * sin + (y - 286) * cos
    });

    let left = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (const {name, map, args} of meshes) {
      const [opacity = 1, , , , , , , clip, rect] = args;
      if (opacity < .001 || clip || rect) continue;
      for (const sample of outlineFor(name)) {
        const point = rotate(map(sample));
        left = Math.min(left, point.x);
        right = Math.max(right, point.x);
        bottom = Math.max(bottom, point.y);
      }
    }

    const {canvas: [width], groundY} = root.CloudyRig;
    const padding = 11;
    const scale = Math.min(.64, (width - 2 * padding) / (right - left));
    let desiredX = width / 2 + sign * shift;
    if (handPlant > 0) {
      // The chest is turned over the far hand in side views.
      const frontView = cfg.prefix === 'front';
      const arm = cfg.arms[frontView ? 0 : 1];
      const name = cfg.prefix + '_' + String(arm.i).padStart(2, '0') + '_connected';
      const mesh = meshes.find(mesh => mesh.name === name);
      if (mesh) {
        const [x, y] = arm.cuff;
        const wrist = rotate(mesh.map({x, y}));
        const target = width / 2 + sign * (frontView ? 43 : 56);
        desiredX = mix(desiredX, target - wrist.x * scale, handPlant);
      }
    }
    if (footPlant > 0) {
      const leg = cfg.legs[0];
      const name = cfg.prefix + '_' + String(leg.i).padStart(2, '0');
      const mesh = meshes.find(mesh => mesh.name === name);
      if (mesh) {
        const [x, y] = leg.j[2];
        const ankle = rotate(mesh.map({x, y}));
        const target = width / 2 + sign * standingShift + (cfg.ankles[0][0] - 180) * scale;
        desiredX = mix(desiredX, target - ankle.x * scale, footPlant);
      }
    }
    const x = clamp(desiredX, padding - left * scale, width - padding - right * scale);
    const y = groundY - 1 - bottom * scale - lift;
    return {
      map(point) {
        const rotated = rotate(point);
        return {x: x + scale * rotated.x, y: y + scale * rotated.y};
      },
      ground: {
        bounds: [0, groundY - 67, width, 72],
        point: (x, y) => ({x, y}),
        shadow(ctx) {
          const halfWidth = (right - left) * scale * .44;
          ctx.beginPath();
          ctx.ellipse(x + (left + right) * scale / 2, groundY - .6, halfWidth, 2.8, 0, 0, Math.PI * 2);
          ctx.fillStyle = lift > 2 ? '#354a5330' : '#354a5340';
          ctx.fill();
        },
        impact: t >= impactTime && t < impactTime + .44
          ? ctx => paintImpact(ctx, width / 2 + sign * impactOffset, groundY,
            sign * Math.sign(impactOffset), (t - impactTime) / .44)
          : null
      }
    };
  }

  function paintImpact(ctx, x, y, sign, time) {
    const spread = ease(time);
    ctx.save();
    ctx.translate(x, y - 4);
    ctx.scale(sign, 1);
    ctx.globalAlpha = (1 - time) ** 1.5;
    ctx.strokeStyle = '#c47f4f';
    ctx.lineWidth = 2.3;
    ctx.beginPath();
    ctx.moveTo(7 + 22 * spread, -11 - 6 * spread);
    ctx.lineTo(25 + 28 * spread, -20 - 9 * spread);
    ctx.moveTo(-1 + 7 * spread, -19 - 12 * spread);
    ctx.lineTo(10 + 9 * spread, -41 - 11 * spread);
    ctx.stroke();
    ctx.fillStyle = '#f4d299';
    for (const [dx, dy, radius] of [[19, -5, 6], [37, -9, 4], [-17, -5, 4.5]]) {
      ctx.beginPath();
      ctx.ellipse(dx * (1 + .5 * spread), dy - 21 * spread, radius * (1 + .4 * spread),
        radius * .7, -.18, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  const clips = {
    trip: recoveringFall(forward, 1.82, forwardRecovery),
    'trip-backward': recoveringFall(backward, 1.96, backwardRecovery)
  };
  root.CloudyActivityTrip = {clips, contour, layout};
})(window);
