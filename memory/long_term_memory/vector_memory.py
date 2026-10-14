"""E5 임베딩과 SQLite로 대화를 오래 보관한다."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4


# 각 항목을 0~1로 정규화한 뒤 합산한다. 필요하면 이 비율만 조정한다.
RECALL_WEIGHTS = {
    "relevance": 0.40,
    "importance": 0.25,
    "emotion": 0.15,
    "recency": 0.10,
    "frequency": 0.10,
}

# 기억 유지 정책. 중요도·감정 강도가 높으면 실제 반감기가 길어진다.
FORGETTING_HALF_LIFE_DAYS = 30
REINFORCEMENT_BOOST = 0.20
FORGETTING_THRESHOLD = 0.15

# 추가 컬럼은 기존 INSERT문도 계속 사용할 수 있도록 기본값을 둔다.
METADATA_COLUMNS = {
    "importance": "INTEGER CHECK (importance IS NULL OR (typeof(importance) = 'integer' AND importance BETWEEN 0 AND 10))",
    "speaker": "TEXT NOT NULL DEFAULT 'conversation' CHECK (speaker IN ('user', 'assistant', 'conversation', 'unknown'))",
    "conversation_id": "TEXT",
    "emotional_intensity": "INTEGER CHECK (emotional_intensity IS NULL OR (typeof(emotional_intensity) = 'integer' AND emotional_intensity BETWEEN 0 AND 10))",
    "recall_count": "INTEGER NOT NULL DEFAULT 0 CHECK (recall_count >= 0)",
    "last_recalled_at": "TEXT",
    "strength": "REAL NOT NULL DEFAULT 1.0 CHECK (strength BETWEEN 0 AND 1)",
}

# 기존 DB에서만 제거한다. 원문·벡터·나머지 메타데이터는 그대로 보존한다.
REMOVED_COLUMNS = ("memory_type", "source", "embedding_model")


@dataclass(frozen=True)
class MemorySearchResult:
    """유사도 검색 결과 한 건."""

    text: str
    score: float
    created_at: str
    memory_id: int = 0
    importance: int | None = None
    speaker: str = "conversation"
    conversation_id: str | None = None
    emotional_intensity: int | None = None
    recall_count: int = 0
    last_recalled_at: str | None = None
    strength: float = 1.0
    recall_score: float = 0.0


class LongTermMemory:
    """텍스트와 E5 벡터를 SQLite 파일에 저장하고 의미로 검색한다."""

    def __init__(
        self,
        database_path: str | Path = "data/long_term_memory.sqlite3",
        model_name: str = "intfloat/multilingual-e5-small",
        embedder: Any | None = None,
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name
        self._embedder = embedder
        # 대화 응답은 별도 스레드에서 처리하므로 SQLite의 스레드 검사를 해제하고 잠근다.
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._lock = RLock()
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                dimension INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        self._connection.commit()
        self._upgrade_schema()

    def _upgrade_schema(self) -> None:
        """기존 기억을 보존하면서 필요한 컬럼을 추가하고 불필요한 컬럼을 제거한다."""
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(memories)")}
        missing = [name for name in METADATA_COLUMNS if name not in columns]
        removed = [name for name in REMOVED_COLUMNS if name in columns]
        if not missing and not removed:
            return

        # SQLite backup API는 실행 중인 DB도 일관된 상태로 복사한다.
        # 구조 변경 전에 백업을 만들며, 완료 후 재실행하면 다시 만들지 않는다.
        if self._connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]:
            backup_path = self.database_path.with_name(
                f"{self.database_path.name}.schema-backup-{uuid4().hex}"
            )
            backup = sqlite3.connect(backup_path)
            try:
                self._connection.backup(backup)
            finally:
                backup.close()
            print(f"[장기기억 DB 백업] {backup_path}")

        # 명시적 트랜잭션으로 컬럼 변경 전체를 성공하거나 되돌린다.
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            # 다른 앱 인스턴스가 먼저 확장했을 수도 있으므로 잠금을 얻은 뒤 다시 확인한다.
            columns = {row[1] for row in self._connection.execute("PRAGMA table_info(memories)")}
            for name in missing:
                if name in columns:
                    continue
                self._connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {METADATA_COLUMNS[name]}")
            for name in removed:
                if name in columns:
                    self._connection.execute(f"ALTER TABLE memories DROP COLUMN {name}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def remember(
        self, text: str, *, importance: int | None = None, speaker: str = "unknown",
        conversation_id: str | None = None,
        emotional_intensity: int | None = None,
    ) -> None:
        """원문과 임베딩에 중요도·발화자 등 메타데이터를 함께 저장한다."""
        self._save_messages([(speaker, text)], importance, conversation_id, emotional_intensity)

    def remember_dialogue(
        self, user_text: str, assistant_text: str, *, importance: int,
        emotional_intensity: int | None = None,
    ) -> str:
        """사용자·AI 발화를 분리하고 같은 대화 ID로 한 번에 저장한다."""
        conversation_id = uuid4().hex
        self._save_messages(
            [("user", user_text), ("assistant", assistant_text)],
            importance, conversation_id, emotional_intensity,
        )
        return conversation_id

    def _save_messages(self, messages, importance, conversation_id, emotional_intensity) -> None:
        if importance is not None and (type(importance) is not int or not 0 <= importance <= 10):
            raise ValueError("importance must be an integer from 0 to 10 or None")
        if emotional_intensity is not None and (type(emotional_intensity) is not int or not 0 <= emotional_intensity <= 10):
            raise ValueError("emotional_intensity must be an integer from 0 to 10 or None")
        if any(speaker not in ("user", "assistant", "conversation", "unknown") for speaker, _ in messages):
            raise ValueError("unknown speaker")

        created_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            rows = []
            for speaker, text in messages:
                text = text.strip()
                if not text:
                    continue
                vector = self._embed(f"passage: {text}")
                rows.append((text, array("f", vector).tobytes(), len(vector), created_at,
                             importance, speaker, conversation_id, emotional_intensity))
            # 두 발화 중 임베딩·저장이 실패하면 일부만 남기지 않는다.
            with self._connection:
                self._connection.executemany(
                    """INSERT INTO memories
                    (text, embedding, dimension, created_at, importance, speaker,
                     conversation_id, emotional_intensity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )

    def count(self) -> int:
        """저장된 기억 수를 반환한다. 비어 있으면 모델을 불러오지 않는다."""
        with self._lock:
            return self._connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def search(self, query: str, limit: int = 3) -> list[MemorySearchResult]:
        """망각된 기억을 제외하고 회상 순위로 선택한 기억을 강화한다."""
        if limit < 1 or not query.strip():
            return []
        with self._lock:
            rows = self._connection.execute(
                """SELECT text, embedding, dimension, created_at, id, importance, speaker,
                          conversation_id, emotional_intensity,
                          recall_count, last_recalled_at, strength FROM memories""",
            ).fetchall()
            now = datetime.now(timezone.utc)
            candidates = []
            for text, blob, dimension, created_at, *metadata in rows:
                memory = MemorySearchResult(text, 0.0, created_at, *metadata)
                strength = self._current_strength(memory, now)
                if strength >= FORGETTING_THRESHOLD:
                    candidates.append((replace(memory, strength=strength), blob, dimension))
            if not candidates:
                return []
            query_vector = self._embed(f"query: {query.strip()}")
            # ponytail: 전체 벡터를 비교하므로 O(n). 기억이 많아지면 벡터 인덱스를 추가한다.
            results = []
            for memory, blob, dimension in candidates:
                vector = list(array("f", blob))
                if len(vector) == dimension == len(query_vector):
                    result = replace(memory, score=self._cosine(query_vector, vector))
                    results.append((self._recall_score(result, now), result))
            selected = sorted(results, key=lambda item: item[0], reverse=True)[:limit]
            with self._connection:
                return [replace(self._reinforce_memory(result, now), recall_score=score)
                        for score, result in selected]

    def get_strength(self, memory_id: int) -> float:
        """시간 경과를 반영한 현재 기억 강도를 조회한다. 조회만으로 강화하지 않는다."""
        with self._lock:
            return self._current_strength(self._read_memory(memory_id), datetime.now(timezone.utc))

    def reinforce(self, memory_id: int) -> float:
        """기억을 직접 회상해 강화한다. 자동 망각된 기억도 복구할 수 있다."""
        with self._lock, self._connection:
            now = datetime.now(timezone.utc)
            memory = self._read_memory(memory_id)
            memory = replace(memory, strength=self._current_strength(memory, now))
            return self._reinforce_memory(memory, now).strength

    def forget(self, memory_id: int) -> None:
        """원문을 삭제하지 않고 기억 강도를 0으로 만들어 검색에서 제외한다."""
        with self._lock, self._connection:
            self._read_memory(memory_id)
            self._connection.execute("UPDATE memories SET strength = 0 WHERE id = ?", (memory_id,))

    def _read_memory(self, memory_id: int) -> MemorySearchResult:
        row = self._connection.execute(
            """SELECT text, 0.0, created_at, id, importance, speaker, conversation_id,
                      emotional_intensity, recall_count, last_recalled_at, strength
               FROM memories WHERE id = ?""", (memory_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Memory {memory_id} does not exist")
        return MemorySearchResult(*row)

    def _reinforce_memory(self, memory: MemorySearchResult, now: datetime) -> MemorySearchResult:
        # DB strength는 이 시각에서의 강도다. 다음 조회는 last_recalled_at부터 감쇠한다.
        reinforced = replace(memory, strength=min(1.0, memory.strength + REINFORCEMENT_BOOST),
                             recall_count=memory.recall_count + 1, last_recalled_at=now.isoformat())
        self._connection.execute(
            "UPDATE memories SET strength = ?, recall_count = ?, last_recalled_at = ? WHERE id = ?",
            (reinforced.strength, reinforced.recall_count, reinforced.last_recalled_at, memory.memory_id),
        )
        return reinforced

    @staticmethod
    def _current_strength(memory: MemorySearchResult, now: datetime) -> float:
        """저장 또는 마지막 회상 이후의 시간만 반영해 감쇠한다."""
        try:
            anchor = datetime.fromisoformat(memory.last_recalled_at or memory.created_at)
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            days = max(0.0, (now - anchor).total_seconds() / 86400)
        except ValueError:
            # 기존 기록의 시간이 불명확하면 임의로 망각시키지 않는다.
            return memory.strength
        half_life = FORGETTING_HALF_LIFE_DAYS * (
            1 + (memory.importance or 0) / 10 + (memory.emotional_intensity or 0) / 10
        )
        return memory.strength * 0.5 ** (days / half_life)

    @staticmethod
    def _recall_score(memory: MemorySearchResult, now: datetime) -> float:
        """저장 중요도를 바꾸지 않고 현재 질문에 대한 회상 점수를 계산한다."""
        try:
            created_at = datetime.fromisoformat(memory.created_at)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            days = max(0.0, (now - created_at).total_seconds() / 86400)
            # 저장 후 30일마다 최근성의 기여도가 절반으로 줄어든다.
            recency = 0.5 ** (days / 30)
        except ValueError:
            recency = 0.0

        factors = {
            "relevance": max(0.0, min(1.0, memory.score)),
            "importance": (memory.importance or 0) / 10,
            "emotion": (memory.emotional_intensity or 0) / 10,
            "recency": recency,
            # 반복 회상 보너스는 점점 작아지며 1을 넘지 않는다.
            "frequency": memory.recall_count / (memory.recall_count + 5),
        }
        return sum(RECALL_WEIGHTS[name] * factor for name, factor in factors.items()) * memory.strength

    def close(self) -> None:
        """SQLite 연결을 닫는다."""
        with self._lock:
            self._connection.close()

    def _embed(self, text: str) -> list[float]:
        """모델을 처음 필요할 때만 불러와 텍스트 하나를 벡터화한다."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(self.model_name)
        vector = self._embedder.encode(text, normalize_embeddings=True)
        return [float(value) for value in vector]

    @staticmethod
    def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
        """SQLite에 저장된 벡터를 Python으로 비교한다."""
        left, right = list(left), list(right)
        denominator = sqrt(sum(value * value for value in left) * sum(value * value for value in right))
        return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
