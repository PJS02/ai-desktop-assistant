# Perception bridge

외부 감정·동작 인식 프로세스의 결과를 데스크톱 캐릭터에 전달하는 로컬 브리지입니다.

## 현재 연결 구조

```text
MediaPipe 또는 외부 모델
  -> JSON Lines TCP (127.0.0.1:8765)
  -> QtPerceptionReceiver
  -> PerceptionController
  -> MoodSystem / 캐릭터 대사
```

캐릭터 앱이 TCP 서버를 열고, `medeapipe_capstone` 앱의
`InteractionEventClient`가 인식 결과를 전송합니다. 캐릭터 앱을 실행할 때는 로그 확인용
`medeapipe_capstone/receiver.py`를 동시에 실행하지 마세요. 두 프로그램이 같은 포트를
사용합니다.

## 실행 순서

프로젝트 루트의 가상환경을 활성화한 터미널 두 개를 사용합니다.

1. 첫 번째 터미널에서 캐릭터를 실행합니다.

   ```powershell
   python main.py
   ```

2. 두 번째 터미널에서 MediaPipe GUI를 실행합니다.

   ```powershell
   python medeapipe_capstone/main.py
   ```

3. MediaPipe GUI에서 카메라와 감정 인식을 켭니다.

## 공통 이벤트 형식

새 외부 모델은 다음 형식으로 한 줄에 JSON 객체 하나를 보냅니다.

```json
{
  "type": "perception",
  "version": 1,
  "source": "external-model-name",
  "timestamp": 0,
  "observation": {"session": "camera-session-id", "sequence": 1, "observed_at": 0},
  "camera_status": "running",
  "emotion": {
    "label": "happy",
    "confidence": 0.91,
    "observation_id": 1,
    "observed_at": 0,
    "model": "external-fer-model",
    "scores": {
      "happy": 0.91,
      "sadness": 0.09
    }
  },
  "motions": [
    {
      "kind": "gesture",
      "label": "wave",
      "side": "right",
      "confidence": 0.87
    }
  ],
  "attention": "screen",
  "speech": "안녕"
}
```

기존 `recognition_state` 형식도 하위 호환으로 지원합니다.

`observation.sequence`는 새 카메라 관측마다, `emotion.observation_id`는 실제 얼굴 추론마다
증가시킵니다. 캐시된 얼굴 결과를 다른 상태와 다시 보낼 때는 얼굴의 ID와 `observed_at`을
유지하세요. `EmotionModelAdapter`는 이 메타데이터를 자동으로 붙입니다.
얼굴의 실제 추론 ID가 없는 송신기는 안정성 확인에 사용할 수 없어 감정에 반영하지 않습니다.
`session`은 카메라 재시작 시 바꾸며, `camera_status`의 `off`·`error`는 관측 이력을 지웁니다.
필드를 생략하면 그 채널을 갱신하지 않습니다. 예를 들어 음성 전용 패킷은 손을 내렸다는
뜻이 아닙니다. 명시적인 빈 `motions`가 동작 해제 관측입니다.

## 감정과 리액션 반영

확정된 인식 → 현재 OCC·Russell·행동·성격에 따른 해석 → 실제 OCC 변화 → 짧은 표정 순서로
처리합니다. 같은 하트도 평온할 때는 기쁨, 두려울 때는 두려움 감소와 안도, 경계 중에는
작은 분노 감소, 활력이 낮을 때는 괴로움 완화로 다르게 받아들입니다. 혼합 감정은 가중치로
함께 반영하며, 표정 인식만으로 사용자에게 책임을 돌리거나 수치심을 만들지 않습니다.

얼굴은 신뢰도 0.55 이상인 서로 다른 추론 3회가 1초 이상 유지돼야 하며, 모든 라벨에 공통
8초 간격을 적용합니다. 같은 표정 유지 시 이후 반영은 25% 강도입니다. 정적 손·고개 동작은
2회 이상·0.25초 안정 관측이 필요하고, 0.4초 동안 명시적인 해제를 확인해야 다시 반응합니다.
양손 하트는 하나의 상호작용이며 손·고개 반응은 3초 간격입니다.

1회 OCC 성분 변화는 최대 0.04, 절댓값 합계는 0.06입니다. 최근 60초의 실제 변화량 합계는
얼굴 0.06, 손·고개 0.20, 전체 0.25로 제한합니다. 인식으로 인한 음수 감정 회복은 1회에
해당 성분의 10% 이내입니다. 반복 감쇠·성격·피로도도 반영하며, 수치는 앱 조정값입니다.

드래그·낙하·수동 Russell 조작 중에는 인식 감정을 건너뜁니다. 게임 중 손·고개는 게임이
소유하고, 얼굴 감정은 25% 강도로 표정 덮어쓰기 없이 반영합니다. 수동 표정 고정은 실제
OCC 변화와 별개로 유지됩니다. 자동 수면은 손 흔들기로만 깨우며, 기상 감정을 중복 가산하지
않습니다. 부드러운 실제 쓰다듬기는 수면을 유지하고 거친 접촉에는 놀람으로 반응합니다.
일반 하트·엄지척·OK·고개 반응은 자동 대사를 만들지 않습니다.

자리 비움은 5초, 복귀는 1초 연속 관측으로 확인합니다. 카메라 정지·오류는 자리 비움으로
해석하지 않으며, 방치 감정은 기존 캐릭터 유휴 시간 경로에서만 반영합니다.
일반 인식 상태 전송은 최대 약 5Hz이며 새 음성·카메라 상태와 진행 중 게임 입력은 즉시
전달합니다. 데스크톱 손 좌표 전송 경로는 별도로 유지합니다.

## 최종 음성인식과 대화

최종 발화를 다음과 같이 보내면 캐릭터의 텍스트 입력과 같은 AI 대화 경로로 전달합니다.

```json
{
  "type": "perception",
  "source": "external-stt",
  "timestamp": 0,
  "speech": {
    "text": "안녕, 오늘 기분은 어때?",
    "final": true,
    "session": "recognizer-session-id",
    "sequence": 1,
    "recognized_at": 0
  }
}
```

예시의 시각 0은 전송 시 실제 Unix 초로 바꾸세요. `session`은 인식기를 다시 시작할 때
바꾸고, `sequence`는 새 최종 발화마다 증가시킵니다. 같은 세션·순번의 반복 전송은
한 번만 처리합니다. 같은 문장을 새 순번으로 전송하면 새 대화입니다.
`final: false`인 중간 결과와 오래된 최종 결과는 대화에 전달하지 않습니다.
기존 문자열 `speech`도 지원하지만, 이벤트 중복과 새 발화를 구분하려면 객체 형식을 사용하세요.

앱이 관리하는 인식 프로세스는 `tts_speaking 1/0` 명령을 받아 재생 중 녹음 조각과
겹친 인식 요청을 무효화하고 재생 종료 후 0.8초 잔향을 차단합니다.
외부 STT를 별도로 연결하는 경우에도 자체 재생 오디오를 입력으로 되먹임하지 않도록
해당 인식기의 녹음 경로에서 같은 처리가 필요합니다.

## 손 흔들기 인사

MediaPipe GUI에서 카메라를 켜고 손을 좌우로 흔들면 캐릭터가 인사 애니메이션과
말풍선으로 반응합니다. 마이크와 STT는 필요하지 않습니다.
인사 간격은 최소 6초이며, 같은 손 흔들기를 유지하는 동안 반복하지 않습니다.
캐릭터를 잡고 있거나 공중·수동 제어·게임 중인 인사는 생략합니다.
대화·TTS 등으로 동작이 바쁠 때는 최대 5초간 보류하며, 재생 시 감정을 다시 가산하지 않습니다.

송신기는 `always.wave.started_at`에 손 흔들기 감지 시작 시각을 Unix 초 단위로
포함하며 같은 동작을 유지하는 동안 바꾸지 않습니다. 오래된 감지 결과의 재생을 막습니다.
공통 `perception` 형식에서는 위 예시의 `wave` 동작만으로 인사할 수 있습니다.
별도 관측 시각이 없으면 이벤트의 `timestamp`를 사용합니다.
감지 로그와 인사 재생·보류·반복 방지 로그는 **사용자 인식** 탭에 표시됩니다.

## 외부 감정 모델 연결

외부 모델 객체가 `predict(input_data)` 메서드에서 `label`, `confidence`, `scores`를
반환하도록 만든 뒤 `EmotionModelAdapter`로 감쌉니다.

```python
from perception.adapters import EmotionModelAdapter

adapter = EmotionModelAdapter(
    predictor=external_model,
    source="external-fer-model",
    label_aliases={"happiness": "happy"},
)
event = adapter.predict_event(frame)
```

모델별 전처리와 추론은 Adapter 바깥의 모델 구현에 남기고, 캐릭터에는 공통 이벤트만
전달합니다.
