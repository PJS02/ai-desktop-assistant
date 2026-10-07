# Cloudy v30 실행 에셋

현재 본 앱과 미리보기에서 사용하는 방향별 Cloudy 원화·동작·감정 에셋입니다. v30 동작을 유지하며, 2026-10-04의 v34에서는 `emotion-fx.js`의 눈물 PNG를 더 큰 망울과 짙은 aqua 면·teal 테두리로 다시 그렸습니다. 정면·좌우 두 눈의 6단계 그림, 총 36개 투명 PNG를 기존 고정 배율로 재생합니다. 좌우 작은 눈을 포함해 실제 원화의 아래 눈꺼풀에 맞췄고, 슬픔·속상함의 눈 높이 차이도 따릅니다. 그림의 형태를 시간에 따라 변형하지 않습니다.

`renderer.js`의 입선 정리는 v35 시안입니다. v34의 정면 괴로움·오른쪽 화남 발화 수정에 이어, 오른쪽 기쁨의 대기·대화에 남던 옛 턱선과 오른쪽 괴로움의 미세 잔여선을 기존 정상 얼굴 그림으로 정리합니다. 얼굴 PNG 자체를 덧칠하지 않으며 실제 입 움직임과 몸·팔의 궤적은 유지합니다. 대표 전후 그림과 검증 범위는 [눈물·입선 변경 기록](../../docs/CLOUDY_TEARS.md)에 있습니다. 이전 시안·대량 검증·복구 자료는 로컬 `integration-validation/tears-v31/`부터 `tears-v35/`까지의 폴더에 보관하며 실행에 필요하지 않습니다.

- `textures/parts.js`: 고유 PNG 3,077개를 참조하는 부품 목록
- `motion.js`, `renderer.js`와 관련 JS: 원본 자세·변형·재질 계산
- `preview.html`, `studio.js`, `travel.js`, `sequence.js`: 미리보기 화면과 제어
- `exports/previews-v35`: 현재 입선 수정을 반영한 미리보기의 감정 썸네일
- `exports/previews`: 저장소에 있는 이전 감정 썸네일
- `exports/previews-v34`: 로컬에 보관한 직전 감정 썸네일
- `emotion-manifest.json`, `sprite-manifest.json`, 텍스처 메타데이터: 에셋 정보

프로젝트 루트에서 미리보기 서버를 실행합니다.

```powershell
.\.venv\Scripts\python.exe assets_cloudy_rig_v4\directional_v5\serve_preview.py
```

주소는 `http://127.0.0.1:8771/directional_v5/preview.html`입니다. URL의 `rollback=v22` 같은 쿼리는 동결 버전을 선택하지 않으며 현재 파일을 사용합니다.

## 달리기 모션 (독립 에셋)

2026-10-07에 `run`을 추가했습니다. 0.8초 주기에 짧은 착지와 두 번의 공중 구간, 무릎을 접는 발 회수, 전방 상체 기울기, 굽힌 팔의 교대 스윙을 넣었습니다. 달리기는 왼쪽·오른쪽 측면만 제공합니다. v38에서 상체 전경사를 약 16.5도로 늘리고, 가까운 팔꿈치는 약 85도, 가려지는 먼 팔꿈치는 약 105도로 접습니다. 팔 스윙 중심을 뒤로 6도 옮기고 진폭을 28도에서 34도로 늘려 뒤로 당기는 범위를 키웠습니다. 이 각도는 리그 입력값이며 실제 해부학적 측정값은 아닙니다. 감정과 대화를 함께 선택할 수 있습니다. 본프로젝트의 동작 목록과 제어 코드는 수정하지 않았으며, 본 앱에 달리기를 연결하지 않았습니다.

미리보기의 **달리기** 버튼으로 재생합니다. 달리기를 선택한 뒤 **좌우 왕복 달리기**를 켜면 발의 착지 속도에 맞춰 이동합니다. `preview.html?action=run&direction=left`로 달리기를 바로 열 수 있고, `direction=right`로 방향을 바꿀 수 있습니다. 달리기를 선택하면 정면 버튼은 비활성화되며, 정면에서 달리기를 시작하면 왼쪽을 사용합니다. 다른 동작의 정면은 그대로 사용할 수 있습니다. **달리기 60fps 시트 저장**은 현재 측면 방향·감정·대화를 반영한 투명 PNG를 생성합니다.

- `CloudyMotion.pose('run', seconds, {emotion, speaking, speechTime})`: 달리기 자세
- `runAmount`: 0~1 사이로 달리기 강도 혼합 (생략하면 `run`에서 1)
- `CloudyMotion.runProfile`, `runGait(phase)`: 주기·착지 속도와 발 궤적
- [시트와 프레임 정보](exports/run-v1/run-manifest.json): 좌우 각 48프레임, 60fps, 360×540 프레임, 12열×4행의 4320×2160 RGBA PNG
- [좌우 반복 영상](exports/run-v1/cloudy-run-side-views.gif), [팔꿈치·상체 전후 비교](exports/run-v1/run-posture-before-after.png), [프레임 모아보기](exports/run-v1/run-contact-sheet.png), [검증 기록](exports/run-v1/validation.json)

시트는 눈 깜빡임과 동반 캐릭터를 제외하여 정확히 반복합니다. 대화를 켠 내보내기는 발화 주기도 0.8초에 맞춥니다. `sprite-manifest.json`의 기존 걷기 정보는 유지하며, 달리기는 별도의 `run-manifest.json`으로 제공합니다.

달리기 계산 검증은 `node --test assets_cloudy_rig_v4/directional_v5/tests/run-motion.test.cjs`로 실행합니다. 시각 확인 자료는 실제 독립 WebGL 렌더러에서 생성했으며, 사용자 모션 승인은 별도입니다.

## 측면에서 가려지는 손 (v39)

가려지는 먼 팔의 손을 **엄지가 손가락 위쪽에 오는 방향**으로 바꿨습니다. 달리기·걷기·대기를 포함한 모든 측면 동작과 좌우 방향 전환에 공통 적용합니다. 손·커프·소매가 연결된 원화를 함께 돌려 손목이나 팔꿈치에 절단면을 만들지 않습니다. 먼 팔의 소매 장식도 팔 방향과 함께 바뀌며 관절 위치는 유지합니다. 정면과 가까운 팔의 기존 매핑은 유지합니다.

독립 미리보기와 좌우 걷기·달리기 PNG 시트에 반영했습니다. 본프로젝트에 동작을 추가하거나 연결하는 변경은 포함하지 않았습니다. 기존 탭은 새로고침하면 `측면 손바닥 수정 · v39` 표시로 확인할 수 있습니다.

- [손·커프 확대 비교](exports/far-palm-v39/palm-hand-closeups.png), [전체 자세 비교](exports/far-palm-v39/palm-before-after.png)
- [걷기 전후 반복 영상](exports/far-palm-v39/palm-walk-before-after.gif), [달리기 전후 반복 영상](exports/far-palm-v39/palm-run-before-after.gif)
- [시각·매핑 검증 기록](exports/far-palm-v39/validation.json): 좌우 대기·걷기·달리기 288개 전후 렌더, 손·커프 확대 캡처, 실제 렌더 뷰를 확인한 방향 전환 6회

과거 원화 제작 중간 파일과 작업 자료 일부는 이 컴퓨터의 `C:\Users\User\Desktop\capstoneproject_cloudy_archive_20261004`에 상대 경로와 함께 보관했습니다. 이후 눈물·입선 작업의 백업은 프로젝트의 `integration-validation/`에, 이전 PNG와 감정 썸네일은 각 버전 폴더에 남겨 복구할 수 있습니다.
