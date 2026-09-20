"""Persistent priority jobs with explicit resume and conservative crash recovery."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .experience import ExperienceStore, _scope, _text


JOB_STATUSES = frozenset({"queued", "running", "paused", "completed", "failed", "cancelled", "unknown"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "unknown"})


def _now():
    return datetime.now(timezone.utc).isoformat()


class Agenda:
    def __init__(self, store: ExperienceStore):
        self.store = store

    def enqueue(self, kind, payload, priority=0, scope="private", *, resumable=False):
        """Only explicitly checkpointable internal work may opt into resumption.

        External actions must remain nonresumable until an executor can prove
        its cursor has safe retry semantics. Unknown results need reconciliation.
        """
        kind, scope = _text(kind, "job kind"), _scope(scope)
        if type(priority) is not int or not isinstance(payload, dict) or type(resumable) is not bool:
            raise ValueError("job requires integer priority, object payload and boolean resumable")
        job = {"id": "job_" + uuid4().hex, "kind": kind, "payload": payload,
               "priority": priority, "scope": scope, "status": "queued", "cursor": None,
               "result": None, "resumable": resumable, "attempts": 0,
               "created_at": _now(), "updated_at": _now()}
        return self.store.write_document("jobs", job["id"], job, expected_version=0)["value"]

    def _read(self, job_id):
        envelope = self.store.read_document("jobs", job_id)
        if envelope is None:
            raise KeyError(job_id)
        return envelope

    def get(self, job_id):
        return self._read(job_id)["value"]

    def _write(self, envelope, **changes):
        value = dict(envelope["value"], **changes, updated_at=_now())
        return self.store.write_document("jobs", envelope["key"], value,
                                         expected_version=envelope["version"])["value"]

    def claim_next(self):
        with self.store.document_transaction():
            jobs = self.store.list_documents("jobs")
            if any(item["value"]["status"] == "running" for item in jobs):
                return None
            queued = [item for item in jobs if item["value"]["status"] == "queued"]
            if not queued:
                return None
            # Stable sort keeps creation order for equal priorities.
            item = sorted(queued, key=lambda item: -item["value"]["priority"])[0]
            return self._write(item, status="running", attempts=item["value"]["attempts"] + 1)

    def finish(self, job_id, status, result=None, cursor=None):
        if status not in JOB_STATUSES - {"queued", "running"}:
            raise ValueError("invalid job finish status")
        with self.store.document_transaction():
            item = self._read(job_id)
            previous = item["value"]
            if previous["status"] in TERMINAL_STATUSES:
                if status == previous["status"] and (result is None or result == previous["result"]) and (
                        cursor is None or cursor == previous["cursor"]):
                    return previous
                raise ValueError("terminal job cannot be rewritten")
            if previous["status"] != "running" and status != "cancelled":
                raise ValueError("only running jobs may finish; queued/paused jobs may be cancelled")
            if status == "paused" and not previous["resumable"]:
                status = "unknown"
            return self._write(item, status=status, result=result,
                               cursor=previous["cursor"] if cursor is None else cursor)

    def checkpoint(self, job_id, cursor):
        with self.store.document_transaction():
            item = self._read(job_id)
            if item["value"]["status"] != "running" or not item["value"]["resumable"]:
                raise ValueError("only running resumable jobs may checkpoint")
            return self._write(item, cursor=cursor)

    def resume(self, job_id):
        with self.store.document_transaction():
            item = self._read(job_id)
            if item["value"]["status"] != "paused" or not item["value"]["resumable"]:
                raise ValueError("only paused checkpointable jobs may resume")
            return self._write(item, status="queued")

    def pause_active(self, reason):
        reason = _text(reason, "pause reason")
        with self.store.document_transaction():
            return [self._write(item, status="paused" if item["value"]["resumable"] else "unknown",
                                result={"reason": reason}) for item in self.store.list_documents("jobs")
                    if item["value"]["status"] == "running"]

    def recover(self):
        """Call at exclusive runtime startup, never to steal a live worker's job."""
        return self.pause_active("runtime restarted; unfinished work requires explicit resume or reconciliation")

    def stop(self, reason="runtime stopped"):
        """Cancel work not yet dispatched; running work retains uncertain effects."""
        reason = _text(reason, "stop reason")
        with self.store.document_transaction():
            changes = self.pause_active(reason)
            for item in self.store.list_documents("jobs"):
                if item["value"]["status"] in {"queued", "paused"}:
                    changes.append(self._write(item, status="cancelled", result={"reason": reason}))
            return changes
