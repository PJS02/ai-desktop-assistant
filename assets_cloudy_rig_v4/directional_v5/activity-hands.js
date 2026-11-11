'use strict';
(function (root) {
  const outline = '#815049';
  const crease = '#ba8175';
  const nail = '#ffede1';
  const mix = (a, b, t) => a + (b - a) * t;

  function skin(ctx, drawShape, palmShape, lineColor = outline, lineWidth = .92) {
    const tint = ctx.createLinearGradient(-7, 0, 7, 20);
    tint.addColorStop(0, '#fff5e9');
    tint.addColorStop(.51, '#ffe4d4');
    tint.addColorStop(1, '#edb4a5');
    const shape = new Path2D();
    drawShape(shape);
    shape.closePath();
    ctx.fillStyle = tint;
    ctx.fill(shape);
    ctx.lineWidth = lineWidth;
    ctx.strokeStyle = lineColor;
    if (!palmShape) {
      ctx.stroke(shape);
      return;
    }
    // Outline only the finger edges that extend beyond the palm.
    const outsidePalm = new Path2D();
    outsidePalm.rect(-32, -32, 64, 64);
    palmShape(outsidePalm);
    outsidePalm.closePath();
    ctx.save();
    ctx.clip(outsidePalm, 'evenodd');
    ctx.stroke(shape);
    ctx.restore();
  }

  function detail(ctx, path) {
    ctx.beginPath();
    path(ctx);
    ctx.lineWidth = .64;
    ctx.strokeStyle = crease;
    ctx.stroke();
  }

  function thumbnail(ctx, x, y, angle = 0) {
    ctx.beginPath();
    ctx.ellipse(x, y, 1.25, 1.8, angle, 0, Math.PI * 2);
    ctx.fillStyle = nail;
    ctx.fill();
  }

  function relaxed(ctx) {
    skin(ctx, c => {
      c.moveTo(-5.6, -8);
      c.bezierCurveTo(-5.7, -1, -5.3, 4.3, -6.7, 7.1);
      c.bezierCurveTo(-9.5, 10.2, -9.7, 14.1, -7.6, 14.4);
      c.quadraticCurveTo(-6.4, 14.6, -4.6, 12.4);
      c.bezierCurveTo(-5.8, 16.2, -4.2, 22.2, -2.2, 22.2);
      c.quadraticCurveTo(-.5, 22.1, -.9, 19.9);
      c.quadraticCurveTo(.6, 22.1, 2.5, 20.5);
      c.quadraticCurveTo(3.5, 19.9, 3.1, 18);
      c.quadraticCurveTo(5.3, 18.4, 5.6, 15.9);
      c.bezierCurveTo(8, 12, 5.5, 6.1, 5.3, 3.4);
      c.lineTo(5.5, -8);
    });
    detail(ctx, c => {
      c.moveTo(-.9, 19.9);
      c.quadraticCurveTo(-2.4, 16.5, -2, 14);
      c.moveTo(3.1, 18);
      c.quadraticCurveTo(1.6, 15.8, 1.5, 13.2);
    });
  }

  function padPalm(ctx) {
    skin(ctx, c => {
      c.moveTo(-5.9, -8);
      c.bezierCurveTo(-5.7, -2, -5.5, 3, -7, 6.6);
      c.bezierCurveTo(-8.2, 9.6, -7.5, 14.3, -4.8, 16.3);
      c.bezierCurveTo(-1.8, 18.8, 3.9, 18.8, 6.9, 15);
      c.bezierCurveTo(8.4, 13.4, 8.2, 11.7, 7.4, 10.4);
      c.quadraticCurveTo(8, 7.5, 5.8, 5.7);
      c.lineTo(5.6, -8);
    });
    detail(ctx, c => {
      c.moveTo(7.4, 10.4);
      c.quadraticCurveTo(5.2, 9.2, 2.6, 10.3);
      c.moveTo(7.2, 13.8);
      c.quadraticCurveTo(5.4, 12.6, 3.1, 13.6);
    });
  }

  function controllerThumb(pressure) {
    return {x: -7.9 - 3.2 * pressure, y: 14 + 4.2 * pressure};
  }

  function rearGripFingers(ctx, x, y, pressure) {
    ctx.save();
    ctx.translate(x + .6 * pressure, y - 1.6 * pressure);
    skin(ctx, c => {
      c.moveTo(-1.7, -5.9);
      c.bezierCurveTo(-4.2, -4.2, -3.3, -1.5, -2.2, -.2);
      c.quadraticCurveTo(-3.9, 2.4, -1.7, 4);
      c.quadraticCurveTo(-.9, 6.5, 1.2, 6.1);
      c.quadraticCurveTo(4.6, 5.8, 4.9, 4);
      c.quadraticCurveTo(6.9, 3.2, 5.9, 1.2);
      c.quadraticCurveTo(7.7, -.3, 6.3, -2.2);
      c.bezierCurveTo(6.9, -4.9, 2, -7.4, -1.7, -5.9);
    });
    detail(ctx, c => {
      c.moveTo(5.9, 1.2);
      c.quadraticCurveTo(4.1, .1, 1.7, .6);
      c.moveTo(4.9, 4);
      c.quadraticCurveTo(3.2, 3.2, 1.1, 3.8);
    });
    ctx.restore();
  }

  function pencilPalmShape(c) {
    c.moveTo(-5.5, -8);
    c.bezierCurveTo(-5.3, -2.2, -5.4, 3.7, -7.1, 6.6);
    c.bezierCurveTo(-8.4, 10.3, -6.6, 13, -3.7, 14.5);
    c.quadraticCurveTo(-3.9, 17.5, -1.6, 18.4);
    c.quadraticCurveTo(.6, 19.4, 1.8, 17.1);
    c.quadraticCurveTo(4.7, 17.3, 5.6, 14.4);
    c.bezierCurveTo(8.3, 13, 8.5, 9.4, 6.3, 7.6);
    c.lineTo(5.5, -8);
  }

  function pencilFingers(ctx) {
    // The bent index lies across the pencil while the other fingers cradle it.
    skin(ctx, c => {
      c.moveTo(4.8, 7.4);
      c.bezierCurveTo(3.1, 6.5, .8, 6.8, -.8, 9);
      c.lineTo(-4.5, 12.1);
      c.bezierCurveTo(-7.1, 14.2, -4.6, 17, -2.6, 15.3);
      c.lineTo(1.2, 12.9);
      c.quadraticCurveTo(2.3, 13.6, 4.1, 12.8);
      c.quadraticCurveTo(6.9, 11, 4.8, 7.4);
    }, pencilPalmShape);
    skin(ctx, c => {
      c.moveTo(-6.5, 5.7);
      c.bezierCurveTo(-9.5, 7, -9.5, 10.4, -8.2, 12.6);
      c.quadraticCurveTo(-6.9, 15, -4.5, 14.4);
      c.quadraticCurveTo(-2.7, 13.6, -3.8, 12);
      c.quadraticCurveTo(-6.1, 10.1, -5.1, 8.7);
      c.quadraticCurveTo(-4.1, 6.6, -6.5, 5.7);
    }, pencilPalmShape);
  }

  function supportPalmShape(c) {
    c.moveTo(-5.6, -8);
    c.bezierCurveTo(-5.7, -3, -5, 2.6, -6.1, 5.9);
    c.bezierCurveTo(-8.5, 9, -8.2, 13.2, -5.6, 15.4);
    c.quadraticCurveTo(-4.4, 17.1, -2, 16.1);
    c.quadraticCurveTo(.3, 18.2, 2.8, 16.7);
    c.quadraticCurveTo(6.6, 16.9, 7.5, 13.6);
    c.bezierCurveTo(9.6, 10.7, 7.4, 7.5, 6.3, 5);
    c.lineTo(5.3, -8);
  }

  function supportPalm(ctx) {
    skin(ctx, supportPalmShape);
    detail(ctx, c => {
      c.moveTo(-2, 16.1);
      c.quadraticCurveTo(-2.2, 13.4, -1, 11.7);
      c.moveTo(2.8, 16.7);
      c.quadraticCurveTo(2, 14, 3.8, 12.1);
    });
  }

  function supportThumbShape(c) {
    c.moveTo(-5.2, 5.5);
    c.bezierCurveTo(-8, 7.3, -10.2, 10.8, -9.8, 14.1);
    c.bezierCurveTo(-9.6, 16.8, -6.1, 17.1, -5.1, 14.7);
    c.quadraticCurveTo(-4.6, 13.1, -4.3, 11.3);
    c.quadraticCurveTo(-2.5, 7.9, -5.2, 5.5);
  }

  function supportThumb(ctx, lineColor, lineWidth) {
    skin(ctx, supportThumbShape, null, lineColor, lineWidth);
    thumbnail(ctx, -7.45, 13.85, -.22);
  }

  function readingContact(curl) {
    return {x: mix(-4.6, -3.2, curl), y: mix(23.1, 14.8, curl)};
  }

  function tapHand(ctx) {
    skin(ctx, c => {
      c.moveTo(-5.4, -8);
      c.bezierCurveTo(-5.3, -1.7, -5, 3.4, -6.4, 5.9);
      c.bezierCurveTo(-8.4, 8.4, -10, 11.7, -8.9, 13.5);
      c.quadraticCurveTo(-7.4, 15.4, -5.4, 12.9);
      c.bezierCurveTo(-5.1, 16.8, -4.6, 20.7, -2.3, 20.7);
      c.quadraticCurveTo(-.8, 20.9, -.4, 18.8);
      c.quadraticCurveTo(1.1, 21.1, 2.7, 19.8);
      c.quadraticCurveTo(3.8, 19.1, 3.5, 17.5);
      c.quadraticCurveTo(5.5, 18.3, 6.1, 16.3);
      c.bezierCurveTo(7.5, 12.8, 6.8, 8, 5.5, 5.3);
      c.lineTo(5.3, -8);
    });
  }

  function reader(ctx, curl) {
    const {x, y} = readingContact(curl);
    skin(ctx, c => {
      c.moveTo(-5.6, -8);
      c.bezierCurveTo(-5.4, -2, -5.6, 3.2, -7.1, 5.8);
      c.bezierCurveTo(-9.4, 8.1, -10.1, 12.1 + curl, -8.7, 13.7 + curl);
      c.quadraticCurveTo(-7, 15.2 + curl, -6.2, 12.5);
      c.bezierCurveTo(-5.8, 15.5, x - 2.3, y - 5.1, x - 2, y - 2.3);
      c.bezierCurveTo(x - 2, y + 1.1, x + 1.7, y + 1.7, x + 2.1, y - 1.2);
      c.quadraticCurveTo(x + 2.3, y - 4.5, .2, 12.4);
      c.bezierCurveTo(2, 16.8, 5.5, 17, 7.1, 14.1);
      c.bezierCurveTo(8.3, 12.5, 8.4, 8.5, 6.4, 6.7);
      c.lineTo(5.3, -8);
    });
    detail(ctx, c => {
      c.moveTo(7.3, 13.6);
      c.quadraticCurveTo(5.6, 11.5, 3.3, 11.8);
      c.moveTo(6.7, 9.3);
      c.quadraticCurveTo(4.9, 8.3, 3.3, 8.9);
    });
    thumbnail(ctx, x, y - 1.9, -.12);
  }

  const supportContact = () => ({x: -7.4, y: 14});
  const poses = {
    relaxed: {paint: relaxed},
    device: {contact: controllerThumb, paint: padPalm},
    pencil: {
      contact: () => ({x: -4.5, y: 12.9}),
      paint: ctx => skin(ctx, pencilPalmShape),
      front: pencilFingers
    },
    writingSupport: {
      contact: supportContact,
      paint: ctx => skin(ctx, supportPalmShape),
      front: ctx => skin(ctx, supportThumbShape, supportPalmShape)
    },
    support: {contact: supportContact, paint: supportPalm, front: ctx => supportThumb(ctx)},
    reader: {contact: readingContact, paint: reader},
    wheel: {contact: supportContact, paint: padPalm, front: ctx => supportThumb(ctx, crease, .55)},
    highFive: {contact: root.CloudyHighFive.contact, paint: root.CloudyHighFive.paintPalm, bounds: root.CloudyHighFive.bounds},
    tap: {contact: () => ({x: -2.3, y: 20.7}), paint: tapHand}
  };

  function hand(kind, mirror, size, target = null, angle = 0, amount = 0) {
    return {art: poses[kind], mirror, size, target, angle, amount};
  }

  // Upper edges of the six painted cuff openings, relative to each cuff pivot.
  const cuffEdges = {
    front_03: [-35, 14, -27, 0, 19, -23, 34, -13],
    front_02: [-35, -14, -18, -23, 27, 0, 34, 14],
    left_02: [-35, -14, -24, -27, 23, -7, 34, 14],
    left_03: [-22, 21, -16, 3, 22, -24, 38, -17],
    right_02: [-26, 17, -13, -7, 22, -25, 36, -17],
    right_03: [-18, 14, -12, -3, 22, -29, 34, -31]
  };

  function cuffForeground(name, image, [x, y], [bx, by, width, height]) {
    const [left, startY, ax, ay, bx2, by2, right, endY] = cuffEdges[name];
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.translate(x - bx, y - by);
    ctx.beginPath();
    ctx.rect(-42, -46, 84, 68);
    ctx.clip();
    ctx.beginPath();
    ctx.moveTo(-width, -height);
    ctx.lineTo(-width, startY);
    ctx.lineTo(left, startY);
    ctx.bezierCurveTo(ax, ay, bx2, by2, right, endY);
    ctx.lineTo(width, endY);
    ctx.lineTo(width, -height);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(image, bx - x, by - y);
    return canvas;
  }

  root.CloudyActivityHands = {hand, cuffForeground, rearGripFingers};
})(window);
