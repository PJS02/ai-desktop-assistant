/* Endpoint-safe, clock-sampled travel for the standalone Cloudy preview.
 * Position is the exact integral of raised-cosine velocity ramps: velocity and
 * acceleration are continuous at departure, cruise joins, and arrival.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudyTravel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Create one trip, independently of animation frame rate.
   * start/end: CSS pixels. maxSpeed: positive CSS pixels/second.
   * ramp: requested acceleration/deceleration time in seconds.
   * sample(time): elapsed seconds since this trip started, not absolute clock.
   */
  function create(start, end, maxSpeed, ramp = 0.55) {
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      throw new TypeError('Travel endpoints must be finite numbers');
    }
    if (!Number.isFinite(maxSpeed) || maxSpeed <= 0) {
      throw new RangeError('maxSpeed must be finite and positive');
    }
    if (!Number.isFinite(ramp) || ramp <= 0) {
      throw new RangeError('ramp must be finite and positive');
    }
    const distance = Math.abs(end - start);
    const direction = Math.sign(end - start);
    if (distance === 0) {
      return {
        duration: 0, start, end, distance: 0, peakSpeed: 0,
        rampDuration: 0, cruiseDuration: 0,
        sample: () => ({x: end, speed: 0, done: true})
      };
    }
    // Each ramp covers peakSpeed * rampDuration / 2. Short journeys reduce
    // BOTH peak speed and ramp time, retaining the full journey's acceleration
    // limit while joining the two cosine halves without a cruise discontinuity.
    const shortJourney = distance < maxSpeed * ramp;
    const rampDuration = shortJourney ? Math.sqrt(distance / maxSpeed * ramp) : ramp;
    const peakSpeed = shortJourney ? Math.min(maxSpeed, distance / rampDuration) : maxSpeed;
    const cruiseDuration = shortJourney ? 0 : Math.max(0, distance / peakSpeed - rampDuration);
    const duration = 2 * rampDuration + cruiseDuration;
    const halfRampDistance = peakSpeed * rampDuration / 2;

    function accelerationDistance(t) {
      const phase = Math.PI * t / rampDuration;
      // t - sin(t) loses significant digits extremely close to departure.
      const phaseMinusSin = Math.abs(phase) < 0.01
        ? phase ** 3 / 6 - phase ** 5 / 120 + phase ** 7 / 5040
        : phase - Math.sin(phase);
      return peakSpeed * rampDuration / (2 * Math.PI) * phaseMinusSin;
    }
    function accelerationSpeed(t) {
      // Equivalent to (1-cos(phase))/2 without near-zero cancellation.
      return peakSpeed * Math.sin(Math.PI * t / (2 * rampDuration)) ** 2;
    }
    function sample(time) {
      if (Number.isNaN(time)) time = 0;
      if (time >= duration) return {x: end, speed: 0, done: true};
      if (!(time > 0)) return {x: start, speed: 0, done: false};
      let travelled, speed;
      if (time < rampDuration) {
        travelled = accelerationDistance(time);
        speed = accelerationSpeed(time);
      } else if (time < rampDuration + cruiseDuration) {
        travelled = halfRampDistance + peakSpeed * (time - rampDuration);
        speed = peakSpeed;
      } else {
        const remaining = duration - time;
        travelled = distance - accelerationDistance(remaining);
        speed = accelerationSpeed(remaining);
      }
      travelled = Math.max(0, Math.min(distance, travelled));
      // Clamping position also guards last-bit rounding for nonzero origins.
      const x = Math.max(Math.min(start, end), Math.min(Math.max(start, end), start + direction * travelled));
      return {x, speed: direction * speed, done: false};
    }
    return {duration, start, end, distance, peakSpeed, rampDuration, cruiseDuration, sample};
  }

  return {create};
});
