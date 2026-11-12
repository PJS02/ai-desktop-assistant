'use strict';
(function (root) {
  const ease = root.CloudyMotion.smoothstep;
  const mix = (a, b, t) => a + (b - a) * t;
  const impactTime = .98;
  const duration = 2.4;
  const bounds = [-16, -10, 32, 47];
  const contact = () => ({x: 0, y: 11});
  const textureName = open => 'fx_high_five_palm_' + Math.round(open * 6);

  function beat(t) {
    const lower = ease((t - 1.43) / .72);
    return {
      lift: ease((t - .10) / .55) * (1 - lower),
      reach: ease((t - .10) / .4) * (1 - lower),
      ready: ease((t - .58) / .17) * (1 - ease((t - .76) / .19)),
      hit: ease((t - .77) / (impactTime - .77)) * (1 - ease((t - impactTime) / .18)),
      recoil: Math.sin(Math.PI * ease((t - impactTime) / .35)) ** 2,
      open: ease((t - .27) / .38) * (1 - ease((t - 1.47) / .55))
    };
  }

  function body(pose, t, side) {
    const {lift, ready, hit, recoil} = beat(t);
    const toward = side || 1;
    pose.bodyX += toward * (3.6 * hit - 2.2 * ready);
    pose.bodyY += 1.8 * ready - 2.2 * lift - 3.2 * hit + 2.6 * recoil;
    pose.lean += toward * (2 * lift - 2.8 * ready + 4.2 * hit - 1.8 * recoil);
    pose.headAngle += toward * (3.2 * lift - 4.6 * hit + 2.4 * recoil);
    pose.armFar += side ? -12 * lift - 6 * hit : 31 - 12 * lift + 6 * hit;
    pose.elbowFar += 12 * lift + 7 * hit;
    pose.exprExcited = lift;
  }

  function layout(cfg, pose, t, bodyPoint) {
    const side = cfg.prefix === 'left' ? -1 : cfg.prefix === 'right' ? 1 : 0;
    const toward = side || 1;
    const {lift, reach, ready, hit, recoil, open} = beat(t);
    const [x, y] = cfg.shoulders[0];
    const dx = mix(side ? 1 : 32, side ? 56 : 48, reach) - 5 * ready + (side ? 23 : 11) * hit - 6 * recoil;
    const dy = mix(85, side ? -28 : -46, lift) + 4 * ready - (side ? 4 : 9) * hit + 3 * recoil;
    return {
      lift, open,
      palm: bodyPoint({x: x + toward * dx, y: y + dy}, pose),
      roll: -toward * (mix(side ? 2 : 17, side ? 157 : 164, lift) + 13 * hit - 10 * recoil),
      mirror: (side === -1 ? 1 : -1) * (side ? .84 + .1 * hit : 1),
      size: .88 + .15 * open + .14 * hit,
      impact: bodyPoint({x: x + toward * (side ? 79 : 59), y: y - (side ? 32 : 55)}, pose)
    };
  }

  const jumpImpact = .76;

  function jumpBeat(t) {
    const bell = (start, end) => t > start && t < end
      ? Math.sin(Math.PI * (t - start) / (end - start)) ** 2 : 0;
    const airTime = Math.max(0, Math.min(1, (t - .46) / .60));
    return {
      crouch: bell(.12, .49),
      flight: 4 * airTime * (1 - airTime),
      land: bell(1.04, 1.34),
      lift: ease((t - .24) / .40) * (1 - ease((t - 1.04) / .56)),
      reach: ease((t - .51) / (jumpImpact - .51)) * (1 - ease((t - jumpImpact) / .39))
    };
  }

  function jumpBody(pose, t, side) {
    const {crouch, flight, land, lift, reach} = jumpBeat(t);
    const toward = side || -1;
    const height = 30 * flight;
    const footTravel = (side === 1 ? -1 : 1) * toward * flight;
    pose.bodyX += toward * (8 * reach - 4 * crouch);
    pose.bodyY += 10 * crouch - height + 9 * land;
    pose.lean += toward * (8 * reach - 3 * crouch + 3 * land);
    pose.headAngle += toward * (4 * lift - 6 * reach);
    pose.footNearX += 8 * footTravel;
    pose.footFarX += 4 * footTravel;
    pose.footNearY -= height + 3 * flight;
    pose.footFarY -= height + 7 * flight;
    pose.footNearAngle += 9 * flight;
    pose.footFarAngle -= 11 * flight;
    pose.armNear -= 13 * crouch + 30 * flight;
    pose.elbowNear += 12 * flight + 6 * land;
    pose.airborne = flight;
    pose.framingZoom = .95; // Reserve headroom throughout the hop.
    pose.exprExcited = lift;
  }

  function jumpLayout(cfg, pose, t, bodyPoint) {
    const toward = cfg.prefix === 'right' ? 1 : -1;
    const front = cfg.prefix === 'front';
    const {crouch, lift, reach} = jumpBeat(t);
    const [x, y] = cfg.shoulders[1];
    const stretchX = front ? 32 : 36;
    const stretchY = front ? 34 : 19;
    const dx = mix(5 - 9 * crouch, 45, lift) + stretchX * reach;
    const dy = mix(91 - 4 * crouch, -24, lift) - stretchY * reach;
    const palm = bodyPoint({x: x + toward * dx, y: y + dy}, pose);
    return {
      lift, reach, open: lift, palm,
      impact: bodyPoint({x: x + toward * (45 + stretchX), y: y - 24 - stretchY}, pose),
      roll: -toward * mix(5, 153 + (front ? 7 : 11) * reach, lift),
      mirror: toward * (.90 + .06 * reach),
      size: .91 + .12 * lift + .10 * reach
    };
  }

  const jump = {impactTime: jumpImpact, duration: 1.85, body: jumpBody, layout: jumpLayout};

  function paintPalm(ctx, open) {
    const thumb = mix(-8.3, -12.1, open);
    const index = mix(-4.9, -7.2, open);
    const middle = mix(-1.5, -2.2, open);
    const ring = mix(2, 3.5, open);
    const pinky = mix(5, 8.4, open);
    const indexTip = mix(20.6, 28.5, open);
    const middleTip = mix(21.7, 32, open);
    const ringTip = mix(21.2, 30, open);
    const pinkyTip = mix(18.7, 24.2, open);
    const tint = ctx.createLinearGradient(-7, 0, 7, 20);
    tint.addColorStop(0, '#fff5e9');
    tint.addColorStop(.51, '#ffe4d4');
    tint.addColorStop(1, '#edb4a5');
    ctx.beginPath();
    ctx.moveTo(-5.5, -8);
    ctx.bezierCurveTo(-5.5, -1.8, -5.8, 3.1, -7.6, 5.5);
    ctx.bezierCurveTo(thumb - 2.6, 7.9, thumb - 2, 13.7, thumb + .5, 14.3);
    ctx.quadraticCurveTo(thumb + 2.1, 14.7, -6.4, 11.9);
    ctx.quadraticCurveTo(index - 1.8, indexTip - 6.2, index - 1.9, indexTip - 1.2);
    ctx.bezierCurveTo(index - 2, indexTip + 1.9, index + 1.9, indexTip + 1.9, index + 2, indexTip - 1);
    ctx.lineTo(mix(-3.2, -4.7, open), mix(17.8, 18, open));
    ctx.quadraticCurveTo(middle - 2.1, middleTip - 4.8, middle - 1.9, middleTip - .8);
    ctx.bezierCurveTo(middle - 1.8, middleTip + 2, middle + 2, middleTip + 2, middle + 2, middleTip - .8);
    ctx.lineTo(mix(.2, .45, open), mix(18.8, 19.2, open));
    ctx.quadraticCurveTo(ring - 2, ringTip - 4.1, ring - 1.8, ringTip - .6);
    ctx.bezierCurveTo(ring - 1.6, ringTip + 1.9, ring + 1.9, ringTip + 2, ring + 1.9, ringTip - .9);
    ctx.lineTo(mix(3.5, 5.1, open), mix(16.7, 17.1, open));
    ctx.quadraticCurveTo(pinky - 1.7, pinkyTip - 4.2, pinky - 1.6, pinkyTip - .5);
    ctx.bezierCurveTo(pinky - 1.4, pinkyTip + 1.7, pinky + 2, pinkyTip + 1.1, pinky + 1.8, pinkyTip - 1.4);
    ctx.bezierCurveTo(pinky + 1.6, 19.1, 8.2, 12.6, 6.9, 8.7);
    ctx.quadraticCurveTo(5.3, 4, 5.5, -8);
    ctx.closePath();
    ctx.fillStyle = tint;
    ctx.fill();
    ctx.strokeStyle = '#a17369';
    ctx.lineWidth = .73;
    ctx.stroke();

    ctx.save();
    ctx.globalAlpha = .62 * open;
    ctx.beginPath();
    ctx.moveTo(-6.1, 10.4);
    ctx.quadraticCurveTo(-1.7, 10.7, -.6, 5.5);
    ctx.moveTo(-2.5, 13.6);
    ctx.quadraticCurveTo(1, 15.6, 5.3, 13.2);
    ctx.strokeStyle = '#ba8175';
    ctx.lineWidth = .64;
    ctx.stroke();
    ctx.restore();
  }

  root.CloudyHighFive = {impactTime, duration, bounds, contact, textureName, body, layout, paintPalm, jump};
})(window);
