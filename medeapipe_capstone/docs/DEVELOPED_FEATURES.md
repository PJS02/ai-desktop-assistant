# 개발 기능 정리

작성일: 2026-05-06

## 1. 프로젝트 개요

이 프로젝트는 카메라 또는 영상 파일에서 사람의 얼굴, 상체, 손을 인식하고, 손 제스처와 얼굴 방향, 감정 상태를 실시간 또는 배치 방식으로 분석하는 MediaPipe/OpenCV 기반 비전 애플리케이션이다.

현재 구현은 크게 다음 세 영역으로 구성된다.

- 실시간 GUI 애플리케이션: `holistic_gui_app.py`
- Holistic 트래킹/제스처 분석 코어: `detailed_holistic_tracker.py`
- 감정 인식 모델 로더 및 추론 모듈: `emotion_recognizer.py`

## 2. 핵심 기능 요약

| 구분 | 기능 | 구현 파일 |
| --- | --- | --- |
| 실시간 GUI | 웹캠 선택, 시작, 상태 표시, 모드 전환 UI | `holistic_gui_app.py` |
| 얼굴/상체/손 트래킹 | MediaPipe Holistic 기반 랜드마크 추출 및 시각화 | `detailed_holistic_tracker.py` |
| 가위바위보 인식 | 손가락 펴짐 상태를 기반으로 ROCK/PAPER/SCISSORS/NONE 판정 | `detailed_holistic_tracker.py`, `holistic_gui_app.py` |
| 참참참 모드 | 눈 중심 대비 코 위치로 얼굴 방향 LEFT/CENTER/RIGHT 판정 | `holistic_gui_app.py` |
| 에어드로잉 | 검지 끝 좌표의 이동 경로를 화면에 선으로 표시 | `holistic_gui_app.py` |
| 감정 인식 | 얼굴 영역 crop 후 MobileNetV3 기반 7개 감정 분류 | `emotion_recognizer.py`, `holistic_gui_app.py` |
| 영상 처리 | 입력 영상 또는 웹캠 프레임을 분석해 주석 영상과 JSON 저장 | `detailed_holistic_tracker.py` |
| 데이터 저장 | 프레임별 랜드마크, 요약 정보, 상체 지표, 손 제스처 JSON 출력 | `detailed_holistic_tracker.py` |

## 3. 실시간 GUI 애플리케이션

`holistic_gui_app.py`는 Tkinter 기반의 실시간 제어 화면을 제공한다.

### 구현된 UI 기능

- 웹캠 자동 탐색 및 목록 표시
- 선택한 웹캠 시작
- 현재 입력 소스, 모드, 인식 결과, 상태 표시
- 모드 버튼:
  - 가위바위보
  - 참참참
  - 에어드로잉
- 토글 옵션:
  - 트래킹 표시 켜기/끄기
  - 검은 화면에 마커만 표시
  - 좌우 반전
  - 좌측 상단 정보 오버레이 표시
  - 감정 인식 켜기/끄기
- 영상 화면을 960x540 영역에 맞춰 비율 유지 렌더링
- 앱 종료 시 카메라와 MediaPipe 리소스 정리

### 실시간 처리 흐름

1. 웹캠 프레임 읽기
2. 좌우 반전 옵션 적용
3. MediaPipe Holistic으로 얼굴, 포즈, 손 랜드마크 추론
4. 프레임 레코드 생성
5. 감정 인식 옵션이 켜진 경우 얼굴 crop 후 감정 추론
6. 마커/정보/모드별 오버레이 적용
7. Tkinter 화면에 렌더링

## 4. Holistic 트래킹 코어

`detailed_holistic_tracker.py`는 GUI와 배치 처리에서 함께 사용하는 핵심 분석 모듈이다.

### 랜드마크 처리

- 얼굴 랜드마크 추출
- 전체 포즈 랜드마크 추출
- 상체 주요 랜드마크만 별도 추출
- 왼손/오른손 21개 랜드마크 추출
- 정규화 좌표와 픽셀 좌표를 함께 기록
- visibility, presence 값이 있는 경우 JSON에 포함

### 상체 분석 지표

상체 랜드마크를 기반으로 다음 지표를 계산한다.

- 어깨 너비
- 골반 너비
- 몸통 높이
- 왼팔/오른팔 상완 길이
- 왼팔/오른팔 전완 길이
- 왼쪽/오른쪽 팔꿈치 각도
- 왼쪽/오른쪽 어깨 각도
- 어깨 기울기
- 눈 기울기
- 코와 어깨 중심 사이 거리
- 어깨 중심 좌표
- 골반 중심 좌표

### 영상 오버레이

- 얼굴 메시, 윤곽, 홍채 표시
- 포즈 연결선 표시
- 손 랜드마크 및 연결선 표시
- 상체 주요 연결선 별도 강조
- 프레임 번호, 트래킹 상태, RPS 상태, 랜드마크 개수, 팔꿈치 각도, 어깨 기울기 표시
- 손 위치 근처에 가위바위보 결과 표시

## 5. 가위바위보 인식

가위바위보 인식은 손 랜드마크의 손가락 관절 각도와 위치를 기반으로 구현되어 있다.

### 판정 방식

- 검지, 중지, 약지, 새끼손가락 각각에 대해 펴짐 여부 계산
- MCP, PIP, TIP 세 점의 각도가 160도 이상이고 TIP이 위쪽에 있을 때 펴진 손가락으로 판단
- 모든 손가락이 펴져 있으면 `PAPER`
- 검지와 중지만 펴져 있으면 `SCISSORS`
- 아무 손가락도 펴져 있지 않으면 `ROCK`
- 위 조건에 맞지 않으면 `NONE`
- RPS 기능이 꺼져 있으면 `OFF`

### GUI 표시

- 왼손/오른손 결과를 하단에 표시
- 손 랜드마크 주변에도 결과 텍스트 표시
- 좌우 반전 옵션이 켜진 경우 화면 표시용 좌우 라벨을 교체

## 6. 참참참 모드

참참참 모드는 얼굴 방향 판정을 제공한다.

### 판정 방식

- 왼쪽 눈과 오른쪽 눈의 중심 x좌표 계산
- 코의 x좌표가 눈 중심에서 얼마나 벗어났는지 계산
- 눈 사이 거리의 16%를 임계값으로 사용
- 코가 왼쪽으로 벗어나면 `LEFT`
- 코가 오른쪽으로 벗어나면 `RIGHT`
- 임계값 안에 있으면 `CENTER`
- 필요한 랜드마크가 없으면 `NONE`

## 7. 에어드로잉 모드

에어드로잉 모드는 손의 검지 끝 이동 경로를 화면에 선으로 남기는 기능이다.

### 구현 내용

- 왼손/오른손 검지 끝 좌표를 각각 추적
- 손이 사라지는 구간에는 경로를 끊기 위해 `None` 삽입
- 손별 최대 180개 포인트 유지
- 왼손은 빨간색, 오른손은 파란색 계열 선으로 표시
- 에어드로잉 모드로 전환할 때 기존 경로 초기화

## 8. 감정 인식 기능

`emotion_recognizer.py`는 PyTorch 기반 감정 인식 모델을 정의하고, `epoch72_best_acc_0.8664.pth` 가중치를 로드해 추론한다.

### 모델 구조

- MobileNetV3 Large 기반
- Squeeze-and-Excitation 계열 블록 포함
- CA, MAXCA, CPSCA attention 모듈 구현
- CPU 추론 기준으로 로드

### 감정 클래스

다음 7개 감정을 분류한다.

- Anger
- Contempt
- Disgust
- Fear
- Happy
- Sadness
- Surprise

### GUI 연동

- 감정 인식 토글이 켜진 경우에만 실행
- 얼굴 랜드마크 범위를 기준으로 얼굴 영역 crop
- crop 영역에 padding 적용
- 모델 예측 결과와 confidence를 우측 상단 오버레이에 표시
- 모델 로드 실패 시 GUI 상태에 오류 메시지 표시

## 9. 배치/CLI 영상 처리 기능

`detailed_holistic_tracker.py`는 명령행에서 직접 실행할 수 있으며, 영상 파일 또는 웹캠을 입력으로 처리한다.

### 주요 실행 옵션

- `--input`: 입력 영상 경로. 생략하면 웹캠 사용
- `--camera-index`: 웹캠 인덱스. `-1`이면 자동 탐색
- `--camera-backend`: Windows 캡처 백엔드 선택 (`auto`, `dshow`, `msmf`, `any`)
- `--camera-width`, `--camera-height`: 웹캠 해상도 요청
- `--output-video`: 주석이 그려진 결과 영상 경로
- `--output-json`: 프레임별 랜드마크 JSON 경로
- `--show-preview`: 처리 중 미리보기 창 표시
- `--draw-labels`: 상체 랜드마크 이름 표시
- `--tracking`: 트래킹 오버레이 켜기/끄기
- `--rps`: 가위바위보 인식 켜기/끄기
- `--max-frames`: 테스트용 최대 프레임 수 제한
- `--model-complexity`: MediaPipe 포즈 모델 복잡도
- `--min-detection-confidence`: 최소 탐지 confidence
- `--min-tracking-confidence`: 최소 추적 confidence

### 출력물

- 주석 처리된 MP4 영상
- 프레임별 JSON 데이터
- 처리된 프레임 수 콘솔 출력

## 10. 웹캠 처리 기능

웹캠 입력은 안정성을 위해 여러 백엔드를 순차적으로 탐색한다.

- DirectShow
- Media Foundation
- Any backend

자동 탐색은 0번부터 5번까지의 카메라 인덱스를 확인한다. 프레임을 실제로 읽을 수 있는 장치만 후보로 등록한다.

## 11. 실험 및 산출물

`정리` 폴더에는 개발 과정에서 사용된 실험 스크립트와 결과물이 보관되어 있다.

### 실험 스크립트

- `정리/test02.py`: MediaPipe Tasks PoseLandmarker 기반 포즈 검출 실험
- `정리/testtest.py`: 포즈 검출 실험 스크립트
- `정리/test01_holistic_tracker.py`: 초기 Holistic 트래킹 스크립트
- `정리/test01_rps_tracker.py`: `test01.mp4`를 기본 입력으로 지정하는 RPS 실행 래퍼
- `정리/detailed_holistic_tracker2.py`: 상세 Holistic 트래커의 이전/중간 버전

### 생성된 결과물

- `정리/output_pose.mp4`
- `정리/pose_landmarks.json`
- `정리/output_holistic_detailed.mp4`
- `정리/holistic_detailed_landmarks.json`
- `정리/test01_holistic_tracking.mp4`
- `정리/test01_holistic_tracking.json`
- `정리/test01_holistic_rps.mp4`
- `정리/test01_holistic_rps.json`

## 12. 주요 파일 설명

| 파일 | 설명 |
| --- | --- |
| `holistic_gui_app.py` | 최종 실시간 GUI 앱. 카메라 제어, 모드 전환, 토글, 감정 인식, 화면 렌더링 담당 |
| `detailed_holistic_tracker.py` | MediaPipe Holistic 분석, 랜드마크 기록, 상체 지표 계산, RPS 판정, 영상/JSON 저장 담당 |
| `emotion_recognizer.py` | MobileNetV3 기반 감정 인식 모델 정의 및 추론 담당 |
| `epoch72_best_acc_0.8664.pth` | 감정 인식 모델 가중치 |
| `pose_landmarker.task` | MediaPipe Tasks 포즈 랜드마커 모델 파일 |
| `input.mp4` | 포즈 검출 실험용 입력 영상 |
| `test01.mp4` | Holistic/RPS 실험용 입력 영상 |
| `정리/` | 실험 스크립트와 생성 결과물 보관 폴더 |

## 13. 실행 예시

### GUI 실행

```bash
python holistic_gui_app.py
```

### 입력 영상 처리

```bash
python detailed_holistic_tracker.py --input test01.mp4 --output-video output_holistic_detailed.mp4 --output-json holistic_detailed_landmarks.json
```

### 웹캠 처리

```bash
python detailed_holistic_tracker.py --show-preview
```

### 빠른 테스트

```bash
python detailed_holistic_tracker.py --input test01.mp4 --max-frames 100
```

## 14. 사용 프레임워크 및 라이브러리

현재 코드 기준으로 사용하는 주요 프레임워크와 라이브러리는 다음과 같다.

### 주요 프레임워크/라이브러리

| 이름 | 용도 | 사용 위치 |
| --- | --- | --- |
| Python | 전체 애플리케이션 구현 언어 | 전체 `.py` 파일 |
| Tkinter | 데스크톱 GUI 화면 구성 | `holistic_gui_app.py` |
| OpenCV (`cv2`) | 카메라/영상 입력, 프레임 처리, 영상 저장, 화면 오버레이 그리기 | `holistic_gui_app.py`, `detailed_holistic_tracker.py`, `emotion_recognizer.py`, `정리/*.py` |
| MediaPipe | 얼굴, 포즈, 손 랜드마크 검출 | `detailed_holistic_tracker.py`, `holistic_gui_app.py`, `정리/*.py` |
| PyTorch (`torch`) | 감정 인식 딥러닝 모델 정의, 가중치 로드, 추론 | `emotion_recognizer.py` |
| NumPy | 이미지 배열 처리, 감정 인식 전처리, 빈 프레임 생성 | `holistic_gui_app.py`, `emotion_recognizer.py` |
| Pillow (`PIL`) | OpenCV 프레임을 Tkinter 화면에 표시 가능한 이미지로 변환 | `holistic_gui_app.py` |

### Python 표준 라이브러리

| 이름 | 용도 | 사용 위치 |
| --- | --- | --- |
| `argparse` | CLI 실행 옵션 파싱 | `detailed_holistic_tracker.py` |
| `json` | 프레임별 랜드마크/분석 결과 JSON 저장 | `detailed_holistic_tracker.py`, `정리/*.py` |
| `math` | 거리, 각도, 기울기 계산 | `detailed_holistic_tracker.py` |
| `pathlib.Path` | 파일 경로 처리 및 출력 폴더 생성 | `detailed_holistic_tracker.py`, `emotion_recognizer.py` |
| `types.SimpleNamespace` | GUI 카메라 설정값 보관 | `holistic_gui_app.py` |
| `functools.partial` | MobileNetV3 설정 구성 | `emotion_recognizer.py` |
| `typing` | 타입 힌트 | `emotion_recognizer.py` |

### 외부 모델/가중치 파일

| 파일 | 용도 |
| --- | --- |
| `epoch72_best_acc_0.8664.pth` | PyTorch 감정 인식 모델 가중치 |
| `pose_landmarker.task` | MediaPipe Tasks 기반 포즈 랜드마커 모델 파일 |

## 15. 현재 구현 상태

완성된 기능:

- 실시간 웹캠 GUI
- 카메라 자동 탐색 및 선택
- 얼굴/포즈/손 Holistic 트래킹
- 상체 주요 지표 계산
- 가위바위보 인식
- 참참참 얼굴 방향 판정
- 에어드로잉
- 감정 인식 모델 연동
- 영상 파일 배치 처리
- 결과 영상 및 JSON 저장
- 실험 스크립트와 결과물 보관

추가 개선 가능 항목:

- `requirements.txt` 추가
- GUI 내 결과 저장 버튼 추가
- 에어드로잉 지우기 버튼 추가
- 감정 인식 confidence 임계값 설정
- 한국어/영어 표시 언어 옵션
- PDF 리포트 자동 생성 스크립트 추가
- 테스트 코드 및 샘플 실행 문서 보강
