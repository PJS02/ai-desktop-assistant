/* Side silhouettes matched to the established front view; no motion changes. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudyGirth = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const smooth = value => {
    const t = Math.max(0, Math.min(1, value));
    return t * t * (3 - 2 * t);
  };
  // q: 0 = hip, 1 = knee, 2 = ankle. These are alpha-silhouette widths
  // measured perpendicular to the source bones, not horizontal image widths.
  const stations = [.15, .35, .55, .75, .95, 1.15, 1.35, 1.55];
  const legs = {
    left: {
      near: [1.127, 1.176, 1.161, 1.048, 1.067, 1.159, 1.152, 1.150],
      far:  [1.166, 1.155, 1.116, 1.035, 1.050, 1.159, 1.162, 1.162]
    },
    right: {
      near: [1.116, 1.107, 1.156, 1.093, 1.121, 1.140, 1.137, 1.145],
      far:  [1.116, 1.143, 1.147, 1.089, 1.098, 1.108, 1.108, 1.129]
    }
  };
  const unchanged = () => 1;
  function interpolate(q, values) {
    // Extend the same width into the hidden upper-thigh overlap. A step at
    // the hip would expose another seam when the skirt and leg separate.
    if (q <= stations[0]) return values[0];
    for (let i = 1; i < stations.length; i++) {
      if (q <= stations[i]) {
        const t = smooth((q - stations[i - 1]) / (stations[i] - stations[i - 1]));
        return values[i - 1] + (values[i] - values[i - 1]) * t;
      }
    }
    return values[values.length - 1];
  }
  /** Callback for CloudyMotion.deformPoint(..., CloudyGirth.scale(...)). */
  function scale(direction, type, near = true) {
    if (!(direction in legs)) return unchanged;
    if (type === 'leg') {
      const values = legs[direction][near ? 'near' : 'far'];
      return (boneIndex, fraction) => {
        // The ankle-to-toe frame stays rigid, including every shoe detail.
        if (boneIndex >= 2) return 1;
        const q = boneIndex + fraction;
        const amount = 1 - smooth((q - 1.60) / .25);
        return 1 + (interpolate(q, values) - 1) * amount;
      };
    }
    if (type === 'arm') {
      const extra = direction === 'left' ? .16 : .30;
      return (boneIndex, fraction) => {
        const q = boneIndex + fraction;
        // Fullness belongs to the loose sleeve, not its shoulder attachment
        // or the connected hand. Return exactly to 1 at the wrist plane.
        const shoulder = smooth((q - .10) / .45);
        const wrist = 1 - smooth((q - 1.50) / .50);
        return 1 + extra * shoulder * wrist;
      };
    }
    return unchanged;
  }
  return {scale};
});
