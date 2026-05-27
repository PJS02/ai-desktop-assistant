#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
캐릭터 위젯 + 감정 감지 시스템 테스트 스크립트
카메라가 없는 환경에서 감정 시뮬레이션으로 테스트
"""

import sys
import time
from PyQt6.QtWidgets import QApplication
from character.character_widget import CharacterWidget


def test_character_with_emotion():
    """캐릭터 위젯과 감정 감지 통합 테스트"""
    
    app = QApplication.instance() or QApplication(sys.argv)
    
    print("[테스트] 캐릭터 위젯 + 감정 감지 시스템")
    print("-" * 50)
    
    # 캐릭터 위젯 생성 (1280x720 해상도)
    widget = CharacterWidget(screen_width=1280, screen_height=720)
    
    print("\n[검증 항목]")
    print(f"✓ 감정 감지기 초기화: {widget.emotion_detector}")
    print(f"✓ 감정 감지기 유효: {widget.emotion_detector.is_available()}")
    
    # 감정 감지 타이머가 작동하는지 확인
    print(f"✓ 감정 폴링 타이머: {widget._emotion_detector_timer.isActive()}")
    print(f"✓ Mood System: {widget.mood_system}")
    
    # 수동 감정 폴링 테스트
    print("\n[감정 시뮬레이션 테스트 - 5초간 3번 폴링]")
    for i in range(3):
        emotion, confidence = widget.emotion_detector.get_emotion()
        print(f"  {i+1}. 감지된 감정: {emotion} (신뢰도: {confidence:.2f})")
        
        # 폴링 메서드 호출
        widget._poll_emotion_detector()
        time.sleep(2)
    
    print("\n[Mood System 상태]")
    mood = widget.mood_system.decide_emotion()
    print(f"현재 기분: {mood['emotion']} (강도: {mood['intensity']:.2f})")
    print(widget.mood_system.get_formatted_mood_log())
    
    print("\n✅ 모든 테스트 완료!")
    print("\n참고:")
    print("- 감정 시뮬레이션이 주기적으로 변경됩니다")
    print("- Mood System이 감정 입력을 받아 상태를 업데이트합니다")
    print("- 실제 카메라가 있으면 DetectionMode.CAMERA로 전환 가능합니다")
    
    # GUI는 띄우지 않고 테스트만 수행
    print("\n(GUI를 띄우려면 widget.show() 후 app.exec() 호출)")
    
    return widget


if __name__ == "__main__":
    widget = test_character_with_emotion()
