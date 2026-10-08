from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from app_logging import log_event


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVICE_SETTINGS_PATH = PROJECT_ROOT / "config" / "device_settings.json"


def load_device_settings(path: Path = DEVICE_SETTINGS_PATH) -> dict[str, Any]:
    """장치 설정이 없거나 손상된 경우 빈 설정으로 안전하게 시작한다."""
    if not path.is_file():
        log_event('device.settings.default', '장치 설정 파일이 없어 기본값 사용',
                  category='시스템', path=str(path), reason='missing')
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log_event('device.settings.default', '장치 설정 읽기 실패로 기본값 사용',
                  category='오류', level='WARNING', path=str(path), reason='unreadable', error=str(exc))
        return {}
    if not isinstance(data, dict):
        log_event('device.settings.default', '장치 설정 형식 오류로 기본값 사용',
                  category='오류', level='WARNING', path=str(path), reason='not_object')
        return {}
    log_event('device.settings.loaded', '장치 설정 불러오기', category='시스템', path=str(path), settings=data)
    return data


def save_device_settings(
    settings: Mapping[str, Any],
    path: Path = DEVICE_SETTINGS_PATH,
) -> None:
    """사용자별 장치 선택만 로컬 JSON 파일에 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(dict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    log_event('device.settings.saved', '장치 설정 파일 저장 완료', category='시스템', path=str(path), settings=dict(settings))


def select_saved_camera(
    candidates: Sequence[Mapping[str, Any]],
    saved_camera: Mapping[str, Any] | None,
):
    """저장된 백엔드까지 일치시키고, 없으면 같은 인덱스나 첫 장치를 고른다."""
    if not candidates:
        log_event('device.camera.selection', '사용 가능한 카메라 없음', category='사용자 인식', reason='no_devices')
        return None
    saved_camera = saved_camera or {}
    saved_index = saved_camera.get("index")
    saved_backend = saved_camera.get("backend_label")

    for candidate in candidates:
        if (
            candidate.get("index") == saved_index
            and candidate.get("backend_label") == saved_backend
        ):
            log_event('device.camera.selection', '저장된 카메라 선택', category='사용자 인식',
                      reason='exact_match', saved=dict(saved_camera), selected=dict(candidate))
            return candidate
    for candidate in candidates:
        if candidate.get("index") == saved_index:
            log_event('device.camera.selection', '저장된 인덱스의 다른 백엔드 선택', category='사용자 인식',
                      reason='index_fallback', saved=dict(saved_camera), selected=dict(candidate))
            return candidate
    log_event('device.camera.selection', '첫 카메라로 대체 선택', category='사용자 인식',
              reason='first_available', saved=dict(saved_camera), selected=dict(candidates[0]))
    return candidates[0]


def merge_camera_candidates(
    candidates: Sequence[Mapping[str, Any]],
    active_camera: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    """사용 중이라 재탐색에서 빠진 카메라를 전체 목록에 다시 포함한다."""
    merged = list(candidates)
    if not active_camera:
        return merged
    active_key = (active_camera.get("index"), active_camera.get("backend_label"))
    existing_keys = {
        (candidate.get("index"), candidate.get("backend_label"))
        for candidate in merged
    }
    if active_key not in existing_keys:
        merged.insert(0, dict(active_camera))
    return merged


def microphone_name(label: str) -> str:
    """변경될 수 있는 장치 인덱스를 제외하고 마이크 이름만 추출한다."""
    separator = " / "
    return label.split(separator, 1)[1] if separator in label else label


def select_saved_microphone(
    labels: Sequence[str],
    saved_microphone: Mapping[str, Any] | None,
) -> str | None:
    """정확한 라벨을 우선 사용하고 인덱스가 바뀌면 장치 이름으로 복원한다."""
    if not labels:
        log_event('device.microphone.selection', '사용 가능한 마이크 없음', category='사용자 인식', reason='no_devices')
        return None
    saved_microphone = saved_microphone or {}
    saved_label = str(saved_microphone.get("label") or "")
    if saved_label in labels:
        log_event('device.microphone.selection', '저장된 마이크 선택', category='사용자 인식',
                  reason='exact_match', saved=dict(saved_microphone), selected=saved_label)
        return saved_label

    saved_name = str(saved_microphone.get("name") or microphone_name(saved_label))
    if saved_name:
        for label in labels:
            if microphone_name(label) == saved_name:
                log_event('device.microphone.selection', '이름이 일치하는 마이크 선택', category='사용자 인식',
                          reason='name_restored', saved=dict(saved_microphone), selected=label)
                return label
    log_event('device.microphone.selection', '첫 마이크로 대체 선택', category='사용자 인식',
              reason='first_available', saved=dict(saved_microphone), selected=labels[0])
    return labels[0]
