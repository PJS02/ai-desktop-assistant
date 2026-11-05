import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from memory.long_term_memory import LongTermMemory
from memory.long_term_memory.dialogue_memory import (
    DIALOGUE_RESPONSE_SCHEMA, apply_dialogue_memory, parse_dialogue_response,
)
from memory.long_term_memory.vector_memory import METADATA_COLUMNS
from test_dialogue_memory import response
from test_vector_memory import FakeEmbedder


class MemoryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.sqlite3"
        self.memory = LongTermMemory(self.path, embedder=FakeEmbedder())
        self.addCleanup(lambda: self.memory.close())

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("""SELECT id, text, embedding, dimension, created_at,
                importance, speaker, conversation_id, emotional_intensity, recall_count,
                last_recalled_at, strength, original_text, superseded_by, superseded_at
                FROM memories ORDER BY id""").fetchall()

    def save(self, text, **kwargs):
        return self.memory.remember_fact(text, original_text=text, importance=8, **kwargs)

    def install_failure_trigger(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""CREATE TRIGGER reject_correction
                BEFORE UPDATE OF superseded_by ON memories
                WHEN NEW.superseded_by IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'correction failed'); END""")

    def test_correction_preserves_history_and_only_new_fact_is_recalled_after_restart(self):
        old_id = self.save("I like cats")
        original = self.rows()[0]
        data = parse_dialogue_response(response(
            memory_summary="I no longer like cats", importance=2,
            superseded_memory_ids=[old_id], used_memory_ids=[old_id],
        ))
        apply_dialogue_memory(self.memory, data, self.memory.search("cats"), "I no longer like cats now")
        old, new = self.rows()
        self.assertEqual(old[:-2], original[:-2])
        self.assertEqual(old[-2], new[0])
        self.assertIsNotNone(old[-1])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT text, original_text, importance, speaker FROM memories WHERE id = ?", (new[0],)
            ).fetchone(), ("I no longer like cats", "I no longer like cats now", 8, "user"))
        self.assertEqual([item.memory_id for item in self.memory.search("cats")], [new[0]])
        self.assertEqual(self.memory.count(), 2)
        self.memory.close()
        self.memory = LongTermMemory(self.path, embedder=FakeEmbedder())
        self.assertEqual([item.memory_id for item in self.memory.search("cats")], [new[0]])

    def test_correction_of_low_importance_existing_fact_bypasses_new_fact_threshold(self):
        self.memory.remember("cats old state", speaker="user", importance=3)
        new_id = self.memory.remember_fact("cats corrected state", original_text="cats correction",
                                           importance=0, superseded_memory_ids=[1])
        self.assertEqual(new_id, 2)
        self.assertEqual(self.rows()[0][-2], 2)

    def test_one_correction_can_supersede_multiple_provided_user_memories(self):
        first = self.save("cats preference")
        second = self.save("I like cats")
        new_id = self.save("I dislike cats now", superseded_memory_ids=[first, second, first])
        self.assertEqual([row[-2] for row in self.rows()], [new_id, new_id, None])
        self.assertEqual([item.memory_id for item in self.memory.search("cats")], [new_id])

    def test_existing_current_fact_can_be_reused_without_double_reinforcement(self):
        old_id = self.save("I like cats")
        current_id = self.save("I dislike cats now")
        data = parse_dialogue_response(response(
            memory_summary="I dislike cats now", importance=1,
            superseded_memory_ids=[old_id], used_memory_ids=[old_id, current_id],
        ))
        apply_dialogue_memory(self.memory, data, self.memory.search("cats"), "cats correction")
        self.assertEqual(self.memory.count(), 2)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT superseded_by, recall_count FROM memories ORDER BY id"
            ).fetchall(), [(current_id, 0), (None, 1)])

    def test_reverting_a_fact_creates_a_new_version_instead_of_reviving_history(self):
        first = self.save("I like cats")
        second = self.save("I dislike cats now", superseded_memory_ids=[first])
        third = self.save("I like cats", superseded_memory_ids=[second])
        self.assertNotEqual(first, third)
        self.assertEqual([row[-2] for row in self.rows()], [second, third, None])
        self.assertEqual([item.memory_id for item in self.memory.search("cats")], [third])
        with self.assertRaises(ValueError):
            self.memory.reinforce(first)

    def test_archived_semantic_duplicate_hint_cannot_revive_old_version(self):
        first = self.save("I like cats")
        second = self.save("I dislike cats now", superseded_memory_ids=[first])
        third = self.save("cats are my preference again", duplicate_memory_id=first)
        self.assertNotIn(third, (first, second))
        self.assertEqual(self.rows()[0][-2], second)

    def test_same_fact_mistakenly_flagged_as_correction_does_not_supersede_itself(self):
        first = self.save("I like cats")
        same = self.save("I like cats", superseded_memory_ids=[first])
        self.assertEqual(first, same)
        self.assertIsNone(self.rows()[0][-2])

    def test_distinct_fact_has_no_implicit_correction_and_missing_target_is_rejected(self):
        first = self.save("I like cats")
        self.save("I like dogs")
        original = self.rows()
        self.assertIsNone(original[0][-2])
        with self.assertRaises(KeyError):
            self.save("cats corrected", superseded_memory_ids=[999])
        self.assertEqual(self.rows(), original)

    def test_stale_correction_is_rejected_without_creating_more_history(self):
        first = self.save("I like cats")
        self.save("I dislike cats now", superseded_memory_ids=[first])
        original = self.rows()
        with self.assertRaises(ValueError):
            self.save("I dislike cats now", superseded_memory_ids=[first])
        self.assertEqual(self.rows(), original)

    def test_only_provided_user_ids_are_eligible_for_automatic_replacement(self):
        user_id = self.save("cats user fact")
        for speaker in ("assistant", "conversation", "unknown"):
            self.memory.remember(f"cats {speaker} fact", speaker=speaker)
        data = parse_dialogue_response(response(
            importance=8, memory_summary="cats corrected fact",
            superseded_memory_ids=[user_id, 2, 3],
        ))
        recalled = [item for item in self.memory.search("cats", limit=4) if item.memory_id != user_id]
        original = self.rows()
        apply_dialogue_memory(self.memory, data, recalled, "cats corrected fact")
        self.assertEqual(self.rows()[:4], original)
        for memory_id in (2, 3, 4):
            with self.assertRaises(ValueError):
                self.save("cats correction", superseded_memory_ids=[memory_id])

    def test_invalid_correction_ids_are_rejected_before_writing(self):
        first = self.save("cats old")
        original = self.rows()
        for ids in ([True], [0], [-1], [1, 2, 3, 4]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.save("cats correction", superseded_memory_ids=ids)
        with self.assertRaises(ValueError):
            self.save("cats correction", duplicate_memory_id=first, superseded_memory_ids=[first])
        self.assertEqual(self.rows(), original)

    def test_failure_to_archive_rolls_back_new_fact_and_history_together(self):
        first = self.save("I like cats")
        original = self.rows()
        self.install_failure_trigger()
        with self.assertRaises(sqlite3.IntegrityError):
            self.save("I dislike cats now", superseded_memory_ids=[first])
        self.assertEqual(self.rows(), original)

    def test_failure_to_archive_rolls_back_reinforcement_of_reused_fact(self):
        first = self.save("I like cats")
        self.save("I dislike cats now")
        original = self.rows()
        self.install_failure_trigger()
        with self.assertRaises(sqlite3.IntegrityError):
            self.save("I dislike cats now", superseded_memory_ids=[first])
        self.assertEqual(self.rows(), original)

    def test_failure_on_second_target_rolls_back_first_target_too(self):
        first = self.save("cats preference one")
        second = self.save("cats preference two")
        original = self.rows()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(f"""CREATE TRIGGER reject_second_correction
                BEFORE UPDATE OF superseded_by ON memories
                WHEN OLD.id = {second} AND NEW.superseded_by IS NOT NULL
                BEGIN SELECT RAISE(ABORT, 'second correction failed'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save("cats corrected", superseded_memory_ids=[first, second])
        self.assertEqual(self.rows(), original)

    def test_embedding_failure_leaves_original_memory_current(self):
        first = self.save("I like cats")
        original = self.rows()
        with patch.object(self.memory, "_embed", side_effect=RuntimeError("embedding failed")):
            with self.assertRaises(RuntimeError):
                self.save("I dislike cats now", superseded_memory_ids=[first])
        self.assertEqual(self.rows(), original)

    def test_without_explicit_correction_different_facts_are_kept_separately(self):
        self.save("I usually like cats")
        self.save("I do not want to see cats today")
        self.assertEqual([row[-2] for row in self.rows()], [None, None])


class MemoryUpdateSchemaTests(unittest.TestCase):
    def test_new_schema_requests_corrections_but_old_responses_still_parse(self):
        self.assertIn("superseded_memory_ids", DIALOGUE_RESPONSE_SCHEMA["required"])
        old = json.loads(response())
        old.pop("superseded_memory_ids", None)
        self.assertEqual(parse_dialogue_response(json.dumps(old))["superseded_memory_ids"], [])

    def test_malformed_or_ambiguous_correction_metadata_is_rejected(self):
        for ids in (None, 1, "1", [True], [0], [-1], [1, 2, 3, 4]):
            with self.subTest(ids=ids):
                self.assertIsNone(parse_dialogue_response(response(memory_summary="cats new", superseded_memory_ids=ids)))
        self.assertIsNone(parse_dialogue_response(response(superseded_memory_ids=[1])))
        self.assertIsNone(parse_dialogue_response(response(
            memory_summary="cats new", superseded_memory_ids=[1], duplicate_memory_id=2,
        )))

    def test_existing_schema_migration_preserves_rows_makes_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            old_columns = {name: value for name, value in METADATA_COLUMNS.items()
                           if name not in ("superseded_by", "superseded_at")}
            with patch("memory.long_term_memory.vector_memory.METADATA_COLUMNS", old_columns):
                memory = LongTermMemory(path, embedder=FakeEmbedder())
                try:
                    memory.remember("cats old", speaker="user", importance=8)
                finally:
                    memory.close()
            with closing(sqlite3.connect(path)) as connection:
                original = connection.execute("SELECT * FROM memories").fetchone()
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), (*original, None, None))
            backups = list(path.parent.glob("memory.sqlite3.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            self.assertEqual(list(path.parent.glob("memory.sqlite3.schema-backup-*")), backups)

    def test_failed_schema_expansion_rolls_back_columns_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            old_columns = {name: value for name, value in METADATA_COLUMNS.items()
                           if name not in ("superseded_by", "superseded_at")}
            with patch("memory.long_term_memory.vector_memory.METADATA_COLUMNS", old_columns):
                memory = LongTermMemory(path, embedder=FakeEmbedder())
                try:
                    memory.remember("cats original", speaker="user", importance=8)
                finally:
                    memory.close()
            with closing(sqlite3.connect(path)) as connection:
                original = connection.execute("SELECT * FROM memories").fetchone()
            real_connect = sqlite3.connect
            connections = []

            def tracked_connect(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                connections.append(connection)
                return connection

            try:
                with patch.dict(METADATA_COLUMNS, {"superseded_at": "TEXT NOT NULL"}), patch(
                        "memory.long_term_memory.vector_memory.sqlite3.connect", side_effect=tracked_connect):
                    with self.assertRaises(sqlite3.OperationalError):
                        LongTermMemory(path, embedder=FakeEmbedder())
                with self.assertRaises(sqlite3.ProgrammingError):
                    connections[0].execute("SELECT 1")
            finally:
                for connection in connections:
                    connection.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
                columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
                self.assertNotIn("superseded_by", columns)
                self.assertNotIn("superseded_at", columns)
            backups = list(path.parent.glob("memory.sqlite3.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
