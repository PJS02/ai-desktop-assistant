"""Tests for integration-sensitive coordinates, identity and latest-result delivery."""
import unittest
import statistics

from PyQt6.QtCore import QRect

from renderer import desktop_geometry, fit_rect, palm_center, screen_point
from tracker import Hand, HandSmoother, HandTracker, Snapshot, demo_snapshot


def hand(label, x):
    return Hand(label, tuple((x, .5, 0.) for _ in range(21)))


class LandmarkTests(unittest.TestCase):
    def test_desktop_hand_reaches_screen_edges_without_fullscreen_window(self):
        original = demo_snapshot().hands[0]
        center_x, center_y = palm_center(original)
        screen = QRect(0, 0, 1920, 1080)
        rectangles = []
        for x, y in ((0, 0), (1, 1)):
            shifted = Hand(original.label, tuple((px + x - center_x, py + y - center_y, z)
                           for px, py, z in original.points))
            geometry, points = desktop_geometry(shifted, screen, 4 / 3)
            self.assertTrue(screen.contains(geometry))
            self.assertLess(geometry.width() * geometry.height(), screen.width() * screen.height() / 10)
            self.assertTrue(all(0 < p.x() < geometry.width() and 0 < p.y() < geometry.height()
                                for p in points))
            rectangles.append(geometry)
        self.assertEqual(rectangles[0].topLeft(), screen.topLeft())
        self.assertEqual(rectangles[1].bottomRight(), screen.bottomRight())

    def test_desktop_shape_preserves_camera_aspect_on_wide_monitor(self):
        original = demo_snapshot().hands[0]
        _, points = desktop_geometry(original, QRect(0, 0, 3440, 1440), 4 / 3)
        # Compare thumb tip and index tip: x/y use the same camera-plane scale.
        a, b = original.points[4], original.points[8]
        dx, dy = points[4].x() - points[8].x(), points[4].y() - points[8].y()
        self.assertAlmostEqual(dx / dy, ((a[0] - b[0]) * (4 / 3)) / (a[1] - b[1]))

    def test_desktop_handles_negative_monitor_origin(self):
        screen = QRect(-1920, -200, 1920, 1080)
        geometry, _ = desktop_geometry(demo_snapshot().hands[0], screen, 4 / 3)
        self.assertTrue(screen.contains(geometry))
        self.assertLess(geometry.x(), 0)

    def test_landmark_projection_preserves_aspect_and_center(self):
        bounds = fit_rect(1920, 1080, 4 / 3)
        self.assertAlmostEqual(bounds.width() / bounds.height(), 4 / 3)
        point = screen_point((.5, .5, 0), bounds)
        self.assertEqual((point.x(), point.y()), (960, 540))
        self.assertEqual(bounds.left(), 240)

    def test_detection_order_does_not_swap_hand_histories(self):
        smoother = HandSmoother()
        smoother.apply((hand("Left", .2), hand("Right", .8)), timestamp=0)
        initial = smoother.apply((hand("Left", .2), hand("Right", .8)), timestamp=1 / 30)
        updated = smoother.apply((hand("Right", .82), hand("Left", .22)), timestamp=2 / 30)
        self.assertEqual([h.track_id for h in initial], [h.track_id for h in updated])
        self.assertLess(updated[0].points[0][0], .22)
        self.assertGreater(updated[1].points[0][0], .8)

    def test_short_dropout_holds_but_long_dropout_hides_and_resets(self):
        smoother = HandSmoother()
        initial = smoother.apply((hand("Right", .4),), timestamp=0)
        self.assertEqual(smoother.apply((), timestamp=.06), initial)
        updated = smoother.apply((hand("Right", .42),), timestamp=.09)
        self.assertEqual(updated[0].track_id, initial[0].track_id)
        self.assertEqual(smoother.apply((), timestamp=.22), ())
        returned = smoother.apply((hand("Right", .8),), timestamp=.25)
        self.assertNotEqual(returned[0].track_id, initial[0].track_id)
        self.assertEqual(returned[0].points[0][0], .8)

    def test_single_frame_large_spike_is_rejected(self):
        smoother = HandSmoother()
        smoother.apply((hand("Right", .2),), timestamp=0)
        spike = smoother.apply((hand("Right", .8),), timestamp=1 / 30)
        self.assertEqual(spike[0].points[0][0], .2)
        returned = smoother.apply((hand("Right", .2),), timestamp=2 / 30)
        self.assertEqual(returned[0].points[0][0], .2)

    def test_confirmed_fast_move_catches_up_without_teleporting(self):
        smoother = HandSmoother()
        smoother.apply((hand("Right", .2),), timestamp=0)
        for i in range(1, 10):
            result = smoother.apply((hand("Right", .8),), timestamp=i / 30)
            if i == 2:
                self.assertGreater(result[0].points[0][0], .2)
                self.assertLess(result[0].points[0][0], .8)
        self.assertAlmostEqual(result[0].points[0][0], .8, delta=.01)

    def test_transient_handedness_flip_does_not_reset_identity(self):
        smoother = HandSmoother()
        initial = smoother.apply((hand("Right", .4),), timestamp=0)[0]
        flipped = smoother.apply((hand("Left", .41),), timestamp=1 / 30)[0]
        self.assertEqual(flipped.label, "Right")
        self.assertEqual(flipped.track_id, initial.track_id)

    def test_stationary_noise_is_reduced(self):
        smoother = HandSmoother()
        raw, filtered = [], []
        for i in range(120):
            x = .5 + (.008 if i % 2 else -.008)
            output = smoother.apply((hand("Right", x),), timestamp=i / 30)
            if i > 20:
                raw.append(x)
                filtered.append(output[0].points[0][0])
        self.assertLess(statistics.pstdev(filtered), statistics.pstdev(raw) * .4)

    def test_filter_disabled_does_not_retain_lost_hands(self):
        smoother = HandSmoother()
        smoother.apply((hand("Right", .4),), timestamp=0)
        self.assertEqual(smoother.apply((), timestamp=.03, enabled=False), ())

    def test_latest_result_replaces_previous_frames(self):
        tracker = HandTracker()
        for i in range(1000):
            tracker.publish(Snapshot(frames=i))
        self.assertEqual(tracker.snapshot().frames, 999)

    def test_stop_is_safe_before_start(self):
        tracker = HandTracker()
        tracker.stop()
        tracker.join()
        self.assertFalse(tracker.running())


if __name__ == "__main__":
    unittest.main()
