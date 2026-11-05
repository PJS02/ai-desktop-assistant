"""기억 실험 설정. 수치의 최적 성능은 별도 평가해야 한다."""

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path


SETTINGS_PATH = Path(__file__).with_name("config.json")
MEMORY_TYPES = ("profile", "temporary", "schedule", "event", "unknown")
RETENTION_POLICIES = ("standard", "persistent")


@dataclass(frozen=True)
class MemorySettings:
    candidate_limit: int = 10
    recall_limit: int = 3
    retrieval_mode: str = "top_k"
    similarity_hint: float = 0.75
    duplicate_similarity_hint: float = 0.90
    half_life_beta: float = 0.2
    max_half_life_days: float = 180.0
    recall_score_mode: str = "legacy"

    def __post_init__(self):
        if type(self.candidate_limit) is not int or self.candidate_limit < 1:
            raise ValueError("candidate_limit must be a positive integer")
        if type(self.recall_limit) is not int or not 1 <= self.recall_limit <= 3:
            raise ValueError("recall_limit must be between 1 and 3")
        if self.candidate_limit < self.recall_limit:
            raise ValueError("candidate_limit must not be smaller than recall_limit")
        if self.retrieval_mode not in ("top_k", "threshold"):
            raise ValueError("retrieval_mode must be top_k or threshold")
        if self.recall_score_mode not in ("legacy", "strength_only"):
            raise ValueError("recall_score_mode must be legacy or strength_only")
        for name in ("similarity_hint", "duplicate_similarity_hint", "half_life_beta", "max_half_life_days"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not -1 <= self.similarity_hint <= 1 or not -1 <= self.duplicate_similarity_hint <= 1:
            raise ValueError("similarity hints must be between -1 and 1")
        if self.half_life_beta < 0 or self.max_half_life_days <= 0:
            raise ValueError("half_life_beta must be nonnegative and max_half_life_days positive")


def load_memory_settings(path=None) -> MemorySettings:
    path = Path(path) if path is not None else SETTINGS_PATH
    if not path.exists():
        return MemorySettings()
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Memory settings must be a JSON object")
    try:
        return MemorySettings(**values)
    except TypeError as error:
        raise ValueError("Unknown memory setting") from error
