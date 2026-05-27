# MediaPipe Capstone

MediaPipe Capstone은 웹캠 또는 영상 파일에서 사람의 얼굴, 상체, 손을 인식하고 여러 제스처와 상태를 판별하는 Python 기반 비전 프로젝트입니다.

현재 버전은 `0.1.0`이며, 기존 프로젝트 상태는 `v0.0.0`, 새 인식 모드가 포함된 현재 상태는 `v0.1.0` 태그로 관리됩니다.

## 프로젝트가 하는 일

이 프로젝트는 MediaPipe Holistic과 OpenCV를 사용해 사람의 주요 랜드마크를 추출합니다. 추출한 얼굴, 포즈, 손 좌표를 바탕으로 가위바위보, 참참참, 에어드로잉, 손 흔들기, 손 제스처, 고개 움직임, 화면 응시 여부를 판단합니다.

GUI 앱을 실행하면 왼쪽에서 카메라와 인식 모드를 선택하고, 오른쪽에서 실시간 인식 화면을 볼 수 있습니다.

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 얼굴/상체/손 트래킹 | MediaPipe Holistic으로 얼굴, 포즈, 양손 랜드마크를 실시간 추적합니다. |
| 가위바위보 | 손가락이 펴진 상태를 이용해 `ROCK`, `PAPER`, `SCISSORS`, `NONE`을 판별합니다. |
| 참참참 | 코와 양쪽 눈 위치를 이용해 얼굴 방향을 `LEFT`, `CENTER`, `RIGHT`로 판별합니다. |
| 에어드로잉 | 검지 끝 좌표를 이어 화면 위에 손가락 이동 경로를 그립니다. |
| 손 흔들기 | 손목 또는 손 기준점이 좌우로 반복 이동하면 인사 의미의 `HELLO`로 인식합니다. |
| 엄지척/하트/OK | 손가락 펴짐 상태와 엄지-검지 거리, 양손 거리 등을 이용해 제스처를 판별합니다. |
| 고개 끄덕임/젓기 | 코와 눈 중심의 위치 변화 히스토리로 끄덕임은 동의, 좌우 흔들림은 부정으로 인식합니다. |
| 화면 응시/자리 비움 | 얼굴과 코 감지 여부, 얼굴 방향을 이용해 화면 응시, 화면 밖 응시, 자리 비움을 판단합니다. |
| 감정 인식 | 얼굴 영역을 crop한 뒤 MobileNetV3 기반 모델로 7가지 감정 중 하나를 예측합니다. |

## 실행 환경

권장 환경:

- Windows
- Python 3.10
- 웹캠
- Git

필요한 Python 패키지는 `requirements.txt`에 정리되어 있습니다. 처음 실행하는 사람은 아래 명령으로 한 번에 설치하면 됩니다.

```powershell
pip install -r requirements.txt
```

직접 설치해야 하는 주요 패키지는 다음과 같습니다.

- `mediapipe`: 얼굴, 포즈, 손 랜드마크 추출
- `opencv-python`: 카메라 입력, 영상 처리, 화면 주석 표시
- `pillow`: Tkinter 화면에 OpenCV 프레임 표시
- `numpy`: 프레임과 좌표 계산
- `torch`: 감정 인식 모델 추론

이 저장소에는 이미 실행에 필요한 모델 파일이 포함되어 있습니다.

- `models/pose_landmarker.task`: MediaPipe pose landmarker 관련 모델 파일
- `models/epoch72_best_acc_0.8664.pth`: 감정 인식 모델 가중치

## 실행 방법

프로젝트 폴더에서 GUI 앱을 실행합니다.

```powershell
python main.py
```

만약 `python` 명령이 잡히지 않고 프로젝트의 가상환경을 사용한다면 다음처럼 실행합니다.

```powershell
.\.venv\Scripts\python.exe main.py
```

JSON 로그를 확인하려면 다른 터미널에서 수신기를 실행합니다.

```powershell
.\.venv\Scripts\python.exe receiver.py
```

## GUI 사용법

1. 앱을 실행합니다.
2. 왼쪽 패널에서 카메라를 선택합니다.
3. `카메라 새로고침`으로 카메라 목록을 갱신할 수 있습니다.
4. `시작` 버튼을 눌러 실시간 영상을 시작합니다.
5. 원하는 모드를 선택합니다.
6. 오른쪽 인식 화면에서 랜드마크, 인식 결과, 상태 메시지를 확인합니다.

## 모드 설명

### 가위바위보

양손의 손가락 펴짐 상태를 분석합니다.

- 모든 손가락이 접혀 있으면 `ROCK`
- 검지와 중지만 펴져 있으면 `SCISSORS`
- 네 손가락이 모두 펴져 있으면 `PAPER`
- 조건이 애매하면 `NONE`

### 참참참

코가 양쪽 눈 중심에서 어느 쪽으로 벗어나는지 계산합니다.

- 왼쪽으로 벗어나면 `LEFT`
- 중앙이면 `CENTER`
- 오른쪽으로 벗어나면 `RIGHT`

### 에어드로잉

검지 끝 좌표를 계속 저장해 화면에 선으로 표시합니다. 손가락을 움직이면 화면에 이동 경로가 그려집니다.

### 손 흔들기

손 기준점의 x좌표를 최근 프레임 동안 저장합니다. 좌우 이동 폭이 충분하고 방향 전환이 반복되면 `HELLO`로 인식합니다.

### 엄지척 / 하트 / OK 제스처

손 랜드마크를 이용해 다음 조건을 확인합니다.

- 엄지척: 엄지가 위로 펴지고 나머지 손가락이 접힌 상태
- OK: 엄지와 검지가 가까워지고 다른 손가락이 비교적 펴진 상태
- 하트: 엄지와 검지가 가까운 상태 또는 양손의 엄지/검지가 서로 가까운 상태

### 고개 끄덕임 / 고개 젓기

코와 양쪽 눈 중심의 상대 위치를 최근 프레임 동안 저장합니다.

- 위아래 변화가 반복되면 `동의`
- 좌우 변화가 반복되면 `부정`

### 화면 응시 / 자리 비움

얼굴 랜드마크와 코 위치를 이용해 상태를 판단합니다.

- 얼굴이 중앙을 향하면 `화면 응시`
- 얼굴이 좌우로 돌아가면 `화면 밖 응시`
- 얼굴과 코가 일정 시간 감지되지 않으면 `자리 비움`

## 토글 옵션

| 옵션 | 설명 |
| --- | --- |
| 트래킹 표시 | 얼굴, 상체, 손 랜드마크 표시 여부를 바꿉니다. |
| 검은화면 마커만 | 원본 영상 대신 검은 배경 위에 마커만 표시합니다. |
| 좌우 반전 | 화면을 거울처럼 좌우 반전합니다. |
| 좌측 상단 정보 | 프레임 번호, 트래킹 상태, 랜드마크 개수 등을 표시합니다. |
| 감정 인식 | 얼굴 crop 기반 감정 인식을 켜거나 끕니다. |

## 파일 구조

| 파일 | 역할 |
| --- | --- |
| `main.py` | GUI 실행 진입점입니다. |
| `receiver.py` | JSON 인식 상태 로그 수신 진입점입니다. |
| `app/` | Tkinter GUI와 앱 버전 정보를 관리합니다. |
| `recognition/` | MediaPipe Holistic, 감정 인식, STT 인식 로직입니다. |
| `bridge/` | JSON 이벤트 송수신 및 로그 확인 도구입니다. |
| `models/` | MediaPipe/감정 인식 모델 파일입니다. |
| `media/` | 테스트용 영상 파일입니다. |
| `docs/` | 변경 기록과 개발 기능 문서입니다. |
| `VERSION` | 현재 버전을 텍스트로 기록합니다. |
| `requirements.txt` | 프로젝트 실행에 필요한 Python 패키지 목록입니다. |

## 배치 영상 처리

GUI가 아니라 영상 파일을 처리하고 싶다면 `recognition/holistic_tracker.py`를 사용할 수 있습니다.

```powershell
python recognition/holistic_tracker.py --input media/test01.mp4 --output-video output_holistic_detailed.mp4 --output-json holistic_detailed_landmarks.json
```

가상환경 Python을 사용할 경우:

```powershell
.\.venv\Scripts\python.exe recognition/holistic_tracker.py --input media/test01.mp4 --output-video output_holistic_detailed.mp4 --output-json holistic_detailed_landmarks.json
```

## 버전 관리

이 프로젝트는 Git 태그로 버전을 관리합니다.

```text
v0.0.0: 기존 프로젝트 기준점
v0.1.0: 버전 메타데이터와 새 인식 모드가 포함된 현재 버전
```

현재 앱 버전은 다음 파일에서 확인할 수 있습니다.

```text
VERSION
app/project_version.py
```

## GitHub 저장소

저장소 주소:

```text
https://github.com/seoridev/medeapipe_capstone
```

## 주의 사항

- 웹캠 권한이 차단되어 있으면 카메라가 열리지 않을 수 있습니다.
- 조명이 어둡거나 손/얼굴이 화면 밖으로 나가면 인식 정확도가 낮아질 수 있습니다.
- 손 제스처와 고개 움직임은 랜드마크 기반 규칙 판정이므로 사용자 거리, 손 각도, 카메라 위치에 따라 임계값 조정이 필요할 수 있습니다.
- 감정 인식 모델 파일이 없으면 감정 인식 기능은 정상 동작하지 않습니다.
## STT controls

The GUI includes a lightweight Google Web Speech STT panel.

1. Select a microphone in the STT section.
2. Choose provider, language, sensitivity, and speech-end silence time.
3. Press `STT start` to keep listening continuously.
4. Speak naturally; STT sends each utterance after a short pause.
5. Press `STT stop` to stop recording.
6. Use `STT save` or `STT clear` for the transcript box.

Google Web Speech needs an internet connection because each detected utterance is sent to Google's recognition service.
