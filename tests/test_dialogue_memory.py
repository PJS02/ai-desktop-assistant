import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from memory.long_term_memory import LongTermMemory
from memory.long_term_memory.dialogue_memory import parse_dialogue_response, apply_dialogue_memory
from test_vector_memory import FakeEmbedder


def response(**changes):
    data = {
        "text": "I remember that", "importance": 0, "emotional_intensity": 0,
        "used_memory_ids": [], "memory_summary": "", "duplicate_memory_id": 0, "superseded_memory_ids": [],
    }
    data.update(changes)
    return json.dumps(data)


class DialogueMemoryTests(unittest.TestCase):
    def test_reinforces_only_supplied_used_ids_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats one", speaker="user")
            memory.remember("cats two", speaker="user")
            recalled = memory.search("cats")
            data = parse_dialogue_response(response(used_memory_ids=[1, 1, 999]))
            apply_dialogue_memory(memory, data, recalled, "What do I like?")
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                counts = connection.execute("SELECT recall_count FROM memories ORDER BY id").fetchall()
            self.assertEqual(counts, [(1,), (0,)])

    def test_failed_api_and_invalid_metadata_have_no_memory_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats", speaker="user")
            recalled = memory.search("cats")
            for raw in ("", "[gemini error] HTTP Error 503: Service Unavailable", "bad JSON",
                        response(text=""), response(used_memory_ids=[True]),
                        response(importance="8"), response(emotional_intensity=11),
                        response(memory_summary=123), response(duplicate_memory_id=-1)):
                data = parse_dialogue_response(raw)
                self.assertIsNone(data)
                if data:
                    apply_dialogue_memory(memory, data, recalled, "cats")
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT recall_count FROM memories").fetchone(), (0,))

    def test_extracted_fact_and_original_are_stored_without_ai_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            data = parse_dialogue_response(response(importance=8, emotional_intensity=3,
                                                    memory_summary="The user likes cats"))
            apply_dialogue_memory(memory, data, [], "I like cats. Please remember!")
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute("SELECT text, original_text, speaker, importance FROM memories").fetchall()
            self.assertEqual(row, [("The user likes cats", "I like cats. Please remember!", "user", 8)])

    def test_rephrased_duplicate_and_used_memory_are_reinforced_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember_fact("I like cats", original_text="Remember cats", importance=8)
            recalled = memory.search("cats")
            data = parse_dialogue_response(response(importance=2, memory_summary="cats are my preference",
                                                    duplicate_memory_id=1, used_memory_ids=[1]))
            apply_dialogue_memory(memory, data, recalled, "I still prefer cats")
            self.assertEqual(memory.count(), 1)
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT recall_count FROM memories").fetchone(), (1,))

    def test_foreign_duplicate_id_cannot_modify_unprovided_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            memory = LongTermMemory(path, embedder=FakeEmbedder())
            memory.remember("cats old", speaker="user")
            data = parse_dialogue_response(response(importance=8, memory_summary="cats new", duplicate_memory_id=1))
            apply_dialogue_memory(memory, data, [], "cats new")
            self.assertEqual(memory.count(), 2)
            memory.close()
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT recall_count FROM memories WHERE id = 1").fetchone(), (0,))

    def test_valid_reply_containing_http_numbers_is_not_an_error(self):
        data = parse_dialogue_response(response(text="500 cats and 401 dogs"))
        self.assertEqual(data["text"], "500 cats and 401 dogs")
