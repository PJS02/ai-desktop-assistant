from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional


class OccEmotion(Enum):
    # OCC 모델의 핵심 감정 목록
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
class OccState:
    # OCC 감정 강도는 [0, 1] 범위로 정규화
    intensities: Dict[OccEmotion, float] = field(default_factory=lambda: {e: 0.0 for e in OccEmotion})

    def clamp_all(self) -> None:
        # 모든 감정 강도를 범위 내로 고정
        for emotion, value in list(self.intensities.items()):
            self.intensities[emotion] = max(0.0, min(1.0, value))

    def decay(self, factor: float = 0.95) -> None:
        # 시간 경과에 따른 감정 약화
        for emotion, value in list(self.intensities.items()):
            self.intensities[emotion] = max(0.0, min(1.0, value * factor))

    def dominant(self) -> Optional[OccEmotion]:
        # 현재 가장 큰 강도의 감정 반환
        if not self.intensities:
            return None
        return max(self.intensities, key=self.intensities.get)


@dataclass
class RussellState:
    # Russell 모델의 정서 좌표는 [-1, 1] 범위
    valence: float = 0.0
    arousal: float = 0.0

    def clamp(self) -> None:
        # 좌표 범위 고정
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(-1.0, min(1.0, self.arousal))

    def decay(self, factor: float = 0.95) -> None:
        # 시간 경과에 따른 좌표 완화
        self.valence = max(-1.0, min(1.0, self.valence * factor))
        self.arousal = max(-1.0, min(1.0, self.arousal * factor))


@dataclass
class EmotionEvent:
    # 사건 평가에 필요한 입력 특성
    # 목표 관련성: [-1, 1], 긍정은 이득, 부정은 손해
    goal_relevance: float = 0.0
    # 예상도: [0, 1], 1에 가까울수록 예측 가능한 사건
    expectedness: float = 0.5
    # 통제 가능성: [0, 1], 1에 가까울수록 통제 가능
    controllability: float = 0.5
    # 자기 귀속: [0, 1], 높을수록 자책/자부 축에 영향
    self_attribution: float = 0.0
    # 타인 의도: [-1, 1], 긍정은 감사, 부정은 분노 축
    agent_benevolence: float = 0.0


class CombinedEmotionSystem:
    def __init__(self) -> None:
        # OCC 강도와 Russell 좌표를 동시에 유지
        self.occ = OccState()
        self.russell = RussellState()

        # OCC 감정 -> Russell 좌표 매핑
        # 값은 (valence, arousal) 방향 벡터이며 강도로 스케일됨
        self._occ_to_russell = {
            OccEmotion.JOY: (0.8, 0.4),
            OccEmotion.DISTRESS: (-0.8, 0.4),
            OccEmotion.HOPE: (0.6, 0.3),
            OccEmotion.FEAR: (-0.7, 0.8),
            OccEmotion.SATISFACTION: (0.7, 0.2),
            OccEmotion.RELIEF: (0.5, -0.2),
            OccEmotion.PRIDE: (0.7, 0.5),
            OccEmotion.SHAME: (-0.6, 0.4),
            OccEmotion.GRATITUDE: (0.7, 0.3),
            OccEmotion.ANGER: (-0.7, 0.7),
        }

    def appraise_event(self, event: EmotionEvent, weight: float = 1.0) -> None:
        # OCC 업데이트: 평가 신호에 따라 감정 강도 누적
        if event.goal_relevance >= 0:
            self._add_occ(OccEmotion.JOY, event.goal_relevance * 0.7 * weight)
            self._add_occ(OccEmotion.HOPE, event.expectedness * 0.3 * weight)
            if event.expectedness >= 0.7:
                self._add_occ(OccEmotion.SATISFACTION, event.expectedness * 0.4 * weight)
        else:
            self._add_occ(OccEmotion.DISTRESS, abs(event.goal_relevance) * 0.7 * weight)
            self._add_occ(OccEmotion.FEAR, (1.0 - event.expectedness) * 0.4 * weight)
            if event.expectedness >= 0.7:
                self._add_occ(OccEmotion.SHAME, event.self_attribution * 0.3 * weight)

        if event.self_attribution > 0.0:
            self._add_occ(OccEmotion.PRIDE, event.self_attribution * 0.4 * weight)

        if event.agent_benevolence > 0.0:
            self._add_occ(OccEmotion.GRATITUDE, event.agent_benevolence * 0.5 * weight)
        elif event.agent_benevolence < 0.0:
            self._add_occ(OccEmotion.ANGER, abs(event.agent_benevolence) * 0.5 * weight)

        # 강도 범위 정리
        self.occ.clamp_all()

        # OCC 결과를 기반으로 Russell 좌표 반영
        self._update_russell_from_occ(weight)

    def decay(self, occ_factor: float = 0.95, russell_factor: float = 0.95) -> None:
        # 시간이 지나며 감정과 좌표를 함께 완화
        self.occ.decay(occ_factor)
        self.russell.decay(russell_factor)

    def get_russell_snapshot(self) -> Dict[str, float]:
        # Russell 좌표를 직렬화하기 쉬운 형태로 반환
        return {"valence": self.russell.valence, "arousal": self.russell.arousal}

    def _add_occ(self, emotion: OccEmotion, delta: float) -> None:
        # OCC 감정 강도 누적
        self.occ.intensities[emotion] = self.occ.intensities.get(emotion, 0.0) + delta

    def _update_russell_from_occ(self, weight: float) -> None:
        # OCC 강도 합으로 valence/arousal 변화량 계산
        delta_valence = 0.0
        delta_arousal = 0.0
        for emotion, intensity in self.occ.intensities.items():
            if intensity <= 0.0:
                continue
            direction = self._occ_to_russell.get(emotion)
            if direction is None:
                continue
            delta_valence += direction[0] * intensity * 0.2 * weight
            delta_arousal += direction[1] * intensity * 0.2 * weight

        self.russell.valence += delta_valence
        self.russell.arousal += delta_arousal
        self.russell.clamp()

    # 앱 이벤트를 감정 평가로 변환하는 예시 메서드
    def on_user_click(self) -> None:
        # 긍정적 상호작용으로 가정
        event = EmotionEvent(
            goal_relevance=0.6,
            expectedness=0.7,
            controllability=0.6,
            self_attribution=0.2,
            agent_benevolence=0.3,
        )
        self.appraise_event(event)

    def on_idle_too_long(self) -> None:
        # 방치로 인한 부정적 사건으로 가정
        event = EmotionEvent(
            goal_relevance=-0.4,
            expectedness=0.6,
            controllability=0.3,
            self_attribution=0.1,
            agent_benevolence=-0.1,
        )
        self.appraise_event(event)

    def on_sudden_move(self) -> None:
        # 갑작스러운 이동으로 놀람/불안 증가 가정
        event = EmotionEvent(
            goal_relevance=-0.3,
            expectedness=0.1,
            controllability=0.2,
            self_attribution=0.0,
            agent_benevolence=0.0,
        )
        self.appraise_event(event)
