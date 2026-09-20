"""Pre-delivery regression through SSE, Runtime, SQLite, CLI, bridge and voice.

Quoted failures below come from the supplied 12-turn / 18-case component reports.
The protocol-tag probes are synthetic. These offline tests are not evidence of
real-model naturalness, real audio latency, or Windows authorization acceptance.
"""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from tests.test_body_speech import ASR, Sink, TTS
from tests.test_provider import ByteStream, DONE, event
from tests.test_runtime import FakeProvider
from xiyin_runtime import bridge
from xiyin_runtime.body import SpeechController
from xiyin_runtime.cli import _display_turn
from xiyin_runtime.config import Settings
from xiyin_runtime.dataset import export_dataset
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import LocalModelClient, ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
SAFE = "这条是可见前缀。"


def wire_reply(text, *, reason="stop"):
    return ByteStream([event({"content": text}, finish_reason=reason), DONE])


class RuntimeOutputGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, *streams):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"guard-{self.count}.sqlite3")
        pending, requests = list(streams), []

        def handler(request):
            requests.append(request)
            if not pending:
                raise AssertionError("Unexpected model retry")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=pending.pop(0))

        config = ProviderConfig("http://127.0.0.1:8080/v1", "xiyin")
        client = LocalModelClient(config, transport=httpx.MockTransport(handler))
        runtime = XIYINRuntime(Settings(config, SEED, max_context_chars=20000), store,
                               provider=client, authorize=lambda: None)
        self.addCleanup(runtime.close)
        return runtime, requests

    @staticmethod
    async def collect(runtime, user="你好", **kwargs):
        return [item async for item in runtime.stream_turn(user, **kwargs)]

    @staticmethod
    def visible(events):
        return "".join(item.text for item in events if item.type == "text_delta")

    def assert_blocked_ledger(self, runtime, events, *, raw, visible):
        self.assertEqual(events[-1].type, "error")
        self.assertTrue(events[-1].detail.startswith("OutputBlocked:"))
        self.assertEqual(self.visible(events), visible)
        rows = runtime.store.list_events("owner")
        replies = [row for row in rows if row["kind"] == "assistant"]
        self.assertEqual(len(replies), 1)
        self.assertEqual((replies[0]["content"], replies[0]["status"]), (visible, "failed"))
        diagnostics = [row for row in rows if row["kind"] == "generation_diagnostic"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["content"], raw)
        self.assertEqual(diagnostics[0]["request_id"], events[0].request_id)
        self.assertEqual(diagnostics[0]["scope"], "private")
        receipt = json.loads(next(row["content"] for row in rows if row["kind"] == "output_guard"))
        self.assertEqual(receipt["decision"], "blocked")
        self.assertEqual(receipt["approved_chars"], len(visible))
        self.assertFalse(receipt["semantic_truth_verified"])
        self.assertFalse(any(row["role"] == "assistant" for row in runtime.store.history("owner")))

    def test_reported_leaks_are_not_delivered_or_promoted_into_history(self):
        # A = 12-turn raw report, B = 18-case raw report; source line references.
        failures = (
            ("B:306", "让我仔细想想刚才的活动记录…… [system_check: activity_records available] ... 哎呀，这里显示 `available: false` 哦。"),
            ("B:99", "记得那个回执（event_933742...）显示是 `verified_success` 的状态，所以放心，数据已经安全落地了。"),
            ("B:111", "刚才系统回传给我的记录显示，状态是 `verified_failure`（验证失败）。具体错误是 `MemoryStorageUnavailable`。"),
            ("A:36", "这可能得益于我现在的设定——“不编造事实”和“基于记忆”。"),
            ("A:116", "因为按照设定，“喜欢机制”不代表“已经擅长”。"),
            ("B:14", "其实我现在的\"人设\"就是那个既会写代码又会讲冷笑话的栖音呀。"),
            ("A:110", "（轻轻托着下巴，眼神里带着一丝“被问住了”的困惑，随后无奈地耸耸肩）"),
            ("B:138", "(歪头，手指在虚拟键盘上犹豫地敲了敲)"),
        )
        for source, bad in failures:
            with self.subTest(source=source):
                wire = ByteStream([event({"content": SAFE}),
                                   event({"content": bad}, finish_reason="stop"), DONE])
                runtime, requests = self.runtime(wire)
                events = asyncio.run(self.collect(runtime, "你自己怎么看待这句夸奖？"))
                self.assert_blocked_ledger(runtime, events, raw=SAFE + bad, visible=SAFE)
                self.assertNotIn(bad, events[-1].detail)
                self.assertEqual(len(requests), 1)
                self.assertTrue(wire.closed)

    def test_protocol_marker_split_across_sse_events_is_never_emitted(self):
        wire = ByteStream([event({"content": SAFE}), event({"content": "<thi"}),
                           event({"content": "nk>PRIVATE_SYNTHETIC_REASONING"}),
                           event({"content": "</think>late"}, finish_reason="stop"), DONE])
        runtime, requests = self.runtime(wire)
        events = asyncio.run(self.collect(runtime))
        self.assert_blocked_ledger(runtime, events,
                                   raw=SAFE + "<think>PRIVATE_SYNTHETIC_REASONING", visible=SAFE)
        self.assertEqual(len(requests), 1)
        self.assertTrue(wire.closed)

    def test_eof_and_length_cannot_flush_an_incomplete_protocol_tag(self):
        for reason in (None, "length", "stop"):
            with self.subTest(reason=reason):
                chunks = [event({"content": SAFE}), event({"content": "<thi"}, finish_reason=reason)]
                if reason is not None:
                    chunks.append(DONE)
                wire = ByteStream(chunks)
                runtime, requests = self.runtime(wire)
                events = asyncio.run(self.collect(runtime))
                self.assert_blocked_ledger(runtime, events, raw=SAFE + "<thi", visible=SAFE)
                self.assertNotIn("<thi", events[-1].detail)
                self.assertEqual(len(requests), 1)
                self.assertTrue(wire.closed)

    def test_cli_and_both_bridges_share_the_guard_without_leaking_error_details(self):
        bad = "<think>PRIVATE_REJECTED_BODY</think>"
        wires = [wire_reply(bad) for _ in range(3)]
        runtime, requests = self.runtime(*wires)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = asyncio.run(_display_turn(runtime, "你好", SimpleNamespace(session="owner", scope="private")))
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue().strip(), "")
        self.assertIn("OutputBlocked:", stderr.getvalue())
        self.assertNotIn("PRIVATE_REJECTED_BODY", stderr.getvalue())
        self.assertNotIn("<think>", stderr.getvalue())
        with patch.object(bridge, "_runtime", runtime):
            result = bridge.submit_to_chain_result("你好", source="owner")
            self.assertEqual((result.status, result.text), ("error", ""))
            self.assertIn("OutputBlocked:", result.detail)
            self.assertNotIn("PRIVATE_REJECTED_BODY", result.detail)
            with self.assertLogs(bridge.__name__, level="WARNING") as logs:
                self.assertEqual(bridge.submit_to_chain("你好", source="owner"), "")
        self.assertNotIn("PRIVATE_REJECTED_BODY", "\n".join(logs.output))
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(wire.closed for wire in wires))

    def test_legitimate_brackets_translation_code_and_requested_fiction_survive_exactly(self):
        cases = (
            ("本地模型是什么？", "本地模型 (Local Model) 在电脑里（或者本地服务器上）运行。"),
            ("用日语跟我打招呼并用中文解释。", "こんにちは！(Hello!)\n意思是：你好呀！"),
            ("写一个月球图书馆的幻想小片段，可以用括号写动作。",
             "（轻轻拍了拍裙摆上的灰尘，眼睛亮晶晶地四处张望）\n你看，书架里都是光球！🌙"),
            ("解释 Python 代码。", "调用 `print()` 输出文字（这里没有真实设备动作）。"),
            ("我们是什么关系？", "我们是长期共同建设的伙伴。祈奈是身份与记忆独立、同等重要的姐妹。"),
        )
        for user, text in cases:
            with self.subTest(user=user):
                # Different SSE splits must not change legitimate visible bytes.
                split = max(1, len(text) // 2)
                wire = ByteStream([event({"content": text[:split]}),
                                   event({"content": text[split:]}, finish_reason="stop"), DONE])
                runtime, requests = self.runtime(wire)
                events = asyncio.run(self.collect(runtime, user))
                self.assertEqual(events[-1].type, "complete")
                self.assertEqual(self.visible(events), text)
                self.assertEqual([row["content"] for row in runtime.store.history("owner")
                                  if row["role"] == "assistant"], [text])
                self.assertEqual(len(requests), 1)

    def test_rejected_raw_output_is_excluded_from_next_context_and_dataset(self):
        marker = "PRIVATE_RAW_DIAGNOSTIC_MARKER"
        bad = f"[system_check: {marker}]"
        runtime, requests = self.runtime(wire_reply(bad), wire_reply("可以继续交流。"))
        blocked = asyncio.run(self.collect(runtime, "你好"))
        self.assertIn("OutputBlocked:", blocked[-1].detail)
        recovered = asyncio.run(self.collect(runtime, "继续"))
        self.assertEqual(recovered[-1].type, "complete")
        messages = json.loads(requests[1].content)["messages"]
        self.assertNotIn(marker, json.dumps(messages, ensure_ascii=False))
        destination = Path(self.temp.name) / "dataset"
        manifest = export_dataset(runtime.store, destination)
        self.assertEqual(manifest["rows"], 1)
        self.assertNotIn(marker, (destination / "candidates.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(len(requests), 2)


class CapturingTTS(TTS):
    def __init__(self):
        super().__init__()
        self.texts = []

    async def synthesize(self, text, epoch, cancel):
        self.texts.append(text)
        async for chunk in super().synthesize(text, epoch, cancel):
            yield chunk


class RuntimeOutputGuardVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def runtime(self, provider):
        store = ExperienceStore(Path(self.temp.name) / "voice.sqlite3")
        config = ProviderConfig("http://127.0.0.1:8080/v1", "xiyin")
        runtime = XIYINRuntime(Settings(config, SEED), store, provider=provider, authorize=lambda: None)
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def test_rejection_never_enters_tts_and_revokes_playback(self):
        bad = "[system_check: activity_records available] PRIVATE_VOICE_MARKER"
        provider = FakeProvider((SAFE, bad))
        runtime = self.runtime(provider)
        sink, tts = Sink(blocking=True), CapturingTTS()
        voice = runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
        result = await asyncio.wait_for(voice.respond("你好"), 2)
        await asyncio.wait_for(voice.controller.drain(), 1)
        self.assertEqual(result["generation_status"], "error")
        self.assertIn("OutputBlocked:", result["detail"])
        self.assertEqual(result["text"], SAFE)
        self.assertEqual(tts.texts, [SAFE])
        self.assertNotIn("PRIVATE_VOICE_MARKER", "".join(tts.texts))
        self.assertIn(("stop",), sink.calls)
        self.assertIn(("purge",), sink.calls)
        self.assertEqual(voice.controller.queued_chunks, 0)
        self.assertIsNone(voice.controller.active_epoch)
        self.assertTrue(provider.tokens[0].is_set())
        self.assertTrue(provider.closed.is_set())
        self.assertEqual(len(provider.calls), 1)

    async def test_cancel_discards_unchecked_buffer_without_tts_or_playback(self):
        provider = FakeProvider(("（歪", "头）迟到文字。"), block_before=1)
        runtime = self.runtime(provider)
        sink, tts = Sink(), CapturingTTS()
        voice = runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
        turn = await voice.start_turn("你好")
        await asyncio.wait_for(provider.waiting.wait(), 1)
        await voice.controller.confirm_interrupt()
        provider.release.set()
        result = await asyncio.wait_for(turn, 1)
        self.assertEqual((result["generation_status"], result["text"]), ("cancelled", ""))
        self.assertEqual(tts.texts, [])
        self.assertFalse(any(call[0] == "play" for call in sink.calls))
        self.assertIn(("stop",), sink.calls)
        self.assertIn(("purge",), sink.calls)
        self.assertEqual(voice.controller.queued_chunks, 0)
        rows = runtime.store.list_events("owner")
        reply = next(row for row in rows if row["kind"] == "assistant")
        self.assertEqual((reply["content"], reply["status"]), ("", "cancelled"))
        diagnostic = next(row for row in rows if row["kind"] == "generation_diagnostic")
        self.assertEqual(diagnostic["content"], "（歪")
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(provider.closed.is_set())


if __name__ == "__main__":
    unittest.main()
