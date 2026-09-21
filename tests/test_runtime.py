"""Foundation lifecycle tests with real persistence and no model or network."""

import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from xiyin_runtime.authorization import AuthorizationError
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig, ProviderError
from xiyin_runtime.runtime import FoundationRuntime, RuntimeBusy


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class FakeProvider:
    """Intentionally ignore cancellation, so the runtime must fence late text."""

    def __init__(self, chunks=("收到。",), *, block_before=None):
        self.chunks = chunks
        self.block_before = block_before
        self.calls = []
        self.tokens = []
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.closed_count = 0

    async def stream(self, messages, cancel):
        self.calls.append(deepcopy(messages))
        self.tokens.append(cancel)
        try:
            for index, chunk in enumerate(self.chunks):
                if index == self.block_before:
                    self.waiting.set()
                    await self.release.wait()
                if isinstance(chunk, Exception):
                    raise chunk
                yield chunk
        finally:
            self.closed_count += 1
            self.closed.set()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "experience.sqlite3"
        self.store = ExperienceStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.settings = Settings(
            ProviderConfig("http://localhost:8080/v1", "xiyin"),
            SEED,
            max_context_chars=20000,
            history_messages=12,
        )

    def runtime(self, provider=None):
        return FoundationRuntime(
            self.settings, self.store, provider=provider or FakeProvider(),
            authorize=lambda: None,
        )

    async def collect(self, runtime, text="你好", **kwargs):
        return [event async for event in runtime.stream_turn(text, **kwargs)]

    def assistant_events(self, session_id="owner", scope="private"):
        return [event for event in self.store.list_events(session_id, scope=scope)
                if event["kind"] == "assistant"]

    async def test_completed_turn_survives_restart_and_enters_next_context(self):
        first = self.runtime(FakeProvider(("今天", "一起看星星。")))
        events = await self.collect(first, "今晚做什么？", session_id="evening")
        self.assertEqual([event.type for event in events],
                         ["start", "text_delta", "complete"])
        self.assertEqual(len({event.request_id for event in events}), 1)
        first.close()

        self.store = ExperienceStore(self.path)
        provider = FakeProvider(("带上外套。",))
        second = self.runtime(provider)
        await self.collect(second, "还要准备什么？", session_id="evening")
        self.assertEqual(provider.calls[0][1:], [
            {"role": "user", "content": "今晚做什么？"},
            {"role": "assistant", "content": "今天一起看星星。"},
            {"role": "user", "content": "还要准备什么？"},
        ])
        replies = self.assistant_events("evening")
        self.assertEqual([reply["status"] for reply in replies],
                         ["completed", "completed"])
        self.assertTrue(all(reply["origin"] == "generated" for reply in replies))

    async def test_cancel_fences_late_provider_text_and_records_only_partial(self):
        provider = FakeProvider(("已经输出。", "迟到内容不得出现"))
        runtime = self.runtime(provider)
        stream = runtime.stream_turn("开始")
        start = await anext(stream)
        first = await anext(stream)
        self.assertEqual(first.text, "已经输出。")
        self.assertFalse(runtime.cancel("another-request"))
        self.assertTrue(runtime.cancel(start.request_id))
        rest = [event async for event in stream]
        self.assertEqual([event.type for event in rest], ["cancelled"])
        self.assertTrue(provider.closed.is_set())
        replies = self.assistant_events()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "cancelled")
        self.assertEqual(replies[0]["content"], "已经输出。")
        self.assertEqual(replies[0]["request_id"], start.request_id)
        self.assertFalse(any(row["role"] == "assistant"
                             for row in self.store.history("owner")))
        self.assertFalse(runtime.cancel())

    async def test_consumer_aclose_records_partial_and_releases_provider(self):
        provider = FakeProvider(("可见前缀。", "后续内容"))
        runtime = self.runtime(provider)
        stream = runtime.stream_turn("开始")
        await anext(stream)
        self.assertEqual((await anext(stream)).text, "可见前缀。")
        await stream.aclose()

        self.assertTrue(provider.closed.is_set(), "aclose must release the provider immediately")
        self.assertTrue(provider.tokens[0].is_set())
        self.assertEqual(provider.closed_count, 1)
        replies = self.assistant_events()
        self.assertEqual(len(replies), 1)
        self.assertIn(replies[0]["status"], {"partial", "cancelled"})
        self.assertEqual(replies[0]["content"], "可见前缀。")
        self.assertFalse(any(row["role"] == "assistant"
                             for row in self.store.history("owner")))
        resumed = await self.collect(runtime, "继续下一轮")
        self.assertEqual(resumed[-1].type, "complete")
        self.assertEqual(provider.closed_count, 2)

    async def test_provider_error_is_failed_evidence_and_not_successful_history(self):
        provider = FakeProvider(("不完整", ProviderError("fixture disconnect")))
        runtime = self.runtime(provider)
        events = await self.collect(runtime)
        self.assertEqual([event.type for event in events], ["start", "text_delta", "error"])
        self.assertEqual("ProviderError: local model request failed", events[-1].detail)
        self.assertNotIn("fixture disconnect", events[-1].detail)
        self.assertTrue(provider.closed.is_set())
        replies = self.assistant_events()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "failed")
        self.assertEqual(replies[0]["content"], "不完整")
        self.assertFalse(any(row["role"] == "assistant"
                             for row in self.store.history("owner")))
        provider.chunks = ("恢复后的完整回答",)
        self.assertEqual((await self.collect(runtime, "重试"))[-1].type, "complete")

    async def test_close_during_turn_preserves_store_until_cancellation_is_saved(self):
        runtime = self.runtime(FakeProvider(("已经输出。", "未输出")))
        stream = runtime.stream_turn("开始")
        await anext(stream)
        await anext(stream)
        with self.assertRaisesRegex(RuntimeBusy, "cancellation requested"):
            runtime.close()
        await stream.aclose()
        replies = self.assistant_events()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["status"], "cancelled")
        self.assertEqual(replies[0]["content"], "已经输出。")
        runtime.close()

    async def test_empty_provider_output_is_not_a_completed_turn(self):
        runtime = self.runtime(FakeProvider((" ",)))
        events = await self.collect(runtime)
        self.assertEqual(events[-1].type, "error")
        self.assertEqual(self.assistant_events()[0]["status"], "failed")

    async def test_history_is_separated_by_scope_and_session(self):
        provider = FakeProvider(("PRIVATE_REPLY_MARKER",))
        runtime = self.runtime(provider)
        await self.collect(runtime, "PRIVATE_INPUT_MARKER", session_id="first")
        provider.chunks = ("PUBLIC_REPLY_MARKER",)
        await self.collect(runtime, "PUBLIC_INPUT_MARKER", session_id="first", scope="public")
        public_context = str(provider.calls[-1])
        self.assertNotIn("PRIVATE_INPUT_MARKER", public_context)
        self.assertNotIn("PRIVATE_REPLY_MARKER", public_context)

        provider.chunks = ("新会话回答",)
        await self.collect(runtime, "新的话题", session_id="second")
        second_context = str(provider.calls[-1])
        for marker in ("PRIVATE_INPUT_MARKER", "PRIVATE_REPLY_MARKER",
                       "PUBLIC_INPUT_MARKER", "PUBLIC_REPLY_MARKER"):
            self.assertNotIn(marker, second_context)

        await self.collect(runtime, "继续", session_id="first")
        resumed_context = str(provider.calls[-1])
        self.assertIn("PRIVATE_INPUT_MARKER", resumed_context)
        self.assertIn("PRIVATE_REPLY_MARKER", resumed_context)
        self.assertNotIn("PUBLIC_INPUT_MARKER", resumed_context)
        self.assertNotIn("PUBLIC_REPLY_MARKER", resumed_context)

    async def test_owner_memory_crosses_private_sessions_but_not_public_scope(self):
        provider = FakeProvider()
        runtime = self.runtime(provider)
        memory_id = runtime.remember("紫色星图是我保存的纪念品", session_id="old")
        await self.collect(runtime, "紫色星图", session_id="new")
        self.assertNotIn(memory_id, str(provider.calls[-1]))
        self.assertIn("紫色星图是我保存的纪念品", str(provider.calls[-1]))
        self.assertEqual([m["role"] for m in provider.calls[-1]], ["system", "user"])

        await self.collect(runtime, "紫色星图", session_id="new", scope="public")
        self.assertNotIn(memory_id, str(provider.calls[-1]))
        self.assertNotIn("紫色星图是我保存的纪念品", str(provider.calls[-1]))

    async def test_bad_memory_replacement_keeps_previous_active_memory(self):
        runtime = self.runtime()
        memory_id = runtime.remember("我喜欢乌龙茶", kind="preference")
        original = self.store.memories()
        with self.assertRaises(ValueError):
            runtime.remember("错误更正", kind="preference", supersedes="missing")
        self.assertEqual(self.store.memories(), original)
        with self.assertRaises(ValueError):
            runtime.remember("跨作用域更正", kind="preference", scope="public", supersedes=memory_id)
        self.assertEqual(self.store.memories(), original)
        self.assertEqual(self.store.memories(scope="public"), [])

    async def test_concurrent_turn_is_rejected_without_cancelling_active_turn(self):
        provider = FakeProvider(("第一轮回答",), block_before=0)
        runtime = self.runtime(provider)
        first = asyncio.create_task(self.collect(runtime, "第一轮"))
        try:
            await asyncio.wait_for(provider.waiting.wait(), timeout=1)
            with self.assertRaises(RuntimeBusy):
                await self.collect(runtime, "第二轮")
            self.assertFalse(provider.tokens[0].is_set())
            self.assertEqual([row["content"] for row in self.store.list_events("owner")], ["第一轮"])
            provider.release.set()
            events = await asyncio.wait_for(first, timeout=1)
            self.assertEqual(events[-1].type, "complete")
            self.assertEqual(self.assistant_events()[0]["content"], "第一轮回答")
            self.assertEqual(len(provider.calls), 1)
        finally:
            provider.release.set()
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)

    async def test_default_authorization_failure_writes_no_events(self):
        provider = FakeProvider()
        runtime = FoundationRuntime(self.settings, self.store, provider=provider)
        # Exercise the actual default function without relying on the test host OS.
        with patch("xiyin_runtime.authorization.os", SimpleNamespace(name="posix")):
            with self.assertRaises(AuthorizationError):
                await self.collect(runtime)
            with self.assertRaises(AuthorizationError):
                runtime.remember("不得保存")
        self.assertEqual(self.store.list_events("owner"), [])
        self.assertEqual(self.store.memories(), [])
        self.assertEqual(provider.calls, [])

    def test_production_open_is_exclusive_and_close_releases_data_root(self):
        (self.path.parent / ".xiyin_data").write_text("xiyin-data-root v1\nid=lease-test\n", encoding="utf-8")
        with (
            patch("xiyin_runtime.runtime.xiyin_paths.data_root_id", return_value="lease-test"),
            patch("xiyin_runtime.runtime.authorize_runtime", return_value=None),
            patch("xiyin_runtime.runtime.load_settings", return_value=self.settings),
            patch("xiyin_runtime.runtime.xiyin_paths.data_root", return_value=self.path.parent),
            patch("xiyin_runtime.runtime.shutil.disk_usage",
                  return_value=SimpleNamespace(free=1024 * 1024 * 1024)),
        ):
            first = FoundationRuntime.open()
            try:
                with self.assertRaisesRegex(RuntimeError, "Another XIYIN runtime"):
                    FoundationRuntime.open()
            finally:
                first.close()
            reopened = FoundationRuntime.open()
            reopened.close()
            # Closing twice must not unlock a later owner's lease.
            next_owner = FoundationRuntime.open()
            try:
                first.close()
                with self.assertRaisesRegex(RuntimeError, "Another XIYIN runtime"):
                    FoundationRuntime.open()
            finally:
                next_owner.close()


if __name__ == "__main__":
    unittest.main()
