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

과거 원화 제작 중간 파일과 작업 자료 일부는 이 컴퓨터의 `C:\Users\User\Desktop\capstoneproject_cloudy_archive_20261004`에 상대 경로와 함께 보관했습니다. 이후 눈물·입선 작업의 백업은 프로젝트의 `integration-validation/`에, 이전 PNG와 감정 썸네일은 각 버전 폴더에 남겨 복구할 수 있습니다.
