"""Replaceable body transports, verified action receipts and speech interruption."""
from .actions import DesktopAdapter, WorkspaceFileAdapter
from .models import (
    ActionReceipt, ActionRequest, AdapterOutcome, Capability, Observation,
    PCMChunk, PlaybackResult, SpeechEpoch, SpeechReceipt,
)
from .pipecat import PipecatFrameBridge
from .registry import BodyRegistry
from .speech import EnergyVAD, SpeechController
from .windows import Win32DesktopDriver, win32_desktop_adapter
from .game import GameActionSpec, TypedGameAdapter

__all__ = [
    "ActionReceipt", "ActionRequest", "AdapterOutcome", "BodyRegistry", "Capability",
    "DesktopAdapter", "EnergyVAD", "Observation", "PCMChunk", "PipecatFrameBridge",
    "PlaybackResult", "SpeechController", "SpeechEpoch", "SpeechReceipt", "WorkspaceFileAdapter",
    "Win32DesktopDriver", "win32_desktop_adapter",
    "GameActionSpec", "TypedGameAdapter",
]
