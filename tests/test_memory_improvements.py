import json
import math
import sqlite3
import tempfile
import unittest
from array import array
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from memory.long_term_memory import LongTermMemory, MemorySearchResult, MemorySettings, load_memory_settings
from memory.long_term_memory.dialogue_memory import (
    DIALOGUE_SYSTEM_INSTRUCTION, apply_dialogue_memory, build_memory_context, parse_dialogue_response,
    validate_memory_references,
)
from memory.long_term_memory.vector_memory import METADATA_COLUMNS
from test_dialogue_memory import response
from test_vector_memory import FakeEmbedder


class ScoreEmbedder:
    def __init__(self, scores):
        self.scores = scores

    def encode(self, text, normalize_embeddings=True):
        if text.startswith("query:"):
            return [1.0, 0.0]
        score = self.scores[text.removeprefix("passage: ")]
        return [score, math.sqrt(1 - score * score)]


class MemoryImprovementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.sqlite3"
        self.now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now

        clock = patch("memory.long_term_memory.vector_memory.datetime", Clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.memory = LongTermMemory(self.path, embedder=FakeEmbedder(), settings=MemorySettings())
        self.addCleanup(self.memory.close)

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM memories ORDER BY id")]

    def execute(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(sql, args)

    def save(self, text, **kwargs):
        return self.memory.remember_fact(text, original_text=text, importance=8, **kwargs)

    def test_top_k_includes_low_similarity_and_limits_candidates_then_answers(self):
        scores = {f"item {index}": 0.2 + index / 100 for index in range(15)}
        self.memory._embedder = ScoreEmbedder(scores)
        for text in scores:
            self.save(text)
        candidates = self.memory.search_candidates("question")
        self.assertEqual(len(candidates), 10)
        self.assertEqual([item.memory_id for item in candidates], list(range(15, 5, -1)))
        self.assertTrue(all(item.score < 0.75 for item in candidates))
        self.assertEqual(len(self.memory.search("question")), 3)
        self.memory.settings = replace(self.memory.settings, candidate_limit=5, recall_limit=2)
        self.assertEqual(len(self.memory.search_candidates("question")), 5)
        self.assertEqual(len(self.memory.search("question")), 2)

    def test_threshold_mode_retains_previous_cutoff_as_experiment(self):
        self.memory.settings = replace(self.memory.settings, retrieval_mode="threshold")
        self.save("dogs")
        self.assertEqual(self.memory.search_candidates("cats"), [])

    def test_high_importance_cannot_enter_raw_similarity_top_k_from_outside(self):
        self.memory.settings = replace(self.memory.settings, candidate_limit=3)
        scores = {"one": 0.8, "two": 0.7, "three": 0.6, "irrelevant": 0.1}
        self.memory._embedder = ScoreEmbedder(scores)
        for text in scores:
            self.memory.remember(text, importance=10 if text == "irrelevant" else 1)
        self.assertEqual({item.text for item in self.memory.search_candidates("question")}, {"one", "two", "three"})

    def test_answer_and_comparison_lists_have_different_permissions(self):
        for index in range(10):
            self.save(f"cats {index}")
        candidates = self.memory.search_candidates("cats")
        prompt, answer = build_memory_context(candidates, self.memory.settings)
        self.assertEqual(len(answer), 3)
        self.assertIn("답변에 사용 금지", prompt)
        self.assertIn("중복검토힌트", prompt)
        extra = next(item for item in candidates if item.memory_id not in {item.memory_id for item in answer})
        data = parse_dialogue_response(response(relevant_memory_ids=[extra.memory_id], used_memory_ids=[extra.memory_id]))
        apply_dialogue_memory(self.memory, data, answer, "cats question", candidates=candidates)
        self.assertTrue(all(row["recall_count"] == 0 for row in self.rows()))

    def test_llm_relevance_rejection_does_not_reinforce_a_high_cosine_candidate(self):
        self.save("cats unrelated person's fact")
        before = self.rows()
        data = parse_dialogue_response(response(relevant_memory_ids=[], used_memory_ids=[]))
        apply_dialogue_memory(self.memory, data, self.memory.search("cats"), "cats question")
        self.assertEqual(self.rows(), before)

    def test_used_ids_must_be_in_explicit_relevant_ids(self):
        self.assertIsNone(parse_dialogue_response(response(relevant_memory_ids=[], used_memory_ids=[1])))
        for invalid in (None, "1", [True], [0], [1, 2, 3, 4]):
            self.assertIsNone(parse_dialogue_response(response(relevant_memory_ids=invalid)))

    def test_non_answer_candidate_can_be_used_for_confirmed_duplicate_only(self):
        for index in range(10):
            self.save(f"cats {index}")
        candidates = self.memory.search_candidates("cats")
        _, answer = build_memory_context(candidates, self.memory.settings)
        extra = next(item for item in candidates if item.memory_id not in {item.memory_id for item in answer})
        data = parse_dialogue_response(response(memory_summary="felines same fact", duplicate_memory_id=extra.memory_id))
        apply_dialogue_memory(self.memory, data, answer, "same fact", candidates=candidates)
        self.assertEqual(self.memory.count(), 10)
        self.assertEqual(self.rows()[extra.memory_id - 1]["recall_count"], 1)

    def test_ids_outside_candidate_catalog_cannot_force_duplicate_or_correction(self):
        self.save("cats first")
        self.save("cats second")
        provided = self.memory.search("cats", limit=1)
        outside = next(row["id"] for row in self.rows() if row["id"] != provided[0].memory_id)
        original = self.rows()
        for fields in ({"duplicate_memory_id": outside}, {"superseded_memory_ids": [outside]},
                       {"duplicate_memory_id": 999}, {"superseded_memory_ids": [999]}):
            data = parse_dialogue_response(response(memory_summary="felines new", importance=1, **fields))
            self.assertFalse(validate_memory_references(data, provided, provided))
            apply_dialogue_memory(self.memory, data, provided, "new fact", candidates=provided)
            self.assertEqual(self.rows(), original)

    def test_failed_or_invalid_responses_cannot_change_new_retention_metadata(self):
        self.save("cats original")
        original = self.rows()
        for raw in ("[gemini error] HTTP Error 503", response(memory_type="invalid"),
                    response(memory_type="profile", retention_policy="persistent", importance=99),
                    response(relevant_memory_ids=[], used_memory_ids=[1])):
            self.assertIsNone(parse_dialogue_response(raw))
        self.assertEqual(self.rows(), original)

    def test_confirmed_duplicate_is_not_vetoed_by_low_cosine(self):
        first = self.save("cats preferred")
        data = parse_dialogue_response(response(memory_summary="felines preferred", duplicate_memory_id=first))
        apply_dialogue_memory(self.memory, data, self.memory.search("cats"), "felines preferred")
        self.assertEqual(self.memory.count(), 1)
        self.assertEqual(self.rows()[0]["recall_count"], 1)

    def test_confirmed_correction_is_not_vetoed_by_low_cosine(self):
        first = self.save("cats preferred")
        data = parse_dialogue_response(response(memory_summary="felines no longer preferred", superseded_memory_ids=[first]))
        apply_dialogue_memory(self.memory, data, self.memory.search("cats"), "felines no longer preferred")
        self.assertEqual(self.rows()[0]["superseded_by"], 2)
        self.assertEqual([item.memory_id for item in self.memory.search_candidates("cats")], [2])

    def test_mock_distinct_people_and_dates_are_not_merged_despite_high_cosine(self):
        self.save("Alice met cats on 2026-10-01")
        for text in ("Alice met cats on 2026-10-02", "Bob met cats on 2026-10-01"):
            data = parse_dialogue_response(response(memory_summary=text, importance=8,
                                                    duplicate_memory_id=0, superseded_memory_ids=[]))
            apply_dialogue_memory(self.memory, data, self.memory.search("cats"), text)
        self.assertEqual(self.memory.count(), 3)
        self.assertTrue(all(row["superseded_by"] is None for row in self.rows()))
        self.assertIn("대상·주체", DIALOGUE_SYSTEM_INSTRUCTION)
        self.assertIn("서로 다른 사람이나 날짜", DIALOGUE_SYSTEM_INSTRUCTION)

    def test_effective_half_life_formula_growth_and_cap(self):
        self.assertEqual(self.memory._effective_half_life(10, 10, 0), 90)
        self.assertAlmostEqual(self.memory._effective_half_life(0, 0, 10), 30 * (1 + 0.2 * math.log(11)))
        self.assertGreater(self.memory._effective_half_life(8, 3, 2), self.memory._effective_half_life(8, 3, 1))
        self.assertEqual(self.memory._effective_half_life(10, 10, 1_000_000), 180)
        self.memory.settings = replace(self.memory.settings, half_life_beta=0.4, max_half_life_days=120)
        self.assertEqual(self.memory._effective_half_life(10, 10, 1_000_000), 120)

    def test_reinforcement_uses_old_count_then_new_half_life_without_double_decay(self):
        first = self.save("cats remembered", emotional_intensity=3)
        old_half = self.memory._effective_half_life(8, 3, 2)
        self.execute("UPDATE memories SET strength = ?, recall_count = ?, last_recalled_at = ?, decay_half_life_days = ?",
                     (0.6, 2, (self.now - timedelta(days=45)).isoformat(), old_half))
        expected = min(1, 0.6 * 2 ** (-45 / old_half) + 0.2)
        self.assertAlmostEqual(self.memory.reinforce(first), expected)
        new_half = self.memory._effective_half_life(8, 3, 3)
        row = self.rows()[0]
        self.assertEqual(row["recall_count"], 3)
        self.assertEqual(row["last_recalled_at"], self.now.isoformat())
        self.assertAlmostEqual(row["decay_half_life_days"], new_half)
        self.now += timedelta(days=30)
        for _ in range(2):
            self.assertAlmostEqual(self.memory.get_strength(first), expected * 2 ** (-30 / new_half))
        self.assertAlmostEqual(self.rows()[0]["strength"], expected)

    def test_legacy_interval_is_not_recalculated_using_new_count_formula(self):
        first = self.save("cats remembered")
        self.execute("""UPDATE memories SET importance = 0, strength = 0.8, recall_count = 50,
                     last_recalled_at = ?, decay_half_life_days = NULL""",
                     ((self.now - timedelta(days=30)).isoformat(),))
        self.assertAlmostEqual(self.memory.get_strength(first), 0.4)
        self.assertIsNone(self.rows()[0]["decay_half_life_days"])
        self.assertAlmostEqual(self.memory.reinforce(first), 0.6)
        self.assertAlmostEqual(self.rows()[0]["decay_half_life_days"], self.memory._effective_half_life(0, None, 51))

    def test_setting_changes_do_not_rewrite_an_ongoing_decay_interval(self):
        first = self.save("cats remembered")
        self.memory.reinforce(first)
        old_half = self.rows()[0]["decay_half_life_days"]
        self.now += timedelta(days=20)
        self.memory.settings = replace(self.memory.settings, half_life_beta=0, max_half_life_days=30)
        self.assertAlmostEqual(self.memory.get_strength(first), 2 ** (-20 / old_half))
        self.memory.reinforce(first)
        self.assertEqual(self.rows()[0]["decay_half_life_days"], 30)

    def test_duplicate_reassessment_updates_only_the_next_interval(self):
        self.memory.remember("cats", importance=1, emotional_intensity=1, speaker="user")
        original = self.rows()[0]
        self.now += timedelta(days=36)
        self.memory.remember_fact("cats", original_text="cats again", importance=9, emotional_intensity=8)
        row = self.rows()[0]
        self.assertAlmostEqual(row["strength"], 0.7)
        self.assertAlmostEqual(row["decay_half_life_days"], self.memory._effective_half_life(9, 8, 1))
        self.assertEqual(row["created_at"], original["created_at"])

    def test_legacy_and_strength_only_score_match_requested_formulas(self):
        item = MemorySearchResult("cats", 0.8, (self.now - timedelta(days=60)).isoformat(),
                                  importance=8, emotional_intensity=5, recall_count=5, strength=0.6)
        common = 0.4 * 0.8 + 0.25 * 0.8 + 0.15 * 0.5 + 0.1 * 0.5
        self.assertAlmostEqual(self.memory._recall_score(item, self.now, "legacy"), 0.6 * (common + 0.1 * 0.25))
        self.assertAlmostEqual(self.memory._recall_score(item, self.now, "strength_only"), 0.6 / 0.9 * common)

    def test_same_db_can_produce_different_rankings_in_the_two_modes(self):
        self.memory._embedder = ScoreEmbedder({"old": 0.8, "recent": 0.65})
        self.memory.remember("old", importance=5)
        self.memory.remember("recent", importance=5)
        self.execute("UPDATE memories SET created_at = ? WHERE id = 1", ((self.now - timedelta(days=300)).isoformat(),))
        self.execute("UPDATE memories SET recall_count = 1, last_recalled_at = ?", (self.now.isoformat(),))
        before = self.rows()
        legacy = self.memory.search("question")
        self.memory.settings = replace(self.memory.settings, recall_score_mode="strength_only")
        new = self.memory.search("question")
        self.assertEqual([item.memory_id for item in legacy], [2, 1])
        self.assertEqual([item.memory_id for item in new], [1, 2])
        self.assertEqual(self.rows(), before)

    def test_profile_survives_age_with_search_floor_but_other_types_do_not(self):
        for kind in ("profile", "temporary", "schedule", "event", "unknown"):
            self.save(f"cats {kind}", memory_type=kind)
        before = self.rows()
        self.now += timedelta(days=10_000)
        results = self.memory.search("cats")
        self.assertEqual([item.memory_type for item in results], ["profile"])
        self.assertLess(results[0].strength, 0.15)
        self.assertEqual(results[0].search_strength, 0.15)
        unprotected = replace(results[0], search_strength=None)
        self.assertGreater(results[0].recall_score, self.memory._recall_score(unprotected, self.now))
        self.assertEqual(self.rows(), before)

    def test_explicit_persistent_policy_and_manual_forget_do_not_conflict(self):
        first = self.save("cats durable requested fact", retention_policy="persistent")
        second = self.save("cats profile", memory_type="profile")
        self.now += timedelta(days=1000)
        self.assertEqual(len(self.memory.search("cats")), 2)
        self.memory.forget(first)
        self.memory.forget(second)
        self.assertEqual(self.memory.search("cats"), [])
        self.assertEqual([row["strength"] for row in self.rows()], [0, 0])

    def test_search_underflow_zero_is_not_mistaken_for_manual_forget(self):
        first = self.save("cats profile", memory_type="profile")
        self.now += timedelta(days=1_000_000)
        result = self.memory.search("cats")[0]
        self.assertEqual(result.strength, 0)
        self.assertEqual(result.search_strength, 0.15)
        self.assertEqual(self.rows()[0]["strength"], 1)
        self.memory.forget(first)
        self.assertEqual(self.memory.search("cats"), [])

    def test_duplicate_classification_cannot_pin_temporary_or_unpin_persistent(self):
        self.save("cats temporary", memory_type="temporary")
        self.save("cats temporary", retention_policy="persistent")
        self.assertEqual((self.rows()[0]["memory_type"], self.rows()[0]["retention_policy"]), ("temporary", "standard"))
        self.save("cats pinned", retention_policy="persistent")
        self.save("cats pinned", memory_type="temporary")
        self.assertEqual((self.rows()[1]["memory_type"], self.rows()[1]["retention_policy"]), ("unknown", "persistent"))

    def test_sustained_information_classification_is_saved_in_same_metadata(self):
        data = parse_dialogue_response(response(memory_summary="cats enduring preference", importance=8,
                                                memory_type="profile", retention_policy="persistent"))
        apply_dialogue_memory(self.memory, data, [], "Please remember my cats preference")
        self.assertEqual(self.rows()[0]["memory_type"], "profile")
        self.assertEqual(self.rows()[0]["retention_policy"], "persistent")

    def test_uncertain_old_metadata_uses_safe_defaults(self):
        data = parse_dialogue_response(response(memory_summary="cats fact", importance=8))
        self.assertEqual(data["memory_type"], "unknown")
        self.assertEqual(data["retention_policy"], "standard")
        for fields in ({"memory_type": "maybe profile"}, {"retention_policy": "always"},
                       {"memory_type": "temporary", "retention_policy": "persistent"}):
            self.assertIsNone(parse_dialogue_response(response(**fields)))


class MemorySettingsAndMigrationTests(unittest.TestCase):
    def make_old_db(self, path):
        columns = {name: value for name, value in METADATA_COLUMNS.items()
                   if name not in ("memory_type", "retention_policy", "decay_half_life_days")}
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("""CREATE TABLE memories (id INTEGER PRIMARY KEY, text TEXT NOT NULL,
                embedding BLOB NOT NULL, dimension INTEGER NOT NULL, created_at TEXT NOT NULL)""")
            for name, declaration in columns.items():
                connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {declaration}")
            connection.execute("""INSERT INTO memories (text, embedding, dimension, created_at, importance,
                speaker, emotional_intensity, recall_count, last_recalled_at, strength, original_text)
                VALUES (?, ?, 2, ?, 8, 'user', 4, 7, ?, 0.6, 'original cats')""",
                ("cats", array("f", [1, 0]).tobytes(), "2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00"))
            return connection.execute("SELECT * FROM memories").fetchone()

    def test_new_columns_preserve_old_fields_and_migration_backup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            original = self.make_old_db(path)
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), (*original, "unknown", "standard", None))
            backups = list(path.parent.glob("*.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.close()
            self.assertEqual(list(path.parent.glob("*.schema-backup-*")), backups)

    def test_preexisting_legacy_type_is_preserved_but_unknown_to_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            self.make_old_db(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("ALTER TABLE memories ADD COLUMN memory_type TEXT DEFAULT 'preference'")
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            try:
                candidates = memory.search_candidates("cats")
                self.assertEqual(candidates[0].memory_type, "unknown")
            finally:
                memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT memory_type FROM memories").fetchone()[0], "preference")

    def test_migration_preserves_existing_supersession_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            self.make_old_db(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("""INSERT INTO memories (text, embedding, dimension, created_at, speaker, importance)
                    SELECT 'cats revised', embedding, dimension, created_at, speaker, importance FROM memories WHERE id = 1""")
                connection.execute("UPDATE memories SET superseded_by = 2, superseded_at = '2026-10-03T00:00:00+00:00' WHERE id = 1")
                original = connection.execute("SELECT * FROM memories ORDER BY id").fetchall()
                old_columns = [row[1] for row in connection.execute("PRAGMA table_info(memories)")]
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            try:
                self.assertEqual([item.memory_id for item in memory.search_candidates("cats")], [2])
                self.assertEqual(memory.count(), 2)
            finally:
                memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute(f"SELECT {', '.join(old_columns)} FROM memories ORDER BY id").fetchall(), original)

    def test_new_policy_column_failure_rolls_back_whole_schema_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            original = self.make_old_db(path)
            with patch.dict(METADATA_COLUMNS, {"retention_policy": "TEXT NOT NULL"}):
                with self.assertRaises(sqlite3.OperationalError):
                    LongTermMemory(path, embedder=FakeEmbedder())
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)
                columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
                self.assertTrue(columns.isdisjoint({"memory_type", "retention_policy", "decay_half_life_days"}))
            backups = list(path.parent.glob("*.schema-backup-*"))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as connection:
                self.assertEqual(connection.execute("SELECT * FROM memories").fetchone(), original)

    def test_json_settings_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(load_memory_settings(path), MemorySettings())
            path.write_text(json.dumps({"candidate_limit": 12, "half_life_beta": 0.4,
                                        "max_half_life_days": 120, "recall_score_mode": "strength_only"}), encoding="utf-8")
            loaded = load_memory_settings(path)
            self.assertEqual((loaded.candidate_limit, loaded.half_life_beta, loaded.max_half_life_days,
                              loaded.recall_score_mode), (12, 0.4, 120, "strength_only"))
            for invalid in ({"candidate_limit": 0}, {"candidate_limit": True}, {"candidate_limit": 2},
                            {"recall_limit": 4}, {"half_life_beta": -0.1}, {"half_life_beta": float("nan")},
                            {"max_half_life_days": 0}, {"recall_score_mode": "better"},
                            {"retrieval_mode": "magic"}, {"typo": 1}, [], {"similarity_hint": 2}):
                with self.subTest(invalid=invalid):
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_memory_settings(path)
