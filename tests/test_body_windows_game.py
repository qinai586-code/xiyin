"""No device access: exercise the Win32 boundary and typed game result contract."""
import asyncio
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from xiyin_runtime.body import (
    ActionRequest, BodyRegistry, GameActionSpec, TypedGameAdapter,
    Win32DesktopDriver, win32_desktop_adapter,
)


class FakeWinAPI:
    def __init__(self):
        self.hwnd = self.foreground_hwnd = 123
        self.pressed = set()
        self.calls = []
        self.title = "test application"

    def is_window(self, hwnd):
        return hwnd == self.hwnd

    def foreground(self):
        return self.foreground_hwnd

    def window_details(self, hwnd):
        if not self.is_window(hwnd):
            raise ValueError("missing HWND")
        return {"width": 800, "height": 600, "x": 30, "y": 40, "dpi": 144,
                "title": self.title, "process_id": 42}

    def key_pressed(self, virtual_key):
        return virtual_key in self.pressed

    def key(self, virtual_key, *, up=False):
        self.calls.append(("key", virtual_key, up))
        if up:
            self.pressed.discard(virtual_key)
        else:
            self.pressed.add(virtual_key)

    def click(self, hwnd, x, y):
        self.calls.append(("click", hwnd, x, y))

    def capture_png(self, hwnd):
        raise ImportError("Pillow is not installed")


class WindowsDriverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = FakeWinAPI()
        self.adapter = win32_desktop_adapter(123, capture=True, api=self.api)
        self.registry = BodyRegistry()
        self.registry.register(self.adapter)
        self.addAsyncCleanup(self.registry.stop)

    async def action(self, operation="click", **arguments):
        observation = await self.registry.observe("desktop")
        return ActionRequest("desktop", operation, observation.observation_id, "hwnd:123",
                             time.monotonic() + 5, arguments, expected_window="hwnd:123")

    async def test_window_geometry_dpi_and_missing_optional_capture_are_honest(self):
        observation = await self.registry.observe("desktop")
        self.assertEqual((observation.width, observation.height, observation.dpi), (800, 600, (1.5, 1.5)))
        self.assertFalse(observation.payload["screenshot"]["available"])
        self.assertEqual(observation.payload["coordinate_space"], "client_physical_pixels")
        self.assertFalse(self.api.calls)

    async def test_only_scoped_input_and_requested_observable_postcondition_can_succeed(self):
        result = await self.registry.execute(await self.action(x=20, y=30))
        self.assertEqual(result.status, "unknown")
        result = await self.registry.execute(await self.action(x=20, y=30,
                            postcondition={"kind": "window_title_equals", "value": "test application"}))
        self.assertEqual(result.status, "success")
        calls = len(self.api.calls)
        self.assertNotEqual((await self.registry.execute(await self.action(x=800, y=30))).status, "success")
        self.assertEqual(len(self.api.calls), calls)
        request = await self.action(x=20, y=30)
        self.api.foreground_hwnd = 999
        self.assertEqual((await self.registry.execute(request)).status, "failure")
        self.assertEqual(len(self.api.calls), calls)

    async def test_real_key_driver_contract_releases_owned_keys_and_not_existing_human_keys(self):
        await self.registry.execute(await self.action("key_down", key="W", lease_seconds=0.8))
        self.assertIn(ord("W"), self.api.pressed)
        await self.registry.stop()
        self.assertNotIn(ord("W"), self.api.pressed)
        self.registry.resume()
        self.api.pressed.add(ord("A"))
        await self.registry.execute(await self.action("key_down", key="A", lease_seconds=0.8))
        self.assertIn(ord("A"), self.api.pressed)
        self.assertNotIn(("key", ord("A"), True), self.api.calls)
        result = await self.registry.execute(await self.action("key_down", key="WIN", lease_seconds=0.8))
        self.assertNotEqual(result.status, "success")

    async def test_non_windows_driver_does_not_load_win32_or_pretend_available(self):
        with patch("xiyin_runtime.body.windows.os.name", "posix"), \
                patch("xiyin_runtime.body.windows.CtypesWin32API", side_effect=AssertionError("device access")):
            driver = Win32DesktopDriver(123)
            self.assertFalse(driver.available)
            self.assertFalse((await driver.health())["available"])
            with self.assertRaises(RuntimeError):
                await driver.observe()


ACTION = GameActionSpec("open_door", "Open a named door as one semantic game action", {
    "type": "object", "properties": {"door": {"type": "string", "enum": ["north", "south"]}},
    "required": ["door"], "additionalProperties": False,
})


class GameTransport:
    connected = True

    def __init__(self):
        self.revision = "r1"
        self.last_action = None
        self.complete = False
        self.calls = []

    async def observe_state(self):
        return {"revision": self.revision, "data": {"door": "closed" if self.revision == "r1" else "open"},
                "last_action_id": self.last_action}

    async def request_action(self, message, *, expected_revision, cancel):
        self.calls.append((message, expected_revision))
        data = {"id": message["data"]["id"], "success": True}
        if self.complete:
            self.revision = "r2"
            self.last_action = message["data"]["id"]
            data.update(phase="completed", verified=True, state_revision=self.revision)
        return {"command": "action/result", "game": "test", "data": data}

    async def cancel_action(self, action_id):
        return True


class GameBodyTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, transport):
        adapter = TypedGameAdapter("test", [ACTION], transport=transport)
        registry = BodyRegistry()
        registry.register(adapter)
        observation = await registry.observe("game:test")
        request = ActionRequest("game:test", "open_door", observation.observation_id, "game:test",
                                 time.monotonic() + 5, {"state_revision": observation.revision,
                                                        "parameters": {"door": "north"}})
        return adapter, registry, request

    async def test_plain_sdk_acceptance_is_not_game_completion(self):
        adapter, registry, request = await self.make(GameTransport())
        receipt = await registry.execute(request)
        self.assertEqual(receipt.status, "unknown")
        self.assertTrue(receipt.evidence["accepted"])
        repeated = await registry.execute(request)
        self.assertEqual(repeated.status, "failure")
        self.assertEqual(len(adapter.transport.calls), 1)

    async def test_completed_result_must_match_observed_state_and_action_id(self):
        transport = GameTransport()
        transport.complete = True
        adapter, registry, request = await self.make(transport)
        receipt = await registry.execute(request)
        self.assertEqual(receipt.status, "success")
        self.assertTrue(receipt.verified)
        self.assertEqual(receipt.evidence["after_revision"], "r2")

    async def test_schema_revision_and_low_level_controls_are_rejected_before_game_dispatch(self):
        transport = GameTransport()
        adapter, registry, request = await self.make(transport)
        request.arguments["parameters"]["door"] = "unknown"
        self.assertEqual((await registry.execute(request)).status, "failure")
        self.assertFalse(transport.calls)
        request.arguments["parameters"]["door"] = "north"
        transport.revision = "new-state"
        self.assertEqual((await registry.execute(request)).status, "failure")
        with self.assertRaises(ValueError):
            GameActionSpec("press_frame", "input every frame", {"type": "object"}, control_level="frame")
        with self.assertRaises(ValueError):
            TypedGameAdapter("test", [ACTION], transport=transport, min_action_interval=0.016)

    async def test_no_game_connection_is_unavailable(self):
        adapter = TypedGameAdapter("test", [ACTION])
        self.assertFalse(adapter.capability.available)
        self.assertFalse((await adapter.health())["available"])
        with self.assertRaises(RuntimeError):
            await adapter.observe()


if __name__ == "__main__":
    unittest.main()
