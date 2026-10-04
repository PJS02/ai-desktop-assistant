# Cloudy v30 실행 에셋

현재 본 앱과 미리보기에서 사용하는 방향별 Cloudy 원화·동작·감정 에셋입니다. PNG와 런타임 JS는 기존 v30의 내용을 유지합니다.

- `textures/parts.js`: 고유 PNG 3,077개를 참조하는 부품 목록
- `motion.js`, `renderer.js`와 관련 JS: 원본 자세·변형·재질 계산
- `preview.html`, `studio.js`, `travel.js`, `sequence.js`: 미리보기 화면과 제어
- `exports/previews`: 미리보기의 감정 썸네일
- `emotion-manifest.json`, `sprite-manifest.json`, 텍스처 메타데이터: 에셋 정보

프로젝트 루트에서 미리보기 서버를 실행합니다.

```powershell
.\.venv\Scripts\python.exe assets_cloudy_rig_v4\directional_v5\serve_preview.py
```

주소는 `http://127.0.0.1:8771/directional_v5/preview.html`입니다. URL의 `rollback=v22` 같은 쿼리는 동결 버전을 선택하지 않으며 현재 파일을 사용합니다.

실행 에셋에는 원화 제작 중간 파일이나 이전 버전의 복사본을 포함하지 않습니다. 과거 문서와 작업 자료는 이 컴퓨터의 `C:\Users\User\Desktop\capstoneproject_cloudy_archive_20261004`에 상대 경로와 함께 보관했습니다.
