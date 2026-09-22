"""A local, single-owner experience ledger and versioned memory projection.

Events belong to one session; memories are explicitly promoted, durable
knowledge for this owner/character pair. Scope must come from the trusted
caller, never from text or model-provided metadata. This module is storage,
not authentication. One connection is serialized by a reentrant lock.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


SCOPES = frozenset({"private", "public"})
STATUSES = frozenset({"recorded", "generated", "complete", "completed", "partial",
                      "cancelled", "failed", "verified_success", "verified_failure", "unknown"})
ORIGINS = frozenset({"observation", "user_report", "user_statement", "owner_statement", "assistant_output",
                     "tool_result", "generated", "reflection", "inference", "simulation", "design_seed"})
MEMORY_KINDS = frozenset({"fact", "preference", "opinion", "relationship", "persona", "strategy", "skill", "goal"})
INCOMPLETE = frozenset({"generated", "partial", "cancelled", "failed", "unknown"})
NON_EVIDENCE = frozenset({"generated", "reflection", "inference", "simulation", "design_seed"})
DOCUMENT_COLLECTIONS = frozenset({"state", "jobs", "goals", "candidates", "releases", "checkpoints"})


class DocumentConflict(RuntimeError):
    """The requested document version no longer owns this update."""


class DocumentCorruptionError(RuntimeError):
    """A persisted document cannot be safely interpreted; never reset it silently."""


def _document_key(collection, key):
    if collection not in DOCUMENT_COLLECTIONS:
        raise ValueError("unsupported document collection")
    key = _text(key, "document key")
    if len(key) > 240 or any(ord(char) < 32 for char in key):
        raise ValueError("invalid document key")
    return key


def _json_object(value):
    if not isinstance(value, dict):
        raise ValueError("document value must be a JSON object")
    # Refuse lossy key conversion, nonfinite numbers and non-JSON objects.
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("document contains a non-JSON value")
    try:
        check(value)
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"invalid document JSON: {exc}") from exc


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be non-empty text without NUL")
    return value.strip()


def _scope(value: str) -> str:
    if value not in SCOPES:
        raise ValueError("scope must be private or public")
    return value


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    return value


class ExperienceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('private', 'public')),
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_id TEXT
                );
                CREATE INDEX IF NOT EXISTS events_session_scope ON events(session_id, scope, seq);
                CREATE TABLE IF NOT EXISTS memories (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('private', 'public')),
                    statement TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    supersedes TEXT REFERENCES memories(id),
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
                );
                CREATE INDEX IF NOT EXISTS memories_scope_active ON memories(scope, active, seq);
                CREATE UNIQUE INDEX IF NOT EXISTS memories_one_successor ON memories(supersedes)
                    WHERE supersedes IS NOT NULL;
                CREATE TABLE IF NOT EXISTS documents (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    key TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version > 0),
                    value TEXT NOT NULL,
                    UNIQUE(collection, key)
                );
            """)

    def __enter__(self) -> "ExperienceStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("experience store is closed")

    @contextmanager
    def document_transaction(self):
        """Short atomic document operations, serialized across SQLite connections.

        Nested document writes use savepoints. Do not perform model calls or
        existing legacy ``with connection`` writers inside this transaction.
        """
        with self._lock:
            self._ensure_open()
            nested = self._db.in_transaction
            savepoint = "document_" + uuid4().hex
            self._db.execute("SAVEPOINT " + savepoint if nested else "BEGIN IMMEDIATE")
            try:
                yield
                if nested:
                    self._db.execute("RELEASE " + savepoint)
                else:
                    self._db.commit()
            except BaseException:
                if nested:
                    self._db.execute("ROLLBACK TO " + savepoint)
                    self._db.execute("RELEASE " + savepoint)
                else:
                    self._db.rollback()
                raise

    @staticmethod
    def _document_envelope(row):
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError("nonfinite JSON number")
        try:
            value = json.loads(row["value"], object_pairs_hook=pairs, parse_constant=invalid_constant)
            if not isinstance(value, dict) or type(row["version"]) is not int or row["version"] < 1:
                raise ValueError("invalid document object or version")
            _json_object(value)
        except (TypeError, ValueError, RecursionError) as exc:
            raise DocumentCorruptionError(f"Cannot read {row['collection']}/{row['key']}: {exc}") from exc
        return {"key": row["key"], "version": row["version"], "value": value}

    def read_document(self, collection: str, key: str) -> dict | None:
        key = _document_key(collection, key)
        with self._lock:
            self._ensure_open()
            row = self._db.execute("SELECT * FROM documents WHERE collection=? AND key=?", (collection, key)).fetchone()
            return self._document_envelope(row) if row is not None else None

    def list_documents(self, collection: str) -> list[dict]:
        _document_key(collection, "validate")
        with self._lock:
            self._ensure_open()
            return [self._document_envelope(row) for row in self._db.execute(
                "SELECT * FROM documents WHERE collection=? ORDER BY seq", (collection,))]

    def write_document(self, collection: str, key: str, value: dict,
                       expected_version: int | None = None) -> dict:
        """Write JSON and its ledger receipt atomically; 0 means create-only.

        None is an unconditional update, not permission to reset corrupt data.
        Callers deriving state from a read must supply its observed version.
        """
        key = _document_key(collection, key)
        if expected_version is not None and (type(expected_version) is not int or expected_version < 0):
            raise ValueError("expected_version must be a nonnegative integer or None")
        serialized = _json_object(value)
        with self.document_transaction():
            prior = self.read_document(collection, key)
            current = prior["version"] if prior else 0
            if expected_version is not None and expected_version != current:
                raise DocumentConflict(f"{collection}/{key}: expected {expected_version}, found {current}")
            version = current + 1
            self._db.execute("INSERT INTO documents(collection,key,version,value) VALUES (?,?,?,?) "
                             "ON CONFLICT(collection,key) DO UPDATE SET version=excluded.version,value=excluded.value",
                             (collection, key, version, serialized))
            self._insert_event("document_updated", json.dumps({"collection": collection, "key": key, "version": version}),
                               "system", _scope(value.get("scope", "private")), "tool_result", "verified_success")
            return {"key": key, "version": version, "value": json.loads(serialized)}

    def append_event(self, kind: str, content: str | dict, *, session_id: str,
                     scope: str = "private", origin: str = "observation",
                     status: str = "recorded", request_id: str | None = None) -> str:
        kind = _text(kind, "kind")
        session_id = _text(session_id, "session_id")
        scope = _scope(scope)
        if origin not in ORIGINS:
            raise ValueError("unsupported event origin")
        if status not in STATUSES:
            raise ValueError("unsupported event status")
        if not isinstance(content, (str, dict)):
            raise ValueError("content must be text or an event object")
        # Metadata in a content object is deliberately never promoted to columns.
        serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if "\x00" in serialized:
            raise ValueError("content cannot contain NUL")
        if request_id is not None:
            request_id = _text(request_id, "request_id")
        with self._lock:
            self._ensure_open()
            with self._db:
                event_id = self._insert_event(kind, serialized, session_id, scope, origin, status, request_id)
        return event_id

    def _insert_event(self, kind, content, session_id, scope, origin, status, request_id=None):
        """Insert validated data inside the caller's lock and transaction."""
        event_id = "event_" + uuid4().hex
        self._db.execute(
            "INSERT INTO events(id, created_at, session_id, scope, kind, content, origin, status, request_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat(), session_id, scope, kind,
             content, origin, status, request_id),
        )
        return event_id

    def list_events(self, session_id: str, scope: str = "private") -> list[dict]:
        """Return the session ledger including failures and partial/cancelled output."""
        session_id, scope = _text(session_id, "session_id"), _scope(scope)
        with self._lock:
            self._ensure_open()
            return [dict(row) for row in self._db.execute(
                "SELECT * FROM events WHERE session_id = ? AND scope = ? ORDER BY seq", (session_id, scope))]

    def history(self, session_id: str, scope: str = "private", limit: int = 12) -> list[dict]:
        """Return chronological complete text messages, never unfinished assistant turns.

        Request-linked user inputs enter dialogue history only with a completed
        reply. Failed, cancelled and interrupted requests stay in the ledger,
        rather than leaving unanswered instructions in the next conversation.
        Legacy inputs without a request id retain their observation semantics.
        Assistant generation becomes history after ``complete/completed``.
        Completed text with origin=generated is a complete textual response,
        not evidence of audio playback, human attention or a successful action.
        Extra metadata can be stripped to role/content by an API adapter.
        """
        session_id, scope, limit = _text(session_id, "session_id"), _scope(scope), _limit(limit)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute("""
                SELECT * FROM events AS message WHERE session_id = ? AND scope = ? AND (
                    (kind IN ('user', 'user_turn') AND status IN ('recorded', 'complete', 'completed')
                     AND (request_id IS NULL OR EXISTS (
                         SELECT 1 FROM events AS reply
                         WHERE reply.request_id = message.request_id
                           AND reply.session_id = message.session_id AND reply.scope = message.scope
                           AND reply.kind IN ('assistant', 'assistant_turn')
                           AND reply.status IN ('complete', 'completed')
                           AND reply.origin NOT IN ('simulation', 'design_seed', 'reflection', 'inference')
                     ))) OR
                    (kind IN ('assistant', 'assistant_turn') AND status IN ('complete', 'completed'))
                ) AND origin NOT IN ('simulation', 'design_seed', 'reflection', 'inference')
                ORDER BY seq DESC LIMIT ?
            """, (session_id, scope, limit)).fetchall()
        return [{"role": "user" if row["kind"] in {"user", "user_turn"} else "assistant",
                 "content": row["content"], "event_id": row["id"], "scope": row["scope"],
                 "origin": row["origin"], "status": row["status"]} for row in reversed(rows)]

    def operation_receipts(self, session_id: str, scope: str = "private", limit: int = 2) -> list[dict]:
        """Read existing memory-operation receipts, not statements about success.

        These are ordinary ledger events; no migration or inferred historical
        receipts are created for records written by earlier versions.
        """
        session_id, scope, limit = _text(session_id, "session_id"), _scope(scope), _limit(limit)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT * FROM events WHERE session_id = ? AND scope = ? AND kind = 'memory_operation' "
                "AND origin = 'tool_result' AND status IN ('verified_success', 'verified_failure') "
                "ORDER BY seq DESC LIMIT ?", (session_id, scope, limit)).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            item["content"] = json.loads(item["content"])
            result.append(item)
        return result

    def action_receipts(self, session_id: str, scope: str = "private", limit: int = 3) -> list[dict]:
        """Read executor receipts for body actions, in chronological order.

        These are the records that answer "did that actually happen". They are
        read exactly like memory receipts: no inference, no reconstruction for
        actions that were recorded before this method existed.
        """
        session_id, scope, limit = _text(session_id, "session_id"), _scope(scope), _limit(limit)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT * FROM events WHERE session_id = ? AND scope = ? AND kind = 'action_result' "
                "AND origin = 'tool_result' ORDER BY seq DESC LIMIT ?", (session_id, scope, limit)).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item["content"] = json.loads(item["content"])
            except (ValueError, RecursionError):
                continue  # A malformed receipt is not projected as an outcome.
            result.append(item)
        return result

    def remember(self, statement: str, *, kind: str = "fact", subject: str = "owner",
                 scope: str = "private", evidence_refs: list[str], supersedes: str | None = None,
                 receipt_session_id: str | None = None) -> str:
        """Promote supported knowledge; corrections atomically retire the prior version.

        A source proves that a statement/observation occurred, not that arbitrary
        claims inside it are true. The caller decides what is justified by it.
        """
        statement, subject, scope = _text(statement, "statement"), _text(subject, "subject"), _scope(scope)
        if receipt_session_id is not None:
            receipt_session_id = _text(receipt_session_id, "receipt_session_id")
        if kind not in MEMORY_KINDS:
            raise ValueError("unsupported memory kind")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise ValueError("memory requires existing evidence_refs")
        refs = list(dict.fromkeys(_text(ref, "evidence_ref") for ref in evidence_refs))
        memory_id = "memory_" + uuid4().hex
        with self._lock:
            self._ensure_open()
            with self.document_transaction():
                origins = []
                for ref in refs:
                    source = self._db.execute("SELECT * FROM events WHERE id = ?", (ref,)).fetchone()
                    if source is not None:
                        unfinished_assistant = (source["kind"] in {"assistant", "assistant_turn"}
                                                and source["status"] not in {"complete", "completed"})
                        if (source["scope"] != scope or source["status"] in INCOMPLETE
                                or source["origin"] in NON_EVIDENCE or unfinished_assistant):
                            raise ValueError("evidence is incomplete, generated, or outside the memory scope")
                        origins.append(source["origin"])
                    else:
                        source = self._db.execute("SELECT * FROM memories WHERE id = ? AND active = 1", (ref,)).fetchone()
                        if source is None or source["scope"] != scope:
                            raise ValueError("memory evidence must exist and have the same scope")
                        origins.append(source["origin"])
                if supersedes is not None:
                    prior = self._db.execute("SELECT * FROM memories WHERE id = ? AND active = 1", (supersedes,)).fetchone()
                    if prior is None or (prior["scope"], prior["kind"], prior["subject"]) != (scope, kind, subject):
                        raise ValueError("supersedes must be an active memory of the same scope, kind and subject")
                    self._db.execute("UPDATE memories SET active = 0 WHERE id = ?", (supersedes,))
                origin = origins[0] if len(set(origins)) == 1 else "mixed_evidence"
                self._db.execute("""
                    INSERT INTO memories(id, created_at, kind, subject, scope, statement, origin, evidence_refs, supersedes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (memory_id, datetime.now(timezone.utc).isoformat(), kind, subject, scope, statement,
                     origin, json.dumps(refs), supersedes))
                if receipt_session_id is not None:
                    # The receipt and memory commit together. An insertion error
                    # cannot leave a changed memory paired with a failure receipt.
                    receipt = {"operation": "replace" if supersedes else "remember", "success": True,
                               "memory_id": memory_id, "statement": statement,
                               "evidence_refs": refs, "supersedes": supersedes}
                    self._insert_event("memory_operation", json.dumps(receipt, ensure_ascii=False),
                                       receipt_session_id, scope, "tool_result", "verified_success")
        return memory_id

    def retract_memory(self, memory_id: str, *, receipt_session_id: str) -> dict:
        """Retire an active projection without deleting its history or evidence.

        This is used for explicit growth rollback to a design seed. A retired
        memory is never represented as a new lived experience or reactivated.
        """
        memory_id = _text(memory_id, "memory_id")
        session_id = _text(receipt_session_id, "receipt_session_id")
        with self.document_transaction():
            prior = self._db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if prior is None or not prior["active"]:
                raise ValueError("Only an active memory may be retracted")
            self._db.execute("UPDATE memories SET active=0 WHERE id=? AND active=1", (memory_id,))
            receipt = {"operation": "retract", "success": True, "memory_id": memory_id,
                       "statement": prior["statement"], "evidence_refs": json.loads(prior["evidence_refs"]),
                       "supersedes": None}
            self._insert_event("memory_operation", json.dumps(receipt, ensure_ascii=False),
                               session_id, prior["scope"], "tool_result", "verified_success")
            return receipt

    @staticmethod
    def _memory_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        result["active"] = bool(result["active"])
        return result

    def memories(self, scope: str = "private", kind: str | None = None) -> list[dict]:
        scope = _scope(scope)
        if kind is not None and kind not in MEMORY_KINDS:
            raise ValueError("unsupported memory kind")
        sql, params = "SELECT * FROM memories WHERE scope = ? AND active = 1", [scope]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        with self._lock:
            self._ensure_open()
            return [self._memory_dict(row) for row in self._db.execute(sql + " ORDER BY seq", params)]

    def search(self, query: str, *, scope: str = "private", session_id: str | None = None,
               limit: int = 5) -> list[dict]:
        """Lexical recall with Chinese bigrams; no embedding service or network.

        Without a session_id only explicitly promoted long-term memories are
        searched. Session observations are historical evidence, not current
        facts. Incomplete and imagined events never enter ordinary retrieval.
        """
        query, scope, limit = _text(query, "query"), _scope(scope), _limit(limit)
        if session_id is not None:
            session_id = _text(session_id, "session_id")
        if len(query) > 2000:
            raise ValueError("query is too long")
        terms = [query.casefold()]
        for token in re.findall(r"[\w]+", query.casefold()):
            terms.append(token)
            if re.search(r"[\u3400-\u9fff]", token):
                terms.extend(token[i:i + 2] for i in range(len(token) - 1))
        terms = list(dict.fromkeys(terms))[:64]
        # Parameterized instr supports Chinese without requiring a particular
        # SQLite FTS tokenizer, including common two-character queries.
        predicate = " OR ".join("instr(lower({column}), ?) > 0" for _ in terms)
        with self._lock:
            self._ensure_open()
            candidates = []
            for row in self._db.execute(
                "SELECT * FROM memories WHERE scope = ? AND active = 1 AND ("
                + predicate.format(column="statement") + ")", [scope, *terms]
            ):
                item = self._memory_dict(row)
                item.update({"source": "memory", "content": item["statement"]})
                candidates.append(item)
            if session_id is not None:
                rows = self._db.execute(
                    "SELECT * FROM events WHERE scope = ? AND session_id = ? AND status NOT IN "
                    "('generated', 'partial', 'cancelled', 'failed', 'unknown') AND origin NOT IN "
                    "('generated', 'reflection', 'inference', 'simulation', 'design_seed') "
                    "AND (kind NOT IN ('assistant', 'assistant_turn') OR status IN ('complete', 'completed')) AND ("
                    + predicate.format(column="content") + ")", [scope, session_id, *terms]
                )
                for row in rows:
                    item = dict(row)
                    item["source"] = "event"
                    item["historical_observation"] = True
                    candidates.append(item)
        for item in candidates:
            body = item["content"].casefold()
            item["score"] = sum(len(term) for term in terms if term in body)
        return sorted(candidates, key=lambda item: (
            item["score"], item["source"] == "memory", item["seq"]), reverse=True)[:limit]
