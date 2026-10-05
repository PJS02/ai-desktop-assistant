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

## 기능

- 화면 위 캐릭터 표시
- 클릭 반응
- 감정 애니메이션
- **캐릭터 대화 시스템** (NEW!)
  - 말풍선 UI 대화 표시
  - 나레이션 박스 UI
  - 순차 대화 큐 시스템
  - 다양한 대사 템플릿
- AI 인사 응답 (준비 중)

## 로컬 음성 읽기 (TTS)

AI 답변을 Supertonic 3 모델로 기기에서 합성해 읽습니다. 별도 TTS API 요금은 없습니다.
처음 음성을 사용할 때 모델 파일 약 400MB를 다운로드하며, 이후 합성은 인터넷 없이 동작합니다.
캐릭터를 우클릭해 **AI 답변 음성으로 읽기**를 켜거나 끄고, **목소리 선택**에서
Supertonic 3의 기본 목소리 F1–F5, M1–M5를 고를 수 있습니다. 처음에는 F1로
음성 읽기가 켜져 있으며 선택은 저장됩니다. 모델은 OpenRAIL-M 라이선스를 따릅니다.

## 외부 감정·동작 인식 연결

`medeapipe_capstone` 또는 외부 모델의 인식 결과는 로컬 TCP JSON 브리지를 통해
캐릭터에 전달할 수 있습니다. 이벤트 형식과 실행 방법은
[`perception/README.md`](perception/README.md)를 참고하세요.

자동 테스트는 개발 의존성을 설치한 뒤 실행합니다.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
```
