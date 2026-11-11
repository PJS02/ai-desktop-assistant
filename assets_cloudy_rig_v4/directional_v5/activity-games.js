'use strict';
(function (root) {
  const {smoothstep: ease} = root.CloudyMotion;
  const {hand, rearGripFingers} = root.CloudyActivityHands;
  const tau = 2 * Math.PI;
  const ink = '#34474e';
  const mix = (a, b, t) => a + (b - a) * t;
  const faceSide = cfg => cfg.prefix === 'left' ? -1 : cfg.prefix === 'right' ? 1 : 0;
  const beat = (t, period) => Math.max(0, Math.sin(tau * t / period)) ** 2;

  function createClips({heldLayout, bodyPoint, shape, box, oval, shade}) {
    function heldDevice(cfg, pose, height, twist, pitch) {
      const side = faceSide(cfg);
      const mirror = side === 1 ? -1 : 1;
      const yaw = side * Math.PI / 4.3;
      const tilt = pitch * Math.PI / 180;
      const center = bodyPoint({x: 180 + side * 27, y: height}, pose);
      const roll = pose.lean + twist;
      const cosRoll = Math.cos(roll * Math.PI / 180);
      const sinRoll = Math.sin(roll * Math.PI / 180);
      const width = mirror * Math.cos(yaw);
      const slope = Math.cos(tilt);
      const shear = -Math.sin(yaw) * Math.sin(tilt);
      const inwardX = -Math.sin(yaw) * Math.cos(tilt);
      const inwardY = -Math.sin(tilt);
      return {
        side, mirror, roll,
        point(x, y, depth = 0) {
          // Positive depth moves from the rear cover toward Cloudy's face.
          const px = width * x + shear * y + inwardX * depth;
          const py = slope * y + inwardY * depth;
          return {x: center.x + px * cosRoll - py * sinRoll, y: center.y + px * sinRoll + py * cosRoll};
        },
        onSurface(ctx, depth, paint) {
          const y = inwardY * depth / slope;
          const x = (inwardX * depth - shear * y) / width;
          ctx.save();
          ctx.translate(x, y);
          paint(ctx);
          ctx.restore();
        }
      };
    }

    function casing(ctx, layout, thickness, outline, edge, rear) {
      for (let depth = thickness; depth > 0; depth -= 1.5) {
        layout.onSurface(ctx, depth, c => shape(c, outline, edge, depth === thickness ? ink : null, 1.6));
      }
      shape(ctx, outline, rear, ink, 1.9);
    }

    function buttonDepth(thickness, pressure) {
      return thickness + 2 - 1.3 * pressure;
    }

    function deviceGrips(layout, thickness, buttonX, buttonY, near, far) {
      const {side, mirror, roll} = layout;
      return [near, far].map((pressure, index) => {
        const isNear = index === 0;
        const sign = isNear || side ? mirror : -mirror;
        const size = side ? (isNear ? .94 : .86) : 1;
        const point = layout.point(isNear ? buttonX : -buttonX, buttonY, buttonDepth(thickness, pressure));
        return hand('device', sign, size, point, sign * (!isNear && side ? 75 : 88) + roll, pressure);
      });
    }

    function controls(ctx, layout, thickness, x, y, near, far, fill) {
      layout.onSurface(ctx, buttonDepth(thickness, near), c => {
        box(c, x - 7, y - 2, 14, 4, 1, fill);
        box(c, x - 2, y - 7, 4, 14, 1, fill);
      });
      layout.onSurface(ctx, buttonDepth(thickness, far), c => {
        for (const [dx, dy] of [[0, 0], [-5, -5], [0, -10], [5, -5]]) {
          oval(c, -x + dx, y + dy, 2.4, 2.4, fill);
        }
      });
    }

    function padOutline(c) {
      c.moveTo(-32, -21);
      c.bezierCurveTo(-47, -22, -51, -4, -54, 12);
      c.bezierCurveTo(-58, 36, -43, 34, -28, 16);
      c.quadraticCurveTo(0, 8, 28, 16);
      c.bezierCurveTo(43, 34, 58, 36, 54, 12);
      c.bezierCurveTo(51, -4, 47, -22, 32, -21);
      c.quadraticCurveTo(0, -16, -32, -21);
      c.closePath();
    }

    const gaming = {
      label: '게임패드',
      game: true,
      duration: 3.2,
      held: true,
      body(p, t) {
        const phase = tau * t / this.duration;
        p.lean = 7.1 * Math.sin(phase) + 2.1 * Math.sin(2 * phase);
        p.bodyX = 3.2 * Math.sin(phase);
        p.bodyY = -1.2 - 3.5 * Math.sin(phase) ** 2;
        p.headAngle = -3.9 * Math.sin(phase - .18);
        p.exprQuiet = 1;
      },
      frame(cfg, pose, t) {
        const near = beat(t + .272, .32);
        const far = beat(t + .112, .32);
        const twist = 6 * Math.sin(tau * t / this.duration - .3);
        const layout = heldDevice(cfg, pose, 327, twist, 27);
        const thickness = 10;
        const buttonX = 34;
        const buttonY = 2;
        return {
          point: layout.point,
          bounds: [-73, -34, 146, 73],
          hands: deviceGrips(layout, thickness, buttonX, buttonY, near, far),
          paint(ctx) {
            // The near cover and edge occlude the controls on the player side.
            controls(ctx, layout, thickness, buttonX, buttonY, near, far, '#4f626f');
            casing(ctx, layout, thickness, padOutline, '#648e94', shade(ctx, -21, 30, '#d4efe7', '#79aaa6'));
            box(ctx, -17, -11, 34, 22, 4, '#9fcac2', '#668e8c', 1.15);
            shape(ctx, c => {
              c.moveTo(-10, 6);
              c.quadraticCurveTo(0, 9, 10, 6);
              for (const side of [-1, 1]) {
                c.moveTo(side * 30, -12);
                c.quadraticCurveTo(side * 40, -11, side * 44, 1);
                c.quadraticCurveTo(side * 47, 13, side * 46, 20);
              }
            }, null, '#64918d', 1.4);
            if (layout.side) rearGripFingers(ctx, -53, 10, far);
          }
        };
      }
    };

    const handheld = {
      label: '휴대용 콘솔',
      game: true,
      held: true,
      duration: 4.8,
      body(p, t, side) {
        const focus = ease((t - .32) / 1.1) * (1 - ease((t - 3.05) / 1.25));
        const release = ease((t - 3.07) / .33) * (1 - ease((t - 3.9) / .5));
        p.lean = (side || 1) * (1.5 + focus * 6);
        p.headAngle = (side || 1) * (4 + focus * 5.5 - release * 8);
        p.bodyY += 4.5 * focus - 2.5 * release;
        p.exprQuiet = 1 - release;
        p.exprHappy = release;
        p.blink *= 1 - release;
      },
      frame(cfg, pose, t) {
        const focus = ease((t - .32) / 1.1) * (1 - ease((t - 3.05) / 1.25));
        const far = beat(t + .19, .4);
        const near = beat(t + .02, .4);
        const twist = (cfg.prefix === 'right' ? -1 : 1) * (-6 + 4 * Math.sin(tau * t / this.duration));
        const layout = heldDevice(cfg, pose, 326 - 18 * focus, twist, 31 + 3 * focus);
        const thickness = 7;
        const buttonX = 44;
        const buttonY = 3;
        return {
          point: layout.point,
          bounds: [-71, -36, 142, 63],
          hands: deviceGrips(layout, thickness, buttonX, buttonY, near, far),
          paint(ctx) {
            layout.onSurface(ctx, thickness, c => box(c, -34, -17, 68, 32, 4, '#485573'));
            controls(ctx, layout, thickness, buttonX, buttonY, near, far, '#5b6084');
            casing(ctx, layout, thickness, c => c.roundRect(-57, -22, 114, 43, 11),
              '#8387ab', shade(ctx, -22, 21, '#e0dcf4', '#a6aacb'));
            box(ctx, -29, -9, 58, 22, 4, '#b2b4d2', '#8e91b3', 1.1);
            for (let x = -15; x <= 15; x += 6) {
              box(ctx, x - 1.1, -15, 2.2, 4.2, 1, '#858bab');
            }
            shape(ctx, c => {
              c.moveTo(-51, -9);
              c.quadraticCurveTo(-50, -16, -44, -17);
              c.moveTo(51, -9);
              c.quadraticCurveTo(50, -16, 44, -17);
            }, null, '#eae8fb', 1.5);
            if (layout.side) rearGripFingers(ctx, -56, 3, far);
          }
        };
      }
    };

    function wheel(ctx, turn) {
      oval(ctx, 0, 2, 42, 41, null, ink, 10);
      oval(ctx, 0, 0, 42, 40, null, shade(ctx, -41, 41, '#6d91a2', '#354c5b'), 7.5);
      shape(ctx, c => {
        c.moveTo(-39, -5);
        c.quadraticCurveTo(-26, -1, -9, 1);
        c.lineTo(9, 1);
        c.quadraticCurveTo(26, -1, 39, -5);
        c.lineTo(39, 5);
        c.lineTo(10, 9);
        c.lineTo(5, 36);
        c.lineTo(-5, 36);
        c.lineTo(-10, 9);
        c.lineTo(-39, 5);
        c.closePath();
      }, shade(ctx, -5, 36, '#d2eee8', '#6caaa9'), ink, 1.6);
      oval(ctx, 0, 3, 13, 11, '#597482', ink, 1.6);
      oval(ctx, 0, 2, 9.5, 7.5, '#b6e8dc');
      shape(ctx, c => {
        c.moveTo(-5, 3);
        c.quadraticCurveTo(-2, -3, 0, 0);
        c.quadraticCurveTo(2, -3, 5, 3);
      }, null, '#47747e', 1.5);
      box(ctx, -4, -44, 8, 8, 2, '#efba85', ink, 1.1);
      for (const side of [-1, 1]) {
        const amount = Math.max(0, side * turn / 32);
        box(ctx, 14 * side - 3, 1, 6, 4, 2, amount > .5 ? '#f5c786' : '#729c9e');
      }
    }

    function steering(t) {
      const phase = tau * t / 4.4;
      return 30 * Math.sin(phase) + 7 * Math.sin(2 * phase - .5);
    }

    const racing = {
      label: '레이싱',
      game: true,
      held: true,
      duration: 4.4,
      body(p, t) {
        const turn = steering(t);
        const bump = 3 * beat(t + .06, 1.1);
        p.bodyX = turn * .23;
        p.bodyY = 3.2 - bump;
        p.lean = .31 * turn;
        p.headAngle = -.18 * turn - bump * .4;
        p.footNearX = 6;
        p.footFarX = -5;
        p.exprCalm = 1;
      },
      frame(cfg, pose, t) {
        const side = faceSide(cfg);
        const mirror = side === 1 ? -1 : 1;
        const turn = steering(t);
        const roll = pose.lean + turn;
        const layout = heldLayout(cfg, pose, 314, turn, .76);
        return {
          point: layout.point,
          bounds: [-49, -49, 98, 99],
          hands: [
            hand('wheel', mirror, side ? .94 : 1, layout.point(42, 1), mirror * 82 + roll),
            side
              ? hand('wheel', mirror, .85, layout.point(-42, 2), mirror * 69 + roll)
              : hand('wheel', -mirror, 1, layout.point(-42, 1), -mirror * 82 + roll)
          ],
          paint: ctx => wheel(ctx, turn)
        };
      }
    };

    const rhythmBeat = .8;
    function tapAt(t, offset) {
      const phase = ((t - offset) % rhythmBeat + rhythmBeat) % rhythmBeat;
      return 1 - ease((phase - .035) / .18) + ease((phase - .66) / .14);
    }

    function rhythmCabinet(ctx, left, right) {
      box(ctx, -22, 189, 44, 12, 4, '#688e99', ink, 1.6);
      box(ctx, -12, 13, 24, 178, 8, shade(ctx, 13, 191, '#87a5ac', '#5d7889'), ink, 1.8);
      box(ctx, -4, 31, 8, 147, 3, '#a9c6c8');
      shape(ctx, c => {
        c.moveTo(-52, -11);
        c.quadraticCurveTo(0, -26, 52, -11);
        c.lineTo(58, 12);
        c.quadraticCurveTo(58, 23, 48, 23);
        c.lineTo(-48, 23);
        c.quadraticCurveTo(-58, 23, -58, 12);
        c.closePath();
      }, shade(ctx, -16, 23, '#e8eeff', '#8294b3'), ink, 1.8);
      for (const [x, power, muted, bright] of [
        [-27, left, '#c89ed4', '#f6d3ff'],
        [27, right, '#6eaeb1', '#b0f2df']
      ]) {
        oval(ctx, x, 1, 20.5, 12, '#607785', ink, 1.1);
        const height = 10 - 2 * power;
        oval(ctx, x, -2 + 2 * power, 17, height, power > .72 ? bright : muted, ink, 1.1);
        oval(ctx, x, -3 + 2 * power, 11, 4.5, power > .72 ? '#fff9e9' : bright);
        if (power > .58) oval(ctx, x, 0, 23, 14, null, bright, 1.45);
      }
      box(ctx, -9, 13, 18, 5, 2, '#4c6678');
      oval(ctx, 0, 15.5, 3, 1.1, left + right > .72 ? '#fff2b5' : '#a9d8cf');
    }

    const rhythm = {
      label: '리듬 게임',
      game: true,
      held: true,
      duration: 4.8,
      body(p, t) {
        const right = tapAt(t, .22);
        const left = tapAt(t, .62);
        p.lean = 3.5 * (right - left);
        p.bodyX = 4 * (right - left);
        p.bodyY = -3 + 8 * (left + right);
        p.headAngle = 3 * Math.sin(tau * (t - .15) / rhythmBeat);
        p.exprExcited = 1;
      },
      frame(cfg, _pose, t) {
        const side = faceSide(cfg);
        const mirror = side === 1 ? -1 : 1;
        const xScale = mirror * (side ? .82 : 1);
        const point = (x, y) => ({x: 180 + side * 29 + xScale * x, y: 333 + y});
        const right = tapAt(t, .22);
        const left = tapAt(t, .62);
        const farMirror = side ? mirror : -mirror;
        return {
          point,
          bounds: [-63, -22, 126, 226],
          farArmInFront: true,
          hands: [
            hand('tap', mirror, .97, point(mix(44, 27, right), mix(-23, 1, right)), mirror * mix(70, 44, right)),
            hand('tap', farMirror, side ? .84 : .97,
              point(mix(-44, -27, left), mix(-23, 1, left)), farMirror * mix(66, 44, left))
          ],
          paint: ctx => rhythmCabinet(ctx, left, right)
        };
      }
    };

    return {gaming, 'gaming-console': handheld, 'gaming-racing': racing, 'gaming-rhythm': rhythm};
  }

  root.CloudyActivityGames = {createClips};
})(window);
