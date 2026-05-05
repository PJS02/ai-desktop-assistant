# AI 데스크톱 어시스턴트 설계서

## 1. 프로젝트 개요

### 1.1 목적
데스크톱 화면 위에 상주하는 AI 기반 캐릭터를 제공하여 사용자와 상호작용하는 인터렉티브한 어시스턴트 애플리케이션

### 1.2 주요 기능
- 데스크톱 위 항상 표시되는 애니메이션 캐릭터
- 감정 시스템 기반 캐릭터 행동 변화
- 사용자 클릭/드래그 상호작용
- AI 음성 인사 응답
- 자동 이동 및 활동 애니메이션

---

## 2. 시스템 아키텍처

### 2.1 전체 구조
```
┌─────────────────┐
│   Main Process  │ (main.py)
└────────┬────────┘
         │
         ├──────────────────────┬────────────────┐
         │                      │                │
    ┌────▼────┐          ┌──────▼──────┐  ┌─────▼────┐
    │Character │          │AI Service   │  │Animation │
    │ Widget   │          │(OpenAI API) │  │Controller│
    └────┬────┘          └─────────────┘  └──────────┘
         │
         ├──────────┬──────────┬──────────┐
         │          │          │          │
    ┌────▼────┐ ┌──▼───┐ ┌───▼──┐ ┌────▼────┐
    │  Mood   │ │Sprite│ │Surface│ │Drag/Move│
    │ System  │ │ Anim │ │System │ │ Handler │
    └─────────┘ └──────┘ └───────┘ └─────────┘
```

### 2.2 모듈 구성

| 모듈 | 파일 | 역할 | 상태 |
|------|------|------|------|
| **메인 진입점** | `main.py` | 애플리케이션 시작 | ✅ 구현됨 |
| **UI 레이어** | `character/character_widget.py` | 캐릭터 렌더링 및 이벤트 처리 | ✅ 구현됨 |
| **감정 시스템** | `character/mood_system.py` | 감정 상태 관리 및 행동 결정 | ✅ 구현됨 |
| **스프라이트 애니메이션** | `character/sprite_animator.py` | 프레임 기반 애니메이션 | ✅ 구현됨 |
| **위치 애니메이션** | `character/animations.py` | 독 호흡, 점프, 이동 효과 | ✅ 구현됨 |
| **AI 서비스** | `ai/ai_service.py` | OpenAI API 연동 | ⚠️ 부분 구현 |

---

## 3. 상세 설계

### 3.1 CharacterWidget 모듈

#### 책임
- PyQt6 QLabel 기반 캐릭터 창 관리
- 마우스 이벤트 처리 (클릭, 드래그)
- 감정 시스템 업데이트
- SpriteAnimator 및 AnimationController 통합

#### 핵심 기능

1. **윈도우 설정**
   ```
   - FramelessWindowHint: 테두리 제거
   - WindowStaysOnTopHint: 항상 최상단
   - WA_TranslucentBackground: 투명 배경
   ```

2. **감정 업데이트 루프**
   - 타이머: 1초 간격 `update_mood()`
   - MoodSystem 조정 및 애니메이션 선택

3. **이동 시스템**
   - 3초 간격 자동 이동 (`random_move()`)
   - smooth_moving으로 선형 이동 구현

4. **Surface 시스템**
   - 캐릭터가 올라갈 수 있는 표면 관리
   - 기본값: 작업표시줄 위 (ground_y = screen_height - char_height - 5px)

#### 이벤트 플로우
```
사용자 입력
    ↓
mousePressEvent → is_dragging = True
    ↓
mouseMoveEvent → 위치 이동 animation 중단
    ↓
mouseReleaseEvent → is_dragging = False → animation 복구
```

---

### 3.2 MoodSystem 모듈

#### 감정 상태 관리
```python
mood = {
    "happy": 초기값 0.5,
    "bored": 초기값 0.2,
    "angry": 초기값 0.1
}
```

#### 상태 변화 규칙

| 이벤트 | happy | bored | angry |
|--------|-------|-------|-------|
| on_click() | +0.1 | - | +0.05 |
| on_idle() | - | +0.1 | - |
| decay() (매초) | ×0.95 | ×0.95 | ×0.95 |

#### 행동 결정 로직
```
IF angry > 0.7     → "angry" (분노 상태 애니메이션)
ELSE IF bored > 0.6 → "bored" (지루함 애니메이션)
ELSE IF happy > 0.6 → "happy" (행복 애니메이션)
ELSE              → "idle" (기본 상태)
```

---

### 3.3 SpriteAnimator 모듈

#### 오퍼레이션
```
load_animation(name) : assets/{name}/frame_*.png 로드
    ↓
play(name, fps, loop) : 애니메이션 재생
    ↓
next_frame() : 타이머 기반 프레임 전환
    ↓
frame_changed 신호 발생 → CharacterWidget 업데이트
```

#### 지원 애니메이션
- `idle/` : 기본 상태 (무한 루프)
- `walk/` : 이동 (일회성)
- `angry/` : 분노 반응 (일회성)

#### 색인 구조
```
assets/
  ├─ idle/
  │  ├─ frame_000.png
  │  ├─ frame_001.png
  │  └─ ...
```

---

## 4. 윈도우 감지 및 상호작용 시스템 (v2.0)

### 4.1 개요
캐릭터가 실시간으로 데스크톱의 활성 윈도우를 감지하고, 감정/성격에 기반해 동적으로 반응합니다.

**주요 기능:**
- ✅ 활성 윈도우 자동 감지
- ✅ 창 위로 올라가기
- ✅ 창 뒤로 숨기기  
- ✅ **스눕 AI**: 창 뒤에 숨었다가 갑자기 튀어나오기
- ✅ 감정 기반 스마트 행동 선택
- ✅ Z-Order & 투명도 제어

### 4.2 WindowMonitor 모듈

#### 책임
- Windows API (ctypes) 사용하여 활성 윈도우 감지
- 윈도우 정보 추출 (제목, 위치, 크기)
- 특수 윈도우 필터링 (작업표시줄, 바탕화면 제외)

#### 주요 메서드
```python
get_active_window() → WindowInfo
    - 현재 활성화된 윈도우 정보 반환

has_window_changed() → bool
    - 윈도우 변경 여부 확인

has_window_moved_or_resized() → bool
    - 윈도우 이동/리사이즈 여부 확인

WindowInfo 클래스
    - hwnd: 윈도우 핸들
    - title: 윈도우 제목
    - x, y: 좌표
    - width, height: 크기
    - is_overlapping(): 충돌 감지
    - get_top_edge(), get_bottom_edge(): 엣지 좌표
```

### 4.3 행동 선택 시스템

#### MoodSystem.decide_window_behavior()

감정과 상황에 기반하여 행동 결정:

```
IF 이미 숨겨있음 AND 30% 확률
    → "snoop_peek_out" (나타나기)

ELSE IF 15% 확률 (스눕 AI)
    → "snoop_hide" (숨기)

ELSE IF happy > 0.7
    → "climb_window" (창 위로 올라가기)

ELSE IF angry > 0.7
    → "hide_behind" (창 뒤로 숨기기)

ELSE IF happy > 0.5 AND 50% 확률
    → "climb_window"

ELSE IF bored > 0.5 AND 40% 확률
    → "hide_behind"

ELSE
    → "ignore" (무시)
```

### 4.4 캐릭터 행동들

#### 1. climb_window: 창 위로 올라가기
```
- Z-Order: WindowStaysOnTopHint 유지 (최상단)
- 투명도: 1.0 (완전 불투명)
- 위치: 윈도우 상단 위쪽으로 이동
- 애니메이션: jump 재생
- Surface: 윈도우 위에 Surface 생성 → 캐릭터 착지
```

#### 2. hide_behind: 창 뒤로 숨기기
```
- Z-Order: WindowStaysOnTopHint 제거 (일반 창으로 변경)
- 투명도: 0.3 (반투명)
- 위치: 윈도우 옆 (왼쪽/오른쪽 50% 확률)
- 감정: 창이 없어질 때까지 유지
```

#### 3. snoop_hide → snoop_peek_out: 스눕 AI
```
단계 1. "snoop_hide" 호출
  - hide_behind와 동일하게 숨기기
  - 타이머 설정: 1~3초 랜덤

단계 2. 타이머 만료 → "snoop_peek_out" 자동 호출
  - Z-Order: 최상단으로 복구
  - 투명도: 1.0 복구
  - 위치: 윈도우 중앙 위쪽에서 갑자기 나타나기
  - 애니메이션: jump 재생
  - 기분: happy +0.15

효과: 평소처럼 있다가 갑자기 튀어나오면서 사용자를 놀래킴
시간: 1~3초 랜덤 (자연스러운 상호작용)
```

### 4.5 Surface 시스템 통합

```
Ground Surface (기본)
    ↓ (캐릭터 떨어짐)
    ├─ Ground 착지 (y = screen_height - char_height - 5)
    │
Window Surface (윈도우 감지시 동적 생성)
    ↓ (캐릭터가 올라가면)
    ├─ Window Top 착지 (y = window.top)
    │   ├─ 중력 가동 →
    │   └─ 일정 시간 후 다시 Ground로 떨어짐
```

### 4.6 Z-Order 제어

```
최상단 (StaysOnTopHint ON)
    ↑
    │ climb_window / restore
    │
캐릭터 (normal)
    │
    │ hide_behind / set_behind
    ↓
일반 창 (StaysOnTopHint OFF)
    ↓
Windows 윈도우들
```

**구현:**
```python
_set_on_top()      # WindowStaysOnTopHint 추가
_set_behind()      # WindowStaysOnTopHint 제거  
_restore_z_order() # 원래 상태로 복구
```

### 4.7 시스템 흐름도

```
┌─────────────────┐
│ 500ms 주기      │
│ _check_active   │
│  _window()      │
└────────┬────────┘
         │
         ├─ 윈도우 None? → _on_window_closed()
         │
         ├─ 새 윈도우? → _on_new_window_detected()
         │                │
         │                ├─ Surface 생성
         │                ├─ on_window_detected() (기분 변경)
         │                └─ decide_window_behavior()
         │                    │
         │                    ├─ climb_window()
         │                    ├─ hide_behind()
         │                    ├─ snoop_hide()
         │                    │   └─ (1~3초 후)
         │                    │   └─ _snoop_peek_out()
         │                    └─ ignore()
         │
         └─ 이동/리사이즈? → _on_window_changed()
                            └─ Surface 업데이트
```

---

## 5. 파일 구조

```
ai-desktop-assistant/
├── main.py                          # 메인 진입점
├── requirements.txt                 # 의존성
├── DESIGN.md                        # 이 파일
├── PROJECT_REPORT.md
├── character/
│   ├── __init__.py
│   ├── character_widget.py          # UI & 윈도우 감지 로직
│   ├── mood_system.py               # 감정 + 행동 결정 시스템 ⭐ 확장됨
│   ├── sprite_animator.py           # 애니메이션 재생
│   ├── animations.py                # 위치 애니메이션
│   └── window_monitor.py            # 윈도우 감지 ⭐ 신규
├── ai/
│   └── ai_service.py                # OpenAI API
├── assets/
│   ├── idle/
│   ├── walk/
│   ├── angry/
│   └── ...
└── scripts/
    └── resize_sprites.py
```

---

## 6. 설치 및 실행

### 의존성 설치
```bash
pip install -r requirements.txt
```

### 실행
```bash
python main.py
```

### 테스트
1. 프로그램 실행
2. 브라우저, VSCode 등 다양한 윈도우 열기
3. 창 활성화 시 캐릭터 반응 확인
   - 창 위로 올라가기
   - 창 뒤로 숨기기
   - 스눕 행동 (1~3초 후 튀어나오기)
  ├─ walk/
  ├─ angry/
```

---

### 3.4 AnimationController 모듈

#### 애니메이션 종류

1. **IdleAnimator** (호흡 및 흔들림)
   ```
   Y축: sin(t × 2) × 5px → 호흡 효과
   X축: cos(t × 1.5) × 3px → 좌우 흔들림
   ```

2. **BounceAnimator** (클릭 시 점프)
   ```
   0.0~0.5: sin(progress × π) × 50px
   0.5~1.0: sin((1-progress) × π) × 10px
   ```

#### 신호 뱀출
```python
position_changed → CharacterWidget.move()
```

---

### 3.5 AI Service 모듈

#### 현재 상태
- ⚠️ **부분 구현**: API 호출 코드 주석 처리됨
- 모의 응답 반환: `"안녕!"`

#### 통합 지점
```
ask_ai(text) 호출
    ↓
OpenAI Chat API (gpt-4o-mini)
    ↓
응답 텍스트 반환 → 캐릭터 표시
```

#### API 환경설정
```
.env 파일에 OPENAI_API_KEY 저장
```

---

## 4. 데이터 흐름

### 4.1 시작 시퀀스
```
main()
  ↓
QApplication 생성
  ↓
CharacterWidget 초기화
  - MoodSystem 생성
  - SpriteAnimator 생성 (idle 로드)
  - AnimationController 생성
  - Surfaces 등록 (ground surface 추가)
  - 타이머 시작 (mood, move, drag 갱신)
  ↓
show() → 화면 표시
  ↓
이벤트 루프 (app.exec())
```

### 4.2 감정 업데이트 사이클
```
타이머 (1초 간격)
  ↓
decay() : mood 자연 감소
  ↓
decide_emotion() : 현재 감정 상태 판단
  ↓
update_animation() : 해당 감정 애니메이션 시작
  ↓
sprite_animator.play() 또는 continue
```

### 4.3 사용자 상호작용 플로우
```
사용자 동작                      결과
───────────────────────────────────────────
마우스 클릭                      on_click() → mood 업데이트
     ↓                        → bounce animation
   드래그                      애니메이션 일시 중단
     ↓                        위치 자유로운 이동
   해제                        current_surface 기반 자동 하강
   
우클릭                         (향후 구현 가능 지점)
```

---

## 5. 기술 스택

| 계층 | 기술 | 버전 |
|------|------|------|
| **UI 프레임워크** | PyQt6 | 6.7.0 |
| **렌더 엔진** | Qt Graphics | - |
| **AI 백엔드** | OpenAI API | v1.0.0+ |
| **런타임** | Python | 3.10+ |
| **주요 라이브러리** | python-dotenv | 1.0.0 |

---

## 6. 파일 구조 및 역할

```
ai-desktop-assistant/
├── main.py                           [진입점]
├── requirements.txt                  [의존성]
├── .env                              [API 키]
├── README.md                         [사용자 문서]
├── DESIGN.md                         [이 파일]
│
├── ai/
│   └── ai_service.py                [OpenAI 연동]
│
├── character/
│   ├── __init__.py
│   ├── character_widget.py           [메인 UI 컴포넌트]
│   ├── mood_system.py                [감정 상태 관리]
│   ├── sprite_animator.py            [스프라이트 애니메이션]
│   ├── animations.py                 [위치 애니메이션]
│   └── (향후) dialogue_manager.py    [대화 관리]
│
├── assets/
│   ├── idle/                         [기본 애니메이션 프레임]
│   │   └── frame_000.png ~ ...
│   ├── walk/                         [이동 애니메이션 프레임]
│   └── angry/                        [분노 반응 애니메이션 프레임]
│
└── scripts/
    └── resize_sprites.py             [스프라이트 리사이징 유틸]
```

---

## 7. 핵심 설계 패턴

### 7.1 신호-슬롯 패턴 (Signal-Slot)
```python
# SpriteAnimator → CharacterWidget
sprite_animator.frame_changed.connect(self.on_sprite_frame_changed)

# AnimationController → CharacterWidget  
animation_controller.position_changed.connect(self.on_animation_position_changed)
```

### 7.2 타이머 기반 갱신
```python
각 업데이트 루프는 QTimer로 구현
- mood 갱신: 1000ms 간격
- 이동: 3000ms 간격
- 드래그: 100ms 간격
- 스프라이트: fps 기반 (예: 10fps = 100ms)
```

### 7.3 상태 머신 (Mood System)
```
mood 값의 상대적 크기로 현재 감정 상태 결정
각 감정마다 대응하는 애니메이션 재생
```

---

## 8. 주요 클래스 다이어그램

```
┌────────────────────────────────────┐
│   CharacterWidget (QLabel)         │
├────────────────────────────────────┤
│ - mood_system: MoodSystem          │
│ - sprite_animator: SpriteAnimator  │
│ - animation_controller: Controller │
│ - surfaces: List[Surface]          │
│ - current_surface: Surface         │
├────────────────────────────────────┤
│ + mousePressEvent()                │
│ + mouseMoveEvent()                 │
│ + mouseReleaseEvent()              │
│ + update_mood()                    │
│ + random_move()                    │
│ + update_render(action)            │
└────────────────────────────────────┘
         ▲
         │ 사용
         │
    ┌────┴─────────┬────────────┬──────────────┐
    │              │            │              │
┌───▼───┐  ┌──────▼─────┐  ┌───▼───┐  ┌─────▼────┐
│Mood   │  │Sprite      │  │Idle   │  │Bounce    │
│System │  │Animator    │  │Anima  │  │Animator  │
└───────┘  └────────────┘  └───────┘  └──────────┘
```

---

## 9. 성능 고려사항

### 9.1 리소스 효율성
- **이미지 캐싱**: 스프라이트 프레임을 메모리에 미리 로드
- **타이머 간격**: 필요한 최소 빈도로 조정
- **윈도우 투명화**: GPU 기반 렌더링으로 최적화

### 9.2 화면 해상도 적응
```python
# 작업표시줄 높이 동적 감지
ground_y = screen_height - char_height - 5px

# 다양한 DPI 대응 (향후)
```

---

## 10. 향후 확장 계획

### 10.1 단기 (Phase 1)
- [ ] AI API 완전 활성화
- [ ] 텍스트 음성 변환 (TTS)
- [ ] 음성 인식 (STT) 통합
- [ ] 우클릭 메뉴 추가
- [ ] 설정 창 (음량, 감도 등)

### 10.2 중기 (Phase 2)
- [ ] 멀티 캐릭터 지원
- [ ] 커스텀 애니메이션 에디터
- [ ] 로컬 언어 모델 지원 (Ollama 등)
- [ ] 감정 학습 (사용자 행동 기반)

### 10.3 장기 (Phase 3)
- [ ] VR/AR 통합
- [ ] 클라우드 동기화
- [ ] 멀티모달 모델 (이미지/텍스트 인식)
- [ ] 플러그인 시스템

---

## 11. 테스트 전략

### 11.1 단위 테스트 (Unit Test)
```
✓ MoodSystem decay() 검증
✓ SpriteAnimator frame 로드 검증
✓ AnimationController 위치 계산 검증
```

### 11.2 통합 테스트 (Integration Test)
```
✓ 마우스 이벤트 → 감정 업데이트
✓ 감정 변화 → 애니메이션 전환
✓ 애니메이션 → 스프라이트 표시
```

### 11.3 E2E 테스트 (End-to-End)
```
✓ 애플리케이션 시작부터 종료까지
✓ 사용자 상호작용 전체 플로우
```

---

## 12. 배포 가이드

### 12.1 개발 환경
```bash
# 가상환경 생성
python -m venv venv
./venv/Scripts/Activate.ps1

# 패키지 설치
pip install -r requirements.txt

# 실행
python main.py
```

### 12.2 배포 (PyInstaller)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico main.py
```

---

## 13. 문제 해결

### 13.1 애니메이션 끊김
- **원인**: 타이머 간격 너무 길음
- **해결**: fps 증가 또는 interval 감소

### 13.2 감정 업데이트 지연
- **원인**: 타이머 간격 > 1초
- **해결**: `timer.start(1000)` 유지

### 13.3 AI 응답 실패
- **원인**: API 키 없음 또는 네트워크 오류
- **해결**: .env 파일 확인, 네트워크 연결 점검

---

## 14. 참고 자료

- **PyQt6 공식 문서**: https://www.riverbankcomputing.com/static/Docs/PyQt6/
- **OpenAI API**: https://platform.openai.com/docs/api-reference
- **애니메이션 원리**: 프레임 기반 (스프라이트) + 위치 기반 (트윈)

---

**최종 업데이트**: 2026년 4월 15일  
**버전**: 1.0  
**상태**: 프로토타입 (개발 중)
