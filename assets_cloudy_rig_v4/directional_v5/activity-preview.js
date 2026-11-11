'use strict';
(function (root) {
  const M = root.CloudyMotion;
  const BaseRenderer = root.CloudyRenderer;
  const {hand, cuffForeground} = root.CloudyActivityHands;
  const trip = root.CloudyActivityTrip;
  const radians = Math.PI / 180;
  const tau = Math.PI * 2;
  const mix = (a, b, t) => a + (b - a) * t;
  const ease = M.smoothstep;
  const loop = (seconds, duration) => (seconds % duration + duration) % duration;
  const pulse = phase => Math.max(0, Math.sin(tau * phase)) ** 2;
  const direction = cfg => cfg.prefix === 'left' ? -1 : cfg.prefix === 'right' ? 1 : 0;
  const handSide = cfg => cfg.prefix === 'right' ? -1 : 1;
  const shortest = degrees => (degrees + 540) % 360 - 180;
  const bodyPoint = BaseRenderer.prototype.bodyPoint;
  const rotate = ({x, y}, angle) => ({
    x: x * Math.cos(angle) - y * Math.sin(angle),
    y: x * Math.sin(angle) + y * Math.cos(angle)
  });

  function headPoint(pose, x, y) {
    const pivot = bodyPoint({x: 180, y: 250}, pose);
    const offset = rotate({x, y}, (pose.lean + pose.headAngle) * radians);
    return {x: pivot.x + offset.x, y: pivot.y + offset.y};
  }

  function heldLayout(cfg, pose, y, angle, width) {
    const side = direction(cfg);
    const center = bodyPoint({x: 180 + side * 27, y}, pose);
    const yawScale = handSide(cfg) * (side ? width : 1);
    const roll = (pose.lean + angle) * radians;
    return {
      roll,
      point(x, y) {
        const offset = rotate({x: x * yawScale, y}, roll);
        return {x: center.x + offset.x, y: center.y + offset.y};
      },
      local(point) {
        const offset = rotate({x: point.x - center.x, y: point.y - center.y}, -roll);
        return {x: offset.x / yawScale, y: offset.y};
      }
    };
  }

  function aimHand(cfg, pose, index, grip) {
    const near = index === 0;
    const suffix = near ? 'Near' : 'Far';
    const [x, y] = cfg.shoulders[index];
    const shoulder = bodyPoint({x, y}, pose);
    const sourcePoint = ([x, y]) => ({x: x * .34, y: y * .34});
    const arm = cfg.arms[index];
    const joints = arm.j.map(sourcePoint);
    const cuff = sourcePoint(arm.cuff);
    const girth = root.CloudyGirth?.scale(cfg.prefix, 'arm', near);
    const normalScale = !near && direction(cfg)
      ? (bone, fraction) => -(girth?.(bone, fraction) ?? 1)
      : girth;
    const bend = direction(cfg) || (near ? -1 : 1);
    const contact = grip.art.contact(grip.amount);
    const finger = {x: contact.x * grip.mirror * grip.size, y: contact.y * grip.size};

    function fitCuff(angle) {
      const offset = rotate(finger, angle * radians);
      const opening = {x: grip.target.x - offset.x, y: grip.target.y - offset.y};
      const wrist = {...opening};
      let solved;
      // Correct for the distance from the rig's wrist joint to the cuff opening.
      for (let i = 0; i < 4; i++) {
        solved = M.solveIK(shoulder, wrist, 38, 46, bend);
        const mapped = M.deformPoint(cuff, joints, [shoulder, solved.knee, solved.ankle], normalScale);
        const dx = opening.x - mapped.x;
        const dy = opening.y - mapped.y;
        if (Math.hypot(dx, dy) < .04) break;
        wrist.x += dx;
        wrist.y += dy;
      }
      return solved;
    }

    let angle = grip.angle;
    let solved = fitCuff(angle);
    let flex = shortest(angle - solved.lowerAngle);
    // Rotate toward the forearm when needed, keeping the contact point fixed.
    for (let i = 0; i < 8 && Math.abs(flex) > 61; i++) {
      angle += Math.sign(flex) * (60 - Math.abs(flex)) * .8;
      solved = fitCuff(angle);
      flex = shortest(angle - solved.lowerAngle);
    }
    const {upperAngle, lowerAngle} = solved;
    const projection = handSide(cfg);
    pose['arm' + suffix] = (upperAngle - pose.lean) / projection;
    pose['elbow' + suffix] = shortest(lowerAngle - upperAngle) / (projection * (!near && cfg.prefix === 'front' ? -1 : 1));
    pose['wrist' + suffix] = flex / projection;
  }

  const ink = '#34474e';
  const mint = '#86d0c2';
  const paper = '#fff9ec';
  const paperLine = '#c6ccc1';

  function shape(ctx, path, fill, stroke, width = 1) {
    ctx.beginPath();
    path(ctx);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
    }
  }

  function box(ctx, x, y, w, h, radius, fill, stroke, lineWidth) {
    shape(ctx, c => c.roundRect(x, y, w, h, radius), fill, stroke, lineWidth);
  }

  function oval(ctx, x, y, rx, ry, fill, stroke, lineWidth) {
    shape(ctx, c => c.ellipse(x, y, rx, ry, 0, 0, tau), fill, stroke, lineWidth);
  }

  function shade(ctx, top, bottom, light, dark) {
    const gradient = ctx.createLinearGradient(0, top, 0, bottom);
    gradient.addColorStop(0, light);
    gradient.addColorStop(1, dark);
    return gradient;
  }

  function band(ctx, front) {
    const arc = c => {
      if (front) {
        c.moveTo(-98, -67);
        c.bezierCurveTo(-135, -247, 136, -247, 98, -67);
      } else {
        c.moveTo(-62, -150);
        c.bezierCurveTo(-45, -218, 81, -212, 61, -66);
      }
    };
    shape(ctx, arc, null, ink, 11);
    shape(ctx, arc, null, shade(ctx, -200, -64, '#def4ed', '#537b80'), 7);
  }

  function earCup(ctx, x, y, roll) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(roll * radians);
    box(ctx, -14, -26, 28, 49, 12, '#35434b', '#26363d', 1.8);
    box(ctx, -17, -21, 30, 43, 11, shade(ctx, -21, 22, '#ebfff9', mint), ink, 1.7);
    box(ctx, -12, -16, 21, 33, 8, shade(ctx, -16, 17, '#72bcb3', '#3c7479'), '#579491', 1);
    oval(ctx, -2, 0, 6, 7, '#385960', '#c4ece2', 1.5);
    oval(ctx, -2, 0, 2.2, 2.8, '#dbfff2');
    ctx.restore();
  }

  const music = {
    label: '음악 듣기',
    duration: 4.8,
    body(p, t, side) {
      const beat = tau * t / .6;
      const sway = Math.sin(tau * t / 2.4);
      const tap = pulse(t / .6 + .12);
      p.lean = 2.5 * sway;
      p.headAngle = (side || 1) * 4.5 * Math.sin(beat - .3) + 1.4 * sway;
      p.bodyY = -2.8 + 2.8 * Math.cos(beat);
      p.footNearX = 5;
      p.footNearY = -8 * tap;
      p.footNearAngle = 11 * tap;
      p.armNear -= 3 * sway;
      p.armFar += 3 * sway;
      p.wristNear = 3 + 6 * Math.sin(beat - .7);
      p.wristFar = -3 + 3 * sway;
      p.idleGesture = .94 + .05 * sway;
      p.exprHappy = 1;
    },
    frame(cfg, pose) {
      const front = cfg.prefix === 'front';
      const point = (x, y) => headPoint(pose, x * handSide(cfg), y);
      return {
        point,
        bounds: [-126, -208, 252, 180],
        hands: [hand('relaxed', handSide(cfg), .93), hand('relaxed', -handSide(cfg), .87)],
        back: front ? ctx => band(ctx, true) : null,
        paint(ctx) {
          if (front) {
            earCup(ctx, -101, -66, -12);
            earCup(ctx, 101, -66, 12);
          } else {
            band(ctx, false);
            earCup(ctx, 61, -56, 11);
          }
        }
      };
    }
  };

  function writingTip(t) {
    const stroke = (time, duration, y) => {
      const progress = ease(time / duration);
      return {x: mix(-24, 23, progress), y: y + 1.4 * Math.sin(tau * 4 * progress), progress};
    };
    const first = stroke(t, 1.14, -9);
    const second = stroke(t - 1.46, 1.04, 3);
    const lift = ease((t - 1.14) / .32);
    const restart = ease((t - 4.6) / .7);
    return {
      x: mix(mix(first.x, second.x, lift), -24, restart),
      y: mix(mix(first.y, second.y, lift) - 5 * Math.sin(Math.PI * lift), -9, restart),
      first: first.progress,
      second: second.progress
    };
  }

  function notebook(ctx, writing, fade) {
    box(ctx, -44, -22, 88, 49, 4, '#5f9e97', ink, 1.7);
    box(ctx, -41, -23, 82, 46, 3, '#dfdbc9', '#67807a', 1.1);
    box(ctx, -40, -25, 81, 45, 3, paper, '#67807a', 1);
    for (let x = -31; x <= 32; x += 9) {
      shape(ctx, c => {
        c.moveTo(x, -20);
        c.bezierCurveTo(x - 5, -21, x - 4, -31, x + 1, -28);
      }, null, ink, 1.7);
    }
    for (const y of [-7, 5, 15]) {
      shape(ctx, c => { c.moveTo(-33, y); c.lineTo(33, y); }, null, paperLine, .65);
    }
    ctx.save();
    ctx.globalAlpha = fade;
    for (const [y, progress] of [[-9, writing.first], [3, writing.second]]) {
      shape(ctx, c => {
        c.moveTo(-24, y);
        for (let i = 1; i <= Math.ceil(48 * progress); i++) {
          const s = Math.min(progress, i / 48);
          c.lineTo(mix(-24, 23, s), y + 1.4 * Math.sin(tau * 4 * s));
        }
      }, null, '#476b92', 1.35);
    }
    ctx.restore();
  }

  function pencil(ctx, tip, roll) {
    ctx.save();
    ctx.translate(tip.x, tip.y);
    ctx.rotate(roll);
    box(ctx, -2.55, -39, 5.1, 32, 1.4, '#f6bc5b', '#80604b', .95);
    shape(ctx, c => { c.moveTo(-1.3, -34); c.lineTo(-1.3, -10); }, null, '#ffe2a1', .75);
    box(ctx, -2.55, -42, 5.1, 5.5, 1.5, '#efa4a0', '#80604b', .9);
    box(ctx, -2.55, -38, 5.1, 3.5, 0, '#e5e8dc', '#80604b', .75);
    shape(ctx, c => {
      c.moveTo(-2.55, -8);
      c.lineTo(0, 0);
      c.lineTo(2.55, -8);
      c.closePath();
    }, '#f4dfb9', '#80604b', 1);
    shape(ctx, c => { c.moveTo(0, 0); c.lineTo(0, -2.8); }, null, ink, 1.5);
    ctx.restore();
  }

  const thinking = t => ease((t - 2.5) / .5) * (1 - ease((t - 4.2) / .62));
  const writing = {
    label: '필기하기',
    duration: 5.6,
    held: true,
    body(p, t, side) {
      const think = thinking(t);
      p.lean = (side || 1) * mix(4.5, -1.5, think);
      p.headAngle = (side || 1) * mix(6.3 + .8 * Math.sin(tau * t / 1.4), -5, think);
      p.bodyY -= 2;
      p.exprThinking = think;
    },
    frame(cfg, pose, t) {
      const layout = heldLayout(cfg, pose, 322, -5 * handSide(cfg), .8);
      const think = thinking(t);
      const mark = writingTip(t);
      const side = direction(cfg);
      const sideOfHand = handSide(cfg);
      const chin = layout.local(headPoint(pose, side ? side * 38 : 0, side ? -22 : -13));
      const tip = {x: mix(mark.x, chin.x, think), y: mix(mark.y, chin.y, think)};
      const angle = mix(29, 167, think) * radians;
      const grip = rotate({x: 0, y: -18}, angle);
      const pinch = layout.point(tip.x + grip.x, tip.y + grip.y);
      return {
        point: layout.point,
        bounds: [-74, -120, 148, 158],
        hands: [
          hand('pencil', sideOfHand, .98, pinch, sideOfHand * mix(79, 101, think)),
          side
            ? hand('writingSupport', sideOfHand, .84, layout.point(-44, 17), sideOfHand * 76)
            : hand('writingSupport', -sideOfHand, .98, layout.point(-41, 13), -sideOfHand * 83)
        ],
        paint: ctx => notebook(ctx, mark, 1 - ease((t - 4.82) / .6)),
        foreground: ctx => pencil(ctx, tip, angle)
      };
    }
  };

  function page(ctx, x, lift, fill, curl = 0) {
    shape(ctx, c => {
      c.moveTo(0, -19);
      c.quadraticCurveTo(x * .53 + curl, -33 - lift * .55, x, -22 - lift);
      c.lineTo(x, 22 - lift);
      c.quadraticCurveTo(x * .5 - curl * .45, 17 - lift * .48, 0, 28);
      c.closePath();
    }, fill, '#a89f8a', .85);
    for (let y = -15; y <= 13; y += 7) {
      const edge = y === 13 ? .73 : .84;
      shape(ctx, c => {
        c.moveTo(x * .16, y - 2 - lift * .17);
        c.quadraticCurveTo(x * .5, y - 6 - lift * .56, x * edge, y - 4 - lift * edge);
      }, null, paperLine, .75);
    }
  }

  function book(ctx, turn) {
    shape(ctx, c => {
      c.moveTo(0, -18);
      c.quadraticCurveTo(-25, -33, -53, -23);
      c.lineTo(-53, 24);
      c.quadraticCurveTo(-24, 21, 0, 32);
      c.quadraticCurveTo(24, 21, 53, 24);
      c.lineTo(53, -23);
      c.quadraticCurveTo(25, -33, 0, -18);
      c.closePath();
    }, shade(ctx, -27, 33, '#82aab3', '#476b85'), ink, 1.8);
    page(ctx, -49, -2, '#e6dcc4');
    page(ctx, 49, -2, '#e6dcc4');
    page(ctx, -49, 0, '#f7edda');
    page(ctx, 49, 0, paper);
    shape(ctx, c => {
      c.moveTo(-34, 19);
      c.lineTo(-34, 32);
      c.lineTo(-29, 28);
      c.lineTo(-24, 32);
      c.lineTo(-24, 20);
      c.closePath();
    }, '#d58a75', '#965f58', .7);
    if (turn > 0 && turn < 1) {
      const lift = 23 * Math.sin(Math.PI * turn);
      const x = 49 * Math.cos(Math.PI * turn);
      ctx.save();
      ctx.globalAlpha = ease(turn / .08) * ease((1 - turn) / .08);
      page(ctx, x, lift, shade(ctx, -22 - lift, 28, '#fffdf5', '#e2d1b0'), lift * .62);
      ctx.restore();
    }
  }

  function readingLine(y, t) {
    // This is the same curve drawn on the right page.
    const start = {x: 49 * .16, y: y - 2};
    const middle = {x: 49 * .5, y: y - 6};
    const end = {x: 49 * .84, y: y - 4};
    return {
      x: mix(mix(start.x, middle.x, t), mix(middle.x, end.x, t), t),
      y: mix(mix(start.y, middle.y, t), mix(middle.y, end.y, t), t)
    };
  }

  function readingFinger(t, turn) {
    const nextLine = ease((t - 1) / .34);
    const first = readingLine(-15, ease(t / 1));
    const second = readingLine(-1, ease((t - 1.34) / .97));
    const catchPage = ease((t - 2.31) / .72);
    const release = ease((t - 3.45) / .89);
    const scanX = mix(first.x, second.x, nextLine);
    const scanY = mix(first.y, second.y, nextLine) - 4 * Math.sin(Math.PI * nextLine);
    return {
      x: mix(mix(scanX, 49 * Math.cos(Math.PI * turn), catchPage), 49 * .16, release),
      y: mix(mix(scanY, 22 - 23 * Math.sin(Math.PI * turn), catchPage), -17, release)
    };
  }

  const reading = {
    label: '책 읽기',
    duration: 4.8,
    held: true,
    body(p, t, side) {
      const scan = Math.sin(tau * t / 2.4);
      p.lean = (side || 1) * (3 + .9 * scan);
      p.headAngle = (side || 1) * (7.2 + 2.8 * scan);
      p.bodyY -= 2.6;
      p.exprCalm = 1;
    },
    frame(cfg, pose, t) {
      const turn = ease((t - 3.03) / 1.12);
      const finger = readingFinger(t, turn);
      const layout = heldLayout(cfg, pose, 322, -3 * handSide(cfg), .78);
      const sideOfHand = handSide(cfg);
      const curl = ease((t - 2.64) / .38) * (1 - ease((t - 3.51) / .42));
      return {
        point: layout.point,
        bounds: [-58, -52, 116, 88],
        hands: [
          hand('reader', sideOfHand, .98, layout.point(finger.x, finger.y), sideOfHand * (105 + 13 * curl), curl),
          direction(cfg)
            ? hand('support', sideOfHand, .84, layout.point(-49, 17), sideOfHand * 72)
            : hand('support', -sideOfHand, .98, layout.point(-48, 16), -sideOfHand * 81)
        ],
        paint: ctx => book(ctx, turn)
      };
    }
  };

  const documentHalfWidth = 34;

  function documentOutline(c) {
    c.moveTo(-documentHalfWidth, -46);
    c.quadraticCurveTo(-4, -49, 24, -46);
    c.quadraticCurveTo(30, -45, documentHalfWidth, -36);
    c.lineTo(documentHalfWidth, 44);
    c.quadraticCurveTo(1, 47, -documentHalfWidth, 44);
    c.quadraticCurveTo(-36, 0, -documentHalfWidth, -46);
    c.closePath();
  }

  function documentBack(ctx) {
    shape(ctx, documentOutline, shade(ctx, -46, 46, '#fffdf5', '#f0eee4'), '#82948e', 1.1);
    shape(ctx, c => {
      c.moveTo(24, -46);
      c.quadraticCurveTo(30, -44, documentHalfWidth, -36);
      c.quadraticCurveTo(28, -39, 24, -37);
      c.quadraticCurveTo(26, -41, 24, -46);
    }, '#e2e7df', '#aebcb0', .75);
  }

  function documentStack(ctx, page) {
    function movingSheet() {
      ctx.save();
      ctx.translate(page.x, page.y);
      ctx.rotate(page.roll);
      ctx.scale(page.width, 1);
      ctx.translate(-documentHalfWidth, 0);
      documentBack(ctx);
      ctx.restore();
    }

    for (const [x, y, roll, fill] of [
      [-3.8, 4.4, -.064, '#bfd3cc'],
      [2.4, 2.4, .043, '#e2e7dc']
    ]) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(roll);
      shape(ctx, documentOutline, fill, '#91a59d', .95);
      ctx.restore();
    }
    const turning = page.progress > 0 && page.progress < 1;
    const tucking = page.progress >= .5;
    if (turning && tucking) movingSheet();
    documentBack(ctx);
    if (turning && !tucking) movingSheet();
  }

  function documentReview(t) {
    return ease((t - .12) / .72) * (1 - ease((t - 4.92) / .6));
  }

  const documents = {
    label: '서류 읽기',
    duration: 5.6,
    held: true,
    body(p, t, side) {
      const read = documentReview(t);
      const scan = Math.sin(tau * (t / 2.8));
      const nod = Math.sin(Math.PI * ease((t - 3.68) / .62)) ** 2;
      p.lean = (side || 1) * (2 + 2.6 * read + scan);
      p.headAngle = (side || 1) * (3.4 + read * (6.6 + 2.9 * scan) + 3.8 * nod);
      p.bodyY += 1.5 * read + 1.1 * nod;
      p.exprQuiet = 1;
    },
    frame(cfg, pose, t) {
      const progress = ease((t - 2.2) / 1.18);
      const lift = Math.sin(Math.PI * progress) ** 2;
      // The printed face stays toward Cloudy as the sheet slides behind the stack.
      const page = {
        progress,
        x: documentHalfWidth + 25 * lift,
        y: -13 * lift,
        width: Math.cos(74 * radians * lift),
        roll: -7 * radians * lift
      };
      const grip = ease((t - 1.66) / .54) * (1 - ease((t - 3.38) / .48));
      const side = direction(cfg);
      const mirror = handSide(cfg);
      const layout = heldLayout(cfg, pose, 321 - 8 * documentReview(t), mirror * (-6 + 3 * lift), .82);
      const pinch = layout.point(mix(33, page.x, grip), mix(22, page.y, grip));
      return {
        point: layout.point,
        bounds: [-51, -77, 126, 136],
        hands: [
          hand('pencil', mirror, side ? .94 : .98, pinch, mirror * mix(82, 69, grip)),
          side
            ? hand('writingSupport', mirror, .84, layout.point(-35, 20), mirror * 79)
            : hand('writingSupport', -mirror, .98, layout.point(-documentHalfWidth, 24), -mirror * 86)
        ],
        paint: ctx => documentStack(ctx, page)
      };
    }
  };

  const highFiveImpact = .98;

  function highFiveBeat(t) {
    const lower = ease((t - 1.43) / .72);
    return {
      lift: ease((t - .10) / .55) * (1 - lower),
      reach: ease((t - .10) / .4) * (1 - lower),
      ready: ease((t - .58) / .17) * (1 - ease((t - .76) / .19)),
      hit: ease((t - .77) / (highFiveImpact - .77)) * (1 - ease((t - highFiveImpact) / .18)),
      recoil: Math.sin(Math.PI * ease((t - highFiveImpact) / .35)) ** 2,
      open: ease((t - .27) / .38) * (1 - ease((t - 1.47) / .55))
    };
  }

  function highFiveSpark(ctx, age, side) {
    const spread = 8 * ease(age);
    ctx.save();
    ctx.scale(side < 0 ? -1 : 1, 1);
    ctx.globalAlpha = (1 - age) ** 1.25;
    for (const [angle, distance, length] of [[side ? -106 : -138, 22, 6], [-83, 26, 9], [-37, 23, 11], [12, 20, 7]]) {
      const a = angle * radians;
      const r = distance + spread;
      shape(ctx, c => {
        c.moveTo(Math.cos(a) * r, Math.sin(a) * r);
        c.lineTo(Math.cos(a) * (r + length), Math.sin(a) * (r + length));
      }, null, '#e2a967', 2.15);
    }
    ctx.translate(22 + spread, -24 - .5 * spread);
    shape(ctx, c => {
      c.moveTo(0, -6);
      c.quadraticCurveTo(1.8, -1.8, 6, 0);
      c.quadraticCurveTo(1.8, 1.8, 0, 6);
      c.quadraticCurveTo(-1.8, 1.8, -6, 0);
      c.quadraticCurveTo(-1.8, -1.8, 0, -6);
    }, '#fff1b7', '#e7ac70', .85);
    ctx.restore();
  }

  const highFive = {
    label: '하이파이브',
    duration: 2.4,
    once: true,
    held: true,
    body(p, t, side) {
      const {lift, ready, hit, recoil} = highFiveBeat(t);
      const toward = side || 1;
      p.bodyX += toward * (3.6 * hit - 2.2 * ready);
      p.bodyY += 1.8 * ready - 2.2 * lift - 3.2 * hit + 2.6 * recoil;
      p.lean += toward * (2 * lift - 2.8 * ready + 4.2 * hit - 1.8 * recoil);
      p.headAngle += toward * (3.2 * lift - 4.6 * hit + 2.4 * recoil);
      p.armFar += side ? -12 * lift - 6 * hit : 31 - 12 * lift + 6 * hit;
      p.elbowFar += 12 * lift + 7 * hit;
      p.exprExcited = lift;
    },
    frame(cfg, pose, t) {
      const side = direction(cfg);
      const toward = side || 1;
      const {lift, reach, ready, hit, recoil, open} = highFiveBeat(t);
      const [x, y] = cfg.shoulders[0];
      const dx = mix(side ? 1 : 32, side ? 56 : 48, reach) - 5 * ready + (side ? 23 : 11) * hit - 6 * recoil;
      const dy = mix(85, side ? -28 : -46, lift) + 4 * ready - (side ? 4 : 9) * hit + 3 * recoil;
      const palm = bodyPoint({x: x + toward * dx, y: y + dy}, pose);
      const roll = -toward * (mix(side ? 2 : 17, side ? 157 : 164, lift) + 13 * hit - 10 * recoil);
      const mirror = (side === -1 ? 1 : -1) * (side ? .84 + .1 * hit : 1);
      const size = .88 + .15 * open + .14 * hit;
      const age = (t - highFiveImpact) / .27;
      const impact = bodyPoint({x: x + toward * (side ? 79 : 59), y: y - (side ? 32 : 55)}, pose);
      return {
        hands: [hand('highFive', mirror, size, palm, roll, open)],
        companionDrop: side >= 0 ? 49 * lift : 0,
        bounds: [-49, -49, 98, 97],
        point: (x, y) => ({x: impact.x + x, y: impact.y + y}),
        foreground: age >= 0 && age < 1 ? ctx => highFiveSpark(ctx, age, side) : null
      };
    }
  };

  const games = root.CloudyActivityGames.createClips({heldLayout, bodyPoint, shape, box, oval, shade});
  const clips = {music, ...games, writing, reading, documents, 'high-five': highFive, ...trip.clips};

  function clipTime(clip, seconds) {
    return clip.once ? Math.max(0, Math.min(clip.duration, seconds)) : loop(seconds, clip.duration);
  }

  function pose(action, seconds, yaw) {
    const clip = clips[action];
    const t = clipTime(clip, seconds);
    const side = yaw < -21 ? -1 : yaw > 21 ? 1 : 0;
    if (clip.sample) return clip.sample(t, side);
    const p = M.pose('idle', t * 4.6 / clip.duration);
    clip.body(p, t, side);
    if (clip.held) {
      p.idleGesture = 0;
      // Raised hands use the existing foreground pass at the normal framing.
      p.airArms = 1;
    }
    return p;
  }

  class Renderer extends BaseRenderer {
    render(pose, yaw, time, options = {}) {
      this.activity = Object.hasOwn(clips, options.action) ? clips[options.action] : null;
      this.activityTime = this.activity ? clipTime(this.activity, options.activityTime ?? time) : 0;
      super.render(pose, yaw, time, this.activity?.fall ? {...options, companion: false} : options);
    }

    renderView(cfg, pose, opacity, time) {
      if (this.activity?.fall) {
        this.renderTrip(cfg, pose, opacity, time);
        return;
      }
      const frame = this.activity?.frame(cfg, pose, this.activityTime);
      this.activityFrame = frame;
      this.handOverlays = [];
      const posed = this.activity?.held ? {...pose} : pose;
      if (this.activity?.held) {
        // Solve against the pose being painted so the moving props and fingers
        // share the same body transform even while the pose is transitioning.
        frame.hands.forEach((grip, index) => aimHand(cfg, posed, index, grip));
      }
      super.renderView(cfg, posed, opacity, time);
      if (frame?.foreground) this.paintLayer(frame, frame.foreground);
      for (const placement of this.handOverlays) this.paintHand(placement, 'front');
    }

    renderTrip(cfg, pose, opacity, time) {
      // Reuse the rig's draw order, then project every character mesh together.
      this.activityFrame = null;
      const meshes = [];
      this.tripMeshes = meshes;
      try {
        super.renderView(cfg, pose, opacity, time);
      } finally {
        this.tripMeshes = null;
      }
      const {map, ground} = trip.layout(cfg, this.activityTime, this.activity.fall, meshes, name => this.tripOutline(name));
      this.paintLayer(ground, ground.shadow, 'ground');
      for (const mesh of meshes) super.mesh(mesh.name, p => map(mesh.map(p)), ...mesh.args);
      if (ground.impact) this.paintLayer(ground, ground.impact, 'ground');
    }

    tripOutline(name) {
      if (!this.textures[name] || !this.images[name]) return [];
      this.tripOutlines ??= new Map();
      if (!this.tripOutlines.has(name)) {
        this.tripOutlines.set(name, trip.contour(this.images[name], this.parts[name].bbox));
      }
      return this.tripOutlines.get(name);
    }

    face(cfg, pose, opacity, time) {
      const frame = this.activityFrame;
      if (frame?.back) this.paintLayer(frame, frame.back);
      super.face(cfg, pose, opacity, time);
      if (frame?.paint) this.paintLayer(frame, frame.paint);
      if (frame?.farArmInFront && cfg.prefix !== 'front') {
        this.paintArm(cfg, 1, pose, opacity, frame.hands[1]);
      }
    }

    limb(cfg, index, type, pose, opacity, surface) {
      const grip = type === 'arm' && this.activityFrame?.hands?.[index];
      if (!grip) {
        super.limb(cfg, index, type, pose, opacity, surface);
        return;
      }
      // The far hand strikes the top of the rhythm pad from both side views.
      if (index === 1 && cfg.prefix !== 'front' && this.activityFrame.farArmInFront) return;
      this.paintArm(cfg, index, pose, opacity, grip, surface);
    }

    paintArm(cfg, index, pose, opacity, grip, surface) {
      const arm = cfg.arms[index];
      const sleeve = cfg.prefix + '_' + String(arm.i).padStart(2, '0');
      const connected = sleeve + '_connected';
      const previous = this.textures[connected];
      this.activityHand = {
        name: cfg.prefix + '_' + String(arm.hand).padStart(2, '0'),
        sleeve,
        cuff: arm.cuff,
        grip,
        flex: handSide(cfg) * pose[index === 0 ? 'wristNear' : 'wristFar']
      };
      // Use the rig's sleeve, detached hand and cuff rim draw order.
      this.textures[connected] = null;
      try {
        super.limb(cfg, index, 'arm', pose, opacity, surface);
      } finally {
        this.textures[connected] = previous;
        this.activityHand = null;
      }
    }

    mesh(name, map, ...options) {
      if (this.tripMeshes) {
        this.tripMeshes.push({name, map, args: options});
        return;
      }
      const active = this.activityHand;
      if (active) {
        // The custom opening mask already covers the wrist at the top edge.
        if (name === active.sleeve + '_rim') return;
        if (name === active.sleeve) active.sleeveMap = map;
      }
      super.mesh(name, map, ...options);
    }

    drawSprite(name, pivot, location, scale, angle, opacity) {
      const drop = this.activityFrame?.companionDrop;
      if (name === 'front_14' && drop) location = {x: location.x, y: location.y + drop};
      const active = this.activityHand;
      if (active?.name !== name) {
        super.drawSprite(name, pivot, location, scale, angle, opacity);
        return;
      }
      const placement = {...active, location, angle, opacity};
      this.paintHand(placement, 'paint');
      this.paintCuffForeground(active, opacity);
      if (active.grip.art.front) this.handOverlays.push(placement);
    }

    paintCuffForeground({sleeve, sleeveMap, cuff}, opacity) {
      const name = 'preview_cuff_' + sleeve;
      if (!this.textures[name]) {
        const part = this.parts[sleeve];
        const foreground = cuffForeground(sleeve, this.images[sleeve], cuff, part.bbox);
        this.parts[name] = part;
        this.uploadCanvas(name, foreground);
      }
      super.mesh(name, sleeveMap, opacity, 8, 26);
    }

    paintHand({grip, location, angle, flex, opacity}, layer) {
      const frame = {
        bounds: grip.art.bounds ?? [-15, -10, 30, 38],
        point(x, y) {
          // Seat the wrist inside the sleeve, then bend into the hand pose.
          const roll = angle - flex * (1 - ease((y + 1) / 10));
          const offset = rotate({x: x * grip.mirror * grip.size, y: y * grip.size}, roll * radians);
          return {x: location.x + offset.x, y: location.y + offset.y};
        }
      };
      this.paintLayer(frame, ctx => grip.art[layer](ctx, grip.amount), 'hand', opacity, 12);
    }

    paintLayer({bounds, point}, paint, slot = 'prop', opacity = 1, rows = 1) {
      const name = 'preview_activity_' + slot;
      this.activityCanvases ??= {};
      if (!this.activityCanvases[slot]) {
        const canvas = document.createElement('canvas');
        this.activityCanvases[slot] = canvas.getContext('2d');
      }
      const [x, y, w, h] = bounds;
      const scale = 2;
      const ctx = this.activityCanvases[slot];
      const canvas = ctx.canvas;
      if (canvas.width !== w * scale) canvas.width = w * scale;
      if (canvas.height !== h * scale) canvas.height = h * scale;
      ctx.setTransform(scale, 0, 0, scale, -x * scale, -y * scale);
      ctx.clearRect(x, y, w, h);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      paint(ctx);
      this.uploadCanvas(name, canvas);
      this.parts[name] = {bbox: [0, 0, canvas.width, canvas.height]};
      this.mesh(name, p => point(x + p.x / scale, y + p.y / scale), opacity, 1, rows);
    }

    uploadCanvas(name, canvas) {
      const gl = this.gl;
      const newTexture = !this.textures[name];
      if (newTexture) this.textures[name] = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.textures[name]);
      if (newTexture) {
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      }
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    }
  }

  root.CloudyActivityPreview = {clips, pose, Renderer};
})(window);
