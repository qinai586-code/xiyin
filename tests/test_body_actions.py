"""Body actions against real temporary files and controlled input transports."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from xiyin_runtime.body import (
    ActionRequest, AdapterOutcome, BodyRegistry, Capability, DesktopAdapter,
    Observation, WorkspaceFileAdapter,
)


class FileBodyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xiyin-body-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.adapter = WorkspaceFileAdapter(self.root)
        self.registry = BodyRegistry()
        self.registry.register(self.adapter)

    async def request(self, operation="write_text", **arguments):
        observation = await self.registry.observe("workspace")
        return ActionRequest("workspace", operation, observation.observation_id, str(self.root),
                             time.monotonic() + 5, arguments)

    async def test_real_write_readback_and_read_receipts(self):
        request = await self.request(path="note.txt", text="栖音的临时文件\n")
        receipt = await self.registry.execute(request)
        self.assertEqual(receipt.status, "success")
        self.assertTrue(receipt.verified)
        self.assertTrue(receipt.evidence["write_occurred"])
        self.assertEqual((self.root / "note.txt").read_text(encoding="utf-8"), "栖音的临时文件\n")
        read = await self.registry.execute(await self.request("read_text", path="note.txt"))
        self.assertEqual(read.evidence["text"], "栖音的临时文件\n")
        self.assertEqual(receipt.to_dict()["action_id"], request.action_id)

    async def test_policy_controls_actual_bytes_and_requires_verification(self):
        request = await self.request(path="limited.txt", text="你好")
        too_small = replace(request, policy={"max_read_bytes": 10, "max_write_bytes": 5})
        self.assertEqual((await self.registry.execute(too_small)).status, "failure")
        self.assertFalse((self.root / "limited.txt").exists())
        for policy in ({"max_read_bytes": 5}, {"verify_after_write": False}, {"encoding": "latin-1"},
                       {"max_write_bytes": True}, {"max_read_bytes": 1048577}):
            with self.subTest(policy=policy):
                self.assertEqual((await self.registry.execute(replace(request, policy=policy))).status, "failure")
        allowed = replace(request, policy={"max_read_bytes": 6, "max_write_bytes": 6,
                                           "verify_after_write": True, "encoding": "utf-8"})
        self.assertEqual((await self.registry.execute(allowed)).status, "success")
        read = await self.request("read_text", path="limited.txt")
        self.assertEqual((await self.registry.execute(replace(read, policy={"max_read_bytes": 5}))).status, "failure")

    async def test_scope_paths_links_and_pre_cancel_never_write(self):
        for path in ("../outside.txt", "nested/file.txt", "C:\\outside.txt", "D:relative.txt", "/outside.txt", "NUL.txt", "trailing."):
            result = await self.registry.execute(await self.request(path=path, text="forbidden"))
            self.assertEqual(result.status, "failure")
        request = await self.request(path="note.txt", text="forbidden")
        self.assertEqual((await self.registry.execute(replace(request, scope=str(self.root.parent)))).status, "failure")
        cancelled = asyncio.Event()
        cancelled.set()
        self.assertEqual((await self.registry.execute(request, cancelled)).status, "cancelled")
        self.assertFalse(list(self.root.iterdir()))
        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside) / "other.txt"
            other.write_text("keep", encoding="utf-8")
            link = self.root / "linked.txt"
            try:
                link.symlink_to(other)
            except OSError:
                return  # Windows without symlink privilege: other cases still ran.
            self.assertEqual((await self.registry.execute(await self.request(path="linked.txt", text="forbidden"))).status, "failure")
            self.assertEqual(other.read_text(encoding="utf-8"), "keep")

    async def test_observation_state_version_age_and_deadline_revalidated(self):
        request = await self.request(path="note.txt", text="no")
        (self.root / "changed.txt").write_text("changed", encoding="utf-8")
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        request = await self.request(path="note.txt", text="no")
        self.assertEqual((await self.registry.execute(replace(request, deadline=time.monotonic() - 1))).status, "failure")
        observation = self.registry._observations[request.observation_id]
        self.registry._observations[request.observation_id] = replace(observation, monotonic_time=time.monotonic() - 60)
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        self.registry._observations[request.observation_id] = replace(observation, adapter_version="old")
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        self.assertFalse((self.root / "note.txt").exists())

    async def test_stop_latches_until_explicit_resume_and_new_observation(self):
        request = await self.request(path="note.txt", text="no")
        await self.registry.stop()
        self.assertEqual((await self.registry.execute(request)).status, "cancelled")
        self.registry.resume()
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        self.assertEqual((await self.registry.execute(await self.request(path="note.txt", text="yes"))).status, "success")


class FakeDesktop:
    def __init__(self):
        self.window = "test-window"
        self.size = (800, 600)
        self.dpi = (1.0, 1.0)
        self.pressed = set()
        self.sent = []
        self.released = []
        self.verified = None

    async def observe(self):
        return {"window_id": self.window, "width": self.size[0], "height": self.size[1],
                "dpi": self.dpi, "revision": "scene-1"}

    async def current_window(self):
        return self.window

    async def send(self, operation, arguments):
        self.sent.append((operation, arguments))
        if operation == "key_down":
            self.pressed.add(arguments["key"])

    async def verify(self, request):
        return self.verified

    async def release_key(self, key):
        self.released.append(key)
        self.pressed.discard(key)


class DesktopBodyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = FakeDesktop()
        self.adapter = DesktopAdapter(driver=self.driver, allowed_window="test-window")
        self.registry = BodyRegistry(stop_timeout=0.1)
        self.registry.register(self.adapter)
        self.addAsyncCleanup(self.registry.stop)

    async def request(self, operation="click", **arguments):
        observation = await self.registry.observe("desktop")
        return ActionRequest("desktop", operation, observation.observation_id, "test-window",
                             time.monotonic() + 5, arguments, expected_window="test-window")

    async def test_send_is_unknown_until_postcondition_is_verified(self):
        result = await self.registry.execute(await self.request(x=20, y=30))
        self.assertEqual(result.status, "unknown")
        self.driver.verified = True
        self.assertEqual((await self.registry.execute(await self.request(x=20, y=30))).status, "success")
        self.driver.verified = False
        self.assertEqual((await self.registry.execute(await self.request(x=20, y=30))).status, "failure")

    async def test_geometry_and_focus_changes_reject_before_dispatch(self):
        request = await self.request(x=20, y=30)
        self.driver.dpi = (1.5, 1.5)
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        request = await self.request(x=20, y=30)
        self.driver.window = "other-window"
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        self.assertFalse(self.driver.sent)

    async def test_emergency_stop_and_focus_watchdog_release_held_keys(self):
        await self.registry.execute(await self.request("key_down", key="W", lease_seconds=0.8))
        self.assertEqual(self.driver.pressed, {"W"})
        await self.registry.stop()
        self.assertFalse(self.driver.pressed)
        self.registry.resume()
        await self.registry.execute(await self.request("key_down", key="A", lease_seconds=0.8))
        self.driver.window = "other-window"
        for _ in range(20):
            if not self.driver.pressed:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(self.driver.pressed)

    async def test_missing_desktop_driver_is_explicitly_unavailable(self):
        adapter = DesktopAdapter(allowed_window="test-window")
        self.assertFalse(adapter.capability.available)
        self.assertFalse((await adapter.health())["available"])
        with self.assertRaises(RuntimeError):
            await adapter.observe()

    async def test_failed_key_release_blocks_more_input_and_can_be_retried(self):
        await self.registry.execute(await self.request("key_down", key="W", lease_seconds=0.8))
        release = self.driver.release_key

        async def failed_release(key):
            raise OSError("transport disconnected")

        self.driver.release_key = failed_release
        report = await self.registry.stop()
        self.assertEqual(report["desktop"]["result"]["status"], "unknown")
        self.assertFalse((await self.adapter.health())["available"])
        self.assertEqual(self.driver.pressed, {"W"})
        self.driver.release_key = release
        await self.registry.stop()
        self.assertTrue((await self.adapter.health())["available"])
        self.assertFalse(self.driver.pressed)

    async def test_cancel_inflight_adapter_calls_stop_and_never_infers_success(self):
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def blocking_send(operation, arguments):
            started.set()
            await asyncio.Event().wait()

        original_stop = self.adapter.stop

        async def recording_stop():
            stopped.set()
            return await original_stop()

        self.driver.send = blocking_send
        self.adapter.stop = recording_stop
        token = asyncio.Event()
        pending = asyncio.create_task(self.registry.execute(await self.request(x=1, y=1), token))
        await asyncio.wait_for(started.wait(), 1)
        token.set()
        receipt = await asyncio.wait_for(pending, 1)
        self.assertTrue(stopped.is_set())
        self.assertEqual(receipt.status, "unknown")

    async def test_uncooperative_action_is_quarantined_until_cleanup_finishes(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_send(operation, arguments):
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue

        self.driver.send = delayed_send
        request = await self.request(x=1, y=1)
        token = asyncio.Event()
        pending = asyncio.create_task(self.registry.execute(request, token))
        await started.wait()
        token.set()
        try:
            receipt = await asyncio.wait_for(pending, 1)
            self.assertEqual(receipt.status, "unknown")
            self.assertFalse((await self.registry.health())["adapters"]["desktop"]["available"])
            with self.assertRaises(RuntimeError):
                self.registry.resume()
        finally:
            release.set()
            await asyncio.gather(*self.registry._unsettled.values(), return_exceptions=True)
        self.registry.resume()
        self.assertTrue((await self.registry.health())["adapters"]["desktop"]["available"])


if __name__ == "__main__":
    unittest.main()
