"""Conversation lifecycle, with persistent evidence and stale-output fencing.

Foundation outputs text, not audio. Completed text is not evidence that a human
heard it. A later Body must supply separate playback receipts.
"""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import time
import uuid

import xiyin_paths
from .authorization import authorize_runtime
from .context import compose_messages, memory_receipt_record, retrieved_record
from .architecture import RuntimeServices
from .config import Settings, load_settings
from .experience import ExperienceStore
from .lifecycle import RuntimeLease
from .persona import load_persona
from .provider import LocalModelClient, ProviderCancelled, ProviderTruncated


_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnEvent:
    type: str
    request_id: str
    session_id: str
    text: str = ""
    detail: str = ""


class RuntimeBusy(RuntimeError):
    pass


class XIYINRuntime(RuntimeServices):
    def __init__(self, settings: Settings, store: ExperienceStore, *, provider=None,
                 authorize=authorize_runtime, data_root_id=None):
        self.settings = settings
        self.store = store
        self.persona = load_persona(settings.persona_path)
        self.provider = provider or LocalModelClient(settings.provider)
        self._authorize = authorize
        self._active: tuple[str, asyncio.Event] | None = None
        self._lease = None
        self._initialize_services(data_root_id=data_root_id)

    @classmethod
    def open(cls, *, model_enabled=True):
        authorize_runtime()
        settings = load_settings()
        root = xiyin_paths.data_root()
        if shutil.disk_usage(root).free < 50 * 1024 * 1024:
            raise RuntimeError("Data volume has less than 50 MiB free")
        lease = RuntimeLease(xiyin_paths.under(root, "runtime.lock"))
        store = None
        try:
            store = ExperienceStore(xiyin_paths.under(root, "experience.sqlite3"))
            from .architecture import DisabledModelProvider
            runtime = cls(settings, store, data_root_id=xiyin_paths.data_root_id(),
                          provider=None if model_enabled else DisabledModelProvider())
            runtime.agenda.recover()
            runtime.reconcile_goals()
            runtime._lease = lease
            return runtime
        except BaseException:
            if store is not None:
                store.close()
            lease.close()
            raise

    def close(self):
        if self._job_active:
            if self._job_token:
                self._job_token.set()
            raise RuntimeBusy("Await the active job before closing runtime")
        if self.cancel():
            # The turn's finalizer still needs the database to record cancellation.
            # Keep both the store and its process lease until the consumer drains
            # or closes the async iterator.
            raise RuntimeBusy("Turn cancellation requested; await or aclose the stream before closing runtime")
        try:
            self.store.close()
        finally:
            if self._lease is not None:
                self._lease.close()

    def cancel(self, request_id: str | None = None) -> bool:
        if self._active and (request_id is None or request_id == self._active[0]):
            self._active[1].set()
            return True
        return False

    def _messages(self, text: str, session_id: str, scope: str) -> list[dict]:
        growth = [m for m in self.store.memories(scope=scope)
                  if m.get("kind") in {"persona", "preference", "opinion", "relationship"}]
        history = [{"role": h["role"], "content": h["content"]}
                   for h in self.store.history(session_id, scope=scope, limit=self.settings.history_messages)]
        receipts = self.store.operation_receipts(session_id, scope=scope, limit=2)
        records = [memory_receipt_record(item) for item in reversed(receipts)]
        for item in self.store.search(text, scope=scope, session_id=session_id, limit=3):
            record = retrieved_record(item)
            if record is not None:
                records.append(record)
        return compose_messages(self.persona.system_prompt(growth), text, history, records,
                                self.settings.max_context_chars,
                                runtime_facts=self.conversation_facts(session_id, scope))

    async def stream_turn(self, text: str, *, session_id: str = "owner", scope: str = "private",
                          cancel: asyncio.Event | None = None):
        self._authorize()
        self._ensure_running()
        if not isinstance(text, str) or not text.strip() or len(text) > self.settings.max_input_chars:
            raise ValueError(f"Input must contain 1–{self.settings.max_input_chars} characters")
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session_id):
            raise ValueError("Session id must be a short ASCII identifier")
        if scope not in {"private", "public"}:
            raise ValueError("Foundation supports private/public; shared sessions require a participant adapter")
        if self._active:
            raise RuntimeBusy("A foreground turn is active; cancel or await it before starting another")
        self._last_input = time.monotonic()
        if self._job_token:
            self._job_token.set()
        token = cancel if cancel is not None else asyncio.Event()
        request_id = uuid.uuid4().hex
        self._active = (request_id, token)
        self._active_task = asyncio.current_task()
        stop_watcher = asyncio.create_task(self.watch_stop(token))
        output = ""
        terminal_recorded = False
        try:
            messages = self._messages(text.strip(), session_id, scope)
            self.sleep_controller.wake("user input")
            evidence_id = self.store.append_event("user", text.strip(), session_id=session_id,
                                    scope=scope, origin="user_report", status="completed", request_id=request_id)
            self.self_state.observe("user_input", {"event_id": evidence_id}, session_id, scope)
            yield TurnEvent("start", request_id, session_id)
            async with aclosing(self.provider.stream(messages, token)) as stream:
                async for chunk in stream:
                    # The output fence holds even if a backend yields a late token.
                    if token.is_set():
                        raise ProviderCancelled("Turn cancelled")
                    if not isinstance(chunk, str):
                        raise ValueError("Provider returned non-text content")
                    output += chunk
                    if len(output) > 20000:
                        raise ValueError("Model output exceeded the foundation text limit")
                    yield TurnEvent("text_delta", request_id, session_id, chunk)
            if token.is_set():
                raise ProviderCancelled("Turn cancelled")
            if not output.strip():
                raise ValueError("Model returned no visible text")
            self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                    origin="generated", status="completed", request_id=request_id)
            terminal_recorded = True
            yield TurnEvent("complete", request_id, session_id)
        except ProviderTruncated as exc:
            reply_id = self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                                origin="generated", status="partial" if output else "failed",
                                                request_id=request_id)
            terminal_recorded = True
            # Use the existing event ledger, no schema change or text rewriting.
            self.store.append_event("generation_end", {"reply_event_id": reply_id, "finish_reason": "length"},
                                    session_id=session_id, scope=scope, origin="observation", status="recorded",
                                    request_id=request_id)
            yield TurnEvent("error", request_id, session_id, detail=f"ProviderTruncated: {exc}")
        except ProviderCancelled:
            self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                    origin="generated", status="cancelled", request_id=request_id)
            terminal_recorded = True
            yield TurnEvent("cancelled", request_id, session_id)
        except (asyncio.CancelledError, GeneratorExit):
            token.set()
            raise
        except Exception as exc:
            self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                    origin="generated", status="failed", request_id=request_id)
            terminal_recorded = True
            yield TurnEvent("error", request_id, session_id, detail=f"{type(exc).__name__}: {exc}")
        finally:
            token.set()
            try:
                await stop_watcher
            finally:
                try:
                    if not terminal_recorded:
                        self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                                origin="generated", status="cancelled", request_id=request_id)
                finally:
                    self._active = None
                    self._active_task = None

    def remember(self, statement: str, *, kind: str = "fact", subject: str = "owner",
                 session_id: str = "owner", scope: str = "private", supersedes=None) -> str:
        self._authorize()
        if not statement.strip() or len(statement) > 2000:
            raise ValueError("Memory statement must contain 1–2000 characters")
        evidence = self.store.append_event("user", statement, session_id=session_id, scope=scope,
                                           origin="user_report", status="completed")
        operation = {"operation": "replace" if supersedes else "remember", "source_event_id": evidence,
                     "statement": statement, "supersedes": supersedes}
        try:
            memory_id = self.store.remember(statement, kind=kind, subject=subject, scope=scope,
                                           evidence_refs=[evidence], supersedes=supersedes,
                                           receipt_session_id=session_id)
        except Exception as exc:
            try:
                self.store.append_event("memory_operation", {**operation, "success": False,
                                                              "error_type": type(exc).__name__},
                                        session_id=session_id, scope=scope, origin="tool_result", status="verified_failure")
            except Exception:
                _logger.warning("Could not persist the failed memory-operation receipt")
            raise
        return memory_id


# The historical import is an alias of the same core, never a second runtime.
FoundationRuntime = XIYINRuntime
