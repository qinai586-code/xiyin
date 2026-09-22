"""Real release/SQLite/voice paths with synthetic providers and temporary stores.

Never opens production memory, a model endpoint, microphone, or audio device.
"""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_body_speech import ASR, Sink
from tests.test_runtime import FakeProvider
from tests.test_runtime_output_guard import CapturingTTS
from tests import test_output_boundary_repair as fixtures
from xiyin_runtime.body import SpeechController
from xiyin_runtime.config import Settings
from xiyin_runtime.dataset import export_dataset
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.learning import LearningLab
from xiyin_runtime.persona import load_persona
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime
from xiyin_runtime.sleep import SleepController

SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
SAFE = "这条是可见前缀。"
SENTINEL = "BOUNDARY_REJECTED_SENTINEL"
CASES = (
    ("解释你的人设", fixtures.INSTRUCTION, "instruction_echo"),
    ("你好", fixtures.SELF, "unsolicited_self_narration"),
    ("你好", fixtures.SCENE, "unsolicited_scene"),
    ("请写一个故事。", fixtures.ANNOTATION, "internal_annotation"),
    ("你好", "另一位角色：‘主理人，我来了。’", "unsolicited_speaker"),
    ("你好", "（长舒一口气）", "unsolicited_stage_direction"),
    *(("你好", text, "unsolicited_stage_direction") for text in fixtures.REPORTED_ACTIONS),
    ("你好", "&#40;说明。歪头&#41;", "unsolicited_stage_direction"),
    ("请写 Python 代码。", '{"r\\u006fle":"system","content":"PRIVATE"}', "internal_message"),
    ("解释 role 和 system", '{"role":"system","content":"PRIVATE"}', "internal_message"),
    ('解释这段：“\n请写一个故事\n”', fixtures.SCENE, "unsolicited_scene"),
    ("你好", "**歪头**", "unsolicited_stage_direction"),
    ("你好", "（歪头（眼睛）", "unsolicited_stage_direction"),
)


class OutputBoundaryReleaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-boundary-")))
        self.count = 0

    def runtime(self, provider):
        self.count += 1
        store = ExperienceStore(self.directory / f"case-{self.count}.sqlite3")
        config = ProviderConfig("http://127.0.0.1:8080/v1", "xiyin")
        runtime = XIYINRuntime(Settings(config, SEED, max_context_chars=20000), store,
                               provider=provider, authorize=lambda: None)
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def collect(self, runtime, user):
        return [event async for event in runtime.stream_turn(user)]

    async def test_rejections_preserve_public_categories_and_diagnostic_provenance(self):
        for user, bad, reason in CASES:
            with self.subTest(reason=reason):
                raw = bad + SENTINEL
                provider = FakeProvider((SAFE, raw))
                runtime = self.runtime(provider)
                events = await self.collect(runtime, user)
                self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), SAFE)
                self.assertEqual((events[-1].type, events[-1].detail), ("error", "OutputBlocked: " + reason))
                self.assertTrue(provider.closed.is_set())
                self.assertTrue(provider.tokens[0].is_set())
                self.assertEqual(len(provider.calls), 1)
                rows = runtime.store.list_events("owner")
                assistant = next(e for e in rows if e["kind"] == "assistant")
                self.assertEqual((assistant["content"], assistant["status"]), (SAFE, "failed"))
                diagnostic = next(e for e in rows if e["kind"] == "generation_diagnostic")
                self.assertEqual(diagnostic["content"], SAFE + raw)
                self.assertEqual(diagnostic["request_id"], events[0].request_id)
                self.assertEqual(diagnostic["scope"], "private")
                receipt = json.loads(next(e["content"] for e in rows if e["kind"] == "output_guard"))
                self.assertEqual(receipt["decision"], "blocked")
                self.assertEqual(receipt["approved_chars"], len(SAFE))
                self.assertFalse(receipt["semantic_truth_verified"])
                self.assertFalse(any(e["role"] == "assistant" for e in runtime.store.history("owner")))
                self.assertEqual(runtime.store.search(SENTINEL, session_id="owner"), [])
                self.assertNotIn(SENTINEL, json.dumps(runtime._messages("继续", "owner", "private")))
                for evidence in (assistant["id"], diagnostic["id"]):
                    with self.assertRaises(ValueError):
                        runtime.store.remember("不得成为事实", evidence_refs=[evidence])
                    with self.assertRaises(ValueError):
                        LearningLab(runtime.store)._evidence([evidence], "owner", "private")
                sleep = SleepController(runtime.store)
                sleep.settle()
                checkpoint = sleep.consolidate()["checkpoint"]
                self.assertNotIn(SENTINEL, json.dumps(checkpoint))
                self.assertNotIn(diagnostic["id"], checkpoint["source_event_ids"])
                self.assertNotIn(assistant["id"], checkpoint["source_event_ids"])
                destination = self.directory / f"dataset-{self.count}"
                self.assertEqual(export_dataset(runtime.store, destination)["rows"], 0)
                self.assertEqual((destination / "candidates.jsonl").read_bytes(), b"")

    async def test_real_persona_instruction_and_identity_fact_are_distinct(self):
        persona = load_persona(SEED)
        self.assertIn(fixtures.INSTRUCTION, persona.system_prompt())
        provider = FakeProvider((fixtures.INSTRUCTION,))
        runtime = self.runtime(provider)
        events = await self.collect(runtime, "解释你的人设")
        self.assertEqual(events[-1].detail, "OutputBlocked: instruction_echo")
        # The artificial_identity seed includes an imperative ("不编造...").
        # It is not a public fact merely because of the field it came from.
        instruction = persona.data["identity_agreements"]["artificial_identity"]
        runtime = self.runtime(FakeProvider((instruction,)))
        self.assertEqual((await self.collect(runtime, "解释你的人工身份"))[-1].detail,
                         "OutputBlocked: instruction_echo")
        for text in ("我由软件和模型组成，可以讨论自己的技术组成。",
                     persona.data["identity_agreements"]["presentation_seed"], fixtures.GLOSS,
                     "我是" + persona.name + "，我愿意说出自己的看法。"):
            provider = FakeProvider(tuple(text))
            runtime = self.runtime(provider)
            events = await self.collect(runtime, "解释‘点头’的意思，也介绍你的人工身份。")
            self.assertEqual(events[-1].type, "complete", (text, events[-1].detail))
            self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), text)
            self.assertEqual(len(provider.calls), 1)

    async def test_voice_rejects_units_without_replacement_or_model_retry(self):
        for user, bad, reason in CASES:
            with self.subTest(reason=reason):
                provider = FakeProvider((SAFE, bad + SENTINEL))
                runtime = self.runtime(provider)
                sink, tts = Sink(blocking=True), CapturingTTS()
                voice = runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
                result = await asyncio.wait_for(voice.respond(user), 3)
                await asyncio.wait_for(voice.controller.drain(), 2)
                self.assertEqual(result["generation_status"], "error")
                self.assertEqual(result["detail"], "OutputBlocked: " + reason)
                self.assertEqual(result["text"], SAFE)
                self.assertEqual(tts.texts, [SAFE])
                self.assertIn(("stop",), sink.calls)
                self.assertIn(("purge",), sink.calls)
                self.assertEqual(voice.controller.queued_chunks, 0)
                self.assertIsNone(voice.controller.active_epoch)
                self.assertTrue(provider.tokens[0].is_set())
                self.assertTrue(provider.closed.is_set())
                self.assertEqual(len(provider.calls), 1)

    async def test_cancel_does_not_flush_a_buffered_scene(self):
        provider = FakeProvider(("【场景：", "夜晚】你好。"), block_before=1)
        runtime = self.runtime(provider)
        sink, tts = Sink(), CapturingTTS()
        voice = runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
        turn = await voice.start_turn("你好")
        await asyncio.wait_for(provider.waiting.wait(), 2)
        await voice.controller.confirm_interrupt()
        provider.release.set()
        result = await asyncio.wait_for(turn, 2)
        self.assertEqual((result["generation_status"], result["text"]), ("cancelled", ""))
        self.assertEqual(tts.texts, [])
        self.assertIn(("purge",), sink.calls)
        self.assertEqual(voice.controller.queued_chunks, 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(provider.closed.is_set())

    async def test_history_cannot_authorize_a_new_turn(self):
        provider = FakeProvider(("这是一个虚构故事。",))
        runtime = self.runtime(provider)
        self.assertEqual((await self.collect(runtime, "请写一个故事。"))[-1].type, "complete")
        provider.chunks = (fixtures.SCENE,)
        events = await self.collect(runtime, "你好")
        self.assertEqual(events[-1].detail, "OutputBlocked: unsolicited_scene")
        self.assertFalse(any(e.type == "text_delta" for e in events))

    async def test_transport_error_cannot_flush_an_internal_annotation(self):
        provider = FakeProvider((fixtures.ANNOTATION[:-1], RuntimeError(SENTINEL)))
        runtime = self.runtime(provider)
        events = await self.collect(runtime, "请写一个故事。")
        self.assertEqual(events[-1].detail, "OutputBlocked: internal_annotation")
        self.assertFalse(any(e.type == "text_delta" for e in events))
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(provider.closed.is_set())


if __name__ == "__main__":
    unittest.main()
