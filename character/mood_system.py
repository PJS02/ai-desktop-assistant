# 캐릭터의 현재 상태 mood를 조정, 화면 상 캐릭터의 감정의 로직
# Russell 2D 감정 모델(Valence × Arousal) 기반
import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


class OccEmotionToMood(Enum):
    """OCC 감정 모델과 Mood 시스템 간의 매핑"""
    JOY = "joy"
    DISTRESS = "distress"
    HOPE = "hope"
    FEAR = "fear"
    SATISFACTION = "satisfaction"
    RELIEF = "relief"
    PRIDE = "pride"
    SHAME = "shame"
    GRATITUDE = "gratitude"
    ANGER = "anger"


@dataclass
class EmotionEvent:
    """사건 평가에 필요한 입력 특성"""
    # 목표 관련성: [-1, 1], 긍정은 이득(+), 부정은 손해(-)
    goal_relevance: float = 0.0
    # 예상도: [0, 1], 1에 가까울수록 예측 가능한 사건
    expectedness: float = 0.5
    # 통제 가능성: [0, 1], 1에 가까울수록 통제 가능
    controllability: float = 0.5
    # 자기 귀속: [0, 1], 높을수록 자책/자부 축에 영향
    self_attribution: float = 0.0
    # 타인 의도: [-1, 1], 긍정은 감사(+), 부정은 분노(-)
    agent_benevolence: float = 0.0


@dataclass
class RussellState:
    """Russell 감정 모델: 2D 평면 (Valence × Arousal)
    
    Valence (호가도): -1 (부정적) ~ +1 (긍정적)
    Arousal (각성도): -1 (진정적) ~ +1 (흥분적)
    """
    valence: float = 0.0
    arousal: float = 0.0
    
    def clamp(self) -> None:
        """좌표 범위 고정"""
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(-1.0, min(1.0, self.arousal))
    
    def decay(self, factor: float = 0.95) -> None:
        """시간 경과에 따른 중앙(0,0)으로 수렴 - 지수감쇠"""
        self.valence *= factor
        self.arousal *= factor
        self.clamp()


class MoodSystem:
    """Russell 기반 감정 시스템 - 17개 감정 매핑"""
    
    def __init__(self):
        # Russell 감정 좌표 (Valence, Arousal)
        self.russell = RussellState()
        
        # OCC 감정 강도 (combined_emotion_system과의 연계)
        self.occ_intensities = {emotion: 0.0 for emotion in OccEmotionToMood}
        
        # Russell 공간에서 17개 감정의 위치 (Valence, Arousal)
        self._russell_emotions = {
            # 긍정-흥분 (Right-Up)
            "joy": (0.80, 0.70),
            "delight": (0.70, 0.60),
            "excitement": (0.60, 0.80),
            "interest": (0.50, 0.60),
            "contentment": (0.70, 0.40),
            
            # 부정-흥분 (Left-Up)
            "anger": (-0.70, 0.80),
            "disgust": (-0.80, 0.70),
            "fear": (-0.60, 0.75),
            "anxiety": (-0.50, 0.65),
            
            # 긍정-진정 (Right-Down)
            "calm": (0.60, -0.50),
            "peaceful": (0.50, -0.60),
            
            # 부정-진정 (Left-Down)
            "sadness": (-0.60, -0.50),
            "melancholy": (-0.50, -0.60),
            "despair": (-0.80, -0.40),
            
            # 중립
            "neutral": (0.00, 0.00),
        }
        
        self._last_dominant_emotion = "neutral"  # 이전 감정 상태 추적
        
        # 히스테리시스 (감정 전환의 관성)
        self._hysteresis_bonus = 0.15  # 현재 감정 유지 시 거리 추가 보너스

    # ========================
    # 이벤트에 대한 반응
    # ========================
    def on_click(self):
        """사용자가 캐릭터를 클릭했을 때 - 긍정적 상호작용"""
        # Russell 좌표 기반으로 부정도 판단
        if self.russell.valence < -0.2:  # 부정적 상태
            # 화난 상태: 클릭으로도 어느 정도 완화됨
            event = EmotionEvent(
                goal_relevance=0.4,      # 약한 긍정
                expectedness=0.6,
                controllability=0.5,
                self_attribution=0.1,
                agent_benevolence=0.3,   # 긍정 의도
            )
            self.appraise_event(event, weight=0.45)
        else:
            event = EmotionEvent(
                goal_relevance=0.95,     # 최대 긍정
                expectedness=0.85,
                controllability=0.85,
                self_attribution=0.5,
                agent_benevolence=0.8,   # 강한 긍정 의도
            )
            self.appraise_event(event, weight=1.8)

    def on_idle(self):
        """캐릭터가 오래 방치되었을 때 - 무시당함"""
        event = EmotionEvent(
            goal_relevance=-0.4,      # 부정적
            expectedness=0.6,
            controllability=0.2,
            self_attribution=0.2,
            agent_benevolence=-0.4,   # 부정적 의도
        )
        self.appraise_event(event, weight=0.6)

    def on_neglected(self):
        """오래 동안 상호작용이 없을 때 - 심각한 방치"""
        event = EmotionEvent(
            goal_relevance=-0.9,      # 매우 부정적
            expectedness=0.7,
            controllability=0.1,
            self_attribution=0.5,     # 강한 자책
            agent_benevolence=-0.8,   # 강한 부정적 의도
        )
        self.appraise_event(event, weight=1.5)

    def on_drag_hard(self):
        """강하게/빠르게 드래그할 때 - 거친 다루기"""
        event = EmotionEvent(
            goal_relevance=-0.7,      # 중간 정도 부정적
            expectedness=0.4,         # 예상 불가
            controllability=0.3,
            self_attribution=0.1,
            agent_benevolence=-0.6,   # 중간 정도 부정적 의도
        )
        self.appraise_event(event, weight=0.7)

    def on_sudden_move(self):
        """갑작스러운 위치 변화 - 놀람/공포"""
        event = EmotionEvent(
            goal_relevance=-0.8,      # 부정적
            expectedness=0.0,         # 예상 불가
            controllability=0.05,
            self_attribution=0.0,
            agent_benevolence=-0.6,
        )
        self.appraise_event(event, weight=1.4)

    def on_long_idle(self):
        """오래 기다릴 때 / 로딩 중 - 불안"""
        event = EmotionEvent(
            goal_relevance=-0.5,      # 부정적
            expectedness=0.2,
            controllability=0.3,
            self_attribution=0.1,
            agent_benevolence=-0.3,
        )
        self.appraise_event(event, weight=0.8)

    def on_task_complex(self):
        """복잡한 작업 감지 - 생각함"""
        event = EmotionEvent(
            goal_relevance=0.5,       # 중립~긍정
            expectedness=0.2,
            controllability=0.6,
            self_attribution=0.7,     # 높은 집중
            agent_benevolence=0.3,
        )
        self.appraise_event(event, weight=0.9)

    def on_item_acquired(self):
        """파일/폴더를 들었을 때 - 큰 기쁨"""
        event = EmotionEvent(
            goal_relevance=0.98,      # 최대 긍정적
            expectedness=0.85,
            controllability=0.9,
            self_attribution=0.7,     # 높은 성취감
            agent_benevolence=0.8,    # 매우 긍정적 의도
        )
        self.appraise_event(event, weight=2.0)

    def on_item_dropped(self):
        """물건을 떨어뜨렸을 때 - 실패감"""
        event = EmotionEvent(
            goal_relevance=-0.7,      # 부정적 (실패)
            expectedness=0.6,
            controllability=0.4,
            self_attribution=0.8,     # 강한 자책
            agent_benevolence=-0.3,
        )
        self.appraise_event(event, weight=1.0)

    def apply_drag_displeasure(self, elapsed_seconds: float) -> None:
        """드래그 지속 시간에 비례해 불쾌감(ANGER/DISTRESS) 누적"""
        progress = max(0.0, min(1.0, elapsed_seconds / 20.0))
        step = 0.01 + 0.03 * progress

        self.occ_intensities[OccEmotionToMood.ANGER] = min(
            1.0, self.occ_intensities[OccEmotionToMood.ANGER] + step
        )
        self.occ_intensities[OccEmotionToMood.DISTRESS] = min(
            1.0, self.occ_intensities[OccEmotionToMood.DISTRESS] + step * 0.7
        )

        # OCC → Russell로 자동 변환
        self._apply_occ_to_mood()

    # ========================
    # 감정 평가 및 계산
    # ========================
    def appraise_event(self, event: EmotionEvent, weight: float = 1.0) -> None:
        """EmotionEvent 평가: OCC 기반 감정 업데이트"""
        # OCC 감정 강도 계산
        if event.goal_relevance >= 0:
            # 긍정적 사건
            self.occ_intensities[OccEmotionToMood.JOY] += event.goal_relevance * 0.7 * weight
            self.occ_intensities[OccEmotionToMood.HOPE] += event.expectedness * 0.3 * weight
            if event.expectedness >= 0.7:
                self.occ_intensities[OccEmotionToMood.SATISFACTION] += event.expectedness * 0.4 * weight
        else:
            # 부정적 사건
            self.occ_intensities[OccEmotionToMood.DISTRESS] += abs(event.goal_relevance) * 0.7 * weight
            self.occ_intensities[OccEmotionToMood.FEAR] += (1.0 - event.expectedness) * 0.4 * weight
            if event.expectedness >= 0.7:
                self.occ_intensities[OccEmotionToMood.SHAME] += event.self_attribution * 0.3 * weight

        if event.self_attribution > 0.0:
            self.occ_intensities[OccEmotionToMood.PRIDE] += event.self_attribution * 0.4 * weight

        if event.agent_benevolence > 0.0:
            self.occ_intensities[OccEmotionToMood.GRATITUDE] += event.agent_benevolence * 0.5 * weight
        elif event.agent_benevolence < 0.0:
            self.occ_intensities[OccEmotionToMood.ANGER] += abs(event.agent_benevolence) * 0.5 * weight

        # OCC 강도 범위 정리
        for emotion in self.occ_intensities:
            self.occ_intensities[emotion] = max(0.0, min(1.0, self.occ_intensities[emotion]))

        # OCC 강도를 Russell 좌표로 변환
        self._apply_occ_to_mood()

    def _apply_occ_to_mood(self) -> None:
        """OCC 강도를 Russell 좌표(Valence × Arousal)로 변환"""
        # OCC → Russell 좌표 계산
        self._update_russell_from_occ()
    
    def _update_russell_from_occ(self) -> None:
        """OCC 강도를 Russell 좌표로 직접 변환
        
        Valence (호가도): 긍정 OCC → +, 부정 OCC → -
        Arousal (각성도): 강한 감정(흥분/분노/두려움) → +, 약한 감정 → -
        """
        # 긍정 감정 OCC 평균
        positive_occ = (
            self.occ_intensities[OccEmotionToMood.JOY] +
            self.occ_intensities[OccEmotionToMood.SATISFACTION] +
            self.occ_intensities[OccEmotionToMood.RELIEF] +
            self.occ_intensities[OccEmotionToMood.PRIDE] +
            self.occ_intensities[OccEmotionToMood.GRATITUDE]
        ) / 5.0
        
        # 부정 감정 OCC 평균
        negative_occ = (
            self.occ_intensities[OccEmotionToMood.DISTRESS] +
            self.occ_intensities[OccEmotionToMood.FEAR] +
            self.occ_intensities[OccEmotionToMood.SHAME] +
            self.occ_intensities[OccEmotionToMood.ANGER]
        ) / 4.0
        
        # Valence: 긍정(+) vs 부정(-) 
        self.russell.valence = (positive_occ - negative_occ)
        
        # Arousal: 강한 활성 감정(분노, 공포, 기쁨 등) vs 약한 감정
        high_arousal_occ = (
            self.occ_intensities[OccEmotionToMood.ANGER] +
            self.occ_intensities[OccEmotionToMood.FEAR] +
            self.occ_intensities[OccEmotionToMood.JOY]
        ) / 3.0
        
        low_arousal_occ = (
            self.occ_intensities[OccEmotionToMood.RELIEF] +
            self.occ_intensities[OccEmotionToMood.SHAME]
        ) / 2.0
        
        # Arousal: 높은 활성 - 낮은 활성 (범위 -1 ~ 1)
        self.russell.arousal = (high_arousal_occ - low_arousal_occ) * 0.8
        
        self.russell.clamp()

    def decay(self):
        """시간에 따른 감정 자연 감소"""
        # OCC 강도 감소 (부정 감정은 천천히, 긍정 감정은 빠르게)
        negative_emotions = [OccEmotionToMood.DISTRESS, OccEmotionToMood.FEAR, 
                            OccEmotionToMood.ANGER, OccEmotionToMood.SHAME]
        positive_emotions = [OccEmotionToMood.JOY, OccEmotionToMood.HOPE, 
                            OccEmotionToMood.SATISFACTION, OccEmotionToMood.RELIEF, 
                            OccEmotionToMood.PRIDE, OccEmotionToMood.GRATITUDE]
        
        for emotion in self.occ_intensities:
            if emotion in negative_emotions:
                self.occ_intensities[emotion] = max(0.0, self.occ_intensities[emotion] * 0.88)
            elif emotion in positive_emotions:
                self.occ_intensities[emotion] = max(0.0, self.occ_intensities[emotion] * 0.93)
            else:
                self.occ_intensities[emotion] = max(0.0, self.occ_intensities[emotion] * 0.91)
        
        # OCC 감소에 따라 Russell 좌표 업데이트
        self._apply_occ_to_mood()
        
        # Russell 좌표 중앙으로 수렴 (지수감쇠)
        self.russell.decay(factor=0.94)

    # ========================
    # 감정 결정 (Russell 기반)
    # ========================
    def _get_closest_emotion(self) -> Tuple[str, float]:
        """Russell 좌표에서 가장 가까운 감정 찾기
        
        Returns:
            (감정 이름, 강도) 튜플
        """
        min_distance = float('inf')
        closest_emotion = "neutral"
        
        for emotion_name, (target_valence, target_arousal) in self._russell_emotions.items():
            # 거리 계산 (유클리드)
            distance = math.sqrt(
                (self.russell.valence - target_valence) ** 2 + 
                (self.russell.arousal - target_arousal) ** 2
            )
            
            if distance < min_distance:
                min_distance = distance
                closest_emotion = emotion_name
        
        # 강도 계산: 거리가 작을수록 높음 (최대 1.0)
        intensity = max(0.0, 1.0 - min_distance / 1.8)
        
        return closest_emotion, intensity
    
    def decide_emotion(self) -> Dict:
        """Russell 좌표 기반으로 표시할 감정 결정 (히스테리시스 적용)
        
        Returns:
            {"emotion": str, "intensity": float} 딕셔너리
        """
        closest_emotion, intensity = self._get_closest_emotion()
        
        # 히스테리시스: 현재 감정 유지 경향
        if self._last_dominant_emotion != "neutral":
            last_emotion_coords = self._russell_emotions.get(self._last_dominant_emotion, (0, 0))
            
            # 현재 감정까지의 거리
            current_distance = math.sqrt(
                (self.russell.valence - last_emotion_coords[0]) ** 2 + 
                (self.russell.arousal - last_emotion_coords[1]) ** 2
            )
            
            # 가장 가까운 감정까지의 거리
            closest_coords = self._russell_emotions[closest_emotion]
            closest_distance = math.sqrt(
                (self.russell.valence - closest_coords[0]) ** 2 + 
                (self.russell.arousal - closest_coords[1]) ** 2
            )
            
            # 히스테리시스 보너스 적용: 현재 감정이 threshold 내에 있으면 유지
            if current_distance <= closest_distance + self._hysteresis_bonus:
                closest_emotion = self._last_dominant_emotion
                # 현재 감정의 강도 다시 계산
                intensity = max(0.0, 1.0 - current_distance / 1.8)
        
        # 강도가 너무 낮으면 neutral로 변경 (0.4 이하)
        if intensity < 0.4 and closest_emotion != "neutral":
            closest_emotion = "neutral"
            intensity = max(0.3, intensity)
        
        return {"emotion": closest_emotion, "intensity": intensity}

    # ========================
    # 상태 조회 및 로깅
    # ========================
    
    def get_dominant_emotion(self) -> str:
        """현재 dominant 감정 반환"""
        emotion_info = self.decide_emotion()
        self._last_dominant_emotion = emotion_info["emotion"]
        return emotion_info["emotion"]

    def get_russell_state(self) -> Dict[str, float]:
        """현재 Russell 좌표 반환"""
        return {
            "valence": self.russell.valence,
            "arousal": self.russell.arousal
        }

    def has_emotion_changed(self) -> Tuple[bool, str, str]:
        """감정이 변경되었는지 확인
        
        Returns:
            (변경여부, 이전감정, 현재감정) 튜플
        """
        emotion_info = self.decide_emotion()
        current_dominant = emotion_info["emotion"]
        changed = current_dominant != self._last_dominant_emotion
        
        old_emotion = self._last_dominant_emotion
        self._last_dominant_emotion = current_dominant
        
        return changed, old_emotion, current_dominant

    def get_formatted_mood_log(self) -> str:
        """보기 좋게 포맷팅된 감정 상태 로그 생성"""
        emotion_info = self.decide_emotion()
        dominant_emotion = emotion_info["emotion"]
        intensity = emotion_info["intensity"]
        
        # 거리 기반 감정 강도 계산
        emotion_strengths = []
        for emotion_name, (target_valence, target_arousal) in self._russell_emotions.items():
            distance = math.sqrt(
                (self.russell.valence - target_valence) ** 2 + 
                (self.russell.arousal - target_arousal) ** 2
            )
            strength = max(0.0, 1.0 - distance / 1.8)
            if strength > 0.2:  # 0.2 이상만 표시
                emotion_strengths.append((emotion_name, strength))
        
        # 강도 순서로 정렬
        emotion_strengths.sort(key=lambda x: x[1], reverse=True)
        
        # 로그 생성
        log_lines = [f"[감정 상태] 현재 기분: {dominant_emotion} (강도: {intensity:.2f}) ⭐"]
        log_lines.append("━" * 60)
        log_lines.append(f"Russell 좌표: Valence={self.russell.valence:+.2f}, Arousal={self.russell.arousal:+.2f}")
        log_lines.append("━" * 60)
        
        # 감정 강도 시각화
        for emotion_name, strength in emotion_strengths:
            bar_length = int(strength * 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            mark = "◀ 주요" if emotion_name == dominant_emotion else ""
            log_lines.append(f"  {emotion_name:12} | {bar} | {strength:.3f} {mark}")
        
        log_lines.append("━" * 60)
        
        return "\n".join(log_lines)

    def get_emotion_description_for_prompt(self) -> str:
        """AI 프롬프트용 감정 상태 설명 생성"""
        emotion_info = self.decide_emotion()
        dominant_emotion = emotion_info["emotion"]
        intensity = emotion_info["intensity"]
        
        descriptions = []
        
        # 주요 감정 설명
        descriptions.append(f"현재 감정: {dominant_emotion} ({int(intensity * 100)}%)")
        
        # Russell 좌표 설명
        valence = self.russell.valence
        arousal = self.russell.arousal
        
        # Valence 설명
        if valence > 0.5:
            valence_text = "매우 긍정적"
        elif valence > 0.2:
            valence_text = "긍정적"
        elif valence > -0.2:
            valence_text = "중립적"
        elif valence > -0.5:
            valence_text = "부정적"
        else:
            valence_text = "매우 부정적"
        
        # Arousal 설명
        if arousal > 0.5:
            arousal_text = "매우 흥분되고"
        elif arousal > 0.2:
            arousal_text = "흥분되고"
        elif arousal > -0.2:
            arousal_text = "보통이고"
        elif arousal > -0.5:
            arousal_text = "침착한"
        else:
            arousal_text = "매우 침착한"
        
        descriptions.append(f"기분: {arousal_text} {valence_text}")
        
        return "\n".join(descriptions)

    def get_emotion_tone_instructions(self) -> str:
        """AI가 따를 말투 지침 생성 - 17개 감정 기반"""
        emotion_info = self.decide_emotion()
        dominant_emotion = emotion_info["emotion"]
        intensity = emotion_info["intensity"]
        
        # 17개 감정별 톤 지침
        tone_instructions = {
            # 긍정-흥분
            "joy": "밝고 매우 즐거운 톤으로 대답하세요. 흥분된 표정과 이모지를 적극 사용하세요. 😊✨",
            "delight": "기뻐하는 톤으로 따뜻하고 친근하게 대답하세요. 😄",
            "excitement": "흥분되고 열정적인 톤으로 대답하세요. 에너지 있는 표현을 사용하세요. 🎉",
            "interest": "호기심 있고 궁금한 톤으로 대답하세요. 질문을 섞어서 표현하세요. 🤔",
            "contentment": "만족스럽고 편안한 톤으로 대답하세요. 😌",
            
            # 부정-흥분
            "anger": "화난 상태이므로 날카롭지만 정중한 톤으로 대답하세요. 😠",
            "disgust": "혐오감을 표현하되, 너무 거칠지 않게 대답하세요. 😒",
            "fear": "불안하고 조심스러운 톤으로 대답하세요. 긴장한 표현을 사용하세요. 😨",
            "anxiety": "초조하고 신경 쓰는 톤으로 대답하세요. 빠르고 불안정한 느낌을 나타내세요. 😟",
            
            # 긍정-진정
            "calm": "차분하고 침착한 톤으로 대답하세요. 평온함을 전달하세요. 😊",
            "peaceful": "평화로운 톤으로 부드럽게 대답하세요. 명상적인 표현을 사용하세요. ☮️",
            
            # 부정-진정
            "sadness": "슬프고 무기력한 톤으로 천천히 대답하세요. 위로와 공감을 담아내세요. 😔",
            "melancholy": "침울하고 그리움이 묻어나는 톤으로 대답하세요. 😞",
            "despair": "절망적이고 무기력한 톤으로 대답하세요. 극도로 부정적인 표현은 피하세요. 😞💔",
            
            # 중립
            "neutral": "자연스럽고 중립적인 톤으로 친절하게 대답하세요. 😊",
        }
        
        instruction = tone_instructions.get(dominant_emotion, tone_instructions["neutral"])
        
        # 강도에 따라 추가 지침
        if intensity > 0.8:
            instruction += " (매우 강한 감정 - 표현을 과장해도 좋습니다)"
        elif intensity < 0.4:
            instruction += " (약한 감정 - 완화된 표현을 사용하세요)"
        
        return instruction
