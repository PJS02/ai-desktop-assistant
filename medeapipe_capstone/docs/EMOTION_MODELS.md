# 감정 인식 모델 선택

MediaPipe GUI의 **감정 인식** 토글 아래에서 모델을 선택합니다. 기본값은 `EmotiEffNet B2`이며, `MobileNetV3 (기존)`으로 언제든 전환할 수 있습니다. 선택은 `config/device_settings.json`에 저장됩니다.

| 선택 | 가중치 | 출력 |
| --- | --- | --- |
| EmotiEffNet B2 | `models/enet_b2_8.pt` | 분노, 경멸, 혐오, 공포, 기쁨, 중립, 슬픔, 놀람 |
| MobileNetV3 | `models/epoch72_best_acc_0.8664.pth` | 위 감정 중 중립을 제외한 7종 |

EmotiEffNet 가중치는 [EmotiEffLib 공식 저장소](https://github.com/sb-ai-lab/EmotiEffLib/tree/main/models/affectnet_emotions)의 `enet_b2_8.pt`입니다. 공식 표에 따르면 AffectNet 8종 평가 정확도는 63.03%입니다. 기존 가중치 파일명에 적힌 `0.8664`와는 평가 데이터가 달라 수치를 직접 비교할 수 없습니다. 실제 사용 환경의 정확도는 별도 검증이 필요합니다.

화면의 최종 감정은 B2에서 모델의 최고 점수 클래스를 그대로 사용합니다. MobileNetV3는 최고 점수가 50% 미만이거나 1·2위 차이가 15%p 미만이면 중립으로 표시합니다.

캐릭터 감정에는 B2의 1위 표정 점수가 30% 이상인 추론이 반영 후보가 됩니다. MobileNetV3의 반영 기준은 신뢰도 55%입니다. 두 모델 모두 같은 비중립 표정이 서로 다른 추론에서 3회 이상 확인되고 첫 확인부터 1초 이상 이어져야 반영합니다.

설치: `pip install -r medeapipe_capstone/requirements.txt`
