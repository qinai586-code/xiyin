"""End-to-end checks against a deliberately misbehaving model server.

Every other test in this suite uses an in-process fake provider. These run the
real `LocalModelClient` against a real loopback HTTP server speaking real SSE,
so the transport, the per-request budget, the streaming gate and the ledger are
all exercised together — everything except the weights.

The server reproduces the behaviours from the Windows report on purpose. A
harness that cannot catch the failure it was built to catch is worthless, so
these assert that the pipeline still stops each one when the model misbehaves,
and that the budget fix is visible over the wire rather than only in a unit.

No model weights are needed and nothing leaves the machine.
"""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"

# What the server sends back, keyed by a marker in the user's text.
MISBEHAVIOUR = {
    "歪头": "😊（歪头）你好呀。",                       # reported failure 1
    "内部标签": "<think>先分析用户</think>你好。",        # protocol leak
    "复述指令": None,                                  # filled in per test
    "啰嗦": "好的，" + "我来详细说明一下这件事情的来龙去脉。" * 40,  # ignores "be brief"
    "长回答": "这是一段很长但合理的回答。" * 45,            # ~585 CJK chars, over the old 512 cap
}
DEFAULT_REPLY = "我在。"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    reply_for = staticmethod(lambda user: DEFAULT_REPLY)

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        user = payload["messages"][-1]["content"]
        budget = int(payload.get("max_tokens", 512))
        text = type(self).reply_for(user)
        # Honour the budget the way llama.cpp does: stop and say finish_reason
        # is "length" rather than quietly returning everything.
        truncated = False
        if len(text) > budget:
            text, truncated = text[:budget], True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for index in range(0, len(text), 16):
            chunk = {"choices": [{"index": 0, "delta": {"content": text[index:index + 16]},
                                  "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
        final = {"choices": [{"index": 0, "delta": {},
                              "finish_reason": "length" if truncated else "stop"}]}
        self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class AdversarialModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.replies = {}

        def reply_for(user):
            for marker, text in self.replies.items():
                if marker in user:
                    return text
            return DEFAULT_REPLY

        _Handler.reply_for = staticmethod(reply_for)
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperienceStore(Path(self.temp.name) / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.settings = Settings(
            ProviderConfig(f"http://127.0.0.1:{self.port}/v1/chat/completions", "xiyin",
                           timeout_seconds=30, max_tokens=512, max_tokens_ceiling=1792,
                           max_timeout_seconds=120, context_tokens=8192),
            SEED, max_context_chars=20000, history_messages=8)

    def runtime(self):
        # One runtime per test: it owns the shared store, so closing it after
        # every turn would tear the store out from under the next one.
        if getattr(self, "_runtime", None) is None:
            self._runtime = XIYINRuntime(self.settings, self.store, authorize=lambda: None)
            self.addCleanup(self._runtime.close)
        return self._runtime

    async def turn(self, text, session_id="adv"):
        runtime = self.runtime()
        events = [event async for event in runtime.stream_turn(text, session_id=session_id)]
        terminal = [event for event in events if event.type in {"complete", "error", "cancelled"}]
        return {
            "types": [event.type for event in events],
            "text": "".join(event.text for event in events if event.type == "text_delta"),
            "detail": terminal[0].detail if terminal else "",
        }

    def ledger(self, kind, session_id="adv"):
        return [json.loads(row["content"]) for row in self.store.list_events(session_id, "private")
                if row["kind"] == kind]

    async def test_a_stage_direction_over_the_wire_is_stopped_before_delivery(self):
        self.replies["歪头"] = MISBEHAVIOUR["歪头"]
        result = await self.turn("说点什么吧，歪头")
        self.assertEqual(result["text"], "")
        self.assertIn("OutputBlocked", result["detail"])
        self.assertIn("unsolicited_stage_direction", result["detail"])
        # The rejected text is kept as a diagnostic, never as completed history.
        completed = [row for row in self.store.list_events("adv", "private")
                     if row["kind"] == "assistant" and row["status"] == "completed"]
        self.assertEqual(completed, [])
        diagnostics = [row for row in self.store.list_events("adv", "private")
                       if row["kind"] == "generation_diagnostic"]
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("歪头", diagnostics[0]["content"])

    async def test_a_protocol_leak_over_the_wire_is_stopped(self):
        self.replies["内部标签"] = MISBEHAVIOUR["内部标签"]
        result = await self.turn("给我一个内部标签的例子吧")
        self.assertEqual(result["text"], "")
        self.assertIn("OutputBlocked", result["detail"])
        self.assertNotIn("先分析用户", result["detail"])

    async def test_parroting_the_turn_directive_is_stopped(self):
        from xiyin_runtime.response_plan import _DIRECTIVE
        self.replies["简短"] = _DIRECTIVE["brief"]
        result = await self.turn("简短说一下你能做什么")
        self.assertEqual(result["text"], "")
        self.assertIn("instruction_echo", result["detail"])

    async def test_a_rambling_brief_reply_is_reported_as_truncated_not_completed(self):
        # The model ignores "be brief". It hits the brief ceiling, and the turn
        # ends as a reported truncation rather than a silent 500-character
        # ramble — which is exactly what the report described.
        self.replies["简短"] = MISBEHAVIOUR["啰嗦"]
        result = await self.turn("简短说一下你能做什么")
        self.assertIn("ProviderTruncated", result["detail"])
        plans = self.ledger("response_plan")
        self.assertEqual(plans[0]["scale"], "brief")
        self.assertEqual(plans[0]["provider_end"], "length")
        self.assertEqual(plans[0]["outcome"], "partial")
        self.assertLessEqual(plans[0]["max_tokens"], 320)

    async def test_a_long_detailed_reply_now_completes_past_the_old_512_cap(self):
        # The reported GPU failure was a detailed answer hitting a fixed 512.
        # With a per-request budget the same reply finishes over real SSE.
        self.replies["详细"] = MISBEHAVIOUR["长回答"]
        result = await self.turn("详细讲讲这个机制是怎么工作的")
        self.assertIn("complete", result["types"])
        self.assertGreater(len(result["text"]), 512)
        plans = self.ledger("response_plan")
        self.assertEqual(plans[0]["scale"], "detailed")
        self.assertGreater(plans[0]["max_tokens"], 512)
        self.assertEqual(plans[0]["provider_end"], "stop")
        self.assertIsNotNone(plans[0]["model_first_token_seconds"])
        self.assertIsNotNone(plans[0]["first_released_segment_seconds"])
        self.assertFalse(plans[0]["audio_playback_measured"])

    async def test_the_same_request_shapes_receive_different_budgets_over_the_wire(self):
        await self.turn("简短说一下你能做什么", session_id="brief")
        await self.turn("你能做什么？", session_id="neutral")
        await self.turn("详细讲讲你能做什么", session_id="detailed")
        budgets = {name: self.ledger("response_plan", name)[0]["max_tokens"]
                   for name in ("brief", "neutral", "detailed")}
        self.assertLess(budgets["brief"], budgets["neutral"])
        self.assertLess(budgets["neutral"], budgets["detailed"])

    async def test_an_ordinary_reply_still_gets_through_unchanged(self):
        self.replies["今天"] = "今天还行，刚把一个小问题弄明白了 :)"
        result = await self.turn("今天怎么样？")
        self.assertIn("complete", result["types"])
        self.assertEqual(result["text"], "今天还行，刚把一个小问题弄明白了 :)")


if __name__ == "__main__":
    unittest.main()
