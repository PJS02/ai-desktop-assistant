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
  "emotion": {
    "label": "happy",
    "confidence": 0.91,
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
