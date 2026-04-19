# AI 데스크톱 어시스턴트: 기술 논문

## 목차
1. 개요
2. 시스템 아키텍처
3. 핵심 모듈 설계
4. 감정 시스템
5. 애니메이션 엔진
6. 물리 시스템
7. 사용자 상호작용
8. 구현 세부사항
9. 향후 개선사항

---

## 1. 개요

### 1.1 프로젝트 목적

본 프로젝트는 **AI 기반 데스크톱 캐릭터 어시스턴트**의 프로토타입 구현으로, 사용자의 데스크톱 환경에 상주하면서 실시간으로 상호작용하는 애니메이션 캐릭터를 제공한다.

### 1.2 주요 특성

| 특성 | 설명 |
|------|------|
| **플랫폼** | Windows 데스크톱 |
| **기술 스택** | Python 3.10+, PyQt6, OpenAI API |
| **UI 패러다임** | 항상 최상단에 표시되는 프레임리스 윈도우 |
| **상호작용** | 마우스 클릭, 드래그, 자동 애니메이션 |
| **지능형 기능** | OpenAI API 연동 음성 응답 |

### 1.3 핵심 기능

```
┌─────────────────────────────────────────┐
│     AI 데스크톱 어시스턴트 기능        │
├─────────────────────────────────────────┤
│ • 데스크톱 위 항상 표시되는 캐릭터      │
│ • 3가지 감정 상태 (행복, 지루함, 화남)  │
│ • 프레임 기반 애니메이션 (Idle/Walk)    │
│ • 중력 및 물리 시뮬레이션               │
│ • 창 감지 및 Surface 시스템             │
│ • 사용자 상호작용 반응 (클릭/드래그)    │
│ • AI 기반 자동 응답                     │
└─────────────────────────────────────────┘
```

---

## 2. 시스템 아키텍처

### 2.1 전체 시스템 구조

```
┌──────────────────────────────────────────────────────┐
│                   Application Layer                  │
│              (main.py - QApplication)                │
└──────────────────────┬───────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
   ┌────▼─────────────┐      ┌───────▼────────┐
   │ CharacterWidget  │      │   AI Service   │
   │   (PyQt6 UI)     │      │  (OpenAI API)  │
   └────┬─────────────┘      └────────────────┘
        │
   ┌────┴─────────────────────────────────────────┐
   │                                              │
┌──▼────────────┐  ┌─────────────┐  ┌───────────▼──┐
│ SpriteAnimator│  │MoodSystem   │  │ AnimationCtrl │
│(프레임 기반)   │  │(감정 관리)  │  │(위치/움직임) │
└────────────────┘  └─────────────┘  └──────────────┘
   │
   ├─ PhysicsEngine (중력)
   ├─ SurfaceSystem (표면 관리)
   ├─ WindowDetection (창 감지)
   └─ InputHandler (마우스 이벤트)
```

### 2.2 데이터 흐름

```
사용자 입력
    │
    ├─► 마우스 클릭 ──► MoodSystem 업데이트 ──► 감정 변화
    │                                           │
    ├─► 드래그 ──────► 위치 이동 ──► Animation 중단
    │
    │
애니메이션 루프 (16ms)
    ├─► 중력 적용 ──► 위치 업데이트
    ├─► 충돌 감지 ──► Surface 착지
    └─► 프레임 렌더링 ──► 화면 표시
```

### 2.3 모듈별 역할

| 모듈 | 파일 | 책임 | 상태 |
|------|------|------|------|
| **메인 진입점** | `main.py` | 애플리케이션 초기화 및 실행 | ✅ |
| **위젯** | `character_widget.py` | UI 렌더링 및 이벤트 처리 | ✅ |
| **감정 관리** | `mood_system.py` | 감정 상태 및 행동 결정 | ✅ |
| **스프라이트** | `sprite_animator.py` | 프레임 기반 애니메이션 | ✅ |
| **애니메이션** | `animations.py` | 위치/움직임 애니메이션 | ✅ |
| **AI 서비스** | `ai_service.py` | OpenAI API 연동 | ⚠️ 부분 |

---

## 3. 핵심 모듈 설계

### 3.1 CharacterWidget (UI 계층)

**역할**: PyQt6 기반 메인 UI 컨트롤러

#### 3.1.1 윈도우 속성

```python
설정 항목                      설명
─────────────────────────────────────────
FramelessWindowHint           테두리 없는 윈도우
WindowStaysOnTopHint          항상 최상단 표시
WA_TranslucentBackground      배경 투명화
위치                          고정 크기 300x400px
```

#### 3.1.2 핵심 시스템

**1. 감정 업데이트 루프**
```python
Timer: 1초 간격
  ├─ MoodSystem.decay()        (감정 자연 감소)
  ├─ MoodSystem.decide_emotion() (행동 결정)
  └─ update_render()           (애니메이션 재생)
```

**2. 이동 시스템**
```python
Timer: 3초 간격
  ├─ random_move()             (목표 위치 선정)
  └─ _smooth_moving()          (부드러운 이동)
     └─ LinearInterpolation    (직선 이동)
```

**3. 입력 처리**
```
mousePressEvent
  └─ is_dragging = True
     ├─ animation_controller.pause()
     └─ drag_time 추적

mouseMoveEvent
  └─ 캐릭터 위치 이동

mouseReleaseEvent
  └─ is_dragging = False
     └─ animation_controller.resume()
```

#### 3.1.3 핵심 메서드

| 메서드 | 목적 | 호출 주기 |
|--------|------|----------|
| `update_mood()` | 감정 시스템 업데이트 | 1초 |
| `update_render()` | 화면 갱신 및 애니메이션 선택 | 감정 변화시 |
| `random_move()` | 자동 이동 대상 선정 | 3초 |
| `_smooth_moving()` | 선형 이동 구현 | 30ms |
| `_apply_gravity()` | 중력 시뮬레이션 | 16ms (60fps) |
| `_scan_windows()` | 활성 창 감지 | 500ms |

### 3.2 MoodSystem (감정 관리)

**역할**: 캐릭터의 감정 상태 및 행동 결정

#### 3.2.1 감정 모델

```python
감정 상태 벡터:
  mood = {
    "happy": float [0.0 ~ 1.0],    # 행복도
    "bored": float [0.0 ~ 1.0],    # 지루함
    "angry": float [0.0 ~ 1.0]     # 화남
  }
```

#### 3.2.2 감정 변화 규칙

**이벤트 기반 변화**
```python
on_click():
  happy += 0.1      (상호작용으로 행복)
  angry += 0.05     (약간의 흥분)

on_idle():
  bored += 0.1      (아무것도 안 할 때 지루해짐)
```

**자연 감소**
```python
decay():
  모든 감정 *= 0.95  (매주기 5%씩 감소)
```

#### 3.2.3 행동 결정 알고리즘

```python
decide_emotion() 결과:

if angry > 0.7:
  return "angry"     ← 우선순위 1
elif bored > 0.6:
  return "bored"     ← 우선순위 2
elif happy > 0.6:
  return "happy"     ← 우선순위 3
else:
  return "idle"      ← 기본값
```

**의미**
- 화남이 가장 높은 우선순위
- 감정은 시간에 따라 자연 감소
- 사용자 상호작용으로 강제 변화 가능

### 3.3 SpriteAnimator (프레임 애니메이션)

**역할**: 폴더 기반 프레임 애니메이션 관리

#### 3.3.1 파일 구조

```
assets/
├─ idle/
│  ├─ frame_000.png
│  ├─ frame_001.png
│  ├─ frame_002.png
│  └─ ...
├─ walk/
│  ├─ frame_000.png
│  └─ ...
└─ angry/
   ├─ frame_000.png
   └─ ...
```

#### 3.3.2 애니메이션 재생

```python
play(animation_name, fps=10, loop=True)
  │
  ├─ load_animation(animation_name)
  │  └─ assets/{name}/*.png 모두 로드
  │
  ├─ Timer 시작 (interval = 1000/fps)
  │
  └─ next_frame() 주기 호출
     ├─ 현재 프레임 출력
     ├─ current_frame++
     └─ 끝이면: loop=True면 반복, False면 종료신호
```

#### 3.3.3 신호 (Signal/Slot)

```python
frame_changed(QPixmap)      # 새 프레임 출력
animation_finished()        # 비반복 애니메이션 완료
```

---

## 4. 감정 시스템 상세

### 4.1 감정 상태 머신

```
        ┌─────────────┐
        │   Neutral   │ (idle = 0.3)
        └──────┬──────┘
         ╱     │      ╲
        ╱      │       ╲
    ┌──▼─┐  ┌─▼──┐  ┌──▼──┐
    │Happy│ │Idle│  │ Bored│
    └──┬──┘ └────┘  └──┬───┘
       │              │
       └──────────────┘
            │
        ┌───▼───┐
        │ Angry │
        └───────┘
```

### 4.2 상태 전이 조건

| 현재 상태 | 전이 조건 | 다음 상태 | 트리거 |
|----------|---------|---------|--------|
| idle | happy > 0.6 | happy | 반복 클릭 |
| idle | bored > 0.6 | bored | 장시간 미사용 |
| any | angry > 0.7 | angry | 강한 자극 |
| any | time | idle | 감정 감소 |

### 4.3 감정과 애니메이션의 매핑

```python
감정 상태        애니메이션    반복 여부    특성
─────────────────────────────────────────────
idle            idle/      O      기본 상태
happy           idle/      O      밝은 분위기
bored           idle/      O      느린 움직임
angry           angry/     O      공격적 표현
walk            walk/      O      이동 중
jump            (위치)     X      물리 기반
```

---

## 5. 애니메이션 엔진

### 5.1 애니메이션 시스템 개요

**두 가지 애니메이션 방식 혼합**

```
1. 스프라이트 애니메이션          2. 위치 애니메이션
   ├─ idle/frame_*.png             ├─ 이동 (선형)
   ├─ walk/frame_*.png             ├─ 호흡 (Sin 곡선)
   └─ angry/frame_*.png            ├─ 점프 (물리)
                                    └─ 흔들기
```

### 5.2 AnimationController (위치/동작)

**역할**: 캐릭터 위치 및 고급 동작 관리

```python
state:
  position_changed.connect() ──► CharacterWidget 위치 갱신

동작 종류:
  start_idle()         # 기본 호흡 애니메이션
  walk_to(target_pos)  # 대상으로 이동
  jump()               # 점프
  idle_shake()         # 흔들기
  dock_breathing()     # 독 호흡 효과
```

### 5.3 물리 기반 애니메이션

**점프 구현**
```python
on_jump():
  velocity_y = -jump_force  (위로 속도)

_apply_gravity():
  velocity_y += gravity
  new_y = current_y + velocity_y
  
  if check_collision(new_y):
    on_ground = True
    velocity_y = 0
```

**호흡 애니메이션**
```python
dock_breathing():
  offset_y = amplitude * sin(t * frequency)
  visual_y = base_y + offset_y  (위아래 반복)
```

---

## 6. 물리 시스템

### 6.1 중력 엔진

**목적**: 자연스러운 떨어지는 효과 및 표면 착지

#### 6.1.1 중력 알고리즘

```python
프레임마다 (16ms 간격):

1. 속도 업데이트
   velocity_y += gravity_acceleration
   velocity_y = min(velocity_y, max_fall_speed)  # 터미널 속도

2. 위치 업데이트
   new_y = current_y + velocity_y

3. 충돌 감지 및 착지
   if new_y >= surface.y_level:
     y = surface.y_level
     velocity_y = 0
     on_ground = True
```

#### 6.1.2 매개변수

```
중력 가속도: 0.5 px/frame²
최대 낙하 속도: 20 px/frame
점프 초기 속도: -15 px/frame (위로)
```

### 6.2 Surface 시스템 (표면 관리)

**목적**: 캐릭터가 올라갈 수 있는 표면 정의

#### 6.2.1 Surface 데이터 구조

```python
class Surface:
  name: str              # "ground", "popup_window_1" 등
  y_level: int          # 캐릭터 바닥이 닿을 Y좌표
  x_min: int            # 표면 좌측 X좌표
  x_max: int            # 표면 우측 X좌표
  height: int | None    # 창 테두리 표시용
  source_key: str       # 창 추적 ID
```

#### 6.1.2 기본 설정

```
화면 해상도: 1920x1080
기본 표면 (ground): y=1080, x=[0, 1920]
캐릭터 높이: 400px
→ 시각적 착지점: y=680 (1080-400)
```

### 6.3 창 감지 시스템 (Window Detection)

**목적**: 활성 창을 감지하고 그 위에 표면 생성

#### 6.3.1 자동 감지 루프

```python
_scan_windows() - 500ms 마다 실행
  │
  ├─ pygetwindow.getWindowsWithTitle() 호출
  │
  ├─ 필터링:
  │  ├─ 최소화된 창 제외
  │  ├─ 너무 작은 창 제외 (< 300x200px)
  │  ├─ 자신의 창 제외
  │  └─ 유효한 앱만 포함
  │
  ├─ 변경 감지:
  │  ├─ 새 창 추가 → add_surface()
  │  ├─ 창 사라짐 → remove_surface()
  │  └─ 창 이동 → update_surface()
  │
  └─ 캐릭터 위치 유효성 검사
```

#### 6.3.2 감지 로직

```python
def _is_interactive_window(window):
  if not window.title:
    return False
  
  if window.isMinimized:
    return False
  
  if window.width < 300 or window.height < 200:
    return False
  
  excluded_patterns = ["IME", "Settings", "Cortana"]
  if any(p in window.title for p in excluded_patterns):
    return False
  
  return True
```

---

## 7. 사용자 상호작용

### 7.1 입력 이벤트 처리

#### 7.1.1 마우스 클릭

```
mousePressEvent()
  │
  ├─ self.drag_pos = current_pos
  ├─ self.is_dragging = True
  ├─ self.drag_time = 0
  │
  └─ mood_system.on_click()
     ├─ happy += 0.1
     └─ angry += 0.05
```

#### 7.1.2 마우스 드래그

```
mouseMoveEvent()
  │
  ├─ if is_dragging:
  │  ├─ new_pos = current_pos - drag_offset
  │  ├─ self.move(new_pos)
  │  └─ animation_controller.pause()
  │
  └─ is_dragging를 유지
```

#### 7.1.3 마우스 해제

```
mouseReleaseEvent()
  │
  ├─ is_dragging = False
  ├─ 중력 재개 (자동으로 표면 착지)
  │
  └─ animation_controller.resume()
     └─ 이전 애니메이션 계속
```

### 7.2 상호작용 흐름도

```
┌─────────────────────────────────────┐
│   사용자 클릭                       │
└────────────────┬────────────────────┘
                 │
                 ├─► MoodSystem 업데이트
                 │   ├─ happy += 0.1
                 │   └─ 감정 변화
                 │
                 ├─► 반응 애니메이션
                 │   ├─ 표정 변화
                 │   └─ 움직임 변화
                 │
                 └─► 화면 갱신
```

---

## 8. 구현 세부사항

### 8.1 메인 실행 흐름

```python
main.py 구조:
┌─────────────────────────────────┐
│ load_dotenv()                   │ ← .env 파일 로드
├─────────────────────────────────┤
│ QApplication 생성               │
├─────────────────────────────────┤
│ CharacterWidget 생성             │
│  ├─ MoodSystem 초기화           │
│  ├─ SpriteAnimator 초기화       │
│  ├─ AnimationController 초기화  │
│  ├─ Surface 시스템 초기화       │
│  └─ 타이머 시작                 │
├─────────────────────────────────┤
│ character.show()                 │
├─────────────────────────────────┤
│ app.exec()                       │ ← 이벤트 루프 시작
└─────────────────────────────────┘
```

### 8.2 타이머 구조

| 타이머 | 간격 | 목적 | 우선순위 |
|--------|------|------|----------|
| `timer` | 1000ms | 감정 업데이트 | ★★☆ |
| `move_timer` | 3000ms | 자동 이동 | ★☆☆ |
| `drag_timer` | 100ms | 드래그 추적 | ★★★ |
| `_gravity_timer` | 16ms | 중력 (60fps) | ★★★ |
| `_window_scan_timer` | 500ms | 창 감지 | ★★☆ |
| `sprite_animator.timer` | ~100ms | 프레임 애니메이션 | ★★☆ |

### 8.3 렌더링 파이프라인

```
프레임 (16ms 간격):

1. 중력 적용
   ├─ velocity_y += gravity
   └─ 위치 업데이트

2. 표면 충돌 감지
   ├─ 새로운 surface 착지?
   └─ on_surface_changed() 이벤트

3. 드래그 상태 확인
   ├─ 드래그 중? → 이동 정지
   └─ 드래그 아님? → 정상 애니메이션

4. 스프라이트 프레임 업데이트
   └─ 감정별 적절한 애니메이션 프레임

5. 화면 렌더링
   └─ self.setPixmap()
```

### 8.4 좌표 시스템

```
화면 좌표계 (Windows):
┌─────────────────────────────────► X
│ (0,0)
│
│  ┌─────────┐
│  │ 캐릭터   │ height=400px
│  │ y=680   │
│  │ (300x400)
│  └─────────┘
│
│
▼
Y
  y=1080 (taskbar level - 작업표시줄 위)
```

---

## 9. 향후 개선사항

### 9.1 단기 개선 (Sprint 1)

```
1. AI 음성 응답 완성
   - OpenAI API 완전 연동
   - TTS (Text-to-Speech) 추가
   - 자연스러운 대화 흐름

2. 애니메이션 확대
   - 4-5가지 감정별 독립 애니메이션
   - 전환 애니메이션 (transition)
   - 특수 동작 (춤, 인사 등)

3. UI 개선
   - 설정 메뉴
   - 이름 커스터마이징
   - 사운드 효과
```

### 9.2 중기 개선 (Sprint 2-3)

```
4. 상태 영속성
   - 선호도 저장 (SQLite)
   - 대화 히스토리
   - 사용자 학습

5. 다중 캐릭터
   - 여러 캐릭터 지원
   - 캐릭터 스킨 시스템
   - 상호작용 지원

6. 고급 물리
   - 투사체 물리
   - 탄성 충돌
   - 미끄러짐/마찰
```

### 9.3 장기 개선 (2026+)

```
7. 크로스 플랫폼
   - macOS 지원
   - Linux 지원
   - 모바일 버전

8. 고급 AI 기능
   - 음성 인식
   - 감정 인식 (이미지 기반)
   - 컨텍스트 인식 응답

9. 커뮤니티
   - 마켓플레이스
   - 사용자 제작 애니메이션
   - 플러그인 시스템
```

---

## 10. 기술 스택 분석

### 10.1 선택 이유

| 기술 | 선택 이유 | 장점 | 단점 |
|------|---------|------|------|
| **Python** | 빠른 개발 | 학습 용이, 라이브러리 풍부 | 성능 제한 |
| **PyQt6** | 네이티브 UI | 크로스 플랫폼, 강력한 기능 | 복잡한 API |
| **OpenAI API** | 최신 AI | 고품질 텍스트 생성 | 비용, 외부 의존 |
| **pygetwindow** | 창 감지 | 간단한 구현 | 제한된 기능성 |

### 10.2 성능 특성

```
메모리 사용량: ~150-200 MB
CPU 사용률: 2-5% (유휴 시)
프레임레이트: 60 FPS (16ms 간격)
응답 시간: <100ms (마우스 입력)
```

---

## 11. 결론

### 11.1 현재 상태

본 프로젝트는 **프로토타입 단계**에서 다음을 성공적으로 구현했다:

- ✅ PyQt6 기반 프레임리스 윈도우
- ✅ 프레임 기반 스프라이트 애니메이션
- ✅ 3가지 감정 상태 머신
- ✅ 중력 및 물리 시뮬레이션
- ✅ 동적 Surface 시스템
- ✅ 마우스 상호작용
- ⚠️ AI 음성 응답 (부분)

### 11.2 핵심 성과

```
1. 모듈화된 아키텍처
   └─ 각 시스템이 독립적으로 작동

2. 확장성 있는 설계
   └─ 새로운 감정/애니메이션 추가 용이

3. 자연스러운 물리
   └─ 사용자가 신뢰할 수 있는 동작

4. 반응형 UI
   └─ 즉시적인 사용자 피드백
```

### 11.3 학습 결과

본 프로젝트를 통해 획득한 기술 경험:

- PyQt6 이벤트 시스템
- 프레임 기반 애니메이션 구현
- 물리 시뮬레이션 기초
- 상태 머신 설계
- Windows API 통합
- OpenAI API 연동

---

## 부록 A: 감정 상태 전이표

| from \ to | idle | happy | bored | angry |
|-----------|------|-------|-------|-------|
| idle | ↺ | click×2 | idle 5초+ | click+decay |
| happy | decay | ↺ | decay | strong_click |
| bored | click | click | ↺ | strong_click |
| angry | decay | decay | decay | ↺ |

---

## 부록 B: 파일 구조

```
ai-desktop-assistant/
├── main.py                    # 메인 진입점
├── requirements.txt           # 의존성
├── .env                       # API 키 설정
│
├── character/
│   ├── __init__.py
│   ├── character_widget.py    # UI 메인 (300줄)
│   ├── mood_system.py         # 감정 관리 (50줄)
│   ├── sprite_animator.py     # 스프라이트 애니메이션 (120줄)
│   └── animations.py          # 위치 애니메이션 (200줄)
│
├── ai/
│   └── ai_service.py          # OpenAI API (100줄)
│
├── assets/
│   ├── idle/                  # 대기 프레임
│   ├── walk/                  # 이동 프레임
│   └── angry/                 # 화남 프레임
│
└── scripts/
    └── resize_sprites.py      # 이미지 리사이징
```

---

## 부록 C: 실행 환경 설정

### 요구사항
- Python 3.10+
- Windows 10/11
- OpenAI API 키

### 설치 단계

```bash
# 1. 저장소 클론
git clone <repo>
cd ai-desktop-assistant

# 2. 가상 환경 생성
python -m venv venv
.\venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. .env 파일 생성
echo OPENAI_API_KEY=your_key > .env

# 5. 실행
python main.py
```

---

**논문 작성일**: 2026년 4월 19일  
**프로젝트 상태**: 프로토타입 (v0.1.0)  
**최종 수정**: 2026년 4월 19일
