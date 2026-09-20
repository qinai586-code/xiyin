"""Cross-domain race regressions with real temporary state and explicit seams.

Injected provider/action behavior only tests scheduler control flow. It is not
model inference, native device validation, or an OS authorization bypass test.
"""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from xiyin_runtime.config import Settings
from xiyin_runtime.body.models import AdapterOutcome, Capability, Observation
from xiyin_runtime.contracts import InputEvent
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig, ProviderCancelled
from xiyin_runtime.runtime import XIYINRuntime
from xiyin_runtime.supervisor import set_stop_marker
from xiyin_runtime.service import serve


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class WaitingProvider:
    def __init__(self):
        self.started = asyncio.Event()
        self.closed = asyncio.Event()

    async def stream(self, messages, cancel):
        self.started.set()
        try:
            await cancel.wait()
            raise ProviderCancelled("synthetic cooperative cancellation")
            yield
        finally:
            self.closed.set()


class ArchitectureEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-architecture-race-"))
        self.base = Path(temporary).resolve()
        self.root = self.base / "data"
        self.root.mkdir()
        (self.root / ".xiyin_data").write_text("xiyin-data-root v1\nid=race-test\n", encoding="utf-8")
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.store = ExperienceStore(self.root / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.provider = WaitingProvider()
        self.runtime = XIYINRuntime(Settings(ProviderConfig("http://localhost:8080/v1", "unused"), SEED),
                                    self.store, provider=self.provider, authorize=lambda: None, data_root_id="race-test")
        self.runtime.register_workspace(self.workspace)

    async def collect(self):
        return [item async for item in self.runtime.stream_turn("synthetic waiting input")]

    def goal(self):
        return self.runtime.create_goal({"title": "synthetic race goal", "steps": [
            {"operation": "read_text", "arguments": {"path": "nonexistent.txt"}}
        ]}, "owner", "private")

    async def test_external_stop_interrupts_active_stream_without_scheduler(self):
        task = asyncio.create_task(self.collect())
        try:
            await asyncio.wait_for(self.provider.started.wait(), 1)
            set_stop_marker(self.root, "race-test")
            events = await asyncio.wait_for(asyncio.shield(task), 1)
            self.assertEqual(events[-1].type, "cancelled")
            self.assertTrue(self.provider.closed.is_set())
        finally:
            self.runtime.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_goal_exception_keeps_goal_and_job_status_consistent(self):
        goal = self.goal()
        self.runtime.execute_action = AsyncMock(side_effect=RuntimeError("synthetic dispatch failure"))
        with self.assertRaisesRegex(RuntimeError, "synthetic dispatch"):
            await self.runtime.tick()
        current = self.store.read_document("goals", goal["id"])["value"]
        job = self.runtime.agenda.get(goal["job_id"])
        self.assertEqual(job["status"], "unknown")
        self.assertEqual(current["status"], job["status"])

    async def test_successful_first_action_does_not_cancel_remaining_goal_steps(self):
        goal = self.runtime.create_goal({"title": "two real file actions", "steps": [
            {"operation": "write_text", "arguments": {"path": "first.txt", "text": "first"}},
            {"operation": "write_text", "arguments": {"path": "second.txt", "text": "second"}},
        ]}, "owner", "private")
        job = await self.runtime.tick()
        self.assertEqual(job["status"], "completed")
        self.assertEqual((self.workspace / "first.txt").read_text(encoding="utf-8"), "first")
        self.assertEqual((self.workspace / "second.txt").read_text(encoding="utf-8"), "second")
        self.assertEqual(self.store.read_document("goals", goal["id"])["value"]["completed_steps"], 2)

    async def test_wake_during_goal_cannot_leave_completed_goal_with_unknown_job(self):
        goal = self.goal()
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed_action(*args, **kwargs):
            started.set()
            await release.wait()
            return {"status": "success", "event_id": "synthetic-control-flow-only"}
        self.runtime.execute_action = delayed_action
        task = asyncio.create_task(self.runtime.tick())
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.runtime.sleep_controller.wake("synthetic foreground preemption")
            release.set()
            await asyncio.wait_for(task, 1)
            current = self.store.read_document("goals", goal["id"])["value"]
            job = self.runtime.agenda.get(goal["job_id"])
            self.assertEqual(current["status"], job["status"])
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_shutdown_drains_cooperative_foreground_before_closing_store(self):
        # An empty registry must not accidentally rely on adapter.stop() to
        # yield long enough for the foreground consumer to finish cleanup.
        await self.runtime.body.unregister("workspace")
        task = asyncio.create_task(self.collect())
        try:
            await asyncio.wait_for(self.provider.started.wait(), 1)
            await self.runtime.shutdown()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
            self.assertTrue(task.done())
            self.assertTrue(self.provider.closed.is_set())
            self.assertTrue(self.store._closed)
        finally:
            self.runtime.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_public_input_cannot_dispatch_owner_operations_or_read_private_context(self):
        for kind in ("status", "remember", "observe", "action", "goal", "backup", "stop", "learn"):
            with self.subTest(kind=kind), self.assertRaises(PermissionError):
                InputEvent(kind, {}, session_id="visitor", scope="public")
        self.runtime.remember("private sentinel must never appear in public context")
        messages = self.runtime._messages("private sentinel", "visitor", "public")
        self.assertFalse(any("private sentinel must never appear" in item["content"] for item in messages))

    async def test_saturated_service_keeps_owner_stop_available(self):
        released = asyncio.Event()
        class SlowObservationAdapter:
            capability = Capability("slow", "1", ("probe",), True, "synthetic")
            async def health(self):
                await released.wait()
                return {"available": True}
            async def observe(self):
                return Observation("slow", "1", "synthetic", 0, 0, (1, 1), "stable")
            async def stop(self):
                released.set()
                return {"held_keys": 0}
        self.runtime.body.register(SlowObservationAdapter())
        commands = [{"kind": "observe", "payload": {"adapter_id": "slow"}, "request_id": f"observe-{i}"}
                    for i in range(32)]
        commands.append({"kind": "stop", "request_id": "priority-stop"})
        source = io.StringIO("".join(json.dumps(command) + "\n" for command in commands))
        destination = io.StringIO()
        try:
            await asyncio.wait_for(serve(self.runtime, input_stream=source, output_stream=destination), 3)
        finally:
            released.set()
        responses = [json.loads(line) for line in destination.getvalue().splitlines()]
        response = next(value for value in responses if value.get("request_id") == "priority-stop")
        self.assertTrue(response["ok"])
        self.assertTrue(response["result"]["stopped"])

    async def test_shutdown_drains_direct_body_action_before_closing_store(self):
        started = asyncio.Event()
        class WaitingAdapter:
            capability = Capability("waiting", "1", ("probe",), True, "synthetic")
            async def health(self):
                return {"available": True}
            async def observe(self):
                return Observation("waiting", "1", "synthetic", 0, 0, (1, 1), "stable")
            async def execute(self, request, cancel):
                started.set()
                await cancel.wait()
                return AdapterOutcome("unknown", detail="Synthetic action cancelled after dispatch")
            async def stop(self):
                return {"held_keys": 0}
        self.runtime.body.register(WaitingAdapter())
        task = asyncio.create_task(self.runtime.dispatch(InputEvent("action", {"adapter_id": "waiting", "operation": "probe"})))
        try:
            await asyncio.wait_for(started.wait(), 1)
            await self.runtime.shutdown()
            results = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
            self.assertTrue(task.done())
            self.assertTrue(self.store._closed)
            self.assertNotIsInstance(results[0], Exception, "Body result must be recorded before the store closes")
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
