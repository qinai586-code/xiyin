"""Real controller/queue races with deterministic ASR/TTS/playback transports."""
import asyncio
import struct
import unittest

from xiyin_runtime.body import EnergyVAD, PCMChunk, PlaybackResult, SpeechController


def pcm(sequence=0, amplitude=2000, frames=240):
    return PCMChunk(struct.pack("<h", amplitude) * frames, 24000, 1, sequence)


class Sink:
    def __init__(self, *, blocking=False, observed=False):
        self.blocking = blocking
        self.observed = observed
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def set_gain(self, gain):
        self.calls.append(("gain", gain))

    async def play(self, chunk, epoch):
        self.calls.append(("play", epoch, chunk.sequence))
        self.started.set()
        if self.blocking:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.calls.append(("play_cancelled", epoch, chunk.sequence))
                raise
        return PlaybackResult(chunk.frames, chunk.frames if self.observed else None)

    async def stop(self):
        self.calls.append(("stop",))
        self.release.set()

    async def purge(self):
        self.calls.append(("purge",))


class TTS:
    def __init__(self, *, blocking=False, chunks=1):
        self.blocking, self.chunks = blocking, chunks
        self.started = asyncio.Event()
        self.cancelled = []
        self.generator_cancelled = False

    async def synthesize(self, text, epoch, cancel):
        self.started.set()
        try:
            for number in range(self.chunks):
                yield pcm(number)
            if self.blocking:
                await asyncio.Event().wait()
        finally:
            self.generator_cancelled = True

    async def cancel(self, epoch):
        self.cancelled.append(epoch)


class ASR:
    def __init__(self):
        self.calls = []
        self.cancelled = []

    async def accept_audio(self, chunk, scene):
        self.calls.append((scene, chunk.sequence))
        return [{"kind": "final_transcript", "text": "用户说话"}]

    async def cancel(self, scene):
        self.cancelled.append(scene)


class SpeechBodyTests(unittest.IsolatedAsyncioTestCase):
    def controller(self, **kwargs):
        value = SpeechController(**kwargs)
        self.addAsyncCleanup(value.close)
        return value

    async def test_candidate_ducks_without_cancelling_and_rejection_restores_gain(self):
        sink, tts, generated_cancel = Sink(blocking=True), TTS(blocking=True), []
        controller = self.controller(sink=sink, tts=tts, generation_cancel=lambda epoch: generated_cancel.append(epoch))
        epoch = await controller.begin()
        synthesis = asyncio.create_task(controller.submit_text("仍然在生成", epoch))
        await asyncio.wait_for(sink.started.wait(), 1)
        await controller.candidate_interrupt()
        self.assertIn(("gain", 0.15), sink.calls)
        self.assertFalse(generated_cancel)
        self.assertFalse(tts.cancelled)
        self.assertFalse(synthesis.done())
        await controller.reject_interrupt()
        self.assertEqual(sink.calls[-1], ("gain", 1.0))
        await controller.cancel()
        await asyncio.gather(synthesis, return_exceptions=True)

    async def test_confirm_cancels_real_tasks_stops_and_purges_queue_without_late_audio(self):
        sink, tts, cancelled = Sink(blocking=True), TTS(blocking=True, chunks=4), []
        controller = self.controller(sink=sink, tts=tts, generation_cancel=lambda epoch: cancelled.append(epoch))
        epoch = await controller.begin()
        synthesis = asyncio.create_task(controller.submit_text("四个语音片段", epoch))
        await asyncio.wait_for(sink.started.wait(), 1)
        for _ in range(20):
            if controller.queued_chunks >= 3:
                break
            await asyncio.sleep(0)
        await controller.candidate_interrupt()
        result = await controller.confirm_interrupt()
        await asyncio.gather(synthesis, return_exceptions=True)
        self.assertEqual(cancelled, [epoch])
        self.assertEqual(tts.cancelled, [epoch])
        self.assertTrue(tts.generator_cancelled)
        self.assertGreaterEqual(result["local_chunks_purged"], 1)
        self.assertIn(("stop",), sink.calls)
        self.assertIn(("purge",), sink.calls)
        self.assertEqual(controller.queued_chunks, 0)
        self.assertFalse(await controller.publish_audio(pcm(99), epoch))
        plays = [call for call in sink.calls if call[0] == "play"]
        self.assertEqual(len(plays), 1)
        new_epoch = await controller.begin()
        sink.blocking = False
        self.assertTrue(await controller.publish_audio(pcm(100), new_epoch))
        await asyncio.wait_for(controller.drain(), 1)
        self.assertEqual([call for call in sink.calls if call[0] == "play"][-1][1], new_epoch)

    async def test_cancel_unblocks_a_full_audio_queue(self):
        sink = Sink(blocking=True)
        controller = self.controller(sink=sink, queue_size=1)
        epoch = await controller.begin()
        await controller.publish_audio(pcm(0), epoch)
        await asyncio.wait_for(sink.started.wait(), 1)
        await controller.publish_audio(pcm(1), epoch)
        blocked = asyncio.create_task(controller.publish_audio(pcm(2), epoch))
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())
        await controller.confirm_interrupt()
        self.assertFalse(await asyncio.wait_for(blocked, 1))
        await asyncio.wait_for(controller.drain(), 1)
        self.assertEqual(len([call for call in sink.calls if call[0] == "play"]), 1)

    async def test_scene_epoch_discards_old_text_audio_and_asr_results(self):
        asr = ASR()
        controller = self.controller(asr=asr, sink=Sink(), tts=TTS())
        old = await controller.begin()
        await controller.new_scene()
        new = await controller.begin()
        self.assertNotEqual(old.scene, new.scene)
        self.assertFalse(await controller.submit_text("旧场景", old))
        self.assertFalse(await controller.publish_audio(pcm(), old))
        self.assertTrue(await controller.submit_text("新场景", new))
        await asyncio.wait_for(controller.drain(), 1)
        self.assertEqual(asr.cancelled, [old.scene])

    async def test_input_keeps_flowing_during_output_cancellation(self):
        asr = ASR()
        controller = self.controller(asr=asr, sink=Sink(blocking=True))
        epoch = await controller.begin()
        await controller.publish_audio(pcm(), epoch)
        await controller.submit_pcm(pcm(1))
        await controller.confirm_interrupt()
        await controller.submit_pcm(pcm(2))
        self.assertEqual(asr.calls, [(0, 1), (0, 2)])
        self.assertEqual(len([event for event in controller.input_events if event["kind"] == "final_transcript"]), 2)

    async def test_late_asr_completion_after_scene_switch_is_not_added_to_new_scene(self):
        started = asyncio.Event()
        asr = ASR()

        async def late_audio(chunk, scene):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return [{"kind": "final_transcript", "text": "old scene"}]

        asr.accept_audio = late_audio
        controller = self.controller(asr=asr)
        pending = asyncio.create_task(controller.submit_pcm(pcm()))
        await asyncio.wait_for(started.wait(), 1)
        await controller.new_scene()
        self.assertEqual(await asyncio.wait_for(pending, 1), [])
        self.assertFalse(any(event.get("text") == "old scene" for event in controller.input_events))

    async def test_receipts_distinguish_text_synthesis_playback_and_output_observation(self):
        controller = self.controller(sink=Sink(observed=True), tts=TTS())
        epoch = await controller.begin()
        await controller.submit_text("你好", epoch)
        await asyncio.wait_for(controller.drain(), 1)
        stages = [receipt.stage for receipt in controller.receipts]
        self.assertEqual(stages, ["generated", "synthesized", "client_played", "output_observed"])
        self.assertNotIn("human_heard", stages)
        self.assertIn("does not prove", controller.receipts[-1].detail)
        silent = self.controller()
        token = await silent.begin()
        self.assertFalse(await silent.submit_text("只有文字", token))
        self.assertEqual(silent.receipts[-1].status, "unavailable")
        self.assertFalse(silent.availability()["playback"]["available"])

    async def test_send_only_sink_cannot_create_played_receipt(self):
        sink = Sink()

        async def sent_only(chunk, epoch):
            return PlaybackResult()

        sink.play = sent_only
        controller = self.controller(sink=sink)
        epoch = await controller.begin()
        await controller.publish_audio(pcm(), epoch)
        await controller.drain()
        self.assertEqual(controller.receipts[-1].status, "unknown")
        self.assertFalse(any(receipt.stage == "output_observed" for receipt in controller.receipts))

    async def test_energy_events_duck_then_confirm_and_do_not_claim_echo_cancellation(self):
        sink = Sink(blocking=True)
        controller = self.controller(sink=sink, vad=EnergyVAD(candidate_ms=20, confirm_ms=40))
        epoch = await controller.begin()
        await controller.publish_audio(pcm(), epoch)
        await asyncio.wait_for(sink.started.wait(), 1)
        await controller.submit_pcm(pcm(frames=480))
        self.assertEqual(controller.active_epoch, epoch)
        await controller.submit_pcm(pcm(frames=480))
        self.assertEqual(controller.active_epoch, epoch)
        self.assertTrue(any(event["kind"] == "confirmation_needs_echo_control" for event in controller.input_events))
        await controller.submit_pcm(pcm(frames=960), echo_suppressed=True)
        self.assertIsNone(controller.active_epoch)

    async def test_control_timeout_does_not_keep_accepting_old_chunks(self):
        sink = Sink()

        async def slow_stop():
            await asyncio.Event().wait()

        sink.stop = slow_stop
        controller = self.controller(sink=sink, control_timeout=0.01)
        epoch = await controller.begin()
        result = await asyncio.wait_for(controller.confirm_interrupt(), 0.5)
        self.assertEqual(result["transports"]["stop"]["status"], "unknown")
        self.assertFalse(await controller.publish_audio(pcm(), epoch))

    async def test_receipt_callback_receives_late_playback_and_failure_is_not_silenced(self):
        saved = []
        controller = self.controller(sink=Sink(observed=True), tts=TTS(), receipt_callback=saved.append)
        epoch = await controller.begin()
        await controller.submit_text("test", epoch)
        await controller.drain()
        self.assertEqual([receipt.stage for receipt in saved], ["generated", "synthesized", "client_played", "output_observed"])
        sink = Sink()

        def cannot_persist(receipt):
            raise OSError("ledger unavailable")

        broken = SpeechController(sink=sink, receipt_callback=cannot_persist)
        token = await broken.begin()
        with self.assertRaisesRegex(RuntimeError, "persistence failed"):
            await broken.submit_text("must not fake a saved receipt", token)
        self.assertIn("ledger unavailable", broken.receipt_error)
        with self.assertRaises(RuntimeError):
            await broken.close()
        self.assertIn(("stop",), sink.calls)
        self.assertTrue(broken._closed)

    async def test_asr_final_cannot_bypass_playback_echo_gate(self):
        sink, asr = Sink(blocking=True), ASR()
        controller = self.controller(sink=sink, asr=asr)
        epoch = await controller.begin()
        await controller.publish_audio(pcm(), epoch)
        await asyncio.wait_for(sink.started.wait(), 1)
        blocked = await controller.submit_pcm(pcm(1), echo_suppressed=False)
        self.assertFalse(next(event for event in blocked if event["kind"] == "final_transcript")["accepted"])
        accepted = await controller.submit_pcm(pcm(2), echo_suppressed=True)
        self.assertTrue(next(event for event in accepted if event["kind"] == "final_transcript")["accepted"])
        await controller.cancel()
        while controller._play_task is not None:
            await asyncio.sleep(0)
        after = await controller.submit_pcm(pcm(3))
        self.assertTrue(next(event for event in after if event["kind"] == "final_transcript")["accepted"])

    async def test_sync_generation_revocation_precedes_tts_child_cleanup(self):
        order = []
        entered = asyncio.Event()

        class WaitingTTS(TTS):
            async def synthesize(self, text, epoch, cancel):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                    yield pcm()
                finally:
                    order.append("tts_cleanup")

        def revoke_generation(epoch):
            order.append("generation_revoked")
            return True

        controller = self.controller(sink=Sink(), tts=WaitingTTS(), generation_cancel=revoke_generation)
        epoch = await controller.begin()
        child = asyncio.create_task(controller.submit_text("wait", epoch))
        await entered.wait()
        result = await controller.confirm_interrupt()
        await asyncio.gather(child, return_exceptions=True)
        self.assertLess(order.index("generation_revoked"), order.index("tts_cleanup"))
        self.assertEqual(result["transports"]["generation"]["status"], "acknowledged")
        self.assertEqual(result["transports"]["stop"]["status"], "requested")


if __name__ == "__main__":
    unittest.main()
