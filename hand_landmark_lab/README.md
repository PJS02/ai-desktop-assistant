# 손 랜드마크 실험

본프로젝트에 연결하기 전, 독립적으로 카메라 손 인식과 점·선 표시를 확인하는 폴더입니다.
기존 `main.py`, 캐릭터 코드, 얼굴/감정 인식 코드는 불러오거나 수정하지 않습니다.

## 실행

`run.cmd`를 더블클릭하면 **카메라 2번으로 연결하고 바탕화면 손 표시를 시작**합니다. 기존 프로젝트의 `.venv`를 사용합니다.
추가 설치나 모델 다운로드 없이 현재 설치된 MediaPipe 0.10.9의 Hands 모델을 사용합니다.

```powershell
# 프로젝트 루트에서 실행
.\hand_landmark_lab\run.cmd
# 검은 배경의 표시창으로 확인하고 싶을 때
.\hand_landmark_lab\run.cmd --preview
# 카메라 없이 합성 손 표시 (인식 검증이 아닌 렌더링 데모)
.\hand_landmark_lab\run.cmd --demo
```

1. 사용자가 손 인식을 확인한 **카메라 2 · DirectShow**를 기본값으로 사용합니다. 변경하려면 중지 후 번호/연결 방식을 바꾸고 카메라 시작을 누르세요. 연결 실패 시 다른 카메라 앱과 Windows 권한을 확인하세요. 가상/실제 카메라가 함께 등록된 경우 같은 번호도 연결 방식에 따라 다른 장치를 가리킬 수 있습니다. 연결이 오래 멈추면 테스트를 종료한 뒤 다른 설정으로 다시 실행하세요.
2. 손을 보여주면 관절 21개와 연결선이 표시됩니다. 기본은 **한 손**입니다. 두 손을 표시하려면 중지 후 **최대 표시 손 수**를 2로 바꾸고 다시 시작하세요. 명령줄에서는 `--max-hands 2`를 사용할 수 있습니다.
3. **거울처럼 좌우 반전**, **좌표 흔들림 보정**, **손 크기 (%)**, **관절 번호 표시**를 조절할 수 있습니다.
4. **바탕화면 위에서 손 이동**이 기본으로 켜져 있습니다. 손마다 작은 투명 창이 제어창이 있는 모니터의 화면 전체에서 손 위치를 따라 이동합니다. 손 창은 마우스 클릭을 통과시키며 키보드 포커스를 가져가지 않습니다. 이 옵션을 끄면 검은 배경의 표시창으로 돌아옵니다.
5. **중지**는 카메라를 해제합니다. **테스트 종료**는 표시창과 카메라를 함께 닫습니다.

카메라 영상은 메모리에서 손 인식에만 사용합니다. UI에는 영상이 전달되지 않으며 저장·전송 기능은 없습니다.
손 위치는 모니터의 전체 가로·세로 영역에 대응시키고, 손 모양은 카메라의 가로세로 비율을 유지하여 작게 표시합니다. 가장자리에서는 손 창을 화면 안으로 제한합니다.
손마다 최대 두 개의 작은 투명 창만 사용합니다. 화면 전체 크기의 투명 창을 매 프레임 그리지 않습니다. 흔들림 보정이 켜져 있으면 0.12초 이내의 짧은 인식 끊김에는 마지막 손을 잠깐 유지하고, 그 이상이면 숨깁니다. 카메라 결과가 갱신되지 않을 때는 0.3초 이후 숨깁니다.
보정에는 좌우 판별이 잠깐 바뀌어도 유지되는 손 ID, 한 프레임짜리 큰 좌표 오류 거르기, 움직임 크기에 따른 보정 강도 조절, 표시 프레임 사이의 이동 보간이 포함됩니다. 빠른 움직임에서도 약간의 지연이 추가될 수 있습니다.
같은 위치·관절 배열의 중복 검출을 제거하고, 추가 두 번째 손은 연속된 두 프레임에서 확인한 뒤 표시합니다. 손가락 위치 오류는 손 크기에 대한 상대 기준으로 검사하고, 다음 프레임의 손 모양까지 일관될 때만 받아들입니다. 안정된 손 모양을 0.18초 이상 확인하지 못하면 이전 자세를 계속 표시하는 대신 숨깁니다.
Windows에서는 매번 투명 픽셀까지 포함한 새 그림으로 작은 손 창 전체를 교체합니다. 창 크기는 일정 블록으로 늘린 후 유지하여 손가락 움직임마다 창을 계속 리사이즈하지 않습니다.

## 구성과 이후 연결 지점

- `tracker.py`: 카메라/인식 스레드, 불변 `Hand`/`Snapshot`, 최신 결과 한 개만 보관. 기본 640×480 요청, 최대 30 FPS, 안정성 우선의 전체 손 모델(`model_complexity=1`).
- `renderer.py`: `DesktopHandWindow`로 작은 손 창을 이동. `desktop_geometry`는 화면상 창 위치와 창 내부 좌표를 반환. 선택 가능한 기존 표시창은 `fit_rect`/`screen_point`로 좌표 변환.
- `app.py`: 시작/중지, 설정, 성능 표시, 데모 및 카메라 검사.
- `native_surface.py`: Windows 전용 작은 투명 창, BGRA 전체 프레임과 위치를 한 번에 교체. 소유한 손 창만 만들고 종료 시 창/비트맵/DC를 해제.

나중에 캐릭터와 연결할 때 실제 표시 위치는 `DesktopHandWindow.points[8]`(창 내부 검지 끝 좌표)에 `window.pos()`를 더해 얻을 수 있습니다. 이 좌표에는 표시 보간까지 적용되어 있습니다. `desktop_geometry`는 보간 전 목표 좌표를 반환합니다.
현재는 캐릭터 접촉/제스처 반응을 구현하지 않았습니다. 본프로젝트 통합 시 기존 얼굴 인식의 카메라와 동시에 열지 않도록 프레임 공유 방식을 정해야 합니다.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s hand_landmark_lab -p "test_*.py"
.\.venv\Scripts\python.exe hand_landmark_lab\verify_ui.py
.\.venv\Scripts\python.exe hand_landmark_lab\app.py --snapshot hand_landmark_lab\verification\demo.png
.\.venv\Scripts\python.exe hand_landmark_lab\app.py --probe-camera --seconds 6
# 실제 표시 손 창 수/프레임 교체 검사 후 UI를 계속 열어둠
.\.venv\Scripts\python.exe hand_landmark_lab\app.py --verify-live --seconds 12
```

데모 이미지/자동검사는 실제 손 인식의 정확성이나 사용자가 느끼는 지연을 증명하지 않습니다.
실제 확인 항목: 두 손, 빠른 움직임, 손 재등장, 좌우 반전, 투명 모드, 중지 후 재시작, 종료 후 카메라 해제.

새 환경이 필요하면 Python 3.10 가상환경에서 이 폴더의 `requirements.txt`를 설치하세요. 기존 프로젝트 환경을 재설치하지 않아도 됩니다.
참고: [MediaPipe Hands 구현과 API](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/hands.py), [최신 Hand Landmarker 문서](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python).
이 실험은 기존 설치와 맞추기 위해 `mp.solutions.hands`를 사용합니다.
Windows 전체 프레임 교체 방식의 API 참고: [UpdateLayeredWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-updatelayeredwindow).

구현 시 확인한 실행 결과는 `verification/RESULTS.md`에 기록했습니다.
`verification/movement-demo.gif`는 합성 좌표로 만든 화면 이동 예시이며 실제 카메라 녹화가 아닙니다.
`--verify-live`는 카메라 영상 대신, 표시한 랜드마크 그림 한 장(`live-hand.png`)과 손 창 개수/속도/프레임 교체 검사 결과(`live-check.json`)만 저장합니다.
