"""Typed, state-based game actions inspired by the official Neuro SDK contract.

Reference: https://github.com/VedalAI/neuro-sdk/blob/main/API/SPECIFICATION.md
blob e65bd478a27cbb6735e879109c32bc78fa5b71a6. Its action/result may acknowledge
validation before execution. Such acknowledgements remain unknown here until
the transport supplies an observed completed state tied to the action id.
This is not a claim of wire compatibility with an unmodified Neuro server.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time

from .models import AdapterOutcome, Capability, Observation


_SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "enum",
                "minimum", "maximum", "minLength", "maxLength", "description"}


def _validate_schema(schema: dict, depth=0):
    if depth > 8 or not isinstance(schema, dict) or set(schema) - _SCHEMA_KEYS:
        raise ValueError("Game actions use a bounded simple JSON schema subset")
    if schema.get("type") not in {"object", "string", "integer", "number", "boolean"}:
        raise ValueError("Unsupported game action schema type")
    if schema["type"] == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list) or any(key not in properties for key in required):
            raise ValueError("Invalid game action property requirements")
        if schema.get("additionalProperties", False) is not False:
            raise ValueError("Game action schemas must reject unknown properties")
        for key, value in properties.items():
            if not isinstance(key, str):
                raise ValueError("Game property names must be strings")
            _validate_schema(value, depth + 1)


def _validate_value(value, schema: dict):
    kind = schema["type"]
    if kind == "object":
        properties = schema.get("properties", {})
        if not isinstance(value, dict) or set(value) - set(properties) or set(schema.get("required", [])) - set(value):
            raise ValueError("Game action properties do not match the registered schema")
        for key, item in value.items():
            _validate_value(item, properties[key])
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError("Game action requires a boolean")
    elif kind in {"integer", "number"}:
        if type(value) not in ({int} if kind == "integer" else {int, float}) or not math.isfinite(value):
            raise ValueError("Game action requires a finite typed number")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError("Game action number is outside its registered range")
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= min(schema.get("maxLength", 4096), 4096):
            raise ValueError("Game action text is outside its registered bounds")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Game action value is outside its registered enum")


@dataclass(frozen=True)
class GameActionSpec:
    name: str
    description: str
    schema: dict
    control_level: str = "semantic"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name) or not self.description:
            raise ValueError("Game actions require a name and description")
        if self.control_level != "semantic":
            raise ValueError("Per-frame model input is unsupported; delegate low-level control to the game")
        _validate_schema(self.schema)
        if self.schema["type"] != "object":
            raise ValueError("Game action parameters must be an object")


class TypedGameAdapter:
    """Host-supplied transport with explicit connected status:

    observe_state()->dict(revision, data, last_action_id optional)
    request_action(message, expected_revision, cancel)->Neuro-style action/result
    cancel_action(action_id)->bool

    Completion extension in result.data: phase='completed', verified=True,
    state_revision=<observed revision>. The new state must also contain matching
    last_action_id. Plain SDK acceptance alone cannot satisfy this contract.
    """
    def __init__(self, game_id: str, actions: list[GameActionSpec], *, transport=None,
                 min_action_interval=0.25, version="1"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", game_id):
            raise ValueError("Game id must be a short stable identifier")
        if not 0.25 <= min_action_interval <= 60:
            raise ValueError("Game decisions must be event/state based, not a per-frame loop")
        if not actions or len({action.name for action in actions}) != len(actions):
            raise ValueError("Register unique typed game actions")
        self.game_id, self.transport = game_id, transport
        self.actions = {action.name: action for action in actions}
        self.min_action_interval = min_action_interval
        self._last_dispatch = -math.inf
        self._last_revision = None
        self._active_action = None
        self.capability = Capability("game:" + game_id, version, tuple(self.actions),
                                     transport is not None and getattr(transport, "connected", False),
                                     "game:" + game_id, "Typed semantic actions with revision and completion receipts")

    async def health(self):
        return {"available": self.transport is not None and getattr(self.transport, "connected", False) is True,
                "version": self.capability.version,
                "detail": "Semantic game transport connected" if self.transport is not None and getattr(self.transport, "connected", False)
                else "No game connection; no play capability is claimed"}

    def registered_actions(self) -> list[dict]:
        return [{"name": action.name, "description": action.description, "schema": action.schema}
                for action in self.actions.values()]

    async def _state(self):
        if not (await self.health())["available"]:
            raise RuntimeError("Game transport unavailable")
        state = await self.transport.observe_state()
        if not isinstance(state, dict) or not isinstance(state.get("revision"), str) or not state["revision"]:
            raise ValueError("Game state must include a nonempty revision")
        if not isinstance(state.get("data", {}), dict):
            raise ValueError("Game state data must be an object")
        return state

    async def observe(self):
        state = await self._state()
        return Observation(self.capability.adapter_id, self.capability.version, self.capability.scope,
                           0, 0, (1.0, 1.0), state["revision"],
                           {"game_state": state.get("data", {}), "actions": self.registered_actions()})

    async def execute(self, request, cancel) -> AdapterOutcome:
        try:
            if request.scope != self.capability.scope or request.operation not in self.actions:
                raise PermissionError("Game action is outside the registered scope")
            if set(request.arguments) != {"state_revision", "parameters"}:
                raise ValueError("Game action needs state_revision and typed parameters")
            state = await self._state()
            revision = request.arguments["state_revision"]
            if revision != state["revision"]:
                raise ValueError("Game state changed; observe before choosing the next semantic action")
            _validate_value(request.arguments["parameters"], self.actions[request.operation].schema)
            if revision == self._last_revision or time.monotonic() - self._last_dispatch < self.min_action_interval:
                raise ValueError("Wait for a new game state/event instead of issuing per-frame actions")
            if cancel.is_set():
                return AdapterOutcome("cancelled", detail="Cancelled before game dispatch")
        except Exception as exc:
            return AdapterOutcome("failure", detail=f"{type(exc).__name__}: {exc}")
        message = {"command": "action", "data": {"id": request.action_id, "name": request.operation,
                   "data": json.dumps(request.arguments["parameters"], ensure_ascii=False)}}
        self._last_dispatch, self._last_revision = time.monotonic(), revision
        self._active_action = request.action_id
        try:
            result = await self.transport.request_action(message, expected_revision=revision, cancel=cancel)
            if not isinstance(result, dict) or result.get("command") != "action/result" or result.get("game") != self.game_id:
                raise ValueError("Unexpected game result envelope")
            data = result.get("data", {})
            if not isinstance(data, dict) or data.get("id") != request.action_id or type(data.get("success")) is not bool:
                raise ValueError("Game result does not match the dispatched action")
            if data["success"] is False:
                return AdapterOutcome("failure", detail=str(data.get("message", "Game rejected action")))
            if data.get("phase") != "completed" or data.get("verified") is not True:
                return AdapterOutcome("unknown", detail="Game accepted/validated action; execution not yet observed",
                                      evidence={"accepted": True, "action_id": request.action_id})
            after = await self._state()
            if (after["revision"] == revision or after["revision"] != data.get("state_revision") or
                    after.get("last_action_id") != request.action_id):
                return AdapterOutcome("unknown", detail="Completion receipt does not match the observed game revision")
            return AdapterOutcome("success", True, "Game completion matched a new observed state",
                                  {"action_id": request.action_id, "before_revision": revision,
                                   "after_revision": after["revision"]})
        except Exception as exc:
            return AdapterOutcome("unknown", detail=f"Game result unverified: {type(exc).__name__}: {exc}")
        finally:
            self._active_action = None

    async def stop(self):
        if self._active_action is None:
            return {"status": "idle"}
        callback = getattr(self.transport, "cancel_action", None)
        if callback is None:
            return {"status": "unknown", "detail": "Game transport cannot acknowledge cancellation"}
        acknowledged = await callback(self._active_action)
        return {"status": "cancelled" if acknowledged is True else "unknown", "action_id": self._active_action}
