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
- AI 인사 응답
