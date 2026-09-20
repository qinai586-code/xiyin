"""Unified architecture integration; real files/SQLite, explicit offline host fixture.

These tests exercise the production domain path. Only host authorization and
text generation are fixtures; they do not claim Windows hardware/model quality.
"""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xiyin_runtime.acceptance import exercise_runtime
from xiyin_runtime.architecture import DisabledModelProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.contracts import InputEvent
from xiyin_runtime.dataset import export_dataset
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime
from xiyin_runtime.service import serve
from xiyin_runtime.supervisor import restore_backup

SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class WaitingProvider:
    def __init__(self):
        self.started = asyncio.Event()

    async def stream(self, messages, cancel):
        self.started.set()
        await cancel.wait()
        yield "late fixture must never be visible"


class ArchitectureFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / ".xiyin_data").write_text("xiyin-data-root v1\nid=integration-test\n", encoding="utf-8")
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.settings = Settings(ProviderConfig("http://localhost:8080/v1", "xiyin"), SEED)
        self.runtime = self.make_runtime()
        self.addCleanup(lambda: self.runtime.close())

    def make_runtime(self, provider=None):
        return XIYINRuntime(self.settings, ExperienceStore(self.data / "experience.sqlite3"),
                            authorize=lambda: None, data_root_id="integration-test",
                            provider=provider or DisabledModelProvider())

    async def test_complete_model_free_architecture_and_restart_restore(self):
        # Any accidentally constructed HTTP client makes this test fail.
        with patch("httpx.AsyncClient", side_effect=AssertionError("No model/network is allowed")):
            result = await exercise_runtime(self.runtime, self.workspace)
            self.runtime.supervisor.create_backup(self.root / "backup")
            self.runtime.remember("after-backup")
            await self.runtime.shutdown()
            restore_backup(self.root / "backup", self.data, "integration-test")
            self.runtime = self.make_runtime()
            self.assertEqual(self.runtime.self_state.persistent_id, result["character_identity"])
            self.assertEqual([m["id"] for m in self.runtime.store.memories()], [result["memory_id"]])
            self.assertEqual(self.runtime.store.read_document("goals", result["goal_id"])["value"]["status"], "completed")

    async def test_disabled_model_fails_honestly_without_fallback(self):
        result = await self.runtime.dispatch(InputEvent("text", {"text": "你好"}))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["text"], "")
        self.assertIn("disabled", result["detail"])
        self.assertFalse(any(row["kind"] == "assistant" and row["status"] == "completed"
                             for row in self.runtime.store.list_events("owner")))

    async def test_public_adapter_cannot_get_private_state_or_control(self):
        for operation in ("status", "remember", "action", "goal", "learn", "backup", "stop"):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                InputEvent(operation, {}, scope="public", session_id="stream")
        event = InputEvent.from_public_adapter("hello", session_id="stream")
        self.assertEqual(event.scope, "public")

    async def test_external_stop_marker_cancels_real_runtime_stream(self):
        provider = WaitingProvider()
        self.runtime.provider = provider
        closing = asyncio.Event()
        background = asyncio.create_task(self.runtime.run_background(closing, interval=0.005))
        turn = asyncio.create_task(self.runtime.dispatch(InputEvent("text", {"text": "wait"})))
        try:
            await asyncio.wait_for(provider.started.wait(), 2)
            self.runtime.supervisor.request_stop("external console")
            result = await asyncio.wait_for(turn, 2)
            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(result["text"], "")
        finally:
            closing.set()
            await background

    async def test_idle_runtime_sleeps_and_user_input_wakes_same_state(self):
        self.runtime._last_input = 0
        closing = asyncio.Event()
        background = asyncio.create_task(self.runtime.run_background(closing, interval=0.005, idle_sleep_seconds=0.001))
        try:
            for _ in range(100):
                if self.runtime.sleep_controller.state()["phase"] == "sleeping":
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(self.runtime.sleep_controller.state()["phase"], "sleeping")
            closing.set()
            await background
            await self.runtime.dispatch(InputEvent("text", {"text": "醒醒"}))
            self.assertEqual(self.runtime.sleep_controller.state()["phase"], "awake")
            self.assertEqual(self.runtime.self_state.snapshot()["mode"], "awake")
        finally:
            closing.set()
            await background

    async def test_goals_advance_in_background_without_repeated_user_commands(self):
        self.runtime.register_workspace(self.workspace)
        goal = await self.runtime.dispatch(InputEvent("goal", {"title": "写入一次", "steps": [
            {"operation": "write_text", "arguments": {"path": "autonomous.txt", "text": "done"}}]}))
        closing = asyncio.Event()
        background = asyncio.create_task(self.runtime.run_background(closing, interval=0.005))
        try:
            for _ in range(100):
                if self.runtime.agenda.get(goal["job_id"])["status"] == "completed":
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(self.runtime.agenda.get(goal["job_id"])["status"], "completed")
            self.assertEqual((self.workspace / "autonomous.txt").read_text(), "done")
        finally:
            closing.set()
            await background

    async def test_strategy_requires_real_evidence_and_cannot_disable_verification(self):
        event = self.runtime.store.append_event("assistant", "I succeeded", session_id="owner",
                                                origin="generated", status="completed")
        with self.assertRaises(ValueError):
            await self.runtime.dispatch(InputEvent("learn", {"goal": "test", "evidence_refs": [event],
                "strategy": {"max_read_bytes": 32, "max_write_bytes": 32,
                             "verify_after_write": False, "encoding": "utf-8"}}))
        self.assertIsNone(self.runtime.lab.active_strategy()["candidate_id"])

    async def test_console_runs_real_commands_in_single_loop_without_model(self):
        source = io.StringIO(json.dumps({"kind": "remember", "payload": {"text": "控制台真实保存"}}) + "\n")
        sink = io.StringIO()
        self.assertEqual(await serve(self.runtime, input_stream=source, output_stream=sink), 0)
        reply = json.loads(sink.getvalue())
        self.assertTrue(reply["ok"])
        self.assertEqual(self.runtime.store.memories()[0]["id"], reply["result"]["memory_id"])

    async def test_dataset_excludes_partial_and_does_not_label_generated_text_gold(self):
        self.runtime.store.append_event("user", "input", session_id="owner", origin="user_report",
                                        status="completed", request_id="test-one")
        self.runtime.store.append_event("assistant", "fixture output", session_id="owner", origin="generated",
                                        status="completed", request_id="test-one")
        self.runtime.store.append_event("user", "input two", session_id="owner", origin="user_report",
                                        status="completed", request_id="test-two")
        self.runtime.store.append_event("assistant", "unfinished", session_id="owner", origin="generated",
                                        status="partial", request_id="test-two")
        result = export_dataset(self.runtime.store, self.root / "dataset")
        self.assertEqual(result["rows"], 1)
        row = json.loads((self.root / "dataset/candidates.jsonl").read_text())
        self.assertEqual(row["quality_label"], "unreviewed")
        self.assertFalse(row["eligible_for_training"])
        self.assertFalse(result["uploaded"])
