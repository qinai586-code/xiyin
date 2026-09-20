"""Voice is a body of the same runtime, with generation and playback epochs."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
import re


class RuntimeVoiceSession:
    def __init__(self, runtime, controller, *, session_id="owner", scope="private"):
        if scope not in {"private", "public"}:
            raise ValueError("Invalid voice scope")
        self.runtime, self.controller = runtime, controller
        self.session_id, self.scope = session_id, scope
        self._epoch = None
        self._turn = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._last_result = None
        self._request_by_epoch = {}
        controller.generation_cancel = self._cancel_generation
        controller.receipt_callback = self._receipt

    def _cancel_generation(self, epoch):
        request = self._request_by_epoch.get(epoch)
        if request:
            self.runtime.cancel(request)

    def _receipt(self, receipt):
        self.runtime.store.append_event("delivery_receipt", receipt.to_dict(), session_id=self.session_id,
                                        scope=self.scope, origin="tool_result", status="recorded")

    async def feed_audio(self, chunk, *, echo_suppressed=False):
        if self._closed:
            raise RuntimeError("Voice session is closed")
        events = await self.controller.submit_pcm(chunk, echo_suppressed=echo_suppressed)
        for event in events:
            if (event.get("kind") == "final_transcript" and event.get("accepted") is True
                    and isinstance(event.get("text"), str) and event["text"].strip()):
                await self.start_turn(event["text"])
        return events

    async def start_turn(self, text):
        """A final utterance supersedes the old voice turn; PCM ingestion stays live."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("Voice session is closed")
            await self.controller.confirm_interrupt()
            if self._turn is not None and not self._turn.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self._turn), 1)
                except TimeoutError:
                    self._turn.cancel()
                    await asyncio.gather(self._turn, return_exceptions=True)
            self._turn = asyncio.create_task(self.respond(text))
            return self._turn

    async def respond(self, text):
        self.runtime._ensure_running()
        epoch = await self.controller.begin()
        self._epoch = epoch
        chunks, pending = [], ""
        terminal, detail = "error", ""

        async def speak(segment):
            task = asyncio.create_task(self.controller.submit_text(segment, epoch))
            try:
                await task
            except asyncio.CancelledError:
                # A confirmed interruption cancels only the synthesis child;
                # generation uses its own token and emits a truthful terminal.
                if self.controller.active_epoch == epoch:
                    raise
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        try:
            async with aclosing(self.runtime.stream_turn(text, session_id=self.session_id, scope=self.scope)) as stream:
                async for event in stream:
                    if event.type == "start":
                        self._request_by_epoch[epoch] = event.request_id
                    elif event.type == "text_delta":
                        chunks.append(event.text)
                        pending += event.text
                        # Runtime has already checked these units. Body only
                        # segments approved text for transport and playback.
                        while pending:
                            boundary = re.search(r"[。！？!?\n]", pending)
                            length = boundary.end() if boundary else (80 if len(pending) >= 80 else 0)
                            if not length:
                                break
                            segment, pending = pending[:length], pending[length:]
                            await speak(segment)
                            if self.controller.active_epoch != epoch:
                                self.runtime.cancel(event.request_id)
                                break
                    elif event.type in {"complete", "cancelled", "error"}:
                        terminal, detail = event.type, event.detail
                        if event.type == "error" and event.detail.startswith("OutputBlocked:"):
                            pending = ""
                            # Revoke the epoch and purge even previously approved
                            # queued audio; no stale tail may outlive a rejection.
                            await self.controller.cancel()
                if terminal == "complete" and pending and self.controller.active_epoch == epoch:
                    await speak(pending)
            self._last_result = {"text": "".join(chunks), "generation_status": terminal, "detail": detail,
                                 "delivery": "see delivery_receipt events; generation is not proof of playback"}
            return self._last_result
        finally:
            self._request_by_epoch.pop(epoch, None)

    async def close(self):
        self._closed = True
        await self.controller.cancel()
        if self._turn and not self._turn.done():
            self._turn.cancel()
            await asyncio.gather(self._turn, return_exceptions=True)
        await self.controller.close()
