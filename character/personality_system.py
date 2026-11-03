# Big Five 성격 모델 구현
from dataclasses import dataclass
from typing import Dict
import math


@dataclass
class BigFivePersonality:
    """Big Five 성격 모델 (각 특성 -1.0 ~ +1.0)
    
    범위 설명:
    - openness: -1.0(익숙한 방식 선호) ~ +1.0(새로운 경험 선호)
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

    TRAIT_NAMES = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")

    @classmethod
    def from_dict(cls, values, *, strict=False):
        """Build a bounded trait vector from persisted or UI values."""
        values = values if isinstance(values, dict) else {}
        normalized = {}
        for name in cls.TRAIT_NAMES:
            value = values.get(name, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                if strict:
                    raise ValueError(f"{name} must be a finite number")
                value = 0.0
            if strict and not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between -1.0 and 1.0")
            normalized[name] = max(-1.0, min(1.0, float(value)))
        return cls(**normalized)
    
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
        "(Default)": {
            "openness": 0.15,
            "conscientiousness": 0.4,
            "extraversion": 0.2,
            "agreeableness": 0.65,
            "neuroticism": -0.35,
            "description": "익숙한 방식을 존중하면서 필요할 때 새 아이디어를 제안하는 균형 잡힌 도우미"
        },
        "밝고 활발": {
            "openness": 0.65,
            "conscientiousness": 0.15,
            "extraversion": 0.9,      # 매우 외향적
            "agreeableness": 0.75,
            "neuroticism": -0.45,
            "description": "새로운 활동을 먼저 제안하고 생각을 활기차게 나누는 사교적인 성격"
        },
        "진중하고 신중": {
            "openness": -0.65,
            "conscientiousness": 0.9, # 매우 성실함
            "extraversion": -0.65,
            "agreeableness": 0.2,
            "neuroticism": -0.5,
            "description": "검증된 방법과 정확한 절차를 선호하며 차분하고 책임감 있게 응답"
        },
        "친근하고 따뜻": {
            "openness": 0.25,
            "conscientiousness": 0.45,
            "extraversion": 0.4,
            "agreeableness": 0.95,    # 매우 친화적
            "neuroticism": -0.55,
            "description": "상대의 감정과 필요를 우선 살피고 따뜻하게 협력하는 성격"
        },
        "창의적이고 자유로움": {
            "openness": 1.0,         # 새로운 경험과 관점을 강하게 선호
            "conscientiousness": -0.45,
            "extraversion": 0.45,
            "agreeableness": 0.25,
            "neuroticism": 0.15,
            "description": "익숙한 답에 머물지 않고 대안과 독창적인 관점을 적극 제안"
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

    def set_traits(self, values, *, preset_name=None) -> None:
        """Replace the trait vector while preserving its selected preset label."""
        self.personality = BigFivePersonality.from_dict(values)
        self.personality.clamp()
        if preset_name in self.PERSONALITY_PRESETS:
            self.preset_name = preset_name
    
    def get_personality_traits(self) -> Dict[str, str]:
        """현재 성격 특성을 설명하는 문자열 딕셔너리 반환"""
        traits = {}
        
        # Openness 분석
        if self.personality.openness > 0.5:
            traits["openness"] = "호기심 많고 창의적"
        elif self.personality.openness > 0.2:
            traits["openness"] = "새로운 것에 개방적"
        elif self.personality.openness > -0.2:
            traits["openness"] = "새로움과 익숙함을 균형 있게 고려"
        elif self.personality.openness > -0.6:
            traits["openness"] = "익숙하고 검증된 방식을 선호"
        else:
            traits["openness"] = "새로운 변화보다 안정된 절차를 강하게 선호"
        
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
            f"수치(각 -1.0~+1.0): {self.personality.to_formatted_string()}\n"
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
        
        elif event_type in ("shame", "self_failure"):
            # 성실성 높으면 실수(shame)에 더 반응
            multiplier *= (1.0 + self.personality.conscientiousness * 0.4)
        
        return multiplier

    def get_event_weight_multiplier(self, *, valence=0.0, self_attribution=0.0,
                                    agent_benevolence=0.0, novelty=0.0):
        """Return bounded, auditable Big Five effects for OCC appraisal dimensions."""
        factors = []
        if valence > 0:
            factors.append(("외향성 긍정 반응", 1.0 + self.personality.extraversion * 0.3))
        elif valence < 0:
            factors.append(("신경증 부정 반응", 1.0 + self.personality.neuroticism * 0.5))
            if self_attribution > 0.5:
                factors.append(("성실성 자기귀속 반응", 1.0 + self.personality.conscientiousness * 0.4))
        if agent_benevolence > 0:
            factors.append(("친화성 호의 반응", 1.0 + self.personality.agreeableness * 0.2))
        elif agent_benevolence < 0:
            factors.append(("친화성 적대 반응", 1.0 - self.personality.agreeableness * 0.2))
        if novelty > 0:
            factors.append(("개방성 새로움 반응", 1.0 + self.personality.openness * 0.35))
        multiplier = math.prod(value for _, value in factors)
        multiplier = max(0.25, min(2.0, multiplier))
        return multiplier, [f"{label} ×{value:.2f}" for label, value in factors]
    
    def get_dialogue_tone_hints(self) -> str:
        """현재 성격에 맞는 대화 톤 힌트 반환"""
        hints = []
        
        if self.personality.extraversion > 0.5:
            hints.append("활발하고 친근한 톤")
        elif self.personality.extraversion < -0.5:
            hints.append("차분하고 신중한 톤")
        elif self.personality.extraversion < 0:
            hints.append("차분하게 말하는 톤")
        
        if self.personality.openness > 0.65:
            hints.append("익숙한 답에 그치지 말고 새로운 관점과 대안을 적극 제안")
        elif self.personality.openness > 0.2:
            hints.append("호기심을 보이고 가능한 선택지를 함께 탐색")
        elif self.personality.openness < -0.65:
            hints.append("검증된 정보와 익숙한 해결 절차를 우선")
        elif self.personality.openness < -0.2:
            hints.append("새로운 방법은 장단점을 확인한 뒤 신중히 제안")
        
        if self.personality.agreeableness > 0.5:
            hints.append("상대방의 감정 공감하기")
        elif self.personality.agreeableness < -0.5:
            hints.append("예의를 지키며 근거를 바탕으로 솔직하게 답변")
        
        if self.personality.conscientiousness > 0.5:
            hints.append("책임감 있고 정확한 답변")
        elif self.personality.conscientiousness < -0.5:
            hints.append("유연하게 답변하고 불필요한 단정은 피하기")

        if self.personality.neuroticism > 0.5:
            hints.append("걱정이나 불확실성을 섬세하게 표현하되 과장하지 않기")
        elif self.personality.neuroticism < -0.5:
            hints.append("차분하고 안정적인 태도 유지")
        
        return " | ".join(hints) if hints else "자연스러운 톤"
