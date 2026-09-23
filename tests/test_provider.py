"""Protocol and cancellation tests without a model, external network, or GPU."""

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from xiyin_runtime.provider import (
    MAX_EVENT_BYTES, LocalModelClient, ProviderCancelled, ProviderConfig, ProviderError,
    ProviderTruncated, sampling_pairs,
)


MESSAGES = [{"role": "user", "content": "你好"}]


def event(delta, **choice_fields):
    payload = {"choices": [{"index": 0, "delta": delta, **choice_fields}]}
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


DONE = b"data: [DONE]\n\n"


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks, block_at=None):
        self.chunks = chunks
        self.block_at = block_at
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        for index, chunk in enumerate(self.chunks):
            if index == self.block_at:
                self.waiting.set()
                await self.release.wait()
            yield chunk

    async def aclose(self):
        self.closed = True


class ConfigTests(unittest.TestCase):
    def test_rejects_remote_ambiguous_and_legacy_endpoints(self):
        for endpoint in (
            "https://example.com/v1", "http://192.168.0.2", "http://0.0.0.0",
            "http://127.0.0.1.example.org", "http://2130706433", "http://127.1",
            "file:///tmp/model", "ftp://127.0.0.1", "//127.0.0.1",
            "http://user:secret@localhost", "http://@localhost", "http://localhost#x",
            "http://localhost?x=1", "http://localhost?", " http://localhost",
            "http://local\nhost", "http://[::1%25eth0]", "http://localhost:99999",
            "http://localhost:0", "http://localhost/generate", "http://localhost/v1/models",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ProviderError):
                ProviderConfig(endpoint, "xiyin")

    def test_validates_limits(self):
        for kwargs in (
            {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")}, {"timeout_seconds": True},
            {"max_tokens": 0}, {"max_tokens": 1.5}, {"max_tokens": True},
            {"enable_thinking": "false"},
            {"sampling": {"temperature": 0.7}}, {"sampling": (("temperature", 3.0),)},
            {"sampling": (("top_k", 20.5),)}, {"sampling": (("seed", 1),)},
            {"sampling": (("top_p", 0.8), ("top_p", 0.9))}, {"sampling": (("min_p", float("nan")),)},
            {"sampling": (("temperature", True),)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProviderError):
                ProviderConfig("http://localhost", "xiyin", **kwargs)

    def test_sampling_pairs_are_sorted_and_checked(self):
        self.assertEqual(sampling_pairs({"top_p": 0.8, "temperature": 0.7, "top_k": 20}),
                         (("temperature", 0.7), ("top_k", 20), ("top_p", 0.8)))
        self.assertEqual(sampling_pairs({}), ())
        with self.assertRaises(ProviderError):
            sampling_pairs({"temperature": "0.7"})


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def client_for(self, stream, *, status=200, headers=None, config=None):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx.Response(status, headers=headers or {"content-type": "text/event-stream"}, stream=stream)

        return LocalModelClient(config or ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), transport=httpx.MockTransport(handler))

    async def collect(self, client, cancel=None):
        return [part async for part in client.stream(MESSAGES, cancel or asyncio.Event())]

    async def test_normalizes_endpoints_and_sends_exact_request_options(self):
        for endpoint in (
            "http://127.0.0.1:8080", "http://127.0.0.1:8080/v1/",
            "http://127.0.0.1:8080/v1/chat/completions", "https://[::1]:8080",
            "http://localhost:8080",
        ):
            with self.subTest(endpoint=endpoint):
                stream = ByteStream([event({"content": "你好"}), DONE])
                client = self.client_for(stream, config=ProviderConfig(endpoint, "xiyin"))
                self.assertEqual(await self.collect(client), ["你好"])
                request = self.requests[0]
                self.assertEqual(request.url.path, "/v1/chat/completions")
                self.assertEqual(request.method, "POST")
                self.assertEqual(json.loads(request.content), {
                    "model": "xiyin", "messages": MESSAGES, "max_tokens": 512,
                    "stream": True, "chat_template_kwargs": {"enable_thinking": False},
                })
                self.assertTrue(stream.closed)

    async def test_fragmented_multiline_sse_filters_reasoning_and_tools(self):
        wire = b"\xef\xbb\xbf: keepalive\r\n\r\n" + event({"role": "assistant", "content": None})
        wire += event({"reasoning_content": "PRIVATE", "reasoning": "SECRET"})
        wire += event({"tool_calls": [{"function": {"arguments": "DONT SPEAK"}}]})
        wire += b'data: {"choices": [\r\ndata: {"index":0,"delta":{"content":"'
        wire += "你好".encode() + b'"}}]}\r\n\r\n'
        wire += event({"content": "！"}) + event({}, finish_reason="stop")
        wire += b'data: {"choices":[],"usage":{"completion_tokens":9}}\r\r'
        wire += DONE
        stream = ByteStream([bytes([byte]) for byte in wire])
        result = await self.collect(self.client_for(stream))
        self.assertEqual(result, ["你好", "！"])
        self.assertTrue(stream.closed)

    async def test_sampling_is_sent_only_when_chosen(self):
        stream = ByteStream([event({"content": "嗯"}), DONE])
        config = ProviderConfig("http://localhost", "xiyin",
                                sampling=sampling_pairs({"temperature": 0.7, "top_k": 20, "presence_penalty": 1.5}))
        await self.collect(self.client_for(stream, config=config))
        body = json.loads(self.requests[0].content)
        self.assertEqual({key: body[key] for key in ("temperature", "top_k", "presence_penalty")},
                         {"temperature": 0.7, "top_k": 20, "presence_penalty": 1.5})
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})

    async def test_thinking_option_is_forwarded_but_reasoning_is_not(self):
        stream = ByteStream([event({"reasoning_content": "secret", "content": "answer"}), DONE])
        client = self.client_for(stream, config=ProviderConfig("http://localhost", "xiyin", enable_thinking=True))
        self.assertEqual(await self.collect(client), ["answer"])
        self.assertTrue(json.loads(self.requests[0].content)["chat_template_kwargs"]["enable_thinking"])

    async def test_cancel_before_request_does_no_io(self):
        stream = ByteStream([event({"content": "late"}), DONE])
        client = self.client_for(stream)
        cancel = asyncio.Event()
        cancel.set()
        with self.assertRaises(ProviderCancelled):
            await self.collect(client, cancel)
        self.assertEqual(self.requests, [])

    async def test_cancel_during_response_header_wait(self):
        entered, never, cancel = asyncio.Event(), asyncio.Event(), asyncio.Event()
        handler_cancelled = asyncio.Event()

        async def handler(request):
            entered.set()
            try:
                await never.wait()
            finally:
                handler_cancelled.set()

        client = LocalModelClient(ProviderConfig("http://localhost", "xiyin"), transport=httpx.MockTransport(handler))
        task = asyncio.create_task(self.collect(client, cancel))
        await asyncio.wait_for(entered.wait(), 1)
        cancel.set()
        with self.assertRaises(ProviderCancelled):
            await asyncio.wait_for(task, 1)
        self.assertTrue(handler_cancelled.is_set())

    async def test_cancel_waiting_for_first_readable_content(self):
        stream = ByteStream([event({"content": "late"}), DONE], block_at=0)
        cancel = asyncio.Event()
        task = asyncio.create_task(self.collect(self.client_for(stream), cancel))
        await asyncio.wait_for(stream.waiting.wait(), 1)
        cancel.set()
        with self.assertRaises(ProviderCancelled):
            await asyncio.wait_for(task, 1)
        self.assertTrue(stream.closed)

    async def test_cancel_after_first_delta_drops_later_delta(self):
        stream = ByteStream([event({"content": "first"}), event({"content": "late"}), DONE], block_at=1)
        cancel = asyncio.Event()
        received = []

        async def run():
            async for part in self.client_for(stream).stream(MESSAGES, cancel):
                received.append(part)

        task = asyncio.create_task(run())
        await asyncio.wait_for(stream.waiting.wait(), 1)
        cancel.set()
        stream.release.set()  # Both result and revocation ready: revocation wins.
        with self.assertRaises(ProviderCancelled):
            await asyncio.wait_for(task, 1)
        self.assertEqual(received, ["first"])
        self.assertTrue(stream.closed)

    async def test_cancel_and_headers_ready_together_closes_response(self):
        cancel = asyncio.Event()
        stream = ByteStream([event({"content": "late"}), DONE])

        def handler(request):
            cancel.set()
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

        client = LocalModelClient(ProviderConfig("http://localhost", "xiyin"), transport=httpx.MockTransport(handler))
        with self.assertRaises(ProviderCancelled):
            await self.collect(client, cancel)
        self.assertTrue(stream.closed)

    async def test_external_task_cancel_and_generator_close_release_response(self):
        stream = ByteStream([event({"content": "late"})], block_at=0)
        task = asyncio.create_task(self.collect(self.client_for(stream)))
        await asyncio.wait_for(stream.waiting.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stream.closed)
        stream = ByteStream([event({"content": "first"}), event({"content": "late"}), DONE])
        generator = self.client_for(stream).stream(MESSAGES, asyncio.Event())
        self.assertEqual(await anext(generator), "first")
        await generator.aclose()
        self.assertTrue(stream.closed)

    async def test_rejects_non_200_without_retry_or_redirect(self):
        for status in (302, 307, 401, 429, 500, 503):
            with self.subTest(status=status):
                stream = ByteStream([event({"content": "must not read"}), DONE])
                client = self.client_for(stream, status=status, headers={"location": "https://example.com", "content-type": "text/event-stream"})
                with self.assertRaisesRegex(ProviderError, f"HTTP {status}"):
                    await self.collect(client)
                self.assertEqual(len(self.requests), 1)
                self.assertTrue(stream.closed)

    async def test_rejects_wrong_media_type_and_compression(self):
        for headers in ({"content-type": "application/json"}, {"content-type": "text/event-stream", "content-encoding": "gzip"}):
            with self.subTest(headers=headers):
                stream = ByteStream([DONE])
                with self.assertRaises(ProviderError):
                    await self.collect(self.client_for(stream, headers=headers))
                self.assertTrue(stream.closed)

    async def test_rejects_empty_malformed_error_and_truncated_events(self):
        for wire in (
            DONE, event({"content": " \n"}) + DONE,
            event({"reasoning_content": "secret"}) + DONE,
            b'data: {"error":{"message":"private detail"}}\n\n',
            b'event: error\ndata: {}\n\n', b'data: {not json}\n\n',
            b'data: []\n\n', b'data: {"choices":[]}\n\n',
            b'data: {"choices":[],"usage":{"count":NaN}}\n\n',
            b'data: {"choices":[],"choices":[],"usage":{}}\n\n',
            b'data: {"choices":[{"delta":null}]}\n\n',
            b'data: {"choices":[{"index":false,"delta":{}}]}\n\n',
            event({"content": ["invalid"]}), b'data: \xff\n\n',
            event({"content": "partial"}), b'data: {"choices":',
            b'data: ' + b'x' * MAX_EVENT_BYTES,
            b'data: x\n' * (MAX_EVENT_BYTES // 5),
        ):
            with self.subTest(wire=wire[:80]):
                stream = ByteStream([wire])
                client = self.client_for(stream)
                with self.assertRaises(ProviderError):
                    await self.collect(client)
                self.assertEqual(len(self.requests), 1)
                self.assertTrue(stream.closed)

    async def test_timeout_closes_stream_without_retry(self):
        stream = ByteStream([event({"content": "late"})], block_at=0)
        client = self.client_for(stream, config=ProviderConfig("http://localhost", "xiyin", timeout_seconds=0.02))
        with self.assertRaisesRegex(ProviderError, "timed out"):
            await asyncio.wait_for(self.collect(client), 1)
        self.assertTrue(stream.closed)
        self.assertEqual(len(self.requests), 1)

    async def test_transport_error_does_not_replay_partial_output(self):
        class FailingStream(ByteStream):
            async def __aiter__(self):
                yield event({"content": "first"})
                raise httpx.ReadError("broken")

        stream = FailingStream([])
        client = self.client_for(stream)
        received = []
        with self.assertRaises(ProviderError):
            async for part in client.stream(MESSAGES, asyncio.Event()):
                received.append(part)
        self.assertEqual(received, ["first"])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(stream.closed)

    async def test_abnormal_finish_after_partial_output_is_not_completion(self):
        for reason in ("content_filter", "tool_calls", "function_call", "unknown_reason", 7):
            with self.subTest(reason=reason):
                stream = ByteStream([
                    event({"content": "partial"}), event({}, finish_reason=reason), DONE,
                ])
                client = self.client_for(stream)
                received = []
                with self.assertRaisesRegex(ProviderError, "finish_reason"):
                    async for part in client.stream(MESSAGES, asyncio.Event()):
                        received.append(part)
                self.assertEqual(received, ["partial"])
                self.assertEqual(len(self.requests), 1)
                self.assertTrue(stream.closed)

    async def test_length_preserves_final_delta_and_has_distinct_incomplete_error(self):
        for prefix, final, expected in (
            ([event({"content": "first"})], "last", ["first", "last"]),
            ([], "only", ["only"]),
            ([event({"content": "first"})], None, ["first"]),
            ([], "", []),
            ([], None, []),
        ):
            with self.subTest(prefix=bool(prefix), final=final):
                stream = ByteStream(prefix + [event({"content": final}, finish_reason="length"), DONE])
                client = self.client_for(stream)
                received = []
                with self.assertRaisesRegex(ProviderTruncated, "finish_reason='length'"):
                    async for part in client.stream(MESSAGES, asyncio.Event()):
                        received.append(part)
                self.assertEqual(received, expected)
                self.assertEqual(len(self.requests), 1, "truncation must not trigger a replay")
                self.assertTrue(stream.closed)

    async def test_stop_preserves_final_delta_but_still_requires_done(self):
        for ending in ([DONE], []):
            with self.subTest(has_done=bool(ending)):
                stream = ByteStream([event({"content": "last"}, finish_reason="stop")] + ending)
                received = []

                async def run():
                    async for part in self.client_for(stream).stream(MESSAGES, asyncio.Event()):
                        received.append(part)

                if ending:
                    await run()
                else:
                    with self.assertRaisesRegex(ProviderError, "before \\[DONE\\]"):
                        await run()
                self.assertEqual(received, ["last"])
                self.assertTrue(stream.closed)

    async def test_stop_rejects_subsequent_completion_deltas(self):
        for extra in (
            event({"content": "late"}),
            event({"content": "late"}, finish_reason="length"),
            event({}, finish_reason="stop"),
        ):
            with self.subTest(extra=extra):
                stream = ByteStream([event({"content": "last"}, finish_reason="stop"), extra, DONE])
                received = []
                with self.assertRaisesRegex(ProviderError, "after finish_reason='stop'"):
                    async for part in self.client_for(stream).stream(MESSAGES, asyncio.Event()):
                        received.append(part)
                self.assertEqual(received, ["last"])
                self.assertTrue(stream.closed)

    async def test_other_finish_errors_never_emit_same_event_content(self):
        for reason in ("content_filter", "tool_calls", "function_call", "unknown_reason", 7):
            with self.subTest(reason=reason):
                stream = ByteStream([event({"content": "must not emit"}, finish_reason=reason), DONE])
                received = []
                with self.assertRaises(ProviderError) as caught:
                    async for part in self.client_for(stream).stream(MESSAGES, asyncio.Event()):
                        received.append(part)
                self.assertNotIsInstance(caught.exception, ProviderTruncated)
                self.assertEqual(received, [])
                self.assertTrue(stream.closed)

    async def test_length_does_not_hide_invalid_content(self):
        stream = ByteStream([event({"content": ["invalid"]}, finish_reason="length"), DONE])
        with self.assertRaisesRegex(ProviderError, "content must be") as caught:
            await self.collect(self.client_for(stream))
        self.assertNotIsInstance(caught.exception, ProviderTruncated)
        self.assertTrue(stream.closed)

    async def test_cancel_ready_with_length_drops_final_delta(self):
        stream = ByteStream([
            event({"content": "first"}),
            event({"content": "late"}, finish_reason="length"), DONE,
        ], block_at=1)
        cancel, received = asyncio.Event(), []

        async def run():
            async for part in self.client_for(stream).stream(MESSAGES, cancel):
                received.append(part)

        task = asyncio.create_task(run())
        await asyncio.wait_for(stream.waiting.wait(), 1)
        cancel.set()
        stream.release.set()
        with self.assertRaises(ProviderCancelled):
            await asyncio.wait_for(task, 1)
        self.assertEqual(received, ["first"])
        self.assertTrue(stream.closed)

    async def test_cancel_after_final_delta_wins_over_finish_reason(self):
        for reason in ("length", "stop"):
            with self.subTest(reason=reason):
                stream = ByteStream([event({"content": "last"}, finish_reason=reason), DONE])
                cancel = asyncio.Event()
                generator = self.client_for(stream).stream(MESSAGES, cancel)
                self.assertEqual(await anext(generator), "last")
                cancel.set()
                with self.assertRaises(ProviderCancelled):
                    await anext(generator)
                self.assertTrue(stream.closed)

    async def test_null_finish_reason_does_not_require_a_final_stop_field(self):
        stream = ByteStream([event({"content": "answer"}, finish_reason=None), DONE])
        self.assertEqual(await self.collect(self.client_for(stream)), ["answer"])
        self.assertTrue(stream.closed)

    async def test_health_returns_only_original_health_object(self):
        stream = ByteStream([b'{"status":"ok"}'])
        client = self.client_for(stream, headers={"content-type": "application/json"})
        self.assertEqual(await client.health(), {"status": "ok"})
        self.assertEqual(self.requests[0].method, "GET")
        self.assertEqual(str(self.requests[0].url), "http://127.0.0.1:8080/health")
        self.assertTrue(stream.closed)

    async def test_health_rejects_bad_responses(self):
        for status, body in ((503, b'{"status":"loading model"}'), (200, b'[]'), (200, b'bad json')):
            with self.subTest(status=status, body=body):
                stream = ByteStream([body])
                with self.assertRaises(ProviderError):
                    await self.client_for(stream, status=status).health()
                self.assertTrue(stream.closed)

    async def test_disables_environment_proxy_discovery(self):
        # No real socket is opened. Fail if HTTPX consults environment proxies.
        with patch("httpx._client.get_environment_proxies", side_effect=AssertionError("environment consulted")):
            async with LocalModelClient(ProviderConfig("http://localhost", "xiyin"))._client() as client:
                self.assertFalse(client.follow_redirects)
                self.assertFalse(client.trust_env)


if __name__ == "__main__":
    unittest.main()
