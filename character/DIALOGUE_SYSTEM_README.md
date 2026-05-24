# 캐릭터 대화 시스템 사용 예제

## 대화 시스템 개요

캐릭터 대화 시스템은 두 가지 UI 스타일을 제공합니다:

### 1. 말풍선 (DialogueBubble)
- 캐릭터 위에 표시되는 클래식한 말풍선
- 자동으로 5초 후 사라짐 (클릭으로 즉시 닫기 가능)
- 호버 시 자동 종료 연기

### 2. 나레이션 박스 (DialogueNarrationBox)
- 화면 하단에 표시되는 대사 박스
- 캐릭터 이름과 함께 대사 표시
- 영상미 있는 게임 스타일 UI

---

## 사용 방법

### 기본 대화 표시

```python
# CharacterWidget 인스턴스에서:

# 말풍선으로 표시
character.dialogue_system.show_dialogue(
    text="안녕하세요!",
    duration=5000,  # 5초
    use_narration=False
)

# 나레이션 박스로 표시
character.dialogue_system.show_dialogue(
    text="저는 AI 어시스턴트입니다.",
    duration=5000,
    use_narration=True,
    character_name="AI 어시스턴트"
)
```

### 순차 대화 (큐)

여러 대화를 순서대로 표시:

```python
# 첫 번째 대화 (즉시)
character.dialogue_system.queue_dialogue(
    text="안녕하세요!",
    duration=3000,
    delay_ms=0
)

# 두 번째 대화 (1초 후)
character.dialogue_system.queue_dialogue(
    text="저는 AI 어시스턴트입니다.",
    duration=3000,
    delay_ms=1000
)

# 세 번째 대화 (나레이션 박스로, 1초 후)
character.dialogue_system.queue_dialogue(
    text="뭔가 도와드릴 것이 있으신가요?",
    duration=3000,
    delay_ms=1000,
    use_narration=True,
    character_name="AI 어시스턴트"
)
```

### 빠른 대사 템플릿

자주 사용하는 대사는 `QuickDialoguePresets`에서 제공:

```python
from character.dialogue_system import QuickDialoguePresets

# 시간대별 인사말 자동 선택
greeting = QuickDialoguePresets.get_greeting()
character.dialogue_system.show_dialogue(greeting, duration=3000)

# 미리 정의된 대사들
character.dialogue_system.show_dialogue(
    QuickDialoguePresets.GREETING,     # "안녕하세요!"
    duration=3000
)

character.dialogue_system.show_dialogue(
    QuickDialoguePresets.ACKNOWLEDGE,  # "네, 확인했습니다!"
    duration=3000
)

character.dialogue_system.show_dialogue(
    QuickDialoguePresets.GAME_DETECTED,  # "게임을 하고 계시네요!"
    duration=3000
)
```

### 현재 상태 확인

```python
# 대화가 표시 중인지 확인
if character.dialogue_system.is_dialogue_active():
    print("현재 대화 중입니다")

# 현재 대화 강제 종료
character.dialogue_system.close_current_dialogue()

# 큐에 있는 모든 대화 제거
character.dialogue_system.clear_queue()
```

---

## 이벤트 연동

### 클릭 시 대화 (이미 구현됨)

캐릭터를 클릭하면 자동으로 "안녕하세요!"라는 대화가 표시됩니다.

### 다른 이벤트와 연동

```python
# CharacterWidget의 mousePressEvent에서:
def mousePressEvent(self, event):
    # ... 기존 코드 ...
    
    # 감정 상태에 따른 대화
    mood = self.mood_system.decide_emotion()
    emotion = mood["emotion"]
    
    if emotion == "happy":
        self.dialogue_system.show_dialogue("기분이 좋아요!", duration=3000)
    elif emotion == "angry":
        self.dialogue_system.show_dialogue("뭔가 화났는데요?", duration=3000)
    elif emotion == "bored":
        self.dialogue_system.show_dialogue("뭐 할 일 없나요?", duration=3000)
```

### 아이템 획득 시 대화

```python
# character_widget.py의 acquire_item 메서드에서:
if len(self.held_items) == 1:
    # 첫 아이템 획득
    self.dialogue_system.show_dialogue(
        text="오! 뭔가 주셨네요!",
        duration=3000,
        use_narration=True
    )
```

---

## 성능 최적화 팁

1. **타이머 정리**: 대화 창은 자동으로 타이머를 정리합니다
2. **메모리**: 오래된 대화 창은 자동으로 메모리에서 제거됩니다
3. **큐 관리**: 필요 없는 큐는 `clear_queue()`로 미리 정리하세요

---

## 커스터마이징

### 말풍선 스타일 변경

`dialogue_widget.py`의 `DialogueBubble` 클래스에서:

```python
# 색상 커스터마이징
self.bubble_color = QColor(50, 50, 60)      # 말풍선 배경색
self.text_color = QColor(255, 255, 255)     # 텍스트 색
self.border_color = QColor(150, 150, 200)   # 테두리 색

# 크기 커스터마이징
self.padding_x = 16         # 좌우 여백
self.padding_y = 12         # 상하 여백
self.tail_height = 12       # 꼬리 높이

# 글꼴 커스터마이징
self.font = QFont("맑은 고딕", 11)
```

### 나레이션 박스 스타일 변경

`dialogue_widget.py`의 `DialogueNarrationBox` 클래스에서:

```python
# 색상 커스터마이징
self.bg_color = QColor(30, 30, 40)          # 배경색
self.text_color = QColor(230, 230, 240)     # 텍스트 색
self.name_color = QColor(100, 180, 255)     # 이름 색
self.border_color = QColor(100, 150, 200)   # 테두리 색
```

---

## 테스트 메서드

프로그램 실행 중 Python 콘솔에서:

```python
# 말풍선 테스트
character.test_dialogue_bubble("이것은 말풍선입니다!")

# 나레이션 박스 테스트
character.test_dialogue_narration("이것은 나레이션 박스입니다!")

# 순차 대화 테스트
character.test_dialogue_sequence()
```

---

## 다음 구현 예상

- [ ] 감정 시스템과의 더 깊은 연동
- [ ] 음성 재생 (TTS API 연동)
- [ ] 프롬프트 시스템과 LLM API 연동
- [ ] 대화 히스토리 기록
- [ ] 더 많은 대사 템플릿
