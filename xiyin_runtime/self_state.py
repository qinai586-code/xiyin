"""Persistent functional state and scoped character growth, not subjective claims.

Trusted runtime callers supply observations, feedback and executor outcomes.
The bounded affect values guide scheduling/expression; they do not establish
conscious feelings, completed external actions, or acquired skills.
"""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .experience import DocumentCorruptionError, ExperienceStore, _json_object, _scope, _text
from .persona import load_persona


OBSERVATIONS = frozenset({"user_input", "user_feedback", "action_result", "activity", "rest", "wake", "stop"})


def _bounded(value, minimum=-1.0, maximum=1.0):
    return min(maximum, max(minimum, value))


class SelfState:
    def __init__(self, store: ExperienceStore, character_id="xiyin", *, persona=None):
        self.store = store
        self.character_id = _text(character_id, "character_id")
        self.persona = persona or load_persona(Path(__file__).resolve().parents[1] / "config/persona/character.seed.json")
        if self.persona.data["character_id"] != self.character_id:
            raise ValueError("character identity does not match the seed")
        with store.document_transaction():
            identity = store.read_document("state", "character_identity")
            if identity is None:
                identity = store.write_document("state", "character_identity", {
                    "character_id": self.character_id, "persistent_id": uuid4().hex,
                    "source": "runtime_initialization", "scope": "private"}, expected_version=0)
            if identity["value"].get("character_id") != self.character_id or not identity["value"].get("persistent_id"):
                raise DocumentCorruptionError("Persistent character identity mismatch; refusing to reset it")
            self.persistent_id = identity["value"]["persistent_id"]

    def _key(self, session_id, scope):
        session_id, scope = _text(session_id, "session_id"), _scope(scope)
        if len(session_id) > 80 or any(char in session_id for char in (":", "\n", "\r")):
            raise ValueError("invalid state session id")
        return f"self:{self.character_id}:{scope}:{session_id}"

    def _state(self, session_id, scope):
        key = self._key(session_id, scope)
        with self.store.document_transaction():
            state = self.store.read_document("state", key)
            if state is None:
                state = self.store.write_document("state", key, {
                    "character_id": self.character_id, "session_id": session_id, "scope": scope,
                    "mode": "awake", "activity": "idle", "attention": None,
                    "affect": {"valence": 0.0, "arousal": 0.0, "control": 0.5},
                    "origin": "runtime_initialization", "last_event_id": None, "observation_count": 0,
                    "updated_at": datetime.now(timezone.utc).isoformat()}, expected_version=0)
            value = state["value"]
            if (value.get("character_id"), value.get("session_id"), value.get("scope")) != (
                    self.character_id, session_id, scope):
                raise DocumentCorruptionError("State identity or scope mismatch")
            try:
                affect = value["affect"]
                if value["mode"] not in {"awake", "sleep", "stopped"}:
                    raise ValueError("unknown state mode")
                for field, minimum in (("valence", -1), ("arousal", 0), ("control", 0)):
                    number = affect[field]
                    if type(number) not in (float, int) or not math.isfinite(number) or not minimum <= number <= 1:
                        raise ValueError("invalid functional affect value")
            except (KeyError, TypeError, ValueError) as exc:
                raise DocumentCorruptionError(f"Invalid self state: {exc}") from exc
            return state

    def snapshot(self, session_id="owner", scope="private"):
        state = self._state(session_id, scope)
        result = copy.deepcopy(state["value"])
        result.update(version=state["version"], persistent_id=self.persistent_id,
                      identity=copy.deepcopy(self.persona.data["identity_agreements"]))
        growth = [item for item in self.store.memories(scope=scope)
                  if item["kind"] in {"persona", "preference", "opinion", "relationship"}]
        overrides = {item["subject"]: item for item in growth if item["kind"] in {"persona", "preference", "opinion"}}
        tendencies = []
        for seed in self.persona.data["tendencies"]:
            learned = overrides.get("tendency:" + seed["id"], overrides.get(seed["id"]))
            tendencies.append({"id": seed["id"], "value": learned["statement"] if learned else seed["default"],
                               "counterexample": seed["counterexample"],
                               "origin": learned["origin"] if learned else "design_seed",
                               "evidence_refs": learned["evidence_refs"] if learned else []})
        expression = copy.deepcopy(self.persona.data["expression_seed"])
        for field in ("private", "public", "emotional_range"):
            learned = overrides.get("expression:" + field)
            if learned:
                expression[field] = learned["statement"]
        result.update(tendencies=tendencies, expression=expression, growth=growth,
                      affect_interpretation="bounded runtime appraisal, not evidence of subjective experience")
        return result

    def disposition(self, session_id="owner", scope="private") -> dict:
        """Project functional state as context for expression and scheduling.

        Without this, mood and attention were computed on every turn and read
        by nothing: the character seed existed as text and the affect values
        existed as numbers, with no path between them. The wording stays
        explicitly functional, because these values are a runtime appraisal,
        not evidence that anything is felt.
        """
        # Strictly read-only: composing context must not create a state
        # document, so a session with no observations yet projects the
        # starting values rather than inventing an observation to write.
        document = self.store.read_document("state", self._key(session_id, scope))
        state = document["value"] if document else {
            "activity": "idle", "attention": None,
            "affect": {"valence": 0.0, "arousal": 0.0, "control": 0.5}}
        affect = state.get("affect", {})
        valence = affect.get("valence", 0.0)
        arousal = affect.get("arousal", 0.0)
        control = affect.get("control", 0.5)
        if any(not isinstance(value, (int, float)) or isinstance(value, bool)
               for value in (valence, arousal, control)):
            valence, arousal, control = 0.0, 0.0, 0.5
        tone = "轻快一些" if valence > 0.25 else ("低一些" if valence < -0.25 else "平稳")
        energy = "投入" if arousal > 0.5 else ("安静" if arousal < 0.15 else "一般")
        # Only a recorded executor outcome is evidence of acting. Without one,
        # the starting control value used to project "动作结果有成有败": a
        # runtime-authored claim of mixed action results that never happened,
        # which the model then elaborated into invented activity. States written
        # before the counter existed still count a moved control value.
        acted = bool(state.get("action_results")) or control != 0.5
        if not acted:
            footing, caution = "这段会话还没有执行过动作", False
        elif control > 0.65:
            footing, caution = "最近的动作大多验证成功", False
        elif control < 0.4:
            footing, caution = "最近有动作没有成功，先确认现状再动手", True
        else:
            footing, caution = "动作结果有成有败", False
        attention = state.get("attention")
        focus = "当前这句话" if attention == "current_input" else (attention or "没有特别集中的事")
        # The state values are hers to state if asked; the note after them
        # is the runtime's instruction about how to use them.
        line_fact = (f"当前功能状态：注意力在{focus}，语气{tone}，状态{energy}"
                     + (f"，{footing}。" if acted else "。"))
        line_note = ("这是运行中的计算状态，可以影响语气和先做什么；它不是主观体验，"
                     "也不需要逐项汇报，更不会自动变成长期性格。")
        return {"activity": state.get("activity", "idle"), "attention": attention,
                "tone": tone, "energy": energy, "footing": footing,
                "caution": caution, "line": line_fact + line_note,
                "line_fact": line_fact, "line_note": line_note,
                "interpretation": "bounded runtime appraisal, not evidence of subjective experience"}

    def observe(self, kind, payload, session_id="owner", scope="private"):
        if kind not in OBSERVATIONS or not isinstance(payload, dict):
            raise ValueError("unsupported state observation or payload")
        _json_object(payload)
        key = self._key(session_id, scope)
        # Validate before adding a source record. A malformed observation has no
        # effect, and the caller cannot set state/version/scope through payload.
        if kind == "user_feedback":
            rating = payload.get("rating")
            if type(rating) not in (float, int) or not math.isfinite(rating) or not -1 <= rating <= 1:
                raise ValueError("feedback rating must be a finite number from -1 to 1")
        if kind == "action_result" and payload.get("status") not in {
                "verified_success", "verified_failure", "unknown", "cancelled"}:
            raise ValueError("action appraisal requires an executor outcome status")
        if kind == "activity":
            _text(payload.get("name"), "activity name")
        if "event_id" in payload:
            sources = {event["id"]: event for event in self.store.list_events(session_id, scope)}
            source = sources.get(payload["event_id"])
            if (source is None or source["kind"] in {"assistant", "assistant_turn"}
                    or source["origin"] in {"generated", "assistant_output", "simulation", "design_seed", "reflection", "inference"}):
                raise ValueError("state source must be a real scoped observation")
            if kind == "action_result" and source["status"] != payload["status"]:
                raise ValueError("executor outcome must match its source status")
            event_id = source["id"]
        else:
            event_id = self.store.append_event("self_state_observation", {"kind": kind, "payload": payload},
                                               session_id=session_id, scope=scope,
                                               origin="user_report" if kind in {"user_input", "user_feedback"} else "observation")
        # A source record can survive failed projection: it remains evidence of
        # the input, never a false claim that the state update committed.
        checkpoint = f"appraisal:{self.character_id}:{scope}:{session_id}:{event_id}"
        with self.store.document_transaction():
            state = self._state(session_id, scope)
            value = copy.deepcopy(state["value"])
            previous = self.store.read_document("checkpoints", checkpoint)
            if previous is not None:
                if previous["value"]["kind"] != kind:
                    raise ValueError("a state observation cannot change its interpretation on replay")
                return self.snapshot(session_id, scope)
            affect = value["affect"]
            if kind == "user_input":
                if value["mode"] != "stopped":
                    value.update(mode="awake", activity="conversation")
                value["attention"] = "current_input"
                affect["arousal"] = _bounded(affect["arousal"] + 0.05, 0)
            elif kind == "user_feedback":
                affect["valence"] = _bounded(affect["valence"] + payload["rating"] * 0.1)
            elif kind == "action_result":
                direction = {"verified_success": 1, "verified_failure": -1, "unknown": 0, "cancelled": 0}[payload["status"]]
                affect["control"] = _bounded(affect["control"] + direction * 0.1, 0)
                affect["valence"] = _bounded(affect["valence"] + direction * 0.05)
                value["action_results"] = int(value.get("action_results", 0)) + 1
            elif kind == "activity":
                value.update(activity=payload["name"], attention=payload.get("attention"))
            elif kind == "rest":
                if value["mode"] != "stopped":
                    value.update(mode="sleep", activity="rest", attention=None)
                affect["arousal"] *= 0.5
                affect["valence"] *= 0.8
            elif kind == "wake":
                value.update(mode="awake", activity="idle", attention=None)
            elif kind == "stop":
                value.update(mode="stopped", activity="stopped", attention=None)
            value.update(origin="inference", last_event_id=event_id,
                         observation_count=value["observation_count"] + 1,
                         updated_at=datetime.now(timezone.utc).isoformat())
            self.store.write_document("state", key, value, expected_version=state["version"])
            self.store.write_document("checkpoints", checkpoint,
                                      {"event_id": event_id, "kind": kind, "state_key": key, "scope": scope},
                                      expected_version=0)
            return self.snapshot(session_id, scope)
