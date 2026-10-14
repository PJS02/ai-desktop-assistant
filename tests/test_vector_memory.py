import tempfile
import sqlite3
import unittest
from array import array
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from memory.long_term_memory import LongTermMemory, MemorySearchResult


class FakeEmbedder:
    def encode(self, text, normalize_embeddings=True):
        return [1.0, 0.0] if "cat" in text else [0.0, 1.0]


class LongTermMemoryTests(unittest.TestCase):
    def test_stores_text_and_searches_by_vector_similarity(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LongTermMemory(Path(directory) / "memory.sqlite3", embedder=FakeEmbedder())
            memory.remember("I like cats")
            memory.remember("I like dogs")
            self.assertEqual(memory.count(), 2)
            results = memory.search("cat food")
            memory.close()

        self.assertEqual(results[0].text, "I like cats")
        self.assertGreater(results[0].score, results[1].score)

    def test_dialogue_metadata_survives_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            conversation_id = memory.remember_dialogue(
                "I like cats", "I will remember that", importance=8,
                emotional_intensity=6,
            )
            memory.close()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            results = memory.search("cat food")
            memory.close()

        self.assertEqual({item.speaker for item in results}, {"user", "assistant"})
        self.assertEqual({item.conversation_id for item in results}, {conversation_id})
        self.assertEqual({item.importance for item in results}, {8})
        self.assertEqual({item.emotional_intensity for item in results}, {6})

    def test_legacy_migration_preserves_original_data_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            original = (1, "user and AI mixed text", array("f", [1.0, 0.0]).tobytes(), 2, "old timestamp")
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, text TEXT NOT NULL, embedding BLOB NOT NULL, dimension INTEGER NOT NULL, created_at TEXT NOT NULL)")
                connection.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?)", original)
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            result = memory.search("cats")[0]
            memory.close()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT id, text, embedding, dimension, created_at FROM memories").fetchone(), original)
            self.assertEqual(result.speaker, "conversation")
            self.assertIsNone(result.importance)
            backups = list(path.parent.glob("*.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)

    def test_failed_embedding_does_not_save_half_a_dialogue(self):
        class FailingEmbedder(FakeEmbedder):
            def encode(self, text, normalize_embeddings=True):
                if "fail" in text:
                    raise RuntimeError("embedding failed")
                return super().encode(text, normalize_embeddings)

        with tempfile.TemporaryDirectory() as directory:
            memory = LongTermMemory(Path(directory) / "memory.sqlite3", embedder=FailingEmbedder())
            with self.assertRaises(RuntimeError):
                memory.remember_dialogue("cats", "fail", importance=7)
            self.assertEqual(memory.count(), 0)
            memory.close()

    def test_removes_obsolete_columns_without_changing_remaining_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats", importance=8, speaker="user", emotional_intensity=6)
            memory.close()
            with closing(sqlite3.connect(path)) as connection, connection:
                original = connection.execute("SELECT * FROM memories").fetchone()
                connection.execute("ALTER TABLE memories ADD COLUMN memory_type TEXT DEFAULT 'preference'")
                connection.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'manual'")
                connection.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT DEFAULT 'old-model'")
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
                columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
                self.assertTrue(columns.isdisjoint({"memory_type", "source", "embedding_model"}))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            backups = list(path.parent.glob("*.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT memory_type, source, embedding_model FROM memories").fetchone(),
                                 ("preference", "manual", "old-model"))
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            self.assertEqual(memory.search("cats")[0].importance, 8)
            memory.close()

    def test_rejects_bad_metadata_before_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = LongTermMemory(Path(directory) / "memory.sqlite3", embedder=FakeEmbedder())
            for metadata in ({"importance": 11}, {"importance": True}, {"speaker": "wrong"},
                             {"emotional_intensity": 11},
                             {"emotional_intensity": True}):
                with self.assertRaises(ValueError):
                    memory.remember("cats", **metadata)
            self.assertEqual(memory.count(), 0)
            memory.close()

    def test_search_skips_vectors_with_different_dimensions(self):
        class ThreeDimensionalEmbedder(FakeEmbedder):
            def encode(self, text, normalize_embeddings=True):
                return [1.0, 0.0, 0.0]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, model_name="model-A", embedder=FakeEmbedder())
            memory.remember("cats")
            memory.close()
            memory = LongTermMemory(path, model_name="model-B", embedder=ThreeDimensionalEmbedder())
            self.assertEqual(memory.search("cats"), [])
            memory.close()

    def test_each_recall_factor_increases_priority(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        base = MemorySearchResult(
            "cats", 0.2, (now - timedelta(days=60)).isoformat(),
            importance=1, emotional_intensity=1,
        )
        baseline = LongTermMemory._recall_score(base, now)
        for changes in ({"score": 0.8}, {"importance": 9}, {"emotional_intensity": 9},
                        {"created_at": now.isoformat()}, {"recall_count": 10}):
            with self.subTest(changes=changes):
                self.assertGreater(LongTermMemory._recall_score(replace(base, **changes), now), baseline)

    def test_only_selected_memories_get_persistent_recall_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats ordinary", importance=1, emotional_intensity=1)
            memory.remember("cats important", importance=9, emotional_intensity=9)
            first = memory.search("cats", limit=1)[0]
            self.assertEqual(first.text, "cats important")
            self.assertEqual(first.recall_count, 1)
            self.assertIsNotNone(first.last_recalled_at)
            memory.close()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            second = memory.search("cats", limit=1)[0]
            self.assertEqual(second.recall_count, 2)
            self.assertGreater(second.recall_score, first.recall_score)
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                rows = connection.execute("SELECT text, importance, recall_count FROM memories ORDER BY id").fetchall()
            self.assertEqual(rows, [("cats ordinary", 1, 0), ("cats important", 9, 2)])

    def test_unknown_legacy_metadata_and_large_recall_count_stay_bounded(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        result = MemorySearchResult("old", 1.0, "invalid timestamp", recall_count=1_000_000)
        score = LongTermMemory._recall_score(result, now)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 1)

    def test_decay_protects_important_emotional_memories(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        memory = MemorySearchResult("cats", 1.0, (now - timedelta(days=30)).isoformat())
        self.assertAlmostEqual(LongTermMemory._current_strength(memory, now), 0.5)
        protected = replace(memory, importance=10, emotional_intensity=10)
        self.assertGreater(LongTermMemory._current_strength(protected, now), 0.5)
        recalled = replace(memory, strength=0.8, last_recalled_at=(now - timedelta(days=15)).isoformat())
        self.assertAlmostEqual(LongTermMemory._current_strength(recalled, now), 0.8 * 0.5 ** 0.5)

    def test_automatic_forgetting_keeps_text_without_loading_embedder(self):
        class UnusedEmbedder(FakeEmbedder):
            def encode(self, text, normalize_embeddings=True):
                raise AssertionError("Forgotten memories should not need embedding")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats")
            memory.close()
            old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE memories SET created_at = ?", (old,))
            memory = LongTermMemory(path, embedder=UnusedEmbedder())
            self.assertLess(memory.get_strength(1), 0.15)
            self.assertEqual(memory.search("cats"), [])
            self.assertEqual(memory.count(), 1)
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT text, recall_count FROM memories").fetchone(), ("cats", 0))

    def test_selected_memory_is_reinforced_and_decay_is_not_applied_twice(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            with patch("memory.long_term_memory.vector_memory.datetime", FixedDatetime):
                memory = LongTermMemory(path, embedder=FakeEmbedder())
                memory.remember("cats selected")
                memory.remember("dogs unselected")
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute("UPDATE memories SET created_at = ?", ((now - timedelta(days=30)).isoformat(),))
                self.assertAlmostEqual(memory.get_strength(1), 0.5)
                self.assertAlmostEqual(memory.get_strength(1), 0.5)
                selected = memory.search("cats", limit=1)[0]
                self.assertAlmostEqual(selected.strength, 0.7)
                self.assertAlmostEqual(memory.get_strength(1), 0.7)
                self.assertAlmostEqual(memory.get_strength(2), 0.5)
                memory.close()
                memory = LongTermMemory(path, embedder=FakeEmbedder())
                self.assertAlmostEqual(memory.get_strength(1), 0.7)
                self.assertAlmostEqual(memory.get_strength(2), 0.5)
                memory.close()

    def test_manual_forgetting_and_recovery_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats", importance=8)
            memory.forget(1)
            memory.close()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            self.assertEqual(memory.get_strength(1), 0)
            self.assertEqual(memory.search("cats"), [])
            self.assertAlmostEqual(memory.reinforce(1), 0.2)
            for _ in range(10):
                memory.reinforce(1)
            self.assertLessEqual(memory.get_strength(1), 1)
            result = memory.search("cats")[0]
            self.assertEqual(result.importance, 8)
            self.assertLessEqual(result.strength, 1)
            for action in (memory.get_strength, memory.forget, memory.reinforce):
                with self.assertRaises(KeyError):
                    action(999)
            memory.close()

    def test_current_strength_changes_recall_priority(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        memory = MemorySearchResult("cats", 0.8, now.isoformat(), importance=8)
        strong = LongTermMemory._recall_score(memory, now)
        weak = LongTermMemory._recall_score(replace(memory, strength=0.2), now)
        self.assertAlmostEqual(weak, strong * 0.2)
