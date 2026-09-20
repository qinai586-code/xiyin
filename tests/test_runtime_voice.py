"""Runtime↔ASR↔TTS↔playback wiring with labeled synthetic transports, no model."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from tests.test_body_speech import ASR, Sink, TTS, pcm
from tests.test_runtime import FakeProvider
from xiyin_runtime.body import SpeechController
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime

SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class RuntimeVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = FakeProvider(("这是合成测试。", "不是真实模型。"))
        self.runtime = XIYINRuntime(Settings(ProviderConfig("http://localhost:8080/v1", "xiyin"), SEED),
                                    ExperienceStore(Path(self.temp.name) / "experience.sqlite3"),
                                    provider=self.provider, authorize=lambda: None)
        self.addAsyncCleanup(self.runtime.shutdown)

    async def test_actual_runtime_text_reaches_speech_and_playback_receipts_reach_ledger(self):
        sink, tts = Sink(observed=True), TTS()
        voice = self.runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
        events = await voice.feed_audio(pcm())
        self.assertEqual(events[0]["kind"], "final_transcript")
        result = await voice._turn
        await voice.controller.drain()
        self.assertEqual(result["generation_status"], "complete")
        self.assertEqual(result["text"], "这是合成测试。不是真实模型。")
        self.assertEqual(len(self.provider.calls), 1)
        records = self.runtime.store.list_events("owner")
        delivered = [item for item in records if item["kind"] == "delivery_receipt"]
        self.assertTrue(delivered)
        self.assertIn("output_observed", str(delivered))
        self.assertFalse(any("heard" in str(item) for item in delivered))
        self.assertEqual([e["content"] for e in records if e["kind"] == "user"], ["用户说话"])

    async def test_confirmed_interrupt_cancels_same_runtime_generation_and_tts_playback(self):
        sink, tts = Sink(blocking=True), TTS(blocking=True)
        voice = self.runtime.attach_speech(SpeechController(asr=ASR(), tts=tts, sink=sink))
        turn = await voice.start_turn("合成输入")
        await asyncio.wait_for(sink.started.wait(), 1)
        await voice.controller.candidate_interrupt()
        self.assertFalse(self.provider.tokens[0].is_set())
        await voice.controller.confirm_interrupt()
        result = await asyncio.wait_for(turn, 1)
        self.assertEqual(result["generation_status"], "cancelled")
        self.assertNotIn("不是真实模型", result["text"])
        self.assertTrue(self.provider.tokens[0].is_set())
        self.assertTrue(self.provider.closed.is_set())
        self.assertIn(("stop",), sink.calls)
        self.assertIn(("purge",), sink.calls)
        self.assertEqual(voice.controller.queued_chunks, 0)
        self.assertTrue(any(row["kind"] == "assistant" and row["status"] == "cancelled"
                            for row in self.runtime.store.list_events("owner")))
