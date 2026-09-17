# Big Five 성격 모델 구현
from dataclasses import dataclass
from typing import Dict


@dataclass
class BigFivePersonality:
    """Big Five 성격 모델 (각 특성 -1.0 ~ +1.0)
    
    범위 설명:
    - openness: -1.0(보수적) ~ +1.0(개방적)
    - conscientiousness: -1.0(충동적) ~ +1.0(성실함)
    - extraversion: -1.0(내향적) ~ +1.0(외향적)
    - agreeableness: -1.0(독립적) ~ +1.0(친화적)
    - neuroticism: -1.0(안정적) ~ +1.0(불안감)
    """
    openness: float = 0.0
    conscientiousness: float = 0.0
    extraversion: float = 0.0
    agreeableness: float = 0.0
    neuroticism: float = 0.0
    
    def clamp(self) -> None:
        """모든 값을 -1.0 ~ +1.0 범위로 정규화"""
        self.openness = max(-1.0, min(1.0, self.openness))
        self.conscientiousness = max(-1.0, min(1.0, self.conscientiousness))
        self.extraversion = max(-1.0, min(1.0, self.extraversion))
        self.agreeableness = max(-1.0, min(1.0, self.agreeableness))
        self.neuroticism = max(-1.0, min(1.0, self.neuroticism))
    
    def to_dict(self) -> Dict[str, float]:
        """딕셔너리 형태로 반환"""
        return {
            "openness": self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion": self.extraversion,
            "agreeableness": self.agreeableness,
            "neuroticism": self.neuroticism,
        }
    
    def to_formatted_string(self) -> str:
        """포맷팅된 문자열로 반환"""
        return (
            f"개방성: {self.openness:+.2f} | "
            f"성실성: {self.conscientiousness:+.2f} | "
            f"외향성: {self.extraversion:+.2f} | "
            f"친화성: {self.agreeableness:+.2f} | "
            f"신경증: {self.neuroticism:+.2f}"
        )


class PersonalitySystem:
    """캐릭터의 Big Five 성격 체계 관리"""
    
    # 성격 프리셋
    PERSONALITY_PRESETS = {
        "Russell (기본)": {
            "openness": 0.7,
            "conscientiousness": 0.6,
            "extraversion": 0.5,
            "agreeableness": 0.8,
            "neuroticism": -0.3,
            "description": "호기심 많고 친절하며 안정적인 도우미"
        },
        "밝고 활발": {
            "openness": 0.8,
            "conscientiousness": 0.5,
            "extraversion": 0.9,      # 매우 외향적
            "agreeableness": 0.7,
            "neuroticism": -0.5,
            "description": "긍정적이고 사교적이며 에너지 넘침"
        },
        "진중하고 신중": {
            "openness": 0.5,
            "conscientiousness": 0.9, # 매우 성실함
            "extraversion": -0.3,
            "agreeableness": 0.6,
            "neuroticism": -0.7,
            "description": "신중하고 책임감 있으며 전문적"
        },
        "친근하고 따뜻": {
            "openness": 0.6,
            "conscientiousness": 0.7,
            "extraversion": 0.6,
            "agreeableness": 0.95,    # 매우 친화적
            "neuroticism": -0.6,
            "description": "공감 능력 뛰어나고 항상 도움을 줌"
        },
        "창의적이고 자유로움": {
            "openness": 0.95,         # 매우 개방적
            "conscientiousness": -0.2,
            "extraversion": 0.4,
            "agreeableness": 0.5,
            "neuroticism": 0.1,
            "description": "혁신적이고 독창적인 아이디어 제시"
        },
    }
    
    def __init__(self, preset_name: str = "Russell (기본)"):
        """기본 성격 초기화
        
        Args:
            preset_name: 사용할 성격 프리셋 이름
        """
        self.load_preset(preset_name)
    
    def load_preset(self, preset_name: str) -> None:
        """프리셋으로 성격 로드
        
        Args:
            preset_name: 프리셋 이름
        """
        if preset_name not in self.PERSONALITY_PRESETS:
            preset_name = "Russell (기본)"
        
        preset = self.PERSONALITY_PRESETS[preset_name]
        self.personality = BigFivePersonality(
            openness=preset["openness"],
            conscientiousness=preset["conscientiousness"],
            extraversion=preset["extraversion"],
            agreeableness=preset["agreeableness"],
            neuroticism=preset["neuroticism"]
        )
        self.personality.clamp()
        self.preset_name = preset_name
    
    def get_personality_traits(self) -> Dict[str, str]:
        """현재 성격 특성을 설명하는 문자열 딕셔너리 반환"""
        traits = {}
        
        # Openness 분석
        if self.personality.openness > 0.5:
            traits["openness"] = "호기심 많고 창의적"
        elif self.personality.openness > 0.0:
            traits["openness"] = "새로운 것에 개방적"
        elif self.personality.openness > -0.5:
            traits["openness"] = "습관을 좋아함"
        else:
            traits["openness"] = "전통적이고 보수적"
        
        # Conscientiousness 분석
        if self.personality.conscientiousness > 0.5:
            traits["conscientiousness"] = "체계적이고 책임감 있음"
        elif self.personality.conscientiousness > 0.0:
            traits["conscientiousness"] = "어느 정도 계획적"
        elif self.personality.conscientiousness > -0.5:
            traits["conscientiousness"] = "다소 즉흥적"
        else:
            traits["conscientiousness"] = "충동적이고 산만함"
        
        # Extraversion 분석
        if self.personality.extraversion > 0.5:
            traits["extraversion"] = "사교적이고 활발"
        elif self.personality.extraversion > 0.0:
            traits["extraversion"] = "상황에 따라 사교적"
        elif self.personality.extraversion > -0.5:
            traits["extraversion"] = "차분하고 조용함"
        else:
            traits["extraversion"] = "내향적이고 혼자 시간을 좋아함"
        
        # Agreeableness 분석
        if self.personality.agreeableness > 0.5:
            traits["agreeableness"] = "친절하고 협력적"
        elif self.personality.agreeableness > 0.0:
            traits["agreeableness"] = "일반적으로 친화적"
        elif self.personality.agreeableness > -0.5:
            traits["agreeableness"] = "직설적이고 독립적"
        else:
            traits["agreeableness"] = "냉정하고 비판적"
        
        # Neuroticism 분석
        if self.personality.neuroticism > 0.5:
            traits["neuroticism"] = "감정 변화가 크고 불안감 있음"
        elif self.personality.neuroticism > 0.0:
            traits["neuroticism"] = "어느 정도 불안정한 감정"
        elif self.personality.neuroticism > -0.5:
            traits["neuroticism"] = "일반적으로 안정적"
        else:
            traits["neuroticism"] = "매우 안정적이고 차분함"
        
        return traits
    
    def get_personality_description(self) -> str:
        """성격 설명을 한 문장으로 반환"""
        traits = self.get_personality_traits()
        description = ", ".join(traits.values())
        return description
    
    def get_personality_for_prompt(self) -> str:
        """AI 프롬프트에 포함할 성격 설명 반환"""
        traits = self.get_personality_traits()
        personality_text = (
            f"개방성: {traits['openness']}\n"
            f"성실성: {traits['conscientiousness']}\n"
            f"외향성: {traits['extraversion']}\n"
            f"친화성: {traits['agreeableness']}\n"
            f"신경증: {traits['neuroticism']}"
        )
        return personality_text
    
    def get_emotion_weight_multiplier(self, event_type: str) -> float:
        """이벤트 유형에 따른 감정 반응 가중치 반환
        
        Args:
            event_type: "positive" 또는 "negative"
        
        Returns:
            감정 반응 가중치 (1.0이 기본값)
        """
        multiplier = 1.0
        
        if event_type == "positive":
            # 외향성 높으면 긍정적 이벤트에 더 반응
            multiplier *= (1.0 + self.personality.extraversion * 0.3)
        
        elif event_type == "negative":
            # 신경증 높으면 부정적 이벤트에 더 반응
            multiplier *= (1.0 + self.personality.neuroticism * 0.5)
        
        elif event_type == "shame":
            # 성실성 높으면 실수(shame)에 더 반응
            multiplier *= (1.0 + self.personality.conscientiousness * 0.4)
        
        return multiplier
    
    def get_dialogue_tone_hints(self) -> str:
        """현재 성격에 맞는 대화 톤 힌트 반환"""
        hints = []
        
        if self.personality.extraversion > 0.5:
            hints.append("활발하고 친근한 톤")
        elif self.personality.extraversion < -0.5:
            hints.append("차분하고 신중한 톤")
        
        if self.personality.openness > 0.5:
            hints.append("호기심을 드러내기")
        
        if self.personality.agreeableness > 0.5:
            hints.append("상대방의 감정 공감하기")
        
        if self.personality.conscientiousness > 0.5:
            hints.append("책임감 있고 정확한 답변")
        
        return " | ".join(hints) if hints else "자연스러운 톤"
