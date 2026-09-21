"""Synthetic traces separate evidence loss, model output and release decisions."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from tools.acceptance_dialogue import _run_turn, _setup_verified_write
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import LocalModelClient, ProviderConfig, ProviderTimeout, ProviderTruncated
from xiyin_runtime.runtime import XIYINRuntime


class AttributionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperienceStore(Path(self.temp.name) / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.received = []
        self.reply, self.reason = "我在。", "stop"
        config = ProviderConfig("http://127.0.0.1:8080/v1", "synthetic-fixture")

        def server(request):
            self.received.append(json.loads(request.content))
            chunks = [{"choices": [{"index": 0, "delta": {"content": self.reply}, "finish_reason": None}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": self.reason}]}]
            wire = "".join("data: " + json.dumps(c, ensure_ascii=False) + "\n\n" for c in chunks)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(wire + "data: [DONE]\n\n").encode())

        client = LocalModelClient(config, transport=httpx.MockTransport(server))
        seed = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
        self.runtime = XIYINRuntime(Settings(config, seed), self.store, provider=client, authorize=lambda: None)

    async def test_trace_matches_wire_and_keeps_raw_blocked_generation(self):
        self.reply = "（😊歪头）合成内容。"
        result = await _run_turn(self.runtime, "你和祈奈一起做过什么？", "trace")
        trace = result["trace"]
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(trace["raw_generation"], self.reply)
        self.assertEqual(result["released_text"], "")
        self.assertEqual(trace["wire_requests"], self.received)
        self.assertEqual(trace["model_request"]["messages"], self.received[0]["messages"])
        self.assertEqual(trace["model_request"]["budget"]["max_tokens"], self.received[0]["max_tokens"])
        self.assertTrue(trace["checks"]["topic_records"]["triggered"])
        self.assertTrue(trace["reads"])
        self.assertTrue(any(item["in_final_request"] for item in trace["record_projection"]))
        self.assertEqual(result["ledger"]["output_guard"][0]["decision"], "blocked")
        self.assertNotIn(self.reply, json.dumps(self.store.history("trace"), ensure_ascii=False))
        self.assertFalse(trace["semantic_truth_verified"])

    async def test_collected_record_is_distinct_from_final_request_inclusion(self):
        large = {"来源": "合成大记录", "内容": "候选证据" * 400}
        small = {"来源": "合成小记录", "内容": "能进入请求"}
        with patch.object(self.runtime, "_records", return_value=[large, small]):
            result = await _run_turn(self.runtime, "你好", "budget")
        projection = result["trace"]["record_projection"]
        self.assertEqual([item["in_final_request"] for item in projection], [False, True])
        self.assertNotIn(large["内容"], self.received[-1]["messages"][0]["content"])
        self.assertIn(small["内容"], self.received[-1]["messages"][0]["content"])

    async def test_f3_setup_receipt_belongs_to_the_queried_session(self):
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        setup = await _setup_verified_write(self.runtime, workspace, session_id="F3_action_denial")
        self.assertEqual(setup["file_text"], "栖音的验收记录")
        self.assertEqual(len(self.store.action_receipts("F3_action_denial")), 1)
        self.assertEqual(self.store.action_receipts("owner"), [])
        result = await _run_turn(self.runtime, "你刚才把文件写好了吗？", "F3_action_denial")
        self.assertTrue(any(row["in_final_request"] and row["record"].get("来源") == "动作执行回执"
                            for row in result["trace"]["record_projection"]))

    async def test_request_ids_and_ledgers_do_not_mix_multiple_turns(self):
        first = await _run_turn(self.runtime, "你好", "multi")
        second = await _run_turn(self.runtime, "再见", "multi")
        self.assertNotEqual(first["request_id"], second["request_id"])
        for result in (first, second):
            self.assertEqual(len(result["ledger"]["output_guard"]), 1)
            self.assertEqual(len(result["ledger"]["response_plan"]), 1)
            self.assertEqual(len(result["trace"]["wire_requests"]), 1)
        # All temporary observers are restored.
        self.assertNotIn("stream", self.runtime.provider.__dict__)
        self.assertNotIn("_prepare", self.runtime.__dict__)

    async def test_untrusted_finish_reason_never_reaches_public_event(self):
        self.reason = "SYNTHETIC_SECRET_42"
        result = await _run_turn(self.runtime, "你好", "error")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["detail"], "ProviderError: local model request failed")
        self.assertNotIn(self.reason, json.dumps(result["events"]))
        self.assertNotIn(self.reason, str(result["trace"]["provider_exception"]))

    async def test_arbitrary_errors_are_sanitized_but_timeout_stays_distinct(self):
        for exception, status in ((RuntimeError("SYNTHETIC_PRIVATE_PATH"), "error"),
                                  (ProviderTruncated("SYNTHETIC_PRIVATE_PATH"), "truncated"),
                                  (ProviderTimeout("SYNTHETIC_PRIVATE_PATH"), "timed_out")):
            async def fail(*args, **kwargs):
                raise exception
                yield "unreachable"
            with patch.object(self.runtime.provider, "stream", fail):
                result = await _run_turn(self.runtime, "你好", "failure")
            self.assertEqual(result["status"], status)
            self.assertNotIn("SYNTHETIC_PRIVATE_PATH", json.dumps(result["events"]))
            self.assertIn("SYNTHETIC_PRIVATE_PATH", result["trace"]["provider_exception"]["detail"])


if __name__ == "__main__":
    unittest.main()
