import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtTest import QTest

from ai import gemini_client
from app_logging import clear_events, get_events
from character.ai_settings import load_ai_settings, save_ai_settings
from character.character_widget import CharacterWidget
from character.dialogue_system import DialogueSystem
from character.settings_controller import SettingsController
from context.active_window_classifier import call_gemini
from memory.long_term_memory import LongTermMemory
from memory.long_term_memory.dialogue_memory import DIALOGUE_RESPONSE_SCHEMA
from memory.long_term_memory.dialogue_memory import build_memory_context
from test_vector_memory import FakeEmbedder


def memory_response(**changes):
    data = dict(text="cats reply", importance=0, emotional_intensity=0,
                used_memory_ids=[], memory_summary="", duplicate_memory_id=0, superseded_memory_ids=[])
    data.update(changes)
    return json.dumps(data)


class SharedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.central = Path(self.directory.name) / "ai" / "gemini_config.json"
        self.legacy = Path(self.directory.name) / "legacy.json"
        self.patchers = [patch.object(gemini_client, "CONFIG_PATH", self.central),
                         patch.object(gemini_client, "LEGACY_CONFIG_PATHS", (self.legacy,))]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_central(self, content):
        self.central.parent.mkdir(exist_ok=True)
        self.central.write_text(content, encoding="utf-8")

    def test_central_settings_win_and_save_preserves_extra_fields(self):
        self.write_central('{"api_key":"old-key","model":"old-model","extra":42}')
        legacy_content = '{"api_key":"legacy-key","model":"legacy-model"}'
        self.legacy.write_text(legacy_content, encoding="utf-8")
        self.assertEqual(load_ai_settings()["api_key"], "old-key")
        save_ai_settings("new-key", "new-model", trace_id="settings-test")
        self.assertEqual(load_ai_settings(), dict(api_key="new-key", model="new-model", extra=42))
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), legacy_content)

    def test_legacy_migration_keeps_original_and_is_idempotent(self):
        content = '{"api_key":"legacy-key","model":"legacy-model","extra":42}'
        self.legacy.write_text(content, encoding="utf-8")
        self.assertEqual(load_ai_settings(), json.loads(content))
        original = self.central.read_bytes()
        self.assertEqual(load_ai_settings(), json.loads(content))
        self.assertEqual(self.central.read_bytes(), original)
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), content)

    def test_failed_atomic_replace_preserves_existing_settings(self):
        self.write_central('{"api_key":"old-key","model":"old-model"}')
        original = self.central.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("write denied")):
            with self.assertRaises(OSError):
                save_ai_settings("new-key", "new-model")
        self.assertEqual(self.central.read_bytes(), original)
        self.assertFalse(self.central.with_suffix(".json.tmp").exists())

    def test_malformed_central_config_is_not_overwritten_or_replaced_by_legacy(self):
        self.legacy.write_text('{"api_key":"legacy-key"}', encoding="utf-8")
        for content in ('{broken', '[]', '{"api_key":123}', '{"model":null}'):
            with self.subTest(content=content):
                self.write_central(content)
                with self.assertRaises(ValueError):
                    load_ai_settings()
                with self.assertRaises(ValueError):
                    save_ai_settings("new-key", "new-model")
                self.assertEqual(self.central.read_text(encoding="utf-8"), content)

    def test_settings_controller_reloads_both_live_consumers(self):
        self.write_central('{"api_key":"old-key","model":"old-model","extra":42}')
        character = QWidget()
        dialogue = SimpleNamespace(gemini_config={})
        character.dialogue_system = dialogue
        character.gemini_config = {}
        character._load_gemini_config = lambda: CharacterWidget._load_gemini_config(character)
        dialogue._load_gemini_config = lambda: DialogueSystem._load_gemini_config(dialogue)
        controller = SettingsController(character, Mock())
        controller.dialog = Mock()
        controller.apply({"local": {"ai": {"api_key": "ui-new-key", "model": "ui-new-model"}},
                          "remote": {}})
        for consumer in (character, dialogue):
            self.assertEqual(consumer.gemini_config,
                             dict(api_key="ui-new-key", model="ui-new-model", extra=42))
        controller.dialog.complete.assert_called_once()
        character.close()


class GeminiTransportTests(unittest.TestCase):
    def setUp(self):
        clear_events()
        self.config = {"api_key": "merge-test-credential", "model": "test-model"}

    def test_dialogue_and_activity_share_transport_but_keep_distinct_schemas(self):
        http = Mock()
        http.__enter__ = Mock(return_value=http)
        http.__exit__ = Mock(return_value=False)
        http.status = 200
        http.read.return_value = json.dumps({"candidates": [{"content": {
            "parts": [{"text": memory_response()}]}}]}).encode()
        fake = SimpleNamespace(_response_provider=None)
        with patch.object(gemini_client, "urlopen", return_value=http) as send:
            DialogueSystem._call_ai(fake, "dialogue", self.config,
                                    log_context={"trace_id": "manual-test", "source": "text"})
            call_gemini("activity", self.config,
                        log_context={"trace_id": "activity-test", "source": "activity"})
        bodies = [json.loads(call.args[0].data) for call in send.call_args_list]
        self.assertEqual(bodies[0]["generationConfig"]["responseJsonSchema"], DIALOGUE_RESPONSE_SCHEMA)
        self.assertEqual(bodies[1]["generationConfig"]["responseJsonSchema"]["required"], ["dialogue"])
        requests = [event for event in get_events() if event.event == "gemini.request"]
        self.assertEqual([event.trace_id for event in requests], ["manual-test", "activity-test"])
        self.assertNotIn(self.config["api_key"], "\n".join(event.details() for event in get_events()))

    def test_http_error_is_logged_with_trace_and_without_credentials(self):
        key = self.config["api_key"]
        error = HTTPError(f"https://example.invalid/?key={key}", 503, f"unavailable {key}", {},
                          io.BytesIO(f"body {key}".encode()))
        with patch.object(gemini_client, "urlopen", side_effect=error):
            response = gemini_client.request_gemini("hello", self.config,
                                                    log_context={"trace_id": "error-test"})
        self.assertTrue(response.startswith("[gemini error]"))
        events = [event for event in get_events() if event.event == "gemini.http_failed"]
        self.assertEqual(events[0].trace_id, "error-test")
        self.assertEqual(events[0].data["status"], 503)
        self.assertNotIn(key, "\n".join(event.details() for event in get_events()))

    def test_automatic_worker_uses_its_config_snapshot_and_activity_schema(self):
        fake = SimpleNamespace(_character_closing=False, gemini_config={"api_key": "later-key"},
                               dialogue_system=SimpleNamespace(_process_gemini_response=lambda raw: "activity reply"),
                               automatic_response_ready=Mock())
        with patch("character.character_widget.get_active_window_info",
                   return_value={"process": "code.exe", "title": "test"}), patch(
                       "character.character_widget.capture_active_window_image", return_value=Mock()), patch(
                       "character.character_widget.request_gemini", return_value='{"dialogue":"activity reply"}') as send:
            CharacterWidget._check_active_window_async(fake, 1, 2, self.config, "calm", "friendly",
                                                       {"trace_id": "snapshot-test"})
        self.assertEqual(send.call_args.args[1], self.config)
        self.assertEqual(send.call_args.kwargs["response_schema"]["required"], ["dialogue"])
        self.assertEqual(send.call_args.kwargs["log_context"]["trace_id"], "snapshot-test")
        fake.automatic_response_ready.emit.assert_called_once()

    def test_automatic_worker_preserves_failure_status_after_normalization(self):
        fake = SimpleNamespace(_character_closing=False,
                               dialogue_system=SimpleNamespace(_process_gemini_response=lambda raw: "Please try again"),
                               automatic_response_ready=Mock())
        for response in ("[gemini error] HTTP Error 503: Service Unavailable",
                         "[gemini error] screen privacy processing failed"):
            with self.subTest(response=response), patch(
                    "character.character_widget.get_active_window_info",
                    return_value={"process": "code.exe", "title": "test"}), patch(
                    "character.character_widget.capture_active_window_image", return_value=Mock()), patch(
                    "character.character_widget.request_gemini", return_value=response):
                CharacterWidget._check_active_window_async(fake, 1, 2, self.config, "calm", "friendly")
                result = fake.automatic_response_ready.emit.call_args.args[0]
                self.assertEqual(result[2], "Please try again")
                self.assertTrue(result[-1])

    def test_manual_generation_reports_capture_failure_without_sending(self):
        fake = SimpleNamespace(_character_closing=False, automatic_response_ready=Mock())
        with patch("character.character_widget.get_active_window_info",
                   return_value={"process": "code.exe", "title": "test"}), patch(
                "character.character_widget.capture_active_window_image", return_value=None), patch(
                "character.character_widget.request_gemini") as send:
            CharacterWidget._check_active_window_async(fake, 1, 2, self.config, "calm", "friendly",
                                                       {"source": "manual_generation", "trace_id": "capture-test"})
        send.assert_not_called()
        result = fake.automatic_response_ready.emit.call_args.args[0]
        self.assertTrue(result[2])
        self.assertTrue(result[-1])


class QueuedMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.memory = LongTermMemory(Path(self.directory.name) / "memory.sqlite3", embedder=FakeEmbedder())
        self.now = [100.0]
        character = SimpleNamespace(mood_system=Mock(), personality_system=Mock())
        with patch("character.dialogue_system.LongTermMemory", return_value=self.memory), patch(
                "character.dialogue_system.DialogueSystem._load_gemini_config"), patch(
                "character.dialogue_system.load_dialogue_style", return_value="default"):
            self.dialogue = DialogueSystem(character, tts=Mock(), time_provider=lambda: self.now[0])
        self.dialogue.show_dialogue = Mock()
        self.dialogue.show_user_dialogue = Mock()
        self.dialogue.show_ai_response = Mock()
        self.dialogue.gemini_config = {"api_key": "first-key", "model": "test-model"}
        self.addCleanup(self.memory.close)
        self.addCleanup(self.dialogue.shutdown)

    def pump_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(1)
        self.assertTrue(condition(), "dialogue worker did not finish")

    def test_text_voice_queue_preserves_memory_order_and_uses_next_request_settings(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []

        def provider(prompt, config):
            calls.append((prompt, config.copy(), threading.get_ident()))
            if len(calls) == 1:
                started.set()
                release.wait(5)
                return memory_response(importance=8, emotional_intensity=3, memory_summary="cats preference")
            return memory_response(used_memory_ids=[1])

        self.dialogue._response_provider = provider
        self.assertTrue(self.dialogue.ask_ai("cats first"))
        self.assertTrue(started.wait(2))
        self.assertTrue(self.dialogue.submit_speech("cats second"))
        self.assertEqual([item.content for item in self.dialogue.conversation_memory.recent()], ["cats first"])
        self.dialogue.gemini_config["api_key"] = "second-key"
        release.set()
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.memory.count(), 1)
        self.now[0] += 11
        self.dialogue._process_next_input()
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertNotIn("cats second", calls[0][0])
        self.assertIn("cats reply", calls[1][0])
        self.assertIn("ID=1", calls[1][0])
        self.assertIn("cats preference", calls[1][0])
        self.assertEqual([call[1]["api_key"] for call in calls], ["first-key", "second-key"])
        self.assertTrue(all(call[2] != threading.get_ident() for call in calls))
        self.assertEqual([item.role for item in self.dialogue.conversation_memory.recent()],
                         ["user", "assistant", "user", "assistant"])
        self.assertEqual([item["state"] for item in self.dialogue.conversation_history], ["completed"] * 4)
        with closing(sqlite3.connect(self.memory.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT original_text, recall_count FROM memories").fetchall(),
                             [("cats first", 1)])

    def test_failed_response_does_not_save_or_reinforce_memories(self):
        self.memory.remember("cats existing", importance=8, speaker="user")
        self.dialogue._response_provider = lambda *_: "[gemini error] HTTP Error 503: Service Unavailable"
        self.dialogue.ask_ai("cats question")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.dialogue.conversation_history[0]["state"], "failed")
        self.assertEqual([item.role for item in self.dialogue.conversation_memory.recent()], ["user"])
        with closing(sqlite3.connect(self.memory.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT recall_count FROM memories").fetchall(), [(0,)])

    def test_memory_reply_waits_for_voice_playback_and_keeps_next_turn_queued(self):
        self.dialogue.show_ai_response = lambda *args, **kwargs: DialogueSystem.show_ai_response(
            self.dialogue, *args, **kwargs)
        self.dialogue.tts.sync_bubble = True
        self.dialogue.tts.enabled = True
        self.dialogue.tts.speak.side_effect = lambda text: self.dialogue._on_tts_busy_changed(True)
        self.dialogue._response_provider = lambda *_: memory_response(importance=8, memory_summary="cats preference")
        self.dialogue.ask_ai("cats first")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.memory.count(), 1)
        self.dialogue.show_user_dialogue.assert_called_once()
        self.dialogue.show_dialogue.assert_not_called()
        self.dialogue.submit_speech("cats second")
        self.now[0] += 11
        self.dialogue._process_next_input()
        self.assertEqual(len(self.dialogue.pending_inputs), 1)
        self.dialogue._on_tts_speaking_changed(True)
        self.dialogue.show_dialogue.assert_called_once()
        self.assertEqual(self.dialogue.show_dialogue.call_args.args[0], "cats reply")
        self.assertEqual([item.content for item in self.dialogue.conversation_memory.recent()],
                         ["cats first", "cats reply"])

    def test_failed_memory_request_displays_notice_without_voice(self):
        self.dialogue.show_ai_response = lambda *args, **kwargs: DialogueSystem.show_ai_response(
            self.dialogue, *args, **kwargs)
        self.dialogue._response_provider = lambda *_: "[gemini error] HTTP Error 503: Service Unavailable"
        self.dialogue.ask_ai("cats question")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.dialogue.conversation_history[0]["state"], "failed")
        self.dialogue.show_dialogue.assert_called_once()
        self.dialogue.tts.speak.assert_not_called()
        self.assertEqual(self.memory.count(), 0)

    def test_worker_applies_correction_and_displays_reply_without_reinforcing_old_fact(self):
        self.memory.remember_fact("I like cats", original_text="cats original", importance=8)
        self.dialogue._response_provider = lambda *_: memory_response(
            text="Updated your cats preference", memory_summary="I dislike cats now", importance=1,
            superseded_memory_ids=[1], used_memory_ids=[1],
        )
        self.dialogue.ask_ai("I dislike cats now")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.dialogue.conversation_history[0]["state"], "completed")
        self.dialogue.show_ai_response.assert_called_once()
        self.assertEqual([item.memory_id for item in self.memory.search("cats")], [2])
        with closing(sqlite3.connect(self.memory.database_path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT superseded_by, recall_count FROM memories ORDER BY id"
            ).fetchall(), [(2, 0), (None, 0)])

    def test_candidate_verification_and_answer_use_one_provider_call(self):
        for index in range(12):
            self.memory.remember_fact(f"cats preference {index}", original_text=f"cats original {index}", importance=8)
        calls = []

        def provider(prompt, config):
            calls.append(prompt)
            self.assertIn("답변용 후보, 최대 3개", prompt)
            self.assertIn("추가 대조 전용 후보", prompt)
            self.assertNotIn("ID=11,", prompt)
            self.assertNotIn("ID=12,", prompt)
            return memory_response(text="No relevant memory needed", relevant_memory_ids=[], used_memory_ids=[])

        self.dialogue._response_provider = provider
        self.dialogue.ask_ai("cats question")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.dialogue.conversation_history[0]["state"], "completed")
        with closing(sqlite3.connect(self.memory.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT SUM(recall_count) FROM memories").fetchone(), (0,))

    def test_comparison_only_memory_reported_as_answer_source_rejects_output(self):
        for index in range(5):
            self.memory.remember_fact(f"cats {index}", original_text=f"cats {index}", importance=8)
        candidates = self.memory.search_candidates("cats")
        _, answer = build_memory_context(candidates, self.memory.settings)
        extra = next(item for item in candidates if item.memory_id not in {item.memory_id for item in answer})
        self.dialogue._response_provider = lambda *_: memory_response(
            text="Invalid memory grounded reply", relevant_memory_ids=[extra.memory_id], used_memory_ids=[extra.memory_id],
            importance=8, memory_summary="cats invalid new fact")
        self.dialogue.ask_ai("cats question")
        self.pump_until(lambda: not self.dialogue.is_ai_responding)
        self.assertEqual(self.dialogue.conversation_history[0]["state"], "failed")
        self.assertEqual(self.memory.count(), 5)
        self.assertNotIn("Invalid memory grounded reply", [item.content for item in self.dialogue.conversation_memory.recent()])

    def test_shutdown_discards_late_response_without_memory_side_effects(self):
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def provider(*_):
            started.set()
            release.wait(5)
            return memory_response(importance=8, memory_summary="cats late fact")

        self.dialogue._response_provider = provider
        self.dialogue.ask_ai("cats late input")
        self.assertTrue(started.wait(2))
        worker = next(thread for thread in threading.enumerate() if thread.name == "character-dialogue-1")
        self.dialogue.shutdown()
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.app.processEvents()
        self.assertEqual(self.memory.count(), 0)
        self.dialogue.show_ai_response.assert_not_called()

    def test_prompt_uses_bounded_short_term_context(self):
        for index in range(20):
            self.dialogue.conversation_memory.add("user", f"cats {index} " + "x" * 1000)
        context = self.dialogue.conversation_memory.build_context()
        prompt = self.dialogue._build_user_prompt("cats now")
        self.assertLessEqual(len(context), 4000)
        self.assertIn(context, prompt)
        self.assertNotIn("cats 0 ", prompt)
        self.assertIn("memory_summary", prompt)
        self.assertIn("6. 사용자가 명시적으로 기억해달라고 했는가?", prompt)
