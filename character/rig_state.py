"""Adapt the existing sprite-player API to independent Cloudy rig channels."""
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap


RIG_EMOTIONS = frozenset({
    "neutral", "happy", "excited", "proud", "relieved", "calm", "anxious",
    "hurt", "displeased", "distressed", "sad", "depressed", "tired", "angry",
    "scared",
})
HOST_EMOTIONS = {
    "idle": "neutral", "joy": "happy", "delight": "happy",
    "excitement": "excited", "interest": "excited", "contentment": "relieved",
    "peaceful": "calm", "anger": "angry", "disgust": "displeased",
    "fear": "scared", "anxiety": "anxious", "sadness": "sad",
    "melancholy": "depressed", "despair": "distressed", "distress": "distressed",
    "pride": "proud", "relief": "relieved", "pain": "hurt", "fatigue": "tired",
}
RIG_ACTIONS = frozenset({
    "idle", "walk", "wave", "thinking", "sleep", "hovering", "jump", "fall", "land",
})


def rig_emotion(name):
    """Keep every authored face available, and translate existing mood names."""
    name = str(name or "neutral").lower()
    return name if name in RIG_EMOTIONS else HOST_EMOTIONS.get(name, "neutral")


class RigAnimator(QObject):
    """SpriteAnimator-compatible control without producing full-frame pixmaps.

    Repeated play requests leave the native action clock running. Face, yaw and
    audio are separate channels, so polling mood never rewinds walking or waving.
    """
    frame_changed = pyqtSignal(QPixmap)
    animation_finished = pyqtSignal()

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.current_animation = None
        self.current_action = "idle"
        self.current_emotion = "neutral"
        self._requested_emotion = "neutral"
        self._emotion_override = None
        self.is_looping = True
        self.is_playing = False
        self._paused = False
        self._released = False
        self.yaw = 0
        self.view.animation_finished.connect(self._finished)

    def set_emotion(self, name):
        if self._released:
            return
        self._requested_emotion = rig_emotion(name)
        emotion = self._emotion_override or self._requested_emotion
        if emotion != self.current_emotion:
            self.current_emotion = emotion
            self.view.set_emotion(emotion)

    def set_emotion_override(self, name=None):
        """Pin only the rendered face while continuing to receive real moods."""
        self._emotion_override = rig_emotion(name) if name else None
        self.set_emotion(self._requested_emotion)

    def set_direction(self, flipped=False, *, front=False):
        self.set_yaw(0 if front else (65 if flipped else -65))

    def set_yaw(self, yaw):
        if self._released:
            return
        yaw = max(-65, min(65, float(yaw)))
        if yaw != self.yaw:
            self.yaw = yaw
            self.view.set_yaw(yaw)

    def set_speaking(self, speaking):
        if not self._released:
            self.view.set_speaking(bool(speaking))

    def play(self, animation_name, fps=24, loop=True):
        del fps  # The rig samples its own monotonic clock.
        if self._released:
            return False
        name = str(animation_name or "idle")
        if name.startswith("walk_"):
            action = "walk"
            self.set_emotion(name[5:])
        elif name in RIG_ACTIONS:
            action = name
        else:
            action = "idle"
            self.set_emotion(name)
        looping = bool(loop)
        if self.current_action == action and self.is_playing and self.is_looping == looping:
            self.current_animation = name
            if self._paused:
                self.resume()
            return True
        self.current_animation = name
        self.current_action = action
        self.is_looping = looping
        self.is_playing = True
        self._paused = False
        self.view.set_action(action, loop=looping)
        self.view.resume()
        return True

    def _finished(self):
        if self._released or self.is_looping or not self.is_playing:
            return
        self.is_playing = False
        self.animation_finished.emit()

    def stop(self):
        if self._released:
            return
        self.is_playing = False
        self._paused = False
        self.view.pause()

    def pause(self):
        if self.is_playing and not self._released:
            self._paused = True
            self.view.pause()

    def resume(self):
        if self.is_playing and not self._released:
            self._paused = False
            self.view.resume()

    def release(self):
        if not self._released:
            self._released = True
            self.is_playing = False
            self.view.release()
