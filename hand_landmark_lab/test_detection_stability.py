"""Regression cases for extra-hand ghosts and unrelated finger-shape outliers."""
import unittest

from tracker import Hand, HandSmoother, demo_snapshot


FRAME = 1 / 30
PALM = (0, 5, 9, 13, 17)


def pose(label="Right", center_x=.25, center_y=.5):
    """A compact, nondegenerate demo pose wholly inside the camera plane."""
    original = demo_snapshot().hands[0]
    center = tuple(sum(original.points[i][axis] for i in PALM) / len(PALM)
                   for axis in (0, 1))
    return Hand(label, tuple((center_x + (x - center[0]) * .4,
                             center_y + (y - center[1]) * .4, z * .4)
                            for x, y, z in original.points))


def shifted(hand, dx=0., dy=0.):
    return Hand(hand.label, tuple((x + dx, y + dy, z) for x, y, z in hand.points))


def changed_tip(hand, index, dx=0., dy=0.):
    points = list(hand.points)
    x, y, z = points[index]
    points[index] = (x + dx, y + dy, z)
    return Hand(hand.label, tuple(points))


def center_x(hand):
    return sum(hand.points[i][0] for i in PALM) / len(PALM)


class DetectionStabilityTests(unittest.TestCase):
    def test_first_hand_is_visible_immediately(self):
        hand = pose()
        output = HandSmoother().apply((hand,), timestamp=0)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0].points, hand.points)

    def test_nearly_identical_second_raw_detection_is_suppressed(self):
        smoother = HandSmoother()
        hand = pose()
        initial = smoother.apply((hand,), timestamp=0)[0]
        for frame in range(1, 5):
            # Same physical hand detected twice must not become two desktop hands,
            # including when detector ordering and handedness labels disagree.
            duplicate = shifted(Hand("Left", hand.points), dx=.01, dy=.006)
            raw = (hand, duplicate) if frame % 2 else (duplicate, hand)
            output = smoother.apply(raw, timestamp=frame * FRAME)
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0].track_id, initial.track_id)

    def test_far_second_hand_requires_two_coherent_frames(self):
        smoother = HandSmoother()
        first, second = pose(), pose("Left", .75)
        initial = smoother.apply((first,), timestamp=0)[0]
        candidate = smoother.apply((first, second), timestamp=FRAME)
        self.assertEqual(len(candidate), 1)
        self.assertEqual(candidate[0].track_id, initial.track_id)

        confirmed = smoother.apply((first, shifted(second, dx=.005)), timestamp=2 * FRAME)
        self.assertEqual(len(confirmed), 2)
        self.assertEqual(len({hand.track_id for hand in confirmed}), 2)
        positions = sorted(center_x(hand) for hand in confirmed)
        self.assertAlmostEqual(positions[0], .25, delta=.01)
        self.assertAlmostEqual(positions[1], .755, delta=.02)

    def test_unconfirmed_second_hand_dropout_does_not_leave_a_ghost(self):
        for extra in (shifted(pose(), dx=.01), pose("Left", .75)):
            with self.subTest(extra_center=center_x(extra)):
                smoother = HandSmoother()
                hand = pose()
                initial = smoother.apply((hand,), timestamp=0)[0]
                smoother.apply((hand, extra), timestamp=FRAME)
                for frame in range(2, 7):
                    output = smoother.apply((hand,), timestamp=frame * FRAME)
                    self.assertEqual(len(output), 1)
                    self.assertEqual(output[0].track_id, initial.track_id)

    def test_unrelated_finger_outliers_do_not_confirm_each_other(self):
        smoother = HandSmoother()
        hand = pose(center_x=.5)
        original = smoother.apply((hand,), timestamp=0)[0]
        # The palm is unchanged in both bad frames. A wholly different fingertip
        # jump cannot corroborate the previous jump merely because palms agree.
        for frame, malformed in enumerate((changed_tip(hand, 8, dx=.5),
                                           changed_tip(hand, 8, dx=-.5)), start=1):
            output = smoother.apply((malformed,), timestamp=frame * FRAME)
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0].track_id, original.track_id)
            self.assertAlmostEqual(output[0].points[8][0], hand.points[8][0], delta=.01)
            self.assertAlmostEqual(output[0].points[8][1], hand.points[8][1], delta=.01)

        recovered = smoother.apply((hand,), timestamp=3 * FRAME)
        self.assertAlmostEqual(recovered[0].points[8][0], hand.points[8][0], delta=.01)

    def test_confirmed_two_hands_survive_detection_order_reversal(self):
        smoother = HandSmoother()
        first, second = pose(), pose("Left", .75)
        smoother.apply((first,), timestamp=0)
        smoother.apply((first, second), timestamp=FRAME)
        confirmed = smoother.apply((first, second), timestamp=2 * FRAME)
        self.assertEqual(len(confirmed), 2)
        initial_ids = {hand.label: hand.track_id for hand in confirmed}

        reversed_output = smoother.apply((shifted(second, dx=-.005),
                                          shifted(first, dx=.005)), timestamp=3 * FRAME)
        self.assertEqual(len(reversed_output), 2)
        self.assertEqual({hand.label: hand.track_id for hand in reversed_output}, initial_ids)
        by_label = {hand.label: hand for hand in reversed_output}
        self.assertLess(center_x(by_label["Right"]), .3)
        self.assertGreater(center_x(by_label["Left"]), .7)


if __name__ == "__main__":
    unittest.main()
