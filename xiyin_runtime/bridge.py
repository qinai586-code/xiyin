"""Retain the existing synchronous L2 entry while using the same foundation."""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import logging
import threading

from .runtime import FoundationRuntime

_runtime = None
_lock = threading.Lock()
_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainResult:
    """A synchronous consumer's text and the original terminal outcome.

    Non-complete text is a visible partial result, never a successful reply.
    ``detail`` retains the runtime's error/finish reason without rewriting text.
    """

    text: str
    status: str
    request_id: str = ""
    detail: str = ""


def submit_to_chain(text: str, source: str = "sidecar") -> str:
    """Compatibility text call; source is provenance, never an authority claim.

Async/voice callers must use stream_turn, not block their event loop here.
Unmapped sidecar sources are refused instead of exposing owner-private context.
"""
    result = submit_to_chain_result(text, source)
    if result.status == "complete":
        return result.text
    # Keep the legacy str/success contract. Callers needing partial output use
    # submit_to_chain_result, rather than mistaking a nonempty str for success.
    # Do not put private response text in the process log.
    _logger.warning("XIYIN incomplete reply: status=%s request_id=%s partial_chars=%d detail=%s",
                    result.status, result.request_id, len(result.text), result.detail)
    return ""


def submit_to_chain_result(text: str, source: str = "sidecar") -> ChainResult:
    """Additive detailed entry; authorization and source isolation are unchanged."""
    if source not in {"interactive", "owner", "sidecar"}:
        raise ValueError("Source needs an explicit session/scope adapter")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Use FoundationRuntime.stream_turn from an async caller")
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = FoundationRuntime.open()

        async def run():
            chunks = []
            request_id = ""
            terminal = None
            async with aclosing(_runtime.stream_turn(
                text, session_id="owner" if source != "sidecar" else "legacy-sidecar",
                scope="private" if source != "sidecar" else "public",
            )) as events:
                async for event in events:
                    request_id = event.request_id
                    if event.type == "text_delta":
                        chunks.append(event.text)
                    elif event.type in {"complete", "cancelled", "error"}:
                        terminal = event
            return ChainResult("".join(chunks), terminal.type if terminal else "error",
                               request_id, terminal.detail if terminal else "Stream ended without a terminal event")

        return asyncio.run(run())
