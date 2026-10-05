/* Attach a periodic cuff to the opaque, painted sleeve mouth. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudySideCuffAttachment = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const clamp = value => Math.max(0, Math.min(1, value));
  const lerp = (a, b, t) => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });

  /**
   * boundary is the actual clean sleeve mouth, in canvas coordinates, ordered
   * from negative to positive forearm normal. The source metadata must choose
   * points inside opaque CLOTH, excluding the hand and antialiased silhouette.
   * Map those atlas points with the same forearm map used to draw that cloth.
   *
   * Both circumference halves share this mouth. A small proximal overlap covers
   * texture filtering and the cloth mesh's interpolation error. Keep the broad
   * painted cuff's proximal bow where it already lies inside the sleeve; pull
   * its exposed side portions under the mouth instead of shortening its center.
   *
   * Only the band's proximal boundary changes. The opening, rim, material roll,
   * front/back visibility ranges and approved hand mapping remain those of cuff.
   */
  function create(options) {
    const cuff = options.cuff;
    const boundary = options.boundary;
    const overlap = options.overlap === undefined ? 1 : options.overlap;
    const bandWidth = options.bandWidth === undefined ? 256 : options.bandWidth;
    const bandHeight = options.bandHeight === undefined ? 96 : options.bandHeight;
    if (!cuff || typeof cuff.bandMap !== 'function' || typeof cuff.theta !== 'function'
      || !Array.isArray(boundary) || boundary.length < 2
      || !Number.isFinite(overlap) || overlap < 0) {
      throw new RangeError('An existing cuff and an opaque sleeve-mouth boundary are required');
    }
    const along = point => (point.x - cuff.anchor.x) * cuff.axis.x + (point.y - cuff.anchor.y) * cuff.axis.y;
    const across = point => (point.x - cuff.anchor.x) * cuff.normal.x + (point.y - cuff.anchor.y) * cuff.normal.y;
    const points = boundary.map(point => {
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
        throw new RangeError('Sleeve-mouth points must be finite');
      }
      return { x: point.x, y: point.y, across: across(point) };
    });
    for (let i = 1; i < points.length; i++) {
      if (!(points[i].across > points[i - 1].across + 1e-8)) {
        throw new RangeError('Sleeve-mouth points must increase along the forearm normal');
      }
    }
    const first = points[0].across, last = points.at(-1).across;
    const mouth = fraction => {
      const n = first + (last - first) * clamp(fraction);
      let i = 0;
      while (i < points.length - 2 && n > points[i + 1].across) i++;
      const a = points[i], b = points[i + 1];
      return lerp(a, b, (n - a.across) / (b.across - a.across));
    };
    const proximal = u => {
      const angle = cuff.theta(u), edge = mouth((Math.sin(angle) + 1) * .5);
      const original = cuff.bandMap({ x: u * bandWidth, y: 0 });
      const retreat = Math.max(overlap, along(edge) - along(original));
      return { x: edge.x - cuff.axis.x * retreat, y: edge.y - cuff.axis.y * retreat };
    };
    const bandMap = point => {
      const u = point.x / bandWidth, v = clamp(point.y / bandHeight);
      // Retain an exact common opening, including the final row of its mesh.
      if (v === 1) return cuff.bandMap(point);
      const originalTop = cuff.bandMap({ x: point.x, y: 0 });
      const attachedTop = proximal(u), original = cuff.bandMap(point);
      return { x: original.x + (attachedTop.x - originalTop.x) * (1 - v),
        y: original.y + (attachedTop.y - originalTop.y) * (1 - v) };
    };
    const attachmentTop = angle => proximal((angle - cuff.theta(0)) / (Math.PI * 2));
    return { ...cuff, bandMap, proximal, attachmentTop, mouth, attachment: {
      boundary: points.map(({x,y}) => ({x,y})), overlap, acrossMinimum: first, acrossMaximum: last
    } };
  }
  return { create };
});
