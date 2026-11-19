"""Local retention for screenshots that completed screen privacy processing."""

from io import BytesIO
from pathlib import Path
import re
from threading import Lock
import time
from uuid import uuid4

from app_paths import LOCAL_APP_DATA


DIRECTORY = LOCAL_APP_DATA / 'Cloudy' / 'screen-history'
MAX_IMAGES = 50
_IMAGE_NAME = re.compile(r'screen-\d{20}-[0-9a-f]{32}\.png')
_lock = Lock()
_enabled = False
_generation = 0


def set_enabled(enabled: bool) -> None:
    global _enabled, _generation
    with _lock:
        if enabled != _enabled:
            _enabled = enabled
            _generation += 1


def capture_generation() -> int | None:
    with _lock:
        return _generation if _enabled else None


def _images() -> list[Path]:
    return sorted((path for path in DIRECTORY.glob('screen-*.png') if _IMAGE_NAME.fullmatch(path.name)),
                  reverse=True)


def _prune() -> tuple[Path, ...]:
    images = _images()
    for path in images[MAX_IMAGES:]:
        path.unlink(missing_ok=True)
    return tuple(images[:MAX_IMAGES])


def list_images() -> tuple[Path, ...]:
    with _lock:
        return _prune()


def save(image, generation: int | None) -> str | None:
    if generation is None:
        return None
    png = BytesIO()
    image.save(png, format='PNG')
    with _lock:
        if not _enabled or generation != _generation:
            return None
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = DIRECTORY / f'screen-{time.time_ns():020d}-{uuid4().hex}.png'
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_bytes(png.getbuffer())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        _prune()
        return path.stem


def clear() -> None:
    with _lock:
        for path in _images():
            path.unlink(missing_ok=True)
