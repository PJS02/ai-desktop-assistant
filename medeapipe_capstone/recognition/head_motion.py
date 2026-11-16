"""Recognize completed nods and head shakes using timestamped face landmarks."""

from collections import deque
import math


def face_offset(frame_record):
    face = frame_record['face_landmarks']
    if len(face) <= 263:
        return None
    nose, left, right = (face[index] for index in (1, 33, 263))
    size = frame_record['image_size']
    eye_x = (right['x'] - left['x']) * size['width']
    eye_y = (right['y'] - left['y']) * size['height']
    eye_span_squared = eye_x ** 2 + eye_y ** 2
    if eye_span_squared < 12 ** 2:
        return None
    nose_x = (nose['x'] - (left['x'] + right['x']) / 2) * size['width']
    nose_y = (nose['y'] - (left['y'] + right['y']) / 2) * size['height']
    # Use the eye line as the x axis so camera distance and head tilt do not mix yaw and pitch.
    return ((nose_x * eye_x + nose_y * eye_y) / eye_span_squared,
            (nose_y * eye_x - nose_x * eye_y) / eye_span_squared)


def _turns(values):
    """Compare with the last extreme so small steps can add up to a stroke."""
    turns = [0]
    extreme = direction = 0
    for index, value in enumerate(values[1:], 1):
        change = value - values[extreme]
        if direction * change > 0:
            extreme = index
        elif abs(change) >= .035:
            if direction:
                turns.append(extreme)
            extreme = index
            direction = 1 if change > 0 else -1
    return turns + [extreme] if direction else turns


class HeadMotionTracker:
    WINDOW_SECONDS = 1.45
    MAX_SAMPLE_GAP = .50
    RESULT_SECONDS = .65

    def __init__(self):
        self._samples = deque()
        self._result = 'WAIT'
        self._result_until = -math.inf
        self._last_at = -math.inf

    def update(self, offset, observed_at):
        if observed_at <= self._last_at:
            return self._result
        gap = observed_at - self._last_at
        self._last_at = observed_at
        # Hold a completed gesture briefly for the preview and the rate-limited receiver.
        if observed_at < self._result_until:
            return self._result
        self._result = 'WAIT'
        if offset is None or not all(map(math.isfinite, offset)):
            self._samples.clear()
            return self._result
        if gap > self.MAX_SAMPLE_GAP:
            self._samples.clear()
        self._samples.append((observed_at, *offset))
        while observed_at - self._samples[0][0] > self.WINDOW_SECONDS:
            self._samples.popleft()
        if len(self._samples) >= 3:
            times, yaw, pitch = zip(*self._samples)
            if self._matches(times, pitch, yaw, (.10, .07)):
                self._result = 'AGREE'
            elif self._matches(times, yaw, pitch, (.07, .17, .07)):
                self._result = 'NEGATIVE'
        if self._result != 'WAIT':
            self._samples.clear()
            self._result_until = observed_at + self.RESULT_SECONDS
        return self._result

    @staticmethod
    def _matches(times, axis, cross_axis, minimum_strokes):
        turns = _turns(axis)
        if len(turns) <= len(minimum_strokes):
            return False
        turns = turns[-(len(minimum_strokes) + 1):]
        for start, end, minimum in zip(turns, turns[1:], minimum_strokes):
            if abs(axis[end] - axis[start]) < minimum or times[end] - times[start] < .07:
                return False
        if len(turns) == 4:
            origin, side_a, side_b = (axis[index] for index in turns[:3])
            # A single glance and return must not look like a shake across both sides.
            if not min(side_a, side_b) + .04 <= origin <= max(side_a, side_b) - .04:
                return False
        start, end = turns[0], turns[-1] + 1
        excursion, cross = axis[start:end], cross_axis[start:end]
        return max(excursion) - min(excursion) > 1.25 * (max(cross) - min(cross))
