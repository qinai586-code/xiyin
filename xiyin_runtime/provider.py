"""Loopback-only llama.cpp chat client.

Closing a response stops local delivery; it does not prove GPU work has stopped.
The async generator must be exhausted or explicitly ``aclose()``-ed by its owner.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import time
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, TypeVar
from urllib.parse import urlsplit

import httpx


class ProviderError(RuntimeError):
    """Configuration, transport, or response protocol failure; no retry is made."""


class ProviderCancelled(ProviderError):
    """The caller revoked this output stream."""


MAX_EVENT_BYTES = 64 * 1024
MAX_HEALTH_BYTES = 64 * 1024
_T = TypeVar("_T")


def _json_object(data: str | bytes | bytearray) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite JSON number")

    result = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("JSON payload must be an object")
    return result


def _urls(endpoint: str) -> tuple[str, str]:
    if not isinstance(endpoint, str) or not endpoint or any(c.isspace() or ord(c) < 32 for c in endpoint):
        raise ProviderError("endpoint must be an explicit loopback HTTP(S) URL")
    try:
        parts = urlsplit(endpoint)
        host, port = parts.hostname, parts.port
        if parts.scheme not in {"http", "https"} or not host:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        if "?" in endpoint or "#" in endpoint or "%" in host:
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if host.lower() != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError
        if parts.path.rstrip("/") not in {"", "/v1", "/v1/chat/completions"}:
            raise ValueError
    except ValueError as exc:
        raise ProviderError("endpoint must use loopback HTTP(S), no credentials/query, and the chat-completions route") from exc
    origin = f"{parts.scheme}://{parts.netloc}"
    return origin + "/v1/chat/completions", origin + "/health"


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: str
    timeout_seconds: float = 60
    max_tokens: int = 512
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        _urls(self.endpoint)
        if not isinstance(self.model, str) or not self.model.strip():
            raise ProviderError("model must be a non-empty string")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ProviderError("timeout_seconds must be finite and positive")
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ProviderError("max_tokens must be a positive integer")
        if type(self.enable_thinking) is not bool:
            raise ProviderError("enable_thinking must be boolean")


async def _wait_io(awaitable: Awaitable[_T], cancel: asyncio.Event, deadline: float) -> _T:
    """Race every network wait with cancellation, including response headers."""
    operation = asyncio.ensure_future(awaitable)
    revoked = asyncio.create_task(cancel.wait())
    transferred = False
    try:
        done, _ = await asyncio.wait(
            (operation, revoked), timeout=max(0, deadline - time.monotonic()),
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Revocation wins even when the result becomes ready in the same turn.
        if cancel.is_set():
            raise ProviderCancelled("local model stream cancelled")
        if operation not in done:
            raise ProviderError("local model request timed out")
        result = operation.result()
        transferred = True
        return result
    finally:
        revoked.cancel()
        if not operation.done():
            operation.cancel()
        await asyncio.gather(revoked, return_exceptions=True)
        if not transferred:
            result = (await asyncio.gather(operation, return_exceptions=True))[0]
            # send() may finish just as cancellation arrives. Do not leak it.
            if isinstance(result, httpx.Response):
                await result.aclose()


class _SSEDecoder:
    """Bounded, UTF-8 SSE records; accepts LF, CRLF, CR and multiline data."""

    def __init__(self) -> None:
        self.line = bytearray()
        self.data: list[str] = []
        self.event = "message"
        self.size = 0
        self.skip_lf = False
        self.first_line = True

    def feed(self, chunk: bytes):
        for byte in chunk:
            if self.skip_lf and byte == 10:
                self.skip_lf = False
                continue
            self.skip_lf = False
            self.size += 1
            if self.size > MAX_EVENT_BYTES:
                raise ProviderError("SSE event exceeds size limit")
            if byte not in (10, 13):
                self.line.append(byte)
                continue
            self.skip_lf = byte == 13
            try:
                line = self.line.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ProviderError("SSE contains invalid UTF-8") from exc
            self.line.clear()
            if self.first_line:
                line = line.removeprefix("\ufeff")
                self.first_line = False
            if not line:
                data, event = self.data, self.event
                self.data, self.event, self.size = [], "message", 0
                if data:
                    yield event, "\n".join(data)
                elif event != "message":
                    raise ProviderError("SSE event has no data")
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                self.data.append(value)
            elif field == "event":
                self.event = value or "message"
            elif field in {"id", "retry"}:
                continue
            else:
                raise ProviderError("unsupported SSE field")


def _content(event: str, data: str) -> str | None:
    if event != "message":
        raise ProviderError("provider returned an error or unsupported SSE event")
    try:
        payload = _json_object(data)
    except (ValueError, RecursionError) as exc:
        raise ProviderError("malformed JSON in SSE event") from exc
    if "error" in payload:
        raise ProviderError("provider returned an invalid or error payload")
    choices = payload.get("choices")
    if choices == [] and isinstance(payload.get("usage"), dict):
        return None
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("expected one chat completion choice")
    choice = choices[0]
    if type(choice.get("index", 0)) is not int or choice.get("index", 0) != 0 or not isinstance(choice.get("delta"), dict):
        raise ProviderError("invalid chat completion delta")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and finish_reason != "stop":
        if not isinstance(finish_reason, str):
            raise ProviderError("invalid chat completion finish_reason")
        raise ProviderError(f"chat did not complete normally: finish_reason={finish_reason[:80]!r}")
    content = choice["delta"].get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderError("chat content must be a string or null")
    # Never forward reasoning, reasoning_content, tool_calls, or other fields.
    return content


class LocalModelClient:
    def __init__(self, config: ProviderConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._chat_url, self._health_url = _urls(config.endpoint)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.config.timeout_seconds, transport=self._transport,
            trust_env=False, follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        )

    async def health(self) -> dict:
        """Return /health JSON verbatim, or fail. This does not run inference."""
        deadline = time.monotonic() + self.config.timeout_seconds
        cancel = asyncio.Event()
        try:
            async with self._client() as client:
                response = await _wait_io(client.send(client.build_request("GET", self._health_url), stream=True), cancel, deadline)
                try:
                    if response.status_code != 200:
                        raise ProviderError(f"health returned HTTP {response.status_code}")
                    body = bytearray()
                    iterator = response.aiter_bytes().__aiter__()
                    while True:
                        try:
                            chunk = await _wait_io(anext(iterator), cancel, deadline)
                        except StopAsyncIteration:
                            break
                        body.extend(chunk)
                        if len(body) > MAX_HEALTH_BYTES:
                            raise ProviderError("health response exceeds size limit")
                    try:
                        result = _json_object(body)
                    except (ValueError, RecursionError) as exc:
                        raise ProviderError("health returned invalid JSON") from exc
                    return result
                finally:
                    await response.aclose()
        except httpx.HTTPError as exc:
            raise ProviderError(f"local model health transport failed: {type(exc).__name__}") from exc

    async def stream(self, messages: list[dict], cancel: asyncio.Event) -> AsyncIterator[str]:
        """Yield content deltas once; require SSE [DONE] and nonblank content.

        timeout_seconds bounds the whole request, including waits between chunks.
        Errors after partial output remain errors; callers must not silently retry.
        """
        if cancel.is_set():
            raise ProviderCancelled("local model stream cancelled")
        if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) for m in messages):
            raise ProviderError("messages must be a non-empty list of objects")
        payload = {
            "model": self.config.model, "messages": messages,
            "max_tokens": self.config.max_tokens, "stream": True,
            "chat_template_kwargs": {"enable_thinking": self.config.enable_thinking},
        }
        deadline = time.monotonic() + self.config.timeout_seconds
        try:
            async with self._client() as client:
                try:
                    request = client.build_request("POST", self._chat_url, json=payload, headers={"Accept": "text/event-stream"})
                except (TypeError, ValueError) as exc:
                    raise ProviderError("messages are not JSON serializable") from exc
                response = await _wait_io(client.send(request, stream=True), cancel, deadline)
                try:
                    if response.status_code != 200:
                        raise ProviderError(f"chat returned HTTP {response.status_code}")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                        raise ProviderError("chat response must be text/event-stream")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ProviderError("compressed SSE is not supported")
                    decoder, has_content = _SSEDecoder(), False
                    iterator = response.aiter_bytes().__aiter__()
                    while True:
                        try:
                            chunk = await _wait_io(anext(iterator), cancel, deadline)
                        except StopAsyncIteration as exc:
                            raise ProviderError("SSE ended before [DONE]") from exc
                        for event, data in decoder.feed(chunk):
                            if cancel.is_set():
                                raise ProviderCancelled("local model stream cancelled")
                            if data.strip() == "[DONE]" and event == "message":
                                if not has_content:
                                    raise ProviderError("model returned no readable content")
                                return
                            content = _content(event, data)
                            if content:
                                has_content = has_content or bool(content.strip())
                                yield content
                finally:
                    await response.aclose()
        except httpx.HTTPError as exc:
            raise ProviderError(f"local model stream transport failed: {type(exc).__name__}") from exc
