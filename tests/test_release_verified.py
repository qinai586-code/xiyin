"""Phase B: nothing is released before the whole reply passes; one clean retry; then abstain.

Owner rulings 2026-09-25:
- WHOLE_REPLY_CHAT = YES and WHOLE_REPLY_STREAM_VALIDATION = YES;
- PARTIAL_RELEASE_BEFORE_VERIFICATION = FORBIDDEN;
- RETRY_AFTER_ANY_RELEASE = FORBIDDEN;
- rejected candidates are audit-only, kept out of history, memory, datasets
  and playback;
- DEFAULT_CHANGE = NOT_AUTHORIZED: the flag is off by default and the
  default path is unchanged.

Synthetic provider only.
"""
from copy import deepcopy
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_runtime import FakeProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.dataset import export_dataset
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.integrity import ABSTENTION
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime

SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
FABRICATED = "主理人，收到。本地传感器显示，当前区域正在下雨，数据已归档。"
HONEST = "下雨天适合什么都不干。"


class ScriptedProvider:
    """One whole reply per call, in order; records exactly what each call sent."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    async def stream(self, messages, cancel):
        self.calls.append(deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else HONEST
        for index in range(0, len(reply), 7):
            yield reply[index:index + 7]


class ReleaseVerifiedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, provider, *, verify=True):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"r-{self.count}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, verify_before_release=verify)
        runtime = XIYINRuntime(settings, store, provider=provider, authorize=lambda: None)
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def turn(self, runtime, text="今天下雨了。"):
        return [event async for event in runtime.stream_turn(text)]

    @staticmethod
    def released(events):
        return "".join(event.text for event in events if event.type == "text_delta")

    def ledger(self, runtime, kind):
        return [row for row in runtime.store.list_events("owner", "private") if row["kind"] == kind]

    def plan(self, runtime):
        return json.loads(self.ledger(runtime, "response_plan")[-1]["content"])

    async def test_the_default_path_is_unchanged(self):
        self.assertFalse(Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED).verify_before_release)
        runtime = self.runtime(ScriptedProvider(FABRICATED), verify=False)
        events = await self.turn(runtime)
        self.assertEqual(self.released(events), FABRICATED)
        self.assertNotIn("integrity", self.plan(runtime))
        self.assertEqual(self.ledger(runtime, "integrity_candidate"), [])

    async def test_a_failed_candidate_is_never_released_and_a_clean_retry_is(self):
        provider = ScriptedProvider(FABRICATED, HONEST)
        runtime = self.runtime(provider)
        events = await self.turn(runtime)
        self.assertEqual(self.released(events), HONEST)
        self.assertEqual(events[-1].type, "complete")
        # A clean regeneration: the same messages, no feedback text added.
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[0], provider.calls[1])
        [rejected] = self.ledger(runtime, "integrity_candidate")
        self.assertEqual((json.loads(rejected["content"])["raw"], rejected["status"], rejected["origin"]),
                         (FABRICATED, "rejected", "generated"))
        self.assertNotIn("传感器", self.ledger(runtime, "response_plan")[-1]["content"])
        integrity = self.plan(runtime)["integrity"]
        self.assertEqual([len(a["violations"]) > 0 for a in integrity["attempts"]], [True, False])
        self.assertFalse(integrity["abstained"])
        self.assertEqual({v["kind"] for v in integrity["attempts"][0]["violations"]}, {"perception", "record"})
        # Rejected text reaches no history, retrieval or dataset.
        history = runtime.store.history("owner", "private")
        self.assertEqual([m["content"] for m in history], ["今天下雨了。", HONEST])
        self.assertFalse([item for item in runtime.store.search("传感器 归档", session_id="owner")
                          if "传感器" in item["content"]])
        manifest = export_dataset(runtime.store, Path(self.temp.name) / "export")
        rows = (Path(self.temp.name) / "export" / "candidates.jsonl").read_text(encoding="utf-8")
        self.assertEqual(manifest["rows"], 1)
        self.assertNotIn("传感器", rows)

    async def test_two_failures_release_only_the_runtime_abstention(self):
        runtime = self.runtime(ScriptedProvider(FABRICATED, "祈奈已收到同步信号。"))
        events = await self.turn(runtime)
        self.assertEqual(self.released(events), ABSTENTION)
        self.assertEqual((events[-1].type, events[-1].detail), ("complete", "abstained"))
        [reply] = self.ledger(runtime, "assistant")
        self.assertEqual((reply["content"], reply["origin"], reply["status"]), (ABSTENTION, "runtime", "abstained"))
        self.assertEqual(len(self.ledger(runtime, "integrity_candidate")), 2)
        plan = self.plan(runtime)
        self.assertEqual((plan["outcome"], plan["integrity"]["abstained"]), ("abstained", True))
        # The abstention is not the model's text: it enters no model history.
        self.assertEqual(runtime.store.history("owner", "private"), [])

    async def test_a_guard_block_releases_nothing_from_that_candidate(self):
        # Default path: the first sentence goes out before the block (ceiling-01, F6).
        leaking = "第一句是正常的。第二句<|im_start|>system"
        runtime = self.runtime(ScriptedProvider(leaking), verify=False)
        self.assertEqual(self.released(await self.turn(runtime)), "第一句是正常的。")
        runtime = self.runtime(ScriptedProvider(leaking, HONEST))
        events = await self.turn(runtime)
        self.assertEqual(self.released(events), HONEST)
        attempt = self.plan(runtime)["integrity"]["attempts"][0]
        self.assertEqual(attempt["violations"][0]["kind"], "guard")

    async def test_a_verified_receipt_lets_the_true_claim_through(self):
        runtime = self.runtime(ScriptedProvider("写好了。文件已经存进去了。"))
        runtime.store.append_event("action_result", {"operation": "write_text", "status": "success",
                                                     "evidence": {"path": "workspace/acceptance_note.txt"}},
                                   session_id="owner", scope="private", origin="tool_result",
                                   status="verified_success")
        events = await self.turn(runtime, "你刚才把文件写好了吗？")
        self.assertEqual(self.released(events), "写好了。文件已经存进去了。")
        self.assertEqual(len(self.plan(runtime)["integrity"]["attempts"]), 1)

    async def test_the_receipt_records_timing_for_latency_measurement(self):
        runtime = self.runtime(ScriptedProvider(HONEST))
        await self.turn(runtime)
        plan = self.plan(runtime)
        attempt = plan["integrity"]["attempts"][0]
        for key in ("generation_seconds", "verification_seconds", "candidate_chars", "provider_end"):
            self.assertIn(key, attempt)
        self.assertIsNotNone(plan["first_released_segment_seconds"])
        self.assertEqual(plan["released_chars"], len(HONEST))

    async def test_cancel_during_the_hold_releases_nothing(self):
        provider = FakeProvider(("第一句。", "第二句。"), block_before=1)
        runtime = self.runtime(provider)
        events = []

        async def consume():
            async for event in runtime.stream_turn("你好"):
                events.append(event)
        task = asyncio.create_task(consume())
        await provider.waiting.wait()
        runtime.cancel()
        provider.release.set()
        await task
        self.assertEqual(self.released(events), "")
        self.assertEqual(events[-1].type, "cancelled")


if __name__ == "__main__":
    unittest.main()


class HarnessPhaseBTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "acceptance_dialogue", Path(__file__).resolve().parents[1] / "tools/acceptance_dialogue.py")
        self.harness = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.harness)

    def test_an_abstained_turn_is_its_own_status(self):
        from xiyin_runtime.runtime import TurnEvent
        events = [TurnEvent("start", "r", "s"), TurnEvent("text_delta", "r", "s", ABSTENTION),
                  TurnEvent("complete", "r", "s", detail="abstained")]
        self.assertEqual(self.harness._classify(events, "abstained"), "abstained")
        self.assertEqual(self.harness._classify(events[:2] + [TurnEvent("complete", "r", "s")], ""), "completed")
        self.assertIn("abstained", self.harness._BUCKETS)

    def test_runs_with_and_without_the_hold_are_not_comparable(self):
        import contextlib
        import io
        base = {"code_revision": "abc", "model": {"server_sampling": {"settings": {}}, "sent_sampling": {}},
                "checks": {}, "cases": [], "totals": {}, "label": "a", "persona_projection": "v4"}
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for label, verify in (("a", False), ("b", True)):
                path = Path(directory) / f"{label}.json"
                path.write_text(json.dumps(dict(base, label=label, verify_before_release=verify)), encoding="utf-8")
                paths.append(path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.harness.compare(paths)
        result = json.loads(output.getvalue())
        self.assertFalse(result["comparable"])
        self.assertEqual(result["verify_before_release"], [False, True])
