# 캐릭터의 현재 상태 mood를 조정, 화면 상 캐릭터의 감정의 로직
import random

class MoodSystem:
    def __init__(self):
        self.mood = {
            # 기존 감정
            "happy": 0.5,
            "bored": 0.2,
            "angry": 0.1,
            # 새 감정
            "sad": 0.0,
            "fear": 0.0,
            "anxiety": 0.0,
            "thinking": 0.0
        }

    # ------------------------
    # 이벤트에 대한 반응
    # ------------------------
    # 기존 이벤트
    def on_click(self):
        """사용자가 캐릭터를 클릭했을 때"""
        self.mood["happy"] += 0.1
        self.mood["angry"] += 0.05
        self.mood["sad"] = max(0, self.mood["sad"] - 0.05)  # 슬픔 감소
        self.mood["anxiety"] = max(0, self.mood["anxiety"] - 0.05)  # 불안 감소

    def on_idle(self):
        """캐릭터가 오래 방치되었을 때"""
        self.mood["bored"] += 0.1
        self.mood["sad"] += 0.05  # 슬픔 약간 증가
        self.mood["anxiety"] += 0.03  # 불안 증가

    # 새 감정 이벤트
    def on_neglected(self):
        """오래 동안 상호작용이 없을 때 (sad 증가)"""
        self.mood["sad"] += 0.15
        self.mood["anxiety"] += 0.08
        self.mood["happy"] = max(0, self.mood["happy"] - 0.1)

    def on_drag_hard(self):
        """강하게/빠르게 드래그할 때 (fear 증가)"""
        self.mood["fear"] += 0.12
        self.mood["anxiety"] += 0.1
        self.mood["happy"] = max(0, self.mood["happy"] - 0.05)

    def on_drag_end(self):
        """드래그 후 놓을 때"""
        self.mood["sad"] += 0.08

    def on_sudden_move(self):
        """갑작스러운 위치 변화 (fear 증가)"""
        self.mood["fear"] += 0.2
        self.mood["anxiety"] += 0.15

    def on_long_idle(self):
        """오래 기다릴 때 / 로딩 중 (anxiety 증가)"""
        self.mood["anxiety"] += 0.12
        self.mood["thinking"] += 0.1
        self.mood["bored"] += 0.05

    def on_high_activity(self):
        """많은 창이 동시에 열림 (anxiety 증가)"""
        self.mood["anxiety"] += 0.15
        self.mood["thinking"] += 0.12
        self.mood["fear"] += 0.08

    def on_task_complex(self):
        """복잡한 작업 감지 (thinking 증가)"""
        self.mood["thinking"] += 0.18
        self.mood["anxiety"] += 0.08
        self.mood["happy"] = max(0, self.mood["happy"] - 0.05)

    def on_cpu_high(self):
        """CPU 사용률 높을 때 (thinking, anxiety 증가)"""
        self.mood["thinking"] += 0.15
        self.mood["anxiety"] += 0.12
        self.mood["bored"] = max(0, self.mood["bored"] - 0.1)

    def on_error(self):
        """에러/버그 발생 시 (sad, fear 증가)"""
        self.mood["sad"] += 0.2
        self.mood["fear"] += 0.15
        self.mood["angry"] += 0.1
        self.mood["happy"] = max(0, self.mood["happy"] - 0.15)

    # ------------------------
    # 자연 감소
    # ------------------------
    def decay(self):
        """시간에 따른 감정 자연 감소"""
        for key in self.mood:
            self.mood[key] *= 0.95
        
        # 모든 감정을 0 이상으로 유지
        for key in self.mood:
            if self.mood[key] < 0:
                self.mood[key] = 0

    # ------------------------
    # 행동 결정 (우선순위 순서)
    # ------------------------
    def decide_emotion(self):
        """현재 mood 값으로 표시할 감정 결정"""
        happy = self.mood["happy"]
        bored = self.mood["bored"]
        angry = self.mood["angry"]
        sad = self.mood["sad"]
        fear = self.mood["fear"]
        anxiety = self.mood["anxiety"]
        thinking = self.mood["thinking"]

        # 우선순위: fear > angry > sad > thinking > anxiety > bored > happy > idle
        if fear > 0.65:
            return {"emotion": "fear", "intensity": fear}
        elif angry > 0.7:
            return {"emotion": "angry", "intensity": angry}
        elif sad > 0.7:
            return {"emotion": "sad", "intensity": sad}
        elif thinking > 0.7:
            return {"emotion": "thinking", "intensity": thinking}
        elif anxiety > 0.65:
            return {"emotion": "anxiety", "intensity": anxiety}
        elif bored > 0.6:
            return {"emotion": "bored", "intensity": bored}
        elif happy > 0.6:
            return {"emotion": "happy", "intensity": happy}
        else:
            return {"emotion": "idle", "intensity": 0.3}