"""Host-bound input contracts. External adapters cannot grant owner authority."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from uuid import uuid4


OPERATIONS = frozenset({"text", "remember", "feedback", "status", "observe", "action",
                       "goal", "plan", "grow", "rollback_growth", "tick", "resume_job", "sleep", "wake", "learn", "rollback_strategy",
                       "stop", "resume", "backup", "export_dataset"})
PUBLIC_OPERATIONS = frozenset({"text", "feedback"})


@dataclass(frozen=True)
class InputEvent:
    kind: str
    payload: dict = field(default_factory=dict)
    session_id: str = "owner"
    scope: str = "private"
    request_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        if self.kind not in OPERATIONS:
            raise ValueError("Unsupported runtime operation")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.session_id):
            raise ValueError("Invalid session id")
        if self.scope not in {"private", "public"}:
            raise ValueError("Invalid scope")
        if self.scope == "public" and self.kind not in PUBLIC_OPERATIONS:
            raise PermissionError("Public adapters may not operate the owner's runtime")
        if not isinstance(self.payload, dict):
            raise ValueError("Operation payload must be an object")
        if len(json.dumps(self.payload, ensure_ascii=False, allow_nan=False)) > 2 * 1024 * 1024:
            raise ValueError("Input payload too large")

    @classmethod
    def from_local_console(cls, data):
        """Only for an already authorized local console, never a network body."""
        if not isinstance(data, dict) or set(data) - {"kind", "payload", "session_id", "scope", "request_id"}:
            raise ValueError("Unexpected console input fields")
        return cls(**data)

    @classmethod
    def from_public_adapter(cls, text, *, session_id):
        return cls("text", {"text": text}, session_id=session_id, scope="public")
