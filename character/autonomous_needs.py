"""Small, transient needs used to choose the character's idle-only activities."""

from __future__ import annotations


class AutonomousNeeds:
    """Track curiosity, play, and rest pressure while the character is unattended."""

    _GROWTH_PER_SECOND = {
        "curiosity": 1.0 / 180.0,
        "play": 1.0 / 240.0,
        "rest": 1.0 / 1200.0,
    }
    VISIBLE_BOREDOM_THRESHOLD = 0.65
    _SATISFACTION = {
        "self_curiosity": ("curiosity", 0.45, 0.75),
        "self_play": ("play", 0.45, 0.35),
        "self_rest": ("rest", 0.55, 1.0),
    }

    def __init__(self, boredom_minutes: int = 3) -> None:
        self.values = {name: 0.0 for name in self._GROWTH_PER_SECOND}
        self.values["boredom"] = 0.0
        self._last_idle_seconds = 0.0
        self.boredom_minutes = 3
        self.set_boredom_minutes(boredom_minutes)

    def set_boredom_minutes(self, minutes: int) -> None:
        self.boredom_minutes = max(0, min(10, int(minutes)))
        if self.boredom_minutes == 0:
            self.values["boredom"] = 0.0

    def update(self, idle_seconds: float) -> None:
        """Grow needs from elapsed unattended time, handling interaction resets."""
        idle_seconds = max(0.0, float(idle_seconds))
        elapsed = max(0.0, idle_seconds - self._last_idle_seconds)
        if idle_seconds < self._last_idle_seconds:
            elapsed = 0.0
        self._last_idle_seconds = idle_seconds

        for name, rate in self._GROWTH_PER_SECOND.items():
            self.values[name] = min(1.0, self.values[name] + elapsed * rate)
        if self.boredom_minutes > 0:
            self.values["boredom"] = min(
                1.0,
                self.values["boredom"] + elapsed / (self.boredom_minutes * 60.0),
            )
        else:
            self.values["boredom"] = 0.0

    def choose(self, emotion: str, intensity: float) -> str:
        """Choose one idle activity from need pressure, with mood as a small bias."""
        emotion = str(emotion or "neutral")
        intensity = max(0.0, min(1.0, float(intensity)))
        negative_mood = emotion in {
            "anger", "disgust", "fear", "anxiety", "sadness", "despair",
        }
        boredom_bias = 0.35 if negative_mood else 1.25
        scores = {
            "self_curiosity": self.values["curiosity"] + 0.12,
            "self_play": self.values["play"] + self.values["boredom"] * boredom_bias,
            "self_rest": self.values["rest"],
        }
        if negative_mood:
            scores["self_rest"] += 0.25 * intensity
        elif emotion in {"joy", "delight", "excitement", "interest", "contentment"}:
            scores["self_play"] += 0.20 * intensity
        if self.values["boredom"] >= 0.85 and not negative_mood:
            scores["self_play"] += 0.5
        return max(scores, key=scores.get)

    def satisfy(self, activity: str) -> None:
        need = self._SATISFACTION.get(activity)
        if need is None:
            return
        name, amount, boredom_retention = need
        self.values[name] = max(0.0, self.values[name] - amount)
        self.values["boredom"] *= boredom_retention

    def on_interaction(self) -> None:
        """User interaction relieves boredom without erasing other needs."""
        self.values["boredom"] *= 0.35
        self._last_idle_seconds = 0.0

    def snapshot(self) -> dict[str, float]:
        return dict(self.values)
