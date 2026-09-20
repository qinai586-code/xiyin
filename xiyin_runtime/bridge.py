"""Retain the existing synchronous L2 entry while using the same foundation."""

import asyncio
import threading

from .runtime import FoundationRuntime

_runtime = None
_lock = threading.Lock()


def submit_to_chain(text: str, source: str = "sidecar") -> str:
    """Compatibility text call; source is provenance, never an authority claim.

Async/voice callers must use stream_turn, not block their event loop here.
Unmapped sidecar sources are refused instead of exposing owner-private context.
"""
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
            complete = False
            async for event in _runtime.stream_turn(
                text, session_id="owner" if source != "sidecar" else "legacy-sidecar",
                scope="private" if source != "sidecar" else "public",
            ):
                if event.type == "text_delta":
                    chunks.append(event.text)
                elif event.type == "complete":
                    complete = True
            return "".join(chunks) if complete else ""

        return asyncio.run(run())
