# 캐릭터의 현재 상태 mood를 조정, 화면 상 캐릭터의 감정의 로직
import random

class MoodSystem:
    # 감정 값의 최대 범위
    MAX_MOOD = 1.0
    MIN_MOOD = 0.0
    
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
        self._last_dominant_emotion = "idle"  # 이전 감정 상태 추적
    
    def _clamp_mood(self, emotion: str, value: float) -> None:
        """감정 값을 최대/최소 범위로 제한"""
        self.mood[emotion] = max(self.MIN_MOOD, min(self.MAX_MOOD, value))

    # ------------------------
    # 이벤트에 대한 반응
    # ------------------------
    # 기존 이벤트
    def on_click(self):
        """사용자가 캐릭터를 클릭했을 때"""
        self._clamp_mood("happy", self.mood["happy"] + 0.1)
        self._clamp_mood("angry", self.mood["angry"] + 0.05)
        self._clamp_mood("sad", self.mood["sad"] - 0.05)
        self._clamp_mood("anxiety", self.mood["anxiety"] - 0.05)

    def on_idle(self):
        """캐릭터가 오래 방치되었을 때"""
        self._clamp_mood("bored", self.mood["bored"] + 0.1)
        self._clamp_mood("sad", self.mood["sad"] + 0.05)
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.03)


    def on_neglected(self):
        """오래 동안 상호작용이 없을 때 (sad 증가, anxiety 소량 증가, bored 증가)"""
        self._clamp_mood("sad", self.mood["sad"] + 0.15)
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.08)
        self._clamp_mood("bored", self.mood["bored"] + 0.2)
        self._clamp_mood("happy", self.mood["happy"] - 0.1)

    def on_drag_hard(self):
        """강하게/빠르게 드래그할 때 (fear 증가)"""
        self._clamp_mood("fear", self.mood["fear"] + 0.12)
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.1)
        self._clamp_mood("happy", self.mood["happy"] - 0.05)

    def on_sudden_move(self):
        """갑작스러운 위치 변화 등 캐릭터가 공포를 느낄만한 상황 (fear 증가)"""
        self._clamp_mood("fear", self.mood["fear"] + 0.2)
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.15)

    def on_long_idle(self):
        """오래 기다릴 때 / 로딩 중 (anxiety 증가)"""
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.12)
        self._clamp_mood("thinking", self.mood["thinking"] + 0.1)
        self._clamp_mood("bored", self.mood["bored"] + 0.05)

    # def on_high_activity(self): - 노필요. 아마 일단 보
    #     """많은 창이 동시에 열림 (anxiety 증가)"""
    #     self._clamp_mood("anxiety", self.mood["anxiety"] + 0.15)
    #     self._clamp_mood("thinking", self.mood["thinking"] + 0.12)
    #     self._clamp_mood("fear", self.mood["fear"] + 0.08)

    def on_task_complex(self):
        """복잡한 작업 감지 (thinking 증가)"""
        self._clamp_mood("thinking", self.mood["thinking"] + 0.18)
        self._clamp_mood("anxiety", self.mood["anxiety"] + 0.08)
        self._clamp_mood("happy", self.mood["happy"] - 0.05)

    def on_item_acquired(self):
        """파일/폴더를 들었을 때 (happy 크게 증가)"""
        self._clamp_mood("happy", self.mood["happy"] + 0.5)
        self._clamp_mood("bored", self.mood["bored"] - 0.2)
        self._clamp_mood("sad", self.mood["sad"] - 0.1)
        self._clamp_mood("anxiety", self.mood["anxiety"] - 0.15)

    def on_item_dropped(self):
        """물건을 떨어뜨렸을 때 (happy 약간 감소)"""
        self._clamp_mood("happy", self.mood["happy"] - 0.15)
        self._clamp_mood("sad", self.mood["sad"] + 0.1)

    # ------------------------
    # 자연 감소
    # ------------------------
    def decay(self):
        """시간에 따른 감정 자연 감소"""
        for key in self.mood:
            # 감정 값을 0.95배로 감소, 그리고 0~1 범위로 제한
            self._clamp_mood(key, self.mood[key] * 0.95)

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

    # ------------------------
    # 로깅 및 상태 조회
    # ------------------------
    def get_formatted_mood_log(self):
        """보기 좋게 포맷팅된 감정 상태 로그 생성"""
        # 감정 점수를 내림차순으로 정렬
        sorted_mood = sorted(self.mood.items(), key=lambda x: x[1], reverse=True)
        
        # 현재 dominant 감정 찾기
        dominant_emotion = self.decide_emotion()["emotion"]
        
        # 로그 문자열 생성
        log_lines = [f"[감정 상태] 현재 기분: {dominant_emotion} ⭐"]
        log_lines.append("━" * 40)
        
        for emotion, score in sorted_mood:
            # 스코어에 따라 시각화 바 생성
            bar_length = int(score * 20)  # 20 칸 기준
            bar = "█" * bar_length + "░" * (20 - bar_length)
            
            # 현재 dominant 감정에 마크 추가
            mark = "◀ 주요" if emotion == dominant_emotion else ""
            
            log_lines.append(f"  {emotion:8} | {bar} | {score:.3f} {mark}")
        
        log_lines.append("━" * 40)
        
        return "\n".join(log_lines)

    def get_dominant_emotion(self):
        """현재 dominant 감정 반환"""
        return self.decide_emotion()["emotion"]

    def has_emotion_changed(self):
        """감정이 변경되었는지 확인"""
        current_dominant = self.get_dominant_emotion()
        changed = current_dominant != self._last_dominant_emotion
        
        if changed:
            self._last_dominant_emotion = current_dominant
        
        return changed, self._last_dominant_emotion, current_dominant