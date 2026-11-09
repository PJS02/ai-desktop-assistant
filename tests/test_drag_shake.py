import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication

from character.drag_shake import DragShakeDetector
from character.mood_system import MoodSystem
from character.rig_state import RigAnimator
from character.rig_v8 import NodeRigPlanner


def triangle(t, period=.48, amplitude=60.):
    phase = (t/period) % 1
    return amplitude*(1-4*abs(phase-.5))


class DragShakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def samples(self, function, fps=120, duration=2):
        detector = DragShakeDetector()
        detector.reset(*function(0), 100)
        return [100+i/fps for i in range(1, int(duration*fps)+1)
                if detector.update(*function(i/fps), 100+i/fps)]

    def test_fast_repositioning_and_small_jitter_remain_neutral(self):
        assert not self.samples(lambda t: (4000*t, 0))
        assert not self.samples(lambda t: (triangle(t, amplitude=5), 0))
        assert not self.samples(lambda t: (triangle(t, period=2), 0), duration=4)
        assert not self.samples(lambda t: (triangle(t), 2*triangle(t)))

    def test_repeated_horizontal_reversals_work_at_different_event_rates(self):
        for fps in (30, 60, 120, 240):
            events = self.samples(lambda t: (triangle(t), 0), fps=fps, duration=4)
            assert events, fps
            assert events[0] < 101.1, (fps, events)
            assert all(b-a >= 1.8 for a, b in zip(events, events[1:]))

    def test_single_direction_correction_is_not_a_shake(self):
        assert not self.samples(lambda t: (min(t, 1)*600 if t < 1 else 600-(t-1)*200, 0))

    def test_shake_changes_mood_with_a_cooldown(self):
        mood = MoodSystem()
        with patch('character.mood_system.time.monotonic', return_value=100) as clock:
            before = (mood._target_valence, mood._target_arousal)
            assert mood.on_drag_hard()
            after = (mood._target_valence, mood._target_arousal)
            assert after != before
            assert not mood.on_drag_hard()
            clock.return_value = 102
            assert mood.on_drag_hard()

    def test_dizzy_persists_through_mood_updates_then_restores_latest_face(self):
        view = Mock()
        animator = RigAnimator(view)
        animator.set_emotion('neutral')
        animator.show_dizzy()
        generation = animator._dizzy_generation
        animator.set_emotion('angry')
        assert animator.current_emotion == 'dizzy'
        animator.show_dizzy()
        animator._finish_dizzy(generation)
        assert animator.current_emotion == 'dizzy'
        animator._finish_dizzy(animator._dizzy_generation)
        assert animator.current_emotion == 'angry'
        animator.release()

    def test_native_spiral_meshes_exist_and_rotate_in_all_three_views(self):
        planner = NodeRigPlanner()
        try:
            for yaw in (-65, 0, 65):
                frames = [planner.plan(dict(action='idle', emotion='dizzy', yaw=yaw, time=t, blink=0))
                          for t in (.2, .6)]
                for frame in frames:
                    assert 'fx_dizzy_spiral' in frame['requiredTextures']
                    assert frame['pose']['dizzy'] == 1
                meshes = [[bytes(c['vertexBytes']) for c in frame['commands'] if c['base']=='fx_dizzy_spiral']
                          for frame in frames]
                assert meshes[0] != meshes[1]
                normal = planner.plan(dict(action='idle', emotion='neutral', yaw=yaw, time=1))
                assert 'fx_dizzy_spiral' not in normal['requiredTextures']
        finally:
            planner.close()


if __name__ == '__main__':
    unittest.main()
