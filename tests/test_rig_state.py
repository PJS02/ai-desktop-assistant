"""Control-channel tests: no GL context, browser, assets, or live window."""
import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from character.rig_state import RigAnimator, RIG_EMOTIONS, rig_emotion


class FakeRigView(QObject):
    animation_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.actions = []
        self.faces = []
        self.yaws = []
        self.speaking = []
        self.pauses = 0
        self.resumes = 0
        self.releases = 0
        self.hidden = False
        self.jump_active = False

    def set_jump_active(self, active):
        self.jump_active = bool(active)

    def set_action(self, action, loop=True):
        self.actions.append((action, loop))

    def set_emotion(self, name):
        self.faces.append(name)

    def set_yaw(self, yaw):
        self.yaws.append(yaw)

    def set_speaking(self, speaking):
        self.speaking.append(speaking)

    def pause(self):
        self.pauses += 1

    def resume(self):
        self.resumes += 1

    def release(self):
        self.releases += 1

    def hide(self):
        self.hidden = True


@pytest.mark.parametrize("name", sorted(RIG_EMOTIONS))
def test_every_authored_face_remains_addressable(name):
    assert rig_emotion(name) == name


@pytest.mark.parametrize("host, face", [
    ("neutral", "neutral"), ("joy", "happy"), ("delight", "happy"),
    ("excitement", "excited"), ("interest", "excited"),
    ("contentment", "relieved"), ("calm", "calm"), ("peaceful", "calm"),
    ("anger", "angry"), ("disgust", "displeased"), ("fear", "scared"),
    ("anxiety", "anxious"), ("sadness", "sad"),
    ("melancholy", "depressed"), ("despair", "distressed"),
])
def test_host_moods_map_to_authored_faces(host, face):
    assert rig_emotion(host) == face


def test_mood_polling_and_speech_do_not_restart_walk_clock():
    view = FakeRigView()
    animator = RigAnimator(view)
    animator.play("walk_happy")
    animator.set_direction(False)
    for _ in range(5):
        animator.play("walk_angry")
        animator.set_speaking(True)
        animator.set_emotion("anxiety")
        animator.set_speaking(False)
    assert view.actions == [("walk", True)]
    assert view.yaws == [-65]
    assert animator.current_emotion == "anxious"
    assert view.speaking == [True, False] * 5


def test_three_directions_change_geometry_channel_only():
    view = FakeRigView()
    animator = RigAnimator(view)
    animator.play("wave", loop=False)
    animator.set_direction(False)
    animator.set_direction(True)
    animator.set_direction(front=True)
    animator.set_direction(front=True)
    assert view.yaws == [-65, 65, 0]
    assert view.actions == [("wave", False)]


def test_one_shot_finishes_once_and_can_be_replayed():
    view = FakeRigView()
    animator = RigAnimator(view)
    completions = []
    animator.animation_finished.connect(lambda: completions.append(1))
    animator.play("land", loop=False)
    view.animation_finished.emit()
    view.animation_finished.emit()
    assert completions == [1]
    assert not animator.is_playing
    animator.play("land", loop=False)
    assert view.actions == [("land", False), ("land", False)]
    assert animator.is_playing


def test_repeated_play_resumes_paused_action_without_rewinding():
    view = FakeRigView()
    animator = RigAnimator(view)
    animator.play("thinking")
    animator.pause()
    animator.play("thinking")
    assert view.actions == [("thinking", True)]
    assert view.pauses == 1 and view.resumes == 2


def test_release_is_idempotent_and_ignores_late_controls_and_finish():
    view = FakeRigView()
    animator = RigAnimator(view)
    completions = []
    animator.animation_finished.connect(lambda: completions.append(1))
    animator.play("wave", loop=False)
    animator.release()
    animator.release()
    animator.set_emotion("sad")
    animator.set_direction(True)
    animator.set_speaking(True)
    assert animator.play("walk") is False
    view.animation_finished.emit()
    assert view.releases == 1
    assert not view.faces and not view.yaws and not view.speaking
    assert not completions and not animator.is_playing
