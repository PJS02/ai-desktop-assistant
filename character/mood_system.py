# 캐릭터의 현재 상태 mood를 조정, 화면 상 캐릭터의 감정의 로직
import random

class MoodSystem:
    def __init__(self):
        self.mood = {
            "happy": 0.5,
            "bored": 0.2,
            "angry": 0.1
        }

    # ------------------------
    # 이벤트에 대한 반응
    # ------------------------
    def on_click(self):
        self.mood["happy"] += 0.1
        self.mood["angry"] += 0.05

    def on_idle(self):
        self.mood["bored"] += 0.1

    # ------------------------
    # 자연 감소
    # ------------------------
    def decay(self):
        for key in self.mood:
            self.mood[key] *= 0.95

    # ------------------------
    # 행동 결정
    # ------------------------
    def decide_emotion(self):
        happy = self.mood["happy"]
        bored = self.mood["bored"]
        angry = self.mood["angry"]

        if angry > 0.7:
            return {"emotion": "angry", "intensity": angry}
        elif bored > 0.6:
            return {"emotion": "bored", "intensity": bored}
        elif happy > 0.6:
            return {"emotion": "happy", "intensity": happy}
        else:
            return {"emotion": "idle", "intensity": 0.3}