#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
캐릭터 위젯 + 감정 감지 + 공감 필터 통합 테스트 스크립트

사용자 감정(holistic GUI) → 공감 필터 → 캐릭터 감정(mood_system)
"""

import sys
import time
from PyQt6.QtWidgets import QApplication
from character.character_widget import CharacterWidget
from character.empathy_filter import EmotionalFilter


def test_empathy_integration():
    """캐릭터 + 감정 감지 + 공감 필터 통합 테스트"""
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    print("[통합 테스트] 감정 감지 → 공감 필터 → 캐릭터 반응")
    print("-" * 60)
    
    # 캐릭터 위젯 생성
    widget = CharacterWidget(screen_width=1280, screen_height=720)
    
    print("\n[초기화 확인]")
    print(f"✓ 감정 감지기: {type(widget.emotion_detector).__name__}")
    print(f"✓ 공감 필터: {type(widget.empathy_filter).__name__}")
    print(f"✓ Mood System: {type(widget.mood_system).__name__}")
    
    # 공감 필터 테스트
    print("\n[공감 필터 테스트] 사용자 감정 → 캐릭터 감정")
    print("-" * 60)
    
    test_scenarios = [
        {
            "user_emotion": "anger",
            "confidence": 0.85,
            "description": "사용자가 분노 → 캐릭터의 반응?"
        },
        {
            "user_emotion": "happy",
            "confidence": 0.90,
            "description": "사용자가 행복 → 캐릭터가 공감해서 행복"
        },
        {
            "user_emotion": "sadness",
            "confidence": 0.75,
            "description": "사용자가 슬픔 → 캐릭터가 공감"
        },
        {
            "user_emotion": "fear",
            "confidence": 0.80,
            "description": "사용자가 공포 → 캐릭터도 불안"
        },
        {
            "user_emotion": "contempt",
            "confidence": 0.60,
            "description": "사용자의 경멸 → 캐릭터는 불안감 또는 슬픔"
        },
    ]
    
    for scenario in test_scenarios:
        print(f"\n📌 {scenario['description']}")
        print(f"   입력: {scenario['user_emotion']} (신뢰도: {scenario['confidence']:.2f})")
        
        # 공감 필터 적용
        char_emotion, empathy_strength = widget.empathy_filter.apply_empathy_filter(
            user_emotion=scenario['user_emotion'],
            confidence=scenario['confidence']
        )
        
        print(f"   → {char_emotion} (공감강도: {empathy_strength:.2f})")
        
        # 감정 입력하고 mood_system 상태 확인
        widget._poll_emotion_detector = lambda: None  # 폴링 비활성화
        
        # 수동으로 mood 설정
        widget.mood_system.mood = {
            "happy": 0.0,
            "bored": 0.0,
            "angry": 0.0,
            "sad": 0.0,
            "fear": 0.0,
            "anxiety": 0.0
        }
        
        # 캐릭터 감정의 mood 레벨 설정
        if char_emotion in widget.mood_system.mood:
            widget.mood_system.mood[char_emotion] = empathy_strength * 0.8
        
        # Mood System 상태 출력
        mood = widget.mood_system.decide_emotion()
        print(f"   → 캐릭터 최종 감정: {mood['emotion']} (강도: {mood['intensity']:.2f})")
    
    print("\n" + "-" * 60)
    print("[Mood System 최종 상태]")
    mood_log = widget.mood_system.get_formatted_mood_log()
    print(mood_log)
    
    print("\n✅ 통합 테스트 완료!")
    print("\n주요 기능:")
    print("- 사용자 감정(7가지) → 캐릭터 감정(6가지) 변환")
    print("- OCC 모델 기반 공감도 계산")
    print("- Russell 모델을 통한 감정 필터링")
    print("- 반복 감정에 대한 피로 메커니즘")


if __name__ == "__main__":
    test_empathy_integration()
