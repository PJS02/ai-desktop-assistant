/* Side greeting cloth: overlapping bone-local surfaces retain their painted width. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudySideWaveSkinning = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const clamp = value => Math.max(0, Math.min(1, value));
  const smooth = value => { const t = clamp(value); return t * t * (3 - 2 * t); };
  const mixPoint = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });

  /**
   * Build two cloth surfaces from the same source texture. The renderer clips
   * the upper surface at axial <= overlap and the forearm at axial >= -overlap.
   * Draw a separate clean painted cap between them to cover the outside elbow,
   * with the mount on upperMap and the hanging label on forearmMap. Extract
   * each painted detail once; extending the original texture across both
   * surfaces would duplicate its tag.
   * Clip coordinates use the same scaled source space as restJoints and the
   * mapping functions, not texture UVs.
   *
   * Each surface is a bone-local affine length map with an independent girth
   * profile. They may overlap at a folded elbow, but never interpolate opposing
   * rotations there. This keeps a sleeve stripe from collapsing at 180 degrees
   * and remains continuous when the intended inward sweep continues past 180.
   *
   * activation is the side greeting lift, not a blend of the rotation angles.
   * The short fade completes during the initial small elbow bend. Pass the
   * ordinary motion.deformPoint as fallback to retain idle/other actions exactly.
   */
  function createLayers(restJoints, posedJoints, options = {}) {
    if (restJoints.length !== 3 || posedJoints.length !== 3) {
      throw new RangeError('Side greeting cloth requires matching three-joint arm chains');
    }
    const normalScale = options.normalScale;
    const frames = [0, 1].map(index => {
      const start = restJoints[index], finish = restJoints[index + 1];
      const posedStart = posedJoints[index], posedFinish = posedJoints[index + 1];
      const dx = finish.x - start.x, dy = finish.y - start.y;
      const px = posedFinish.x - posedStart.x, py = posedFinish.y - posedStart.y;
      const length = Math.hypot(dx, dy), posedLength = Math.hypot(px, py);
      if (!Number.isFinite(length) || !Number.isFinite(posedLength)
          || !(length > 1e-6) || !(posedLength > 1e-6)) {
        throw new RangeError('Arm bones must have finite positive lengths');
      }
      return { start, posedStart, length, scale: posedLength / length,
        x: dx / length, y: dy / length, px: px / posedLength, py: py / posedLength };
    });
    let bx = frames[0].x + frames[1].x, by = frames[0].y + frames[1].y;
    const bisectorLength = Math.hypot(bx, by);
    if (bisectorLength < 1e-6) { bx = frames[0].x; by = frames[0].y; }
    else { bx /= bisectorLength; by /= bisectorLength; }
    const origin = { x: restJoints[1].x, y: restJoints[1].y };
    const axis = { x: bx, y: by };
    const normalAxis = { x: -by, y: bx };
    const axial = point => (point.x - origin.x) * bx + (point.y - origin.y) * by;
    const normal = point => -(point.x - origin.x) * by + (point.y - origin.y) * bx;
    const overlap = options.overlap === undefined ? 3 : Math.max(0, options.overlap);
    const activation = options.activation === undefined ? 1 : clamp(options.activation);
    // At zero the existing map is literally returned. Finish the transition
    // while the arm is low, before opposing joint transforms can compress it.
    const amount = smooth((activation - .002) / .028);
    // Joint coverage can enter later than the two bone-local cloth surfaces.
    // Keep their maps and the hand attachment independent of that timing.
    const capAmount = options.capActivation === undefined ? amount : clamp(options.capActivation);
    // About a source sleeve half-width, bounded well above the wrist/cuff.
    // The left source is a loose asymmetric sleeve; its wider elbow needs a
    // larger cap than a conventional narrow bone-joint overlap.
    const capRadius = options.capRadius === undefined
      ? Math.min(frames[0].length, frames[1].length) * .66
      : Math.max(0, options.capRadius);
    const fallback = options.fallback;
    if (amount < 1 && typeof fallback !== 'function') {
      throw new TypeError('A fallback point map is required while greeting cloth fades in');
    }
    const rigid = (point, index) => {
      const b = frames[index], dx = point.x - b.start.x, dy = point.y - b.start.y;
      const along = dx * b.x + dy * b.y;
      const width = normalScale ? normalScale(index, along / b.length) : 1;
      const normal = (-dx * b.y + dy * b.x) * width;
      return { x: b.posedStart.x + along * b.scale * b.px - normal * b.py,
        y: b.posedStart.y + along * b.scale * b.py + normal * b.px };
    };
    const surface = index => point => {
      if (amount === 0) return fallback(point);
      const mapped = rigid(point, index);
      return amount === 1 ? mapped : mixPoint(fallback(point), mapped, amount);
    };
    const upperMap = surface(0), forearmMap = surface(1);
    // A short strip joins the cloth cuts before the rounded cap enters. At
    // these smaller bends its two edge maps can meet without pinching. The
    // strip contracts under the growing cap and is gone before the large fold.
    const bridgeWidth = 6 * amount * (1 - capAmount);
    const bridgeMap = point => {
      const t = smooth((axial(point) + bridgeWidth) / Math.max(2 * bridgeWidth, 1e-6));
      return mixPoint(upperMap(point), forearmMap(point), t);
    };
    // A clean painted cap is a separate small surface centered on the elbow.
    // Use constant joint girth here: a forearm/upper-arm point blend would bring
    // the very collapse this cap replaces back into its round silhouette.
    // A patch source uses the same atlas/scaled-source coordinates as the arm;
    // its transparent disk is centered on restJoints[1]. It is drawn after the
    // upper cloth and before the forearm; each detail uses its own bone map.
    const capLengthScale = (frames[0].scale + frames[1].scale) * .5;
    const capNormalScale = normalScale ? normalScale(0, 1) : 1;
    // Fit the painted joint to the sleeve section, independently of the bones.
    // Fixed-size caps are revealed by the renderer beneath the sleeve instead
    // of swelling from a point. Historical callers keep the growth map.
    const capScale = options.capScale || { along: 1, across: 1 };
    const capOffset = options.capOffset || { along: 0, across: 0 };
    const alongScale = capLengthScale * capScale.along;
    const acrossScale = capNormalScale * capScale.across;
    const capGeometryAmount = options.capStatic ? 1 : capAmount;
    const capMap = point => {
      const b = frames[0], dx = point.x - origin.x, dy = point.y - origin.y;
      const along = ((dx * b.x + dy * b.y) * alongScale + capOffset.along) * capGeometryAmount;
      const across = ((-dx * b.y + dy * b.x) * acrossScale + capOffset.across) * capGeometryAmount;
      return { x: posedJoints[1].x + along * b.px - across * b.py,
        y: posedJoints[1].y + along * b.py + across * b.px };
    };
    // Useful for single point queries and attachment locations. Actual cloth
    // must use both clipped surfaces, rather than tessellating across this cut.
    const map = point => axial(point) <= 0 ? upperMap(point) : forearmMap(point);
    const upperContains = point => axial(point) <= overlap;
    const forearmContains = point => axial(point) >= -overlap;
    return { amount, capAmount, upperMap, forearmMap, capMap, bridgeMap, bridgeWidth, map, axial, normal, upperContains, forearmContains,
      capGeometry: { origin, radius: capRadius, lengthScale: alongScale, normalScale: acrossScale, offset: capOffset },
      clip: { origin, axis, normalAxis, overlap } };
  }

  return { createLayers };
});
