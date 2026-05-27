#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Russell 기반 17개 감정 시스템 최종 테스트"""

from character.mood_system import MoodSystem

print("═" * 70)
print("Russell 기반 17개 감정 시스템 - 최종 테스트")
print("═" * 70)
print()

# 테스트 1: 모든 이벤트 테스트
events = [
    ("on_click", "긍정 상호작용"),
    ("on_idle", "무시당함"),
    ("on_neglected", "심각한 방치"),
    ("on_drag_hard", "거친 다루기"),
    ("on_sudden_move", "갑작스러운 이동"),
    ("on_long_idle", "오래 기다림"),
    ("on_task_complex", "복잡한 작업"),
    ("on_item_acquired", "아이템 획득"),
    ("on_item_dropped", "아이템 분실"),
]

print("이벤트별 감정 변화:")
print("─" * 70)

for event_name, description in events:
    m = MoodSystem()
    method = getattr(m, event_name)
    method()
    emotion_info = m.decide_emotion()
    emotion = emotion_info["emotion"]
    intensity = emotion_info["intensity"]
    russell = m.get_russell_state()
    
    print(f"{description:20} → {emotion:12} (강도: {intensity:.2f}, V:{russell['valence']:+.2f} A:{russell['arousal']:+.2f})")

print()

# 테스트 2: 감정 감소 시뮬레이션
print("═" * 70)
print("감정 감소 시뮬레이션 (on_neglected → 10회 decay)")
print("─" * 70)

m = MoodSystem()
m.on_neglected()

for i in range(11):
    emotion_info = m.decide_emotion()
    emotion = emotion_info["emotion"]
    intensity = emotion_info["intensity"]
    russell = m.get_russell_state()
    
    if i == 0:
        print(f"초기: {emotion:12} (강도: {intensity:.2f}, V:{russell['valence']:+.2f} A:{russell['arousal']:+.2f})")
    else:
        print(f"decay x{i}: {emotion:12} (강도: {intensity:.2f}, V:{russell['valence']:+.2f} A:{russell['arousal']:+.2f})")
    
    if i < 10:
        m.decay()

print()

# 테스트 3: 17개 감정 매핑 확인
print("═" * 70)
print("17개 감정 Russell 좌표 매핑")
print("─" * 70)

m = MoodSystem()
for emotion_name, (valence, arousal) in m._russell_emotions.items():
    print(f"{emotion_name:12} → V={valence:+.2f}, A={arousal:+.2f}")

print()
print("═" * 70)
print("✅ 모든 17개 감정 시스템 변경 완료!")
print("═" * 70)
