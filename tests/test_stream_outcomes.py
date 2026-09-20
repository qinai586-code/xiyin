"""Offline end-to-end stream contracts, not Windows runtime authorization tests.

Use the real SSE client, Runtime and SQLite with an explicit test authorization
stub. MockTransport opens no socket; no model, production data or SID is used.
"""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

from tests.test_provider import ByteStream, DONE, event
from xiyin_runtime import bridge
from xiyin_runtime.cli import _display_turn
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import LocalModelClient, ProviderConfig
from xiyin_runtime.runtime import FoundationRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class DisconnectingStream(ByteStream):
    async def __aiter__(self):
        yield event({"content": "before disconnect"})
        raise httpx.ReadError("fixture disconnect")


class StreamOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime_count = 0

    def make_runtime(self, *streams):
        """Instantiate all production layers; only transport and auth are fixtures."""
        self.runtime_count += 1
        store = ExperienceStore(Path(self.temp.name) / f"test-{self.runtime_count}.sqlite3")
        self.addCleanup(store.close)
        pending = list(streams)
        requests = []

        def handler(request):
            requests.append(request)
            if not pending:
                raise AssertionError("Unexpected additional request or automatic retry")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=pending.pop(0))

        config = ProviderConfig("http://127.0.0.1:8080/v1", "xiyin")
        client = LocalModelClient(config, transport=httpx.MockTransport(handler))
        test_authorize = Mock(name="explicit_offline_test_authorization", return_value=None)
        runtime = FoundationRuntime(Settings(config, SEED, max_context_chars=20000), store,
                                    provider=client, authorize=test_authorize)
        self.addCleanup(runtime.close)
        return runtime, requests, test_authorize

    @staticmethod
    async def collect(runtime, text="开始"):
        return [item async for item in runtime.stream_turn(text)]

    def reply_record(self, runtime, request_id):
        replies = [row for row in runtime.store.list_events("owner")
                   if row["kind"] == "assistant" and row["request_id"] == request_id]
        self.assertEqual(len(replies), 1)
        return replies[0]

    def test_stop_final_content_completes_and_enters_history(self):
        wire = ByteStream([event({"content": "first "}),
                           event({"content": "last"}, finish_reason="stop"), DONE])
        runtime, requests, authorization = self.make_runtime(wire)
        events = asyncio.run(self.collect(runtime))
        self.assertEqual([item.type for item in events],
                         ["start", "text_delta", "text_delta", "complete"])
        self.assertEqual("".join(item.text for item in events), "first last")
        reply = self.reply_record(runtime, events[0].request_id)
        self.assertEqual((reply["content"], reply["status"]), ("first last", "completed"))
        self.assertEqual([row["content"] for row in runtime.store.history("owner")
                          if row["role"] == "assistant"], ["first last"])
        authorization.assert_called_once_with()
        self.assertEqual(len(requests), 1)
        self.assertTrue(wire.closed)

    def test_length_keeps_final_content_and_records_reason_without_complete_history(self):
        wire = ByteStream([event({"content": "first "}),
                           event({"content": "last"}, finish_reason="length"), DONE])
        runtime, requests, _ = self.make_runtime(wire)
        events = asyncio.run(self.collect(runtime))
        self.assertEqual([item.type for item in events],
                         ["start", "text_delta", "text_delta", "error"])
        self.assertEqual("".join(item.text for item in events), "first last")
        self.assertIn("ProviderTruncated", events[-1].detail)
        self.assertIn("finish_reason='length'", events[-1].detail)
        reply = self.reply_record(runtime, events[0].request_id)
        self.assertEqual((reply["content"], reply["status"]), ("first last", "partial"))
        endings = [row for row in runtime.store.list_events("owner")
                   if row["kind"] == "generation_end"]
        self.assertEqual(len(endings), 1)
        self.assertEqual(json.loads(endings[0]["content"]),
                         {"reply_event_id": reply["id"], "finish_reason": "length"})
        self.assertEqual(endings[0]["request_id"], reply["request_id"])
        self.assertFalse(any(row["role"] == "assistant" for row in runtime.store.history("owner")))
        self.assertEqual(len(requests), 1)
        self.assertTrue(wire.closed)

    def test_empty_length_is_failed_and_still_records_the_real_finish_reason(self):
        wire = ByteStream([event({}, finish_reason="length"), DONE])
        runtime, requests, _ = self.make_runtime(wire)
        events = asyncio.run(self.collect(runtime))
        self.assertEqual([item.type for item in events], ["start", "error"])
        reply = self.reply_record(runtime, events[0].request_id)
        self.assertEqual((reply["content"], reply["status"]), ("", "failed"))
        ending = next(row for row in runtime.store.list_events("owner")
                      if row["kind"] == "generation_end")
        self.assertEqual(json.loads(ending["content"])["finish_reason"], "length")
        self.assertFalse(any(row["role"] == "assistant" for row in runtime.store.history("owner")))
        self.assertEqual(len(requests), 1)
        self.assertTrue(wire.closed)

    def test_transport_and_protocol_errors_keep_prior_text_without_replay(self):
        cases = (
            (DisconnectingStream([]), "before disconnect", "transport failed"),
            (ByteStream([event({"content": "before EOF"})]), "before EOF", "before [DONE]"),
            (ByteStream([event({"content": "before error"}),
                         b'data: {"error":{"message":"private backend detail"}}\n\n']),
             "before error", "error payload"),
        )
        for wire, expected, detail in cases:
            with self.subTest(detail=detail):
                runtime, requests, _ = self.make_runtime(wire)
                events = asyncio.run(self.collect(runtime))
                self.assertEqual([item.type for item in events], ["start", "text_delta", "error"])
                self.assertEqual("".join(item.text for item in events), expected)
                self.assertIn(detail, events[-1].detail)
                reply = self.reply_record(runtime, events[0].request_id)
                self.assertEqual((reply["content"], reply["status"]), (expected, "failed"))
                self.assertFalse(any(row["role"] == "assistant" for row in runtime.store.history("owner")))
                self.assertEqual(len(requests), 1)
                self.assertTrue(wire.closed)

    def test_cancel_before_and_after_first_text_allows_next_real_client_turn(self):
        for before_first in (True, False):
            with self.subTest(before_first=before_first):
                chunks = ([] if before_first else [event({"content": "visible"})])
                wire = ByteStream(chunks + [event({"content": "late"}, finish_reason="length"), DONE],
                                  block_at=len(chunks))
                recovery = ByteStream([event({"content": "recovered"}, finish_reason="stop"), DONE])
                runtime, requests, _ = self.make_runtime(wire, recovery)
                events = []

                async def run():
                    async def consume():
                        async for item in runtime.stream_turn("取消测试"):
                            events.append(item)

                    task = asyncio.create_task(consume())
                    await asyncio.wait_for(wire.waiting.wait(), 1)
                    self.assertTrue(runtime.cancel(events[0].request_id))
                    wire.release.set()
                    await asyncio.wait_for(task, 1)
                    return await self.collect(runtime, "下一轮")

                recovered = asyncio.run(run())
                self.assertEqual(events[-1].type, "cancelled")
                visible = "" if before_first else "visible"
                self.assertEqual("".join(item.text for item in events), visible)
                reply = self.reply_record(runtime, events[0].request_id)
                self.assertEqual((reply["content"], reply["status"]), (visible, "cancelled"))
                self.assertEqual(recovered[-1].type, "complete")
                self.assertEqual([row["content"] for row in runtime.store.history("owner")
                                  if row["role"] == "assistant"], ["recovered"])
                self.assertEqual(len(requests), 2)
                self.assertTrue(wire.closed and recovery.closed)

    def test_cli_preserves_partial_stdout_and_reports_incomplete_on_stderr(self):
        for reason, expected_code in (("stop", 0), ("length", 1)):
            with self.subTest(reason=reason):
                wire = ByteStream([event({"content": "visible body"}, finish_reason=reason), DONE])
                runtime, _, _ = self.make_runtime(wire)
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = asyncio.run(_display_turn(runtime, "开始", SimpleNamespace(session="owner", scope="private")))
                self.assertEqual(code, expected_code)
                self.assertEqual(stdout.getvalue(), "visible body\n")
                if reason == "length":
                    self.assertIn("ProviderTruncated", stderr.getvalue())
                    self.assertIn("finish_reason='length'", stderr.getvalue())
                else:
                    self.assertEqual(stderr.getvalue(), "")

    def test_detailed_bridge_matches_stream_terminal_and_partial_content(self):
        for reason, content in (("stop", "answer"), ("length", "partial"), ("length", "")):
            with self.subTest(reason=reason, empty=not content):
                wires = [ByteStream([event({"content": content}, finish_reason=reason), DONE])
                         for _ in range(2)]
                runtime, requests, authorization = self.make_runtime(*wires)
                events = asyncio.run(self.collect(runtime))
                with patch.object(bridge, "_runtime", runtime):
                    result = bridge.submit_to_chain_result("开始", source="owner")
                self.assertIsInstance(result, bridge.ChainResult)
                self.assertEqual(result.text, "".join(item.text for item in events))
                self.assertEqual((result.status, result.detail), (events[-1].type, events[-1].detail))
                self.assertTrue(result.request_id)
                self.assertNotEqual(result.request_id, events[-1].request_id)
                self.assertEqual(len(requests), 2)
                self.assertEqual(authorization.call_count, 2)
                self.assertTrue(all(wire.closed for wire in wires))

    def test_legacy_bridge_keeps_str_contract_and_logs_outcome_without_private_body(self):
        private_body = "PRIVATE_PARTIAL_MARKER"
        wires = [
            ByteStream([event({"content": "complete reply"}, finish_reason="stop"), DONE]),
            ByteStream([event({"content": private_body}, finish_reason="length"), DONE]),
            ByteStream([event({"content": private_body})]),
        ]
        runtime, requests, _ = self.make_runtime(*wires)
        with patch.object(bridge, "_runtime", runtime):
            self.assertEqual(bridge.submit_to_chain("正常", source="owner"), "complete reply")
            for question in ("截断", "断流"):
                with self.subTest(question=question), self.assertLogs(bridge.__name__, level="WARNING") as logs:
                    self.assertEqual(bridge.submit_to_chain(question, source="owner"), "")
                log = "\n".join(logs.output)
                self.assertIn("status=error", log)
                self.assertIn(f"partial_chars={len(private_body)}", log)
                self.assertNotIn(private_body, log)
                self.assertIn("request_id=", log)
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(wire.closed for wire in wires))


if __name__ == "__main__":
    unittest.main()
