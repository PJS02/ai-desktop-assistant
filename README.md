# AI Desktop Assistant (Prototype)

Python + PyQt 기반 데스크탑 캐릭터 예제 프로젝트

## 실행 방법

1. Python 설치 (3.10+ 권장)

2. 라이브러리 설치

pip install -r requirements.txt

3. API 키 설정

템플릿을 복사해 실제 설정 파일을 만드세요.

context/config/gemini_config.template.json -> context/config/gemini_config.json
context/config/igdb_config.template.json -> context/config/igdb_config.json

gemini_config.json 예시:

{
	"api_key": "YOUR_KEY",
	"model": "gemma-3-4b-it"
}

igdb_config.json 예시:

{
	"client_id": "YOUR_ID",
	"client_secret": "YOUR_SECRET"
}

4. 실행

python main.py

카메라·음성 인식 작업은 이 앱이 창 없는 백그라운드 프로세스로 시작하고 종료합니다.
캐릭터 우클릭 → **설정 → 사용자 인식**에서
카메라 미리보기, 장치 시작·중지, 인식 옵션을 관리할 수 있습니다.
미리보기는 해당 탭에서 켰을 때만 전송되며, 탭 이동·창 닫기·최소화 시 전송을 멈춥니다.
카메라 영상은 로그에 저장하지 않습니다. 인식 작업이 예기치 않게 종료되면 최대 3회 재연결하고,
계속 실패하면 설정의 장치 새로고침으로 다시 연결할 수 있습니다.

개발용 기존 진단 창은 `python medeapipe_capstone/main.py --diagnostic-gui`로 별도 실행할 수 있습니다.

## 기능

- 화면 위 캐릭터 표시
- 클릭 반응
- 감정 애니메이션
- **캐릭터 대화 시스템** (NEW!)
  - 텍스트·최종 음성인식을 같은 AI 대화 경로로 처리
  - 기존형·둥근 말풍선형·간결한 자막형 선택
  - 나레이션 박스 UI
  - 순차 대화 큐 시스템
  - 다양한 대사 템플릿
- 캐릭터 위 가위바위보 카운트다운·선택·승패 표시
- 캐릭터 우클릭 → **참참참 하기**: 정면 확인 후 마지막 ‘참!’에 캐릭터가 좌우로 회전하며 5판 진행
  - 화면 기준으로 같은 방향이면 잡힘, 반대 방향이면 회피 성공
  - 얼굴 미인식·정면 유지는 점수 없이 같은 판 재시도, 매 판 정면 복귀 후 준비
  - 우클릭 메뉴에서 다시 하기·종료 가능, 종료하면 기존 인식 모드와 캐릭터 방향 복원
- 별도 점프 모션과 경과시간 기반 중력·창 착지

## 로컬 음성 읽기 (TTS)

AI 답변을 Supertonic 3 모델로 기기에서 합성해 읽습니다. 별도 TTS API 요금은 없습니다.
처음 음성을 사용할 때 모델 파일 약 400MB를 다운로드하며, 이후 합성은 인터넷 없이 동작합니다.
캐릭터를 우클릭해 **설정 → 음성**에서 **AI 답변 음성으로 읽기**를 켜거나 끄고, **목소리**에서
Supertonic 3의 기본 목소리 F1–F5, M1–M5를 고를 수 있습니다. 처음에는 F1로
음성 읽기가 켜져 있으며 선택은 저장됩니다. 모델은 OpenRAIL-M 라이선스를 따릅니다.

GPT-SoVITS와 OpenVoice V2도 **설정 → 음성**에서 설치하고 선택할 수 있습니다.
추가 음성은 Windows Python 3.10과 지원되는 NVIDIA GPU/드라이버가 필요하며,
앱을 닫고 `setup_tts_runtime.cmd`로 전용 실행 환경을 한 번 준비한 뒤 모델만 다운로드합니다.
학습한 목소리는 [TTS 릴리스](https://github.com/PJS02/ai-desktop-assistant/releases/tag/tts-74107e113436-v1)에서 제공하며, 설정창이 필요한 파일을 자동으로 다운로드하고 검증합니다.
설치·배포 절차와 파일 구성은 [추가 TTS 설치 안내](docs/tts-installation.md)를 참고하세요.

## 외부 감정·동작 인식 연결

`medeapipe_capstone` 또는 외부 모델의 인식 결과는 로컬 TCP JSON 브리지를 통해
캐릭터에 전달할 수 있습니다. 이벤트 형식과 실행 방법은
[`perception/README.md`](perception/README.md)를 참고하세요.

카메라가 실행 중일 때 손을 좌우로 흔들면 캐릭터가 손을 흔들고 “안녕! 👋” 말풍선을 표시합니다.
마이크나 STT 없이 손동작만으로 인사할 수 있습니다. **상시 인식**을 켜면
인식 콘솔에서도 손 흔들기 상태를 확인할 수 있습니다.
같은 인식 결과로 인사를 반복하지 않고 다음 인사까지 6초의 간격을 둡니다.
로그의 **사용자 인식** 탭에 손 흔들기 감지, 인사 재생·보류·반복 방지 여부가 표시됩니다.
잡고 있거나 점프·낙하·착지 중이면 동작이 끝난 뒤 인사합니다.
10초 안에 인사할 수 없는 경우에는 보류한 인사를 취소합니다.
손 흔들기는 기본 네이티브 리깅 렌더러의 인사 애니메이션을 사용하며,
인사 이미지가 없는 PNG 렌더러에서는 말풍선만 표시합니다.

자동 테스트는 개발 의존성을 설치한 뒤 실행합니다.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
