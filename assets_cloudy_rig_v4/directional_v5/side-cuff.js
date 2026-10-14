/* One periodic sleeve cuff, with front/back surfaces sharing a wrist anchor. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudySideCuff = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const TAU = Math.PI * 2;
  const clamp = value => Math.max(0, Math.min(1, value));

  function visibleRanges(roll, front, width) {
    const minimum = front ? -Math.PI / 2 : Math.PI / 2;
    const maximum = minimum + Math.PI;
    const ranges = [];
    for (let turn = -2; turn <= 2; turn++) {
      const a = (minimum + turn * TAU - roll) / TAU + .25;
      const b = (maximum + turn * TAU - roll) / TAU + .25;
      const lo = Math.max(0, a), hi = Math.min(1, b);
      if (hi - lo > 1e-10) ranges.push({ min: lo * width, max: hi * width });
    }
    return ranges.sort((a, b) => a.min - b.min);
  }

  /**
   * The band texture is a periodic 256 x 96 rectangle: X is circumference,
   * Y travels from sleeve to wrist. Mint is the initial front half X=0..128,
   * and white cloth the back half X=128..256. The 256 x 24 rim texture uses
   * the same circumference, with Y traveling from its outer to inner edge.
   *
   * anchor/axis/radius/height/depth are final canvas coordinates. They belong
   * to the rigid forearm wrist frame. Do not apply connected-hand palm growth
   * or the distal wrist-flex gradient to individual cuff vertices. The hand
   * retains its original map and is drawn between the back and front ranges.
   *
   * Clip each mesh in source X to the returned ranges. Draw back ranges first,
   * then the existing connected hand, then front ranges. Shared endpoints make
   * one closed elliptic opening, rather than independent rotating rim pieces.
   * roll moves toward the REST thumb normal (+ left, - right) without angle
   * wrapping, and a return to rest reverses exactly the same material path.
   */
  function create(options) {
    const anchor = options.anchor;
    const axisLength = Math.hypot(options.axis.x, options.axis.y);
    const radius = options.radius, height = options.height;
    const depth = options.depth === undefined ? 2.4 : options.depth;
    if (!anchor || !Number.isFinite(anchor.x) || !Number.isFinite(anchor.y)
      || !Number.isFinite(axisLength) || !(axisLength > 1e-6)
      || !Number.isFinite(radius) || !(radius > 0)
      || !Number.isFinite(height) || !(height > 0)
      || !Number.isFinite(depth) || !(depth >= 0)) {
      throw new RangeError('A finite wrist frame and positive cuff dimensions are required');
    }
    const axis = { x: options.axis.x / axisLength, y: options.axis.y / axisLength };
    const normal = { x: -axis.y, y: axis.x };
    const progress = clamp(options.progress === undefined ? 0 : options.progress);
    const thumbSign = options.thumbSign < 0 ? -1 : 1;
    const roll = thumbSign * Math.PI * progress;
    const bandWidth = options.bandWidth === undefined ? 256 : options.bandWidth;
    const bandHeight = options.bandHeight === undefined ? 96 : options.bandHeight;
    const rimWidth = options.rimWidth === undefined ? 256 : options.rimWidth;
    const rimHeight = options.rimHeight === undefined ? 24 : options.rimHeight;
    const rimInset = options.rimInset === undefined ? .12 : clamp(options.rimInset);
    const axialOffset = options.axialOffset === undefined ? 0 : options.axialOffset;
    const normalOffset = options.normalOffset === undefined ? 0 : options.normalOffset;
    const edgeHeightRatio = options.edgeHeightRatio === undefined ? 1 : clamp(options.edgeHeightRatio);
    const flare = options.flare === undefined ? 1 : options.flare;
    if (!Number.isFinite(axialOffset) || !Number.isFinite(normalOffset)
      || !Number.isFinite(flare) || !(flare > 0)) {
      throw new RangeError('Cuff offsets and flare must be finite');
    }
    const theta = u => TAU * (u - .25) + roll;
    const localToCanvas = (across, along) => ({
      x: anchor.x + normal.x * (across + normalOffset) + axis.x * (along + axialOffset),
      y: anchor.y + normal.y * (across + normalOffset) + axis.y * (along + axialOffset)
    });
    const opening = u => {
      const angle = theta(u);
      // In the painted rest cuff the visible front lip bows proximally; the
      // back lip extends distally behind the hand. A positive cosine depth
      // would reverse that ellipse and leave a white ledge above the band.
      return localToCanvas(radius * Math.sin(angle), -depth * Math.cos(angle));
    };
    const bandMap = point => {
      const angle = theta(point.x / bandWidth), v = point.y / bandHeight;
      const cosine = Math.cos(angle);
      const localHeight = height * (edgeHeightRatio + (1 - edgeHeightRatio) * cosine * cosine);
      const localRadius = radius * (1 + (flare - 1) * (1 - v));
      return localToCanvas(localRadius * Math.sin(angle), -localHeight * (1 - v) - depth * cosine);
    };
    const rimMap = point => {
      const angle = theta(point.x / rimWidth), v = point.y / rimHeight;
      const fraction = 1 - rimInset * v;
      return localToCanvas(radius * fraction * Math.sin(angle), -depth * fraction * Math.cos(angle));
    };
    return { bandMap, rimMap, opening, theta, roll, progress, thumbSign,
      anchor: { x: anchor.x, y: anchor.y }, axis, normal, radius, height, depth,
      openingCenter: localToCanvas(0,0), axialOffset, normalOffset, edgeHeightRatio, flare,
      frontRanges: visibleRanges(roll, true, bandWidth),
      backRanges: visibleRanges(roll, false, bandWidth),
      rimFrontRanges: visibleRanges(roll, true, rimWidth),
      rimBackRanges: visibleRanges(roll, false, rimWidth) };
  }

  return { create };
});
