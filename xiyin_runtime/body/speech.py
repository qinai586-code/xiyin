"""Continuous input and two-stage interruption with cancellable output epochs.

ASR, TTS and playback are separate host-supplied transports. No microphone,
audio package or model is installed or claimed available by this controller.
"""
from __future__ import annotations

import array
import asyncio
from collections import deque
from contextlib import aclosing
import inspect
import math
import sys
import time

from .models import PCMChunk, PlaybackResult, SpeechEpoch, SpeechReceipt


class EnergyVAD:
    """Optional PCM energy event source, not an echo canceller or trained VAD.

    During playback, confirmation additionally requires the caller's explicit
    echo_suppressed input indication. A real transport should supply AEC/VAD.
    """
    def __init__(self, *, threshold=0.025, candidate_ms=40, confirm_ms=140, silence_ms=250):
        if not 0 < threshold < 1 or not 0 < candidate_ms < confirm_ms or silence_ms <= 0:
            raise ValueError("Invalid energy activity thresholds")
        self.threshold = threshold
        self.candidate_ms, self.confirm_ms, self.silence_ms = candidate_ms, confirm_ms, silence_ms
        self.reset()

    def reset(self):
        self._speech_ms = self._quiet_ms = 0.0
        self._candidate = self._confirmed = False

    def process(self, chunk: PCMChunk) -> list[str]:
        samples = array.array("h", chunk.audio)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
        duration = 1000 * chunk.frames / chunk.sample_rate
        events = []
        if rms >= self.threshold:
            self._quiet_ms = 0
            self._speech_ms += duration
            if not self._candidate and self._speech_ms >= self.candidate_ms:
                self._candidate = True
                events.append("speech_candidate")
            if not self._confirmed and self._speech_ms >= self.confirm_ms:
                self._confirmed = True
                events.append("speech_confirmed")
        else:
            self._quiet_ms += duration
            if not self._confirmed and self._quiet_ms >= self.candidate_ms:
                if self._candidate:
                    events.append("speech_rejected")
                self.reset()
            elif self._confirmed and self._quiet_ms >= self.silence_ms:
                events.append("speech_ended")
                self.reset()
        return events


class SpeechController:
    """Transport contracts:

    asr.accept_audio(PCMChunk, scene:int) -> list[dict(kind,text,...)]
    tts.synthesize(text, SpeechEpoch, cancel:Event) -> async iterator[PCMChunk]
    tts.cancel(epoch), sink.play(chunk, epoch)->PlaybackResult,
    sink.set_gain(float), sink.stop(), sink.purge(). All methods are async.
    generation_cancel(epoch) may be synchronous or async and must cancel the
    real generation source. Missing transports always report unavailable.
    """
    def __init__(self, *, asr=None, tts=None, sink=None, generation_cancel=None,
                 receipt_callback=None, vad: EnergyVAD | None = None, queue_size=32, control_timeout=0.5):
        if type(queue_size) is not int or queue_size < 1 or not 0 < control_timeout <= 10:
            raise ValueError("Invalid speech queue/control limits")
        self.asr, self.tts, self.sink = asr, tts, sink
        self.generation_cancel = generation_cancel
        self.receipt_callback = receipt_callback
        self.receipt_error = None
        self.vad = vad
        self.control_timeout = control_timeout
        self._queue = asyncio.Queue(maxsize=queue_size)
        self._lock = asyncio.Lock()
        self._control = asyncio.Lock()
        self._input_lock = asyncio.Lock()
        self._synthesis_lock = asyncio.Lock()
        self._scene = self._utterance = 0
        self._active: SpeechEpoch | None = None
        self._revoked = asyncio.Event()
        self._tts_tasks = set()
        self._input_tasks = set()
        self._background = set()
        self._pending_publications = set()
        self._play_task = self._worker = None
        self._candidate = None
        self._closed = False
        self.receipts = deque(maxlen=2048)
        self.input_events = deque(maxlen=2048)

    def availability(self) -> dict:
        return {name: {"available": component is not None,
                       "detail": "Host transport connected; hardware readiness requires transport health"
                       if component is not None else "No transport connected"}
                for name, component in (("asr", self.asr), ("tts", self.tts), ("playback", self.sink))}

    @property
    def active_epoch(self) -> SpeechEpoch | None:
        return self._active

    @property
    def queued_chunks(self) -> int:
        return self._queue.qsize()

    def _record(self, stage, epoch, status, *, sequence=0, frames=0, detail=""):
        receipt = SpeechReceipt(stage, epoch, status, sequence, frames, detail)
        if self.receipt_callback is not None:
            try:
                value = self.receipt_callback(receipt)
                if inspect.isawaitable(value):
                    if inspect.iscoroutine(value):
                        value.close()
                    raise TypeError("Speech receipt callback must persist synchronously")
            except Exception as exc:
                self.receipt_error = f"{type(exc).__name__}: {exc}"
                self._revoked.set()
                self.receipts.append(SpeechReceipt("receipt_persistence_failed", epoch, "failure",
                                                   detail=self.receipt_error))
                raise RuntimeError("Speech receipt persistence failed") from exc
        self.receipts.append(receipt)
        return receipt

    def _current(self, epoch):
        return not self._closed and epoch == self._active and not self._revoked.is_set()

    def _discarded(self, epoch, sequence=0):
        self._record("output_discarded", epoch, "cancelled", sequence=sequence, detail="Stale utterance or scene")

    @staticmethod
    def _control_result(value) -> dict:
        if value is True or isinstance(value, dict) and (
                value.get("status") in {"stopped", "purged", "cancelled", "released"} or
                any(value.get(key) is True for key in ("stopped", "purged", "cancelled"))):
            return {"status": "acknowledged", "result": value}
        if value is None:
            return {"status": "requested", "detail": "Transport returned no completion acknowledgement"}
        return {"status": "unknown", "result": value}

    def _start_call(self, callback, *args):
        if callback is None:
            return {"status": "unavailable"}
        try:
            value = callback(*args)
            return asyncio.ensure_future(value) if inspect.isawaitable(value) else self._control_result(value)
        except Exception as exc:
            return {"status": "unknown", "detail": f"{type(exc).__name__}: {exc}"}

    async def _finish_call(self, started) -> dict:
        if isinstance(started, dict):
            return started
        task = started
        done, _ = await asyncio.wait((task,), timeout=self.control_timeout)
        if task not in done:
            task.cancel()
            self._track_background(task)
            return {"status": "unknown", "detail": "Control acknowledgement timed out"}
        try:
            return self._control_result(task.result())
        except BaseException as exc:
            return {"status": "unknown", "detail": f"{type(exc).__name__}: {exc}"}

    async def _call(self, callback, *args) -> dict:
        return await self._finish_call(self._start_call(callback, *args))

    def _track_background(self, task):
        self._background.add(task)

        def finished(value):
            self._background.discard(value)
            if not value.cancelled():
                value.exception()
        task.add_done_callback(finished)

    async def _cancel_output(self, reason: str) -> dict:
        receipt_failure = None
        async with self._lock:
            epoch = self._active
            self._active = None
            self._revoked.set()
            self._candidate = None
            # Runtime.cancel is synchronous: revoke its real model token before
            # cancelling the TTS child that its stream loop may be awaiting.
            # Async cancellation is scheduled here before other transport tasks.
            generation = self._start_call(self.generation_cancel, epoch) if epoch else self._start_call(None)
            for put in self._pending_publications:
                put.cancel()
            purged = 0
            while not self._queue.empty():
                old_epoch, chunk = self._queue.get_nowait()
                self._queue.task_done()
                try:
                    self._discarded(old_epoch, chunk.sequence)
                except RuntimeError as exc:
                    receipt_failure = exc
                purged += 1
            tasks = [task for task in self._tts_tasks if task is not asyncio.current_task()]
            if self._play_task is not None:
                tasks.append(self._play_task)
            for task in tasks:
                task.cancel()
        # Epoch revocation and local purge happen before any transport awaits.
        calls = {
            "generation": self._finish_call(generation),
            "tts": self._call(getattr(self.tts, "cancel", None), epoch) if epoch else self._call(None),
            "stop": self._call(getattr(self.sink, "stop", None)),
            "purge": self._call(getattr(self.sink, "purge", None)),
        }
        values = await asyncio.gather(*calls.values())
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=self.control_timeout)
            for task in done:
                if not task.cancelled():
                    task.exception()
            for task in pending:
                self._track_background(task)
        result = {"reason": reason, "epoch": epoch, "local_chunks_purged": purged,
                  "transports": dict(zip(calls, values))}
        if epoch:
            status = "cancelled" if all(item["status"] == "acknowledged" for item in values) else "unknown"
            try:
                self._record("interrupted", epoch, status, detail=reason)
            except RuntimeError as exc:
                receipt_failure = exc
        if receipt_failure:
            raise receipt_failure
        return result

    async def begin(self) -> SpeechEpoch:
        async with self._control:
            if self._closed:
                raise RuntimeError("Speech controller is closed")
            if self.receipt_error:
                raise RuntimeError("Speech receipt sink failed; repair it before starting more output")
            if self._active is not None:
                await self._cancel_output("superseded")
            self._utterance += 1
            self._active = SpeechEpoch(self._scene, self._utterance)
            self._revoked = asyncio.Event()
            if self.sink is not None:
                await self._call(self.sink.set_gain, 1.0)
                if self._worker is None or self._worker.done():
                    self._worker = asyncio.create_task(self._playback_loop())
                    self._track_background(self._worker)
            return self._active

    async def candidate_interrupt(self) -> dict:
        async with self._control:
            if self._active is None:
                return {"status": "idle"}
            epoch = self._active
            self._candidate = epoch
            result = await self._call(getattr(self.sink, "set_gain", None), 0.15)
            self._record("ducked", epoch, result["status"], detail="Candidate speech; generation and TTS remain active")
            return result

    async def reject_interrupt(self) -> dict:
        async with self._control:
            if self._candidate is None or self._candidate != self._active:
                return {"status": "idle"}
            epoch, self._candidate = self._candidate, None
            result = await self._call(getattr(self.sink, "set_gain", None), 1.0)
            self._record("duck_released", epoch, result["status"])
            return result

    async def confirm_interrupt(self) -> dict:
        async with self._control:
            return await self._cancel_output("confirmed_user_interruption")

    async def cancel(self) -> dict:
        async with self._control:
            return await self._cancel_output("explicit_cancel")

    async def new_scene(self) -> int:
        async with self._control:
            await self._cancel_output("scene_changed")
            old_scene = self._scene
            self._scene += 1
            self._utterance = 0
            if self.vad:
                self.vad.reset()
            for task in self._input_tasks:
                if task is not asyncio.current_task():
                    task.cancel()
            await self._call(getattr(self.asr, "cancel", None), old_scene)
            return self._scene

    async def submit_pcm(self, chunk: PCMChunk, *, echo_suppressed=False) -> list[dict]:
        if self._closed:
            raise RuntimeError("Speech controller is closed")
        scene = self._scene
        playback_at_capture = self._play_task is not None
        self.input_events.append({"kind": "pcm_received", "scene": scene, "sequence": chunk.sequence,
                                  "frames": chunk.frames, "monotonic_time": time.monotonic()})
        events = []
        if self.vad:
            events.extend({"kind": name} for name in self.vad.process(chunk))
        task = asyncio.current_task()
        self._input_tasks.add(task)
        try:
            if self.asr is not None:
                async with self._input_lock:
                    if scene != self._scene:
                        return []
                    events.extend(await self.asr.accept_audio(chunk, scene))
            else:
                events.append({"kind": "asr_unavailable"})
        finally:
            self._input_tasks.discard(task)
        if scene != self._scene or self._closed:
            return []
        returned = []
        for event in events:
            event = {**event, "scene": scene}
            if event["kind"] == "final_transcript":
                event["accepted"] = (scene == self._scene and not self._closed and
                                     (echo_suppressed or not playback_at_capture) and
                                     isinstance(event.get("text"), str) and bool(event["text"].strip()))
                if not event["accepted"]:
                    event["rejection_reason"] = "Playback echo is not controlled, scene changed, or transcript is empty"
            returned.append(event)
            self.input_events.append(event)
            if event["kind"] == "speech_candidate":
                await self.candidate_interrupt()
            elif event["kind"] == "speech_rejected":
                await self.reject_interrupt()
            elif event["kind"] == "speech_confirmed":
                if playback_at_capture and not echo_suppressed:
                    self.input_events.append({"kind": "confirmation_needs_echo_control", "scene": scene})
                    if self.vad:
                        self.vad.reset()
                else:
                    await self.confirm_interrupt()
        return returned

    async def submit_text(self, text: str, epoch: SpeechEpoch) -> bool:
        if not isinstance(text, str) or not text:
            raise ValueError("Speech text must be nonempty")
        if not self._current(epoch):
            self._discarded(epoch)
            return False
        self._record("generated", epoch, "recorded", detail="Text exists; audio and listening are not established")
        if self.tts is None:
            self._record("synthesized", epoch, "unavailable", detail="No TTS transport connected")
            return False
        task = asyncio.current_task()
        self._tts_tasks.add(task)
        token = self._revoked
        try:
            async with self._synthesis_lock:
                if not self._current(epoch):
                    self._discarded(epoch)
                    return False
                async with aclosing(self.tts.synthesize(text, epoch, token)) as stream:
                    async for chunk in stream:
                        if not self._current(epoch):
                            self._discarded(epoch, chunk.sequence)
                            return False
                        self._record("synthesized", epoch, "recorded", sequence=chunk.sequence, frames=chunk.frames)
                        if not await self.publish_audio(chunk, epoch):
                            return False
            return self._current(epoch)
        except asyncio.CancelledError:
            self._record("synthesis_cancelled", epoch, "cancelled")
            raise
        except Exception as exc:
            self._record("synthesis_failed", epoch, "failure", detail=f"{type(exc).__name__}: {exc}")
            return False
        finally:
            self._tts_tasks.discard(task)

    async def publish_audio(self, chunk: PCMChunk, epoch: SpeechEpoch) -> bool:
        if not isinstance(chunk, PCMChunk):
            raise ValueError("Audio publication requires a validated PCMChunk")
        if not self._current(epoch):
            self._discarded(epoch, chunk.sequence)
            return False
        if self.sink is None:
            self._record("client_played", epoch, "unavailable", sequence=chunk.sequence, detail="No playback transport connected")
            return False
        revoked = asyncio.create_task(self._revoked.wait())
        put = asyncio.create_task(self._queue.put((epoch, chunk)))
        self._pending_publications.add(put)
        try:
            done, _ = await asyncio.wait((put, revoked), return_when=asyncio.FIRST_COMPLETED)
            if revoked in done or not self._current(epoch):
                self._discarded(epoch, chunk.sequence)
                return False
            await put
            return True
        finally:
            self._pending_publications.discard(put)
            for task in (put, revoked):
                if not task.done():
                    task.cancel()
            await asyncio.gather(put, revoked, return_exceptions=True)

    async def _playback_loop(self):
        while not self._closed:
            epoch, chunk = await self._queue.get()
            try:
                async with self._lock:
                    if not self._current(epoch):
                        self._discarded(epoch, chunk.sequence)
                        continue
                    task = asyncio.create_task(self.sink.play(chunk, epoch))
                    self._play_task = task
                try:
                    result = await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    self._record("playback_cancelled", epoch, "cancelled", sequence=chunk.sequence)
                    continue
                if not isinstance(result, PlaybackResult):
                    raise ValueError("Playback transport must return explicit playback evidence")
                if (type(result.client_played_frames) is not int or
                        not 0 <= result.client_played_frames <= chunk.frames or
                        result.output_observed_frames is not None and
                        (type(result.output_observed_frames) is not int or not 0 <= result.output_observed_frames <= chunk.frames)):
                    raise ValueError("Invalid playback receipt frame counts")
                # Preserve real acknowledgements even if interruption raced their
                # return. They remain tagged with the old epoch, never new speech.
                if result.client_played_frames:
                    self._record("client_played", epoch, "acknowledged", sequence=chunk.sequence,
                                 frames=result.client_played_frames, detail=result.detail)
                else:
                    self._record("client_played", epoch, "unknown", sequence=chunk.sequence,
                                 detail="No client playback acknowledgement")
                if result.output_observed_frames is not None:
                    self._record("output_observed", epoch, "observed", sequence=chunk.sequence,
                                 frames=result.output_observed_frames, detail="Output observation does not prove human hearing")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.receipt_error:
                    raise
                self._record("playback_failed", epoch, "unknown", sequence=chunk.sequence,
                             detail=f"{type(exc).__name__}: {exc}")
            finally:
                self._play_task = None
                self._queue.task_done()

    async def drain(self):
        await self._queue.join()

    async def close(self):
        async with self._control:
            if self._closed:
                return
            try:
                await self._cancel_output("closed")
            finally:
                self._closed = True
                for task in self._input_tasks:
                    if task is not asyncio.current_task():
                        task.cancel()
                await self._call(getattr(self.asr, "cancel", None), self._scene)
                if self._worker is not None:
                    self._worker.cancel()
                    await asyncio.gather(self._worker, return_exceptions=True)
