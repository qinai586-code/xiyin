"""Typed goal proposals and evidence-bound character growth in the single Mind.

Planners propose data, never permissions or executable code. FileSkillPlanner
instantiates two known skills without claiming language-model reasoning. The
runtime still observes, executes and verifies every action through its Body.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PureWindowsPath
import re
from uuid import uuid4

from .experience import _json_object, _scope, _text


_NAME = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_ADAPTER_NAME = re.compile(r"[A-Za-z0-9_-]{1,80}(?::[A-Za-z0-9_-]{1,80})?\Z")
_BLOCKED_OPERATIONS = {"shell", "exec", "execute", "run_command", "eval", "python", "powershell", "bash"}
_RESERVED_ARGUMENTS = {"scope", "policy", "capabilities", "permissions", "authority", "shell", "command", "code", "script"}
_GROWTH_KINDS = {"persona", "preference", "opinion"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _session(session_id, scope):
    if not isinstance(session_id, str) or not _NAME.fullmatch(session_id):
        raise ValueError("Invalid director session id")
    return session_id, _scope(scope)


def _filename(value):
    if (not isinstance(value, str) or not value or value in {".", ".."}
            or any(ord(char) < 32 for char in value) or any(char in value for char in '/\\:<>"|?*')
            or value.endswith((" ", ".")) or PureWindowsPath(value).is_reserved()):
        raise ValueError("File skills require a direct relative workspace filename")
    return value


def _capabilities(capabilities):
    if not isinstance(capabilities, (list, tuple)):
        raise ValueError("Use the host Body registry capability snapshot")
    result = {}
    for item in capabilities:
        if (not isinstance(item, dict) or not isinstance(item.get("adapter_id"), str)
                or not _ADAPTER_NAME.fullmatch(item["adapter_id"]) or item["adapter_id"] in result
                or type(item.get("available")) is not bool
                or not isinstance(item.get("operations"), (list, tuple))
                or any(not isinstance(op, str) or not _NAME.fullmatch(op) for op in item["operations"])):
            raise ValueError("Invalid or duplicate host capability")
        result[item["adapter_id"]] = {
            "adapter_id": item["adapter_id"], "version": _text(item.get("version"), "adapter version"),
            "scope": _text(item.get("scope"), "adapter scope"), "available": item["available"],
            "operations": list(item["operations"]),
        }
    return result


def validate_plan(plan, capabilities):
    """Validate an untrusted planner result; bind scope only from host records."""
    caps = _capabilities(capabilities)
    if not isinstance(plan, dict) or set(plan) != {"title", "steps"}:
        raise ValueError("A plan contains only title and typed steps")
    title = _text(plan["title"], "goal title")
    if len(title) > 2000 or not isinstance(plan["steps"], list) or not 1 <= len(plan["steps"]) <= 32:
        raise ValueError("A goal needs a short title and 1–32 actions")
    steps, used = [], set()
    for step in plan["steps"]:
        if not isinstance(step, dict) or set(step) != {"adapter_id", "operation", "arguments"}:
            raise ValueError("Each action contains only adapter_id, operation and arguments")
        identifier, operation = step["adapter_id"], step["operation"]
        if not isinstance(identifier, str) or identifier not in caps or not caps[identifier]["available"]:
            raise ValueError("Action requires an available registered adapter")
        if (not isinstance(operation, str) or operation not in caps[identifier]["operations"]
                or operation.casefold() in _BLOCKED_OPERATIONS):
            raise ValueError("Action operation is unavailable or is executable code")
        arguments = step["arguments"]
        _json_object(arguments)
        def reject_controls(value):
            if isinstance(value, dict):
                if set(value) & _RESERVED_ARGUMENTS:
                    raise ValueError("Action arguments cannot grant scope, authority or executable code")
                for child in value.values():
                    reject_controls(child)
            elif isinstance(value, list):
                for child in value:
                    reject_controls(child)
        reject_controls(arguments)
        if operation in {"read_text", "write_text"}:
            wanted = {"path"} if operation == "read_text" else {"path", "text"}
            if set(arguments) != wanted:
                raise ValueError("Unexpected file skill arguments")
            _filename(arguments["path"])
            if operation == "write_text" and (not isinstance(arguments["text"], str)
                    or len(arguments["text"].encode("utf-8")) > 1024 * 1024):
                raise ValueError("Write skill text must fit the Body byte limit")
        if len(_json_object(arguments)) > 2 * 1024 * 1024:
            raise ValueError("Action arguments exceed the plan budget")
        used.add(identifier)
        steps.append(deepcopy(step))
    # Cross-body orchestration needs its own typed transfer contract. It cannot
    # be inferred from a planner choosing a second adapter or filesystem root.
    if len(used) != 1:
        raise ValueError("A plan cannot cross adapter domains")
    return {"title": title, "steps": steps, "capability_bindings": [caps[name] for name in sorted(used)]}


class FileSkillPlanner:
    """Explicit template planner for read/write skills, with no model calls."""
    planner_kind = "rule_file_skill"

    def __call__(self, *, objective, capabilities, state):
        if not isinstance(objective, dict) or objective.get("skill") not in {"read_text", "write_text"}:
            raise ValueError("Rule planner requires a structured read_text or write_text objective")
        skill = objective["skill"]
        wanted = {"skill", "path"} | ({"text"} if skill == "write_text" else set())
        if set(objective) - {"adapter_id"} != wanted:
            raise ValueError("Unexpected file skill objective fields")
        identifier = objective.get("adapter_id", "workspace")
        arguments = {key: objective[key] for key in wanted - {"skill"}}
        return {"title": f"{skill}: {objective['path']}",
                "steps": [{"adapter_id": identifier, "operation": skill, "arguments": arguments}]}


class Director:
    def __init__(self, store, self_state, agenda, planner=None):
        if planner is not None and not callable(planner):
            raise ValueError("Planner must be callable")
        if self_state.store is not store or agenda.store is not store:
            raise ValueError("Director, state and agenda must share one experience store")
        self.store, self.self_state, self.agenda, self.planner = store, self_state, agenda, planner

    def propose_goal(self, objective, capabilities, session_id="owner", scope="private"):
        session_id, scope = _session(session_id, scope)
        if scope != "private":
            raise PermissionError("Public conversation cannot schedule owner actions")
        caps = _capabilities(capabilities)
        if self.planner is None:
            return {"status": "unavailable", "reason": "No goal planner is configured", "planner": None}
        if not isinstance(objective, (str, dict)) or (isinstance(objective, str) and not objective.strip()):
            raise ValueError("A goal objective is required")
        # The planner only sees data copies; it cannot mutate registry bindings.
        proposed = self.planner(objective=deepcopy(objective), capabilities=deepcopy(list(caps.values())),
                                state=self.self_state.snapshot(session_id, scope))
        plan = validate_plan(proposed, list(caps.values()))
        goal_id = "goal_" + uuid4().hex
        goal = dict(plan, id=goal_id, objective=deepcopy(objective), session_id=session_id, scope=scope,
                    status="queued", completed_steps=0, created_at=_now(),
                    planner=getattr(self.planner, "planner_kind", "injected_planner"))
        with self.store.document_transaction():
            job = self.agenda.enqueue("goal", {"goal_id": goal_id, "session_id": session_id}, scope=scope)
            goal["job_id"] = job["id"]
            return self.store.write_document("goals", goal_id, goal, expected_version=0)["value"]

    def _growth_field(self, kind, subject):
        if kind not in _GROWTH_KINDS or not isinstance(subject, str):
            raise ValueError("Only character persona, preference and opinion can grow here")
        seed = self.self_state.persona.data
        allowed = {"tendency:" + item["id"] for item in seed["tendencies"] if item.get("mutable_from_experience")}
        allowed.update({"expression:private", "expression:public", "expression:emotional_range"})
        if subject not in allowed:
            raise ValueError("Growth cannot overwrite identity, owner facts, authority or unassigned fields")

    def _growth_evidence(self, value):
        refs = value["evidence_refs"]
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("Growth requires explicit user-feedback event ids")
        events = {event["id"]: event for event in self.store.list_events(value["session_id"], value["scope"])}
        expected = {key: value[key] for key in ("kind", "subject", "statement")}
        for ref in refs:
            event = events.get(ref)
            if (event is None or event["origin"] not in {"user_report", "user_statement", "owner_statement"}
                    or event["status"] not in {"recorded", "complete", "completed"}):
                raise ValueError("Growth source must be completed real user feedback in the same session and scope")
            try:
                content = json.loads(event["content"])
                if event["kind"] == "self_state_observation" and content.get("kind") == "user_feedback":
                    content = content["payload"]
                elif event["kind"] != "user_feedback":
                    raise ValueError("Not an explicit growth feedback event")
                if not isinstance(content, dict) or content.get("growth") != expected:
                    raise ValueError("Feedback does not explicitly support this character field and statement")
            except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
                raise ValueError("Malformed growth feedback evidence") from exc

    @staticmethod
    def _growth_payload(value):
        return {key: value[key] for key in ("kind", "subject", "statement", "evidence_refs", "session_id", "scope")}

    def propose_growth(self, kind, subject, statement, evidence_refs, session_id="owner", scope="private"):
        session_id, scope = _session(session_id, scope)
        if scope != "private":
            # A viewer can send feedback, and feedback is what growth reads. Without
            # this, a public adapter could plant a growth-shaped payload and shape
            # her character — `expression:public` most of all. Scope isolation keeps
            # such a memory out of private turns, but it must not form at all.
            raise PermissionError("Character growth requires owner-scope evidence; viewers cannot shape it")
        self._growth_field(kind, subject)
        statement = _text(statement, "growth statement")
        if len(statement) > 2000:
            raise ValueError("Growth statement is too long")
        value = {"kind": kind, "subject": subject, "statement": statement, "evidence_refs": evidence_refs,
                 "session_id": session_id, "scope": scope}
        self._growth_evidence(value)
        value["evidence_refs"] = list(dict.fromkeys(evidence_refs))
        candidate_id = "growth_" + uuid4().hex
        value.update(id=candidate_id, candidate_type="character_growth", status="proposed", created_at=_now(),
                     digest=_digest(self._growth_payload(value)))
        return self.store.write_document("candidates", candidate_id, value, expected_version=0)["value"]

    def review_feedback_growth(self, session_id="owner", scope="private", *, adopt=True, limit=8):
        """Turn feedback already on record into growth, without asking again.

        Growth existed but only ever started from an explicit owner command,
        so real interaction outcomes never reached it. This reads the feedback
        events the owner already gave, which ``_growth_evidence`` validates
        against the same rules, and proposes the fields they support. Ordinary
        reversible growth needs no separate approval; ``rollback_growth``
        remains the way back. Nothing here infers a field from tone, from a
        model's output, or from the mere passage of time.
        """
        session_id, scope = _session(session_id, scope)
        if scope != "private":
            return []
        known = {item["value"].get("digest") for item in self.store.list_documents("candidates")
                 if item["value"].get("candidate_type") == "character_growth"}
        results = []
        for event in self.store.list_events(session_id, scope):
            if len(results) >= limit:
                break
            if event["kind"] != "self_state_observation" or event["origin"] != "user_report":
                continue
            try:
                payload = json.loads(event["content"])
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or payload.get("kind") != "user_feedback":
                continue
            growth = payload.get("payload", {}).get("growth") if isinstance(payload.get("payload"), dict) else None
            if not isinstance(growth, dict) or set(growth) != {"kind", "subject", "statement"}:
                continue
            value = {**growth, "evidence_refs": [event["id"]], "session_id": session_id, "scope": scope}
            try:
                self._growth_field(growth["kind"], growth["subject"])
            except ValueError:
                continue
            if _digest(self._growth_payload(value)) in known:
                continue
            try:
                candidate = self.propose_growth(growth["kind"], growth["subject"], growth["statement"],
                                                [event["id"]], session_id=session_id, scope=scope)
                results.append(self.adopt_growth(candidate["id"]) if adopt else candidate)
                known.add(candidate["digest"])
            except (ValueError, KeyError):
                # Unsupported or superseded feedback is skipped, not forced.
                continue
        return results

    def _candidate(self, candidate_id):
        document = self.store.read_document("candidates", candidate_id)
        if document is None:
            raise KeyError(candidate_id)
        value = document["value"]
        if value.get("candidate_type") != "character_growth":
            raise ValueError("Only character-growth candidates belong to this director")
        self._growth_field(value["kind"], value["subject"])
        if value.get("digest") != _digest(self._growth_payload(value)):
            raise ValueError("Growth candidate changed after registration")
        self._growth_evidence(value)
        return document

    def adopt_growth(self, candidate_id):
        with self.store.document_transaction():
            document = self._candidate(candidate_id)
            value = document["value"]
            if value["status"] == "adopted":
                return value
            if value["status"] != "proposed":
                raise ValueError("Only proposed growth may be adopted")
            existing = [item for item in self.store.memories(scope=value["scope"])
                        if item["subject"] == value["subject"] and item["kind"] in _GROWTH_KINDS]
            if len(existing) > 1 or (existing and existing[0]["kind"] != value["kind"]):
                raise ValueError("Growth must retain its field's current memory kind and unambiguous version")
            prior = existing[0] if existing else None
            value["previous"] = prior
            value["memory_id"] = self.store.remember(
                value["statement"], kind=value["kind"], subject=value["subject"], scope=value["scope"],
                evidence_refs=value["evidence_refs"], supersedes=prior["id"] if prior else None,
                receipt_session_id=value["session_id"])
            value.update(status="adopted", adopted_at=_now())
            return self.store.write_document("candidates", candidate_id, value, expected_version=document["version"])["value"]

    def rollback_growth(self, candidate_id):
        with self.store.document_transaction():
            document = self._candidate(candidate_id)
            value = document["value"]
            if value["status"] == "rolled_back":
                return value
            if value["status"] != "adopted":
                raise ValueError("Only adopted growth may be rolled back")
            current = [item for item in self.store.memories(scope=value["scope"])
                       if item["subject"] == value["subject"] and item["kind"] in _GROWTH_KINDS]
            if len(current) != 1 or current[0]["id"] != value["memory_id"]:
                raise ValueError("Growth was superseded; rollback must not erase a later correction")
            previous = value["previous"]
            if previous is None:
                self.store.retract_memory(value["memory_id"], receipt_session_id=value["session_id"])
                restored = None
            else:
                restored = self.store.remember(
                    previous["statement"], kind=previous["kind"], subject=previous["subject"], scope=previous["scope"],
                    evidence_refs=previous["evidence_refs"], supersedes=value["memory_id"],
                    receipt_session_id=value["session_id"])
            value.update(status="rolled_back", rolled_back_at=_now(), restored_memory_id=restored)
            return self.store.write_document("candidates", candidate_id, value, expected_version=document["version"])["value"]
