"""develop의 감정 이름과 작업 브랜치의 에셋 이름 사이의 호환 계층."""

from pathlib import Path


def resolve_animation_asset(assets_path: Path, action: str) -> str:
    """기존 fear 에셋을 보존하고, 없는 감정 표정은 idle로 대체한다."""
    # 논리 감정 매핑은 develop과 동일하게 유지하고 에셋 선택만 분리한다.
    # 기존 fear가 있으면 이를 사용하되 develop만 있는 환경은 scared를 사용한다.
    if action == "scared" and (assets_path / "fear").is_dir():
        return "fear"
    if action in {"scared", "sad"}:
        if not (assets_path / action).is_dir() and not (assets_path / f"{action}.png").is_file():
            return "idle"
    return action
