"""Body facts and receipts; delivery is not proof of a successful action."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import time
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Capability:
    adapter_id: str
    version: str
    operations: tuple[str, ...]
    available: bool
    scope: str
    detail: str = ""
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    adapter_id: str
    adapter_version: str
    window_id: str
    width: int
    height: int
    dpi: tuple[float, float]
    revision: str
    payload: dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=utc_now)
    monotonic_time: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ActionRequest:
    adapter_id: str
    operation: str
    observation_id: str
    scope: str
    deadline: float
    arguments: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    max_observation_age: float = 5.0
    expected_window: str | None = None
    action_id: str = field(default_factory=lambda: uuid4().hex)


class InputRejected(PermissionError):
    """A driver refused before anything was sent to the desktop.

    Distinguishing this from a transport error matters to the person asking:
    "the window was not focused, so I did not click" and "I clicked and cannot
    confirm what happened" are different answers, and the previous code turned
    both into an unverified outcome with no way to tell them apart.
    """


@dataclass(frozen=True)
class AdapterOutcome:
    status: str
    verified: bool = False
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    adapter_id: str
    operation: str
    status: str
    verified: bool
    detail: str
    observation_id: str
    timestamp: str = field(default_factory=utc_now)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SpeechEpoch:
    scene: int
    utterance: int


@dataclass(frozen=True)
class PCMChunk:
    audio: bytes
    sample_rate: int = 24000
    channels: int = 1
    sequence: int = 0

    def __post_init__(self):
        if not isinstance(self.audio, bytes) or not self.audio:
            raise ValueError("PCM must contain bytes")
        if type(self.sample_rate) is not int or not 8000 <= self.sample_rate <= 192000:
            raise ValueError("Unsupported PCM sample rate")
        if type(self.channels) is not int or self.channels not in (1, 2):
            raise ValueError("PCM must be mono or stereo")
        if len(self.audio) % (2 * self.channels):
            raise ValueError("PCM must contain complete signed 16-bit frames")
        if len(self.audio) > self.sample_rate * self.channels * 2:
            raise ValueError("Split PCM into chunks no longer than one second")

    @property
    def frames(self) -> int:
        return len(self.audio) // (2 * self.channels)


@dataclass(frozen=True)
class PlaybackResult:
    """Counts acknowledged by a client and independently observed at output.

    Neither count establishes that a person was present or heard the sound.
    Returning from a socket write alone must leave client_played_frames at 0.
    """
    client_played_frames: int = 0
    output_observed_frames: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class SpeechReceipt:
    stage: str
    epoch: SpeechEpoch
    status: str
    sequence: int = 0
    frames: int = 0
    detail: str = ""
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)
