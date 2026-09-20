"""Persistent light consolidation; elapsed sleeping time invents no events."""
from __future__ import annotations

from datetime import datetime, timezone
import threading


PHASES = {"awake", "settling", "consolidating", "sleeping", "waking"}


class SleepController:
    def __init__(self, store, agenda=None):
        self.store, self.agenda = store, agenda
        self._wake = threading.Event()
        self._lock = threading.RLock()

    def state(self):
        document = self.store.read_document("state", "sleep")
        return document["value"] if document else {"phase": "awake", "transitions": [], "interrupted": False}

    def _transition(self, phase, **fields):
        if phase not in PHASES:
            raise ValueError("Unknown sleep phase")
        with self._lock:
            document = self.store.read_document("state", "sleep")
            current = document["value"] if document else self.state()
            value = {**current, **fields, "phase": phase,
                     "transitions": (current.get("transitions", []) + [{"phase": phase,
                                      "at": datetime.now(timezone.utc).isoformat()}])[-32:]}
            return self.store.write_document("state", "sleep", value,
                                              expected_version=document["version"] if document else 0)["value"]

    def settle(self):
        with self._lock:
            if self.state()["phase"] not in {"awake", "sleeping"}:
                raise RuntimeError("Sleep transition is already in progress")
            self._wake.clear()
            return self._transition("settling", interrupted=False)

    def consolidate(self, session_id="owner", scope="private", max_events=100, *, job_id=None):
        if type(max_events) is not int or not 1 <= max_events <= 1000:
            raise ValueError("Consolidation batch must contain 1..1000 events")
        with self._lock:
            if self.state()["phase"] != "settling" or self._wake.is_set():
                raise RuntimeError("Settle before consolidation; a wake request prevents background work")
            self._transition("consolidating")
        key = "sleep_" + scope + "_" + session_id
        checkpoint = self.store.read_document("checkpoints", key)
        last_seq = checkpoint["value"].get("last_seq", 0) if checkpoint else 0
        records = [event for event in self.store.list_events(session_id, scope=scope) if event["seq"] > last_seq][:max_events]
        excerpts = []
        for event in records:
            if self._wake.is_set():
                return {"interrupted": True, "checkpoint": checkpoint["value"] if checkpoint else None}
            # This summarizes actual utterances, not facts asserted by them.
            if event["kind"] in {"user", "assistant", "user_turn", "assistant_turn"}:
                excerpts.append({"event_id": event["id"], "speaker": event["kind"],
                                 "status": event["status"], "origin": event["origin"],
                                 "quoted_excerpt": event["content"][:240],
                                 "excerpt_truncated": len(event["content"]) > 240})
        pending = [{"id": item["key"], "status": item["value"].get("status"),
                    "cursor": item["value"].get("cursor")} for item in self.store.list_documents("jobs")
                   if item["value"].get("scope") == scope
                   and item["value"].get("status") in {"queued", "running", "paused", "unknown"}]
        with self._lock:
            if self._wake.is_set() or self.state()["phase"] != "consolidating":
                return {"interrupted": True, "checkpoint": checkpoint["value"] if checkpoint else None}
            value = {"session_id": session_id, "scope": scope,
                     "last_seq": records[-1]["seq"] if records else last_seq,
                     "kind": "conversation_excerpt_index", "not_verified_facts": True,
                     "excerpts": ((checkpoint["value"].get("excerpts", []) if checkpoint else []) + excerpts)[-100:],
                     "pending_jobs": pending,
                     "source_event_ids": [event["id"] for event in records]}
            result = self.store.write_document("checkpoints", key, value,
                                               expected_version=checkpoint["version"] if checkpoint else 0)
            if job_id is not None and self.agenda is not None:
                self.agenda.finish(job_id, "completed", result={"checkpoint": key}, cursor={"last_seq": value["last_seq"]})
            self._transition("settling", last_checkpoint=key)
            return {"interrupted": False, "checkpoint": result["value"]}

    def sleep(self):
        with self._lock:
            if self._wake.is_set() or self.state()["phase"] != "settling":
                raise RuntimeError("Only a settled controller may enter sleep")
            return self._transition("sleeping")

    def wake(self, reason="foreground input"):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError("A short wake reason is required")
        self._wake.set()  # Preempt consolidation before waiting on its commit lock.
        if self.agenda is not None:
            self.agenda.pause_active(reason)
        with self._lock:
            self._transition("waking", interrupted=True, wake_reason=reason)
            return self._transition("awake")
