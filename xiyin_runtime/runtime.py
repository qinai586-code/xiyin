"""Conversation lifecycle, with persistent evidence and stale-output fencing.

Foundation outputs text, not audio. Completed text is not evidence that a human
heard it. A later Body must supply separate playback receipts.
"""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import inspect
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
from .grounding import action_receipt_record, premise_records, topic_records
from .lifecycle import RuntimeLease
from .persona import load_persona
from .output_guard import OutputGuard, OutputBlocked, VERSION as OUTPUT_GUARD_VERSION
from .provider import GenerationBudget, LocalModelClient, ProviderCancelled, ProviderTruncated
from .prompt_provenance import PromptSource, runtime_projection
from .response_plan import ResponsePlan, estimate_tokens, plan_response, updated_rate
from .turn_policy import build_turn_policy


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
        self._provider_takes_budget = self._accepts_budget(self.provider)
        self._authorize = authorize
        self._active: tuple[str, asyncio.Event] | None = None
        self._lease = None
        self._initialize_services(data_root_id=data_root_id)

    @staticmethod
    def _accepts_budget(provider) -> bool:
        try:
            parameters = inspect.signature(provider.stream).parameters
        except (TypeError, ValueError):
            return False
        return "budget" in parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                             for p in parameters.values())

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

    def _records(self, text: str, session_id: str, scope: str) -> list[dict]:
        """Order evidence by how directly it decides this turn's honesty.

        Records are dropped from the tail when the budget runs out, so a
        premise check and a verified action receipt must come before general
        lexical recall — those are the ones a wrong answer turns into a false
        denial or a fabricated experience.
        """
        records = list(premise_records(self.store, text, session_id=session_id, scope=scope))
        for item in reversed(self.store.action_receipts(session_id, scope=scope, limit=3)):
            record = action_receipt_record(item)
            if record is not None:
                records.append(record)
        # Keep only the newest receipt per memory. A retraction that follows a
        # save otherwise leaves "saved: completed" standing next to it, and the
        # stale one reads as the current status of a memory that is now gone.
        seen_memories = set()
        for item in reversed(self.store.operation_receipts(session_id, scope=scope, limit=6)):
            content = item.get("content")
            key = content.get("memory_id") if isinstance(content, dict) else None
            if key is not None:
                if key in seen_memories:
                    continue
                seen_memories.add(key)
            records.append(memory_receipt_record(item))
            if len(seen_memories) >= 2:
                break
        records.extend(topic_records(self.store, text, session_id=session_id, scope=scope))
        for item in self.store.search(text, scope=scope, session_id=session_id, limit=3):
            record = retrieved_record(item)
            if record is not None:
                records.append(record)
        return records

    def _prepare(self, text: str, session_id: str, scope: str) -> dict:
        """Gather everything a turn reads from the ledger, exactly once.

        Planning needs the assembled prompt to size its budget, and the final
        prompt differs only by one directive line. Composition is pure, so the
        reads happen here and the two compositions reuse them.
        """
        growth = [m for m in self.store.memories(scope=scope)
                  if m.get("kind") in {"persona", "preference", "opinion", "relationship"}]
        history = [{"role": h["role"], "content": h["content"]}
                   for h in self.store.history(session_id, scope=scope, limit=self.settings.history_messages)]
        persona = self.persona.system_projection(growth)
        return {"persona": persona.text, "protected_instructions": persona.protected_instructions,
                "public_identity": tuple(f.text for f in persona.fragments if f.source is PromptSource.PUBLIC_IDENTITY),
                "history": history,
                "records": self._records(text, session_id, scope),
                "facts": self.conversation_facts(session_id, scope)}

    def _compose(self, prepared: dict, text: str, response_directive: str = "") -> list[dict]:
        return compose_messages(prepared["persona"], text, prepared["history"], prepared["records"],
                                self.settings.max_context_chars,
                                runtime_facts=prepared["facts"],
                                response_directive=response_directive)

    def _messages(self, text: str, session_id: str, scope: str,
                  *, response_directive: str = "") -> list[dict]:
        return self._compose(self._prepare(text, session_id, scope), text, response_directive)

    def _plan_turn(self, text: str, messages: list[dict], session_id: str, scope: str) -> ResponsePlan:
        """Size this turn from the request, the assembled prompt and the machine."""
        provider = self.settings.provider
        state = self.store.read_document("state", "generation_profile")
        measured = state["value"].get("tokens_per_second") if state else None
        if not isinstance(measured, (int, float)) or isinstance(measured, bool) or measured <= 0:
            measured = None
        snapshot = self.store.read_document("state", f"self:xiyin:{scope}:{session_id}")
        affect = snapshot["value"].get("affect", {}) if snapshot else {}
        arousal = affect.get("arousal", 0.0)
        engagement = float(arousal) if isinstance(arousal, (int, float)) and not isinstance(arousal, bool) else 0.0
        prompt_tokens = sum(estimate_tokens(message["content"]) for message in messages)
        return plan_response(text, prompt_tokens=prompt_tokens, context_tokens=provider.context_tokens,
                             ceiling=provider.max_tokens_ceiling,
                             default_rate=provider.default_tokens_per_second,
                             max_timeout=provider.max_timeout_seconds,
                             measured_rate=measured, engagement=engagement)

    def _record_generation_rate(self, text: str, seconds: float) -> None:
        """Learn this machine's throughput from real completed generations."""
        state = self.store.read_document("state", "generation_profile")
        previous = state["value"].get("tokens_per_second") if state else None
        if not isinstance(previous, (int, float)) or isinstance(previous, bool):
            previous = None
        rate = updated_rate(previous, estimate_tokens(text), seconds)
        if rate is None or rate == previous:
            return
        value = {"tokens_per_second": float(rate), "scope": "private",
                 "samples": int((state["value"].get("samples", 0) if state else 0)) + 1,
                 "source": "measured_completed_generations"}
        try:
            self.store.write_document("state", "generation_profile", value,
                                      expected_version=state["version"] if state else 0)
        except Exception:
            # A losing race just skips one sample; the estimate is advisory.
            _logger.debug("Generation profile update skipped")

    def _stream_with_budget(self, messages, token, plan):
        if not self._provider_takes_budget:
            # A host-supplied provider may predate per-request budgets; it then
            # runs on the configured defaults rather than failing the turn.
            return self.provider.stream(messages, token)
        return self.provider.stream(messages, token,
                                    budget=GenerationBudget(plan.max_tokens, plan.timeout_seconds))

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
        raw_output = ""
        guard = None
        outcome = "cancelled"
        provider_end = None
        terminal_recorded = False
        plan = None
        started = time.monotonic()
        first_token_at = None
        first_released_at = None
        try:
            prompt = text.strip()
            # Plan against the assembled prompt so the budget accounts for the
            # real context, then recompose with this turn's scope directive.
            prepared = self._prepare(prompt, session_id, scope)
            plan = self._plan_turn(prompt, self._compose(prepared, prompt), session_id, scope)
            messages = self._compose(prepared, prompt, plan.directive)
            protected = (prepared["protected_instructions"]
                         + runtime_projection(prepared["facts"], plan.directive).protected_instructions)
            guard = OutputGuard(prompt, persona_prompt=messages[0]["content"],
                                turn_directive=plan.directive, protected_instructions=protected,
                                policy=build_turn_policy(prompt), public_identity=prepared["public_identity"])
            self.sleep_controller.wake("user input")
            evidence_id = self.store.append_event("user", prompt, session_id=session_id,
                                    scope=scope, origin="user_report", status="completed", request_id=request_id)
            self.self_state.observe("user_input", {"event_id": evidence_id}, session_id, scope)
            yield TurnEvent("start", request_id, session_id)
            started = time.monotonic()
            try:
                async with aclosing(self._stream_with_budget(messages, token, plan)) as stream:
                    async for chunk in stream:
                        if first_token_at is None:
                            first_token_at = time.monotonic()
                        # Fence both newly received and buffered text. Only checked
                        # units may reach CLI, bridges, or the shared voice body.
                        if token.is_set():
                            raise ProviderCancelled("Turn cancelled")
                        if not isinstance(chunk, str):
                            raise ValueError("Provider returned non-text content")
                        raw_output += chunk
                        if len(raw_output) > 20000:
                            raise OutputBlocked("output_buffer_limit")
                        for segment in guard.feed(chunk):
                            if token.is_set():
                                raise ProviderCancelled("Turn cancelled")
                            if first_released_at is None:
                                first_released_at = time.monotonic()
                            output += segment
                            yield TurnEvent("text_delta", request_id, session_id, segment)
            except (OutputBlocked, ProviderCancelled, asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                provider_end = "length" if isinstance(exc, ProviderTruncated) else "error"
                if token.is_set():
                    raise ProviderCancelled("Turn cancelled") from exc
                # A broken/truncated stream may still have a safe partial tail.
                # Check it; never flush a pending tag simply because transport ended.
                for segment in guard.finish():
                    if token.is_set():
                        raise ProviderCancelled("Turn cancelled")
                    if first_released_at is None:
                        first_released_at = time.monotonic()
                    output += segment
                    yield TurnEvent("text_delta", request_id, session_id, segment)
                raise
            provider_end = "stop"
            if token.is_set():
                raise ProviderCancelled("Turn cancelled")
            for segment in guard.finish():
                if token.is_set():
                    raise ProviderCancelled("Turn cancelled")
                if first_released_at is None:
                    first_released_at = time.monotonic()
                output += segment
                yield TurnEvent("text_delta", request_id, session_id, segment)
            if token.is_set():
                raise ProviderCancelled("Turn cancelled")
            if not output.strip():
                raise ValueError("Model returned no visible text")
            self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                    origin="generated", status="completed", request_id=request_id)
            terminal_recorded = True
            outcome = "completed"
            # Only a completed generation measures throughput; a blocked or
            # cancelled turn says nothing about how fast this machine runs.
            self._record_generation_rate(raw_output, max(time.monotonic() - started, 1e-6))
            yield TurnEvent("complete", request_id, session_id)
        except OutputBlocked as exc:
            token.set()
            outcome = "failed"
            self.store.append_event("assistant", output, session_id=session_id, scope=scope,
                                    origin="generated", status="failed", request_id=request_id)
            terminal_recorded = True
            # No rejected content in the terminal detail, spoken fallback, or
            # completed assistant history. The original remains a diagnostic.
            if guard is not None:
                guard.blocked = exc.reason
            yield TurnEvent("error", request_id, session_id, detail=f"OutputBlocked: {exc.reason}")
        except ProviderTruncated as exc:
            outcome = "partial" if output else "failed"
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
            outcome = "failed"
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
                    if plan is not None:
                        # Keep the plan and what actually happened together, so
                        # length adaptation and latency can be measured from the
                        # ledger instead of judged from one transcript.
                        self.store.append_event("response_plan", {
                            **plan.to_dict(), "outcome": outcome,
                            "released_chars": len(output), "generated_chars": len(raw_output),
                            "estimated_output_tokens": estimate_tokens(raw_output),
                            "provider_end": provider_end,
                            # Three separate instants. The gate buffers whole
                            # units, so released text lags the first token; and
                            # neither says anything about audio reaching a person.
                            "model_first_token_seconds": (round(first_token_at - started, 3)
                                                          if first_token_at else None),
                            "first_released_segment_seconds": (round(first_released_at - started, 3)
                                                               if first_released_at else None),
                            "generation_seconds": round(time.monotonic() - started, 3),
                            "audio_playback_measured": False,
                        }, session_id=session_id, scope=scope, origin="observation",
                            status="recorded", request_id=request_id)
                    if guard is not None:
                        self.store.append_event("output_guard", {
                            "version": OUTPUT_GUARD_VERSION,
                            "decision": "blocked" if guard.blocked else (
                                "allowed_by_rules" if outcome == "completed" else "incomplete"),
                            "reason": guard.blocked, "approved_chars": len(output),
                            "received_chars": len(raw_output), "provider_end": provider_end,
                            "semantic_truth_verified": False,
                        }, session_id=session_id, scope=scope, origin="observation",
                            status="recorded", request_id=request_id)
                        if raw_output != output:
                            self.store.append_event("generation_diagnostic", raw_output[:20000],
                                                    session_id=session_id, scope=scope, origin="generated",
                                                    status=outcome if outcome != "completed" else "failed",
                                                    request_id=request_id)
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
