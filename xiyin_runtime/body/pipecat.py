"""Optional frame bridge; does not install or create a Pipecat host.

Interface research: pipecat-ai/pipecat dbdf21a017f86624fb7768e35730417169524e0d,
src/pipecat/frames/frames.py and src/pipecat/transports/base_output.py.
https://github.com/pipecat-ai/pipecat/tree/dbdf21a017f86624fb7768e35730417169524e0d
Input/OutputAudioRawFrame carry signed 16-bit PCM, rate and channels;
InterruptionFrame is a priority system event. Transport cancellation/purge
still belongs to SpeechController and the connected transport, not this mapper.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util

from .models import PCMChunk, SpeechEpoch


class PipecatFrameBridge:
    def availability(self) -> dict:
        installed = importlib.util.find_spec("pipecat") is not None
        try:
            version = importlib.metadata.version("pipecat-ai") if installed else None
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return {"available": installed, "version": version, "transport_connected": False,
                "detail": "Frame conversion only; microphone/TTS/playback require explicit transports"
                if installed else "Optional pipecat-ai package is not installed"}

    @staticmethod
    def _frames():
        try:
            return importlib.import_module("pipecat.frames.frames")
        except ImportError as exc:
            raise RuntimeError("Pipecat frame support is unavailable; no package was installed automatically") from exc

    def input_frame(self, chunk: PCMChunk):
        return self._frames().InputAudioRawFrame(audio=chunk.audio, sample_rate=chunk.sample_rate,
                                                 num_channels=chunk.channels)

    def output_frame(self, chunk: PCMChunk, epoch: SpeechEpoch | None = None):
        frame = self._frames().OutputAudioRawFrame(audio=chunk.audio, sample_rate=chunk.sample_rate,
                                                  num_channels=chunk.channels)
        if epoch is not None:
            frame.metadata.update(xiyin_scene=epoch.scene, xiyin_utterance=epoch.utterance,
                                  xiyin_sequence=chunk.sequence)
        return frame

    def interruption_frame(self):
        return self._frames().InterruptionFrame()
