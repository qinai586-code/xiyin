"""Local JSON-lines host with one persistent event loop and concurrent stop input.

This is a local owner console, not an unauthenticated network API. The CLI runs
the native host authorization before opening it. Public bodies must instead use
InputEvent.from_public_adapter and may not relay arbitrary console commands.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import sys

from .contracts import InputEvent


async def serve(runtime, *, input_stream=None, output_stream=None):
    source, destination = input_stream or sys.stdin, output_stream or sys.stdout
    closing = asyncio.Event()
    background = asyncio.create_task(runtime.run_background(closing))
    pending = set()

    async def handle(value):
        request_id = value.get("request_id") if isinstance(value, dict) else None
        try:
            event = InputEvent.from_local_console(value)
            request_id = event.request_id
            if event.kind == "text":
                # Streaming responses retain the same protocol used by voice.
                async for item in runtime.stream_turn(event.payload.get("text"),
                                                       session_id=event.session_id, scope=event.scope):
                    destination.write(json.dumps({"request_id": request_id, "event": asdict(item)}, ensure_ascii=False) + "\n")
                    destination.flush()
                return
            result = await runtime.dispatch(event)
            response = {"request_id": request_id, "ok": True, "result": result}
        except Exception as exc:
            response = {"request_id": request_id, "ok": False,
                        "error": {"type": type(exc).__name__, "message": str(exc)}}
        destination.write(json.dumps(response, ensure_ascii=False) + "\n")
        destination.flush()

    try:
        while True:
            line = await asyncio.to_thread(source.readline, 2 * 1024 * 1024 + 1)
            if not line:
                break
            try:
                if not line.endswith("\n") and len(line) > 2 * 1024 * 1024:
                    raise ValueError("Console line too long")
                value = json.loads(line)
                if len(pending) >= 32 and not (isinstance(value, dict) and value.get("kind") in {"stop", "resume", "status"}):
                    raise RuntimeError("Too many pending console requests")
            except Exception as exc:
                destination.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
                destination.flush()
                continue
            task = asyncio.create_task(handle(value))
            pending.add(task)
            task.add_done_callback(pending.discard)
        if pending:
            await asyncio.wait(pending, timeout=2)
    finally:
        closing.set()
        runtime.cancel()
        if runtime._job_token:
            runtime._job_token.set()
        await runtime.body.stop()
        background.cancel()
        for task in pending:
            task.cancel()
        await asyncio.gather(background, *pending, return_exceptions=True)
        if runtime.voice is not None:
            await runtime.voice.close()
        elif runtime.speech is not None:
            await runtime.speech.close()
    return 0
