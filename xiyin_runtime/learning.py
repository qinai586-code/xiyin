"""Data-only strategy candidates, independent checks, adoption and rollback.

An adopted policy changes the active policy record consumed by the Body. This
does not train weights or establish unmeasured skill/transfer improvements.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import uuid


DEFAULT_POLICY = {"max_read_bytes": 65536, "max_write_bytes": 65536,
                  "verify_after_write": True, "encoding": "utf-8"}
POLICY_CHECKS = ("schema", "budget_bounds", "verified_file_roundtrip")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY):
        raise ValueError("Only the bounded file-operation strategy fields may change")
    for key in ("max_read_bytes", "max_write_bytes"):
        if type(policy[key]) is not int or not 1 <= policy[key] <= 1024 * 1024:
            raise ValueError("File strategy budgets must be between 1 and 1048576 bytes")
    if policy["verify_after_write"] is not True or policy["encoding"] != "utf-8":
        raise ValueError("Strategies cannot disable verification or change the encoding")
    return deepcopy(policy)


class BuiltinPolicyEvaluator:
    """Independent deterministic scope/budget check, not an intelligence score."""
    def __call__(self, candidate, *, checks):
        if set(checks) != set(POLICY_CHECKS):
            raise ValueError("Builtin evaluator covers only its three declared checks")
        policy = validate_policy(candidate["policy"])
        # An actual temporary round-trip exercises the policy's fixed encoding;
        # no candidate code or text is executed and no production files are used.
        with tempfile.TemporaryDirectory(prefix="xiyin-policy-eval-") as directory:
            path = Path(directory) / "probe.txt"
            text = "栖音" if min(policy["max_read_bytes"], policy["max_write_bytes"]) >= 6 else "x"
            raw = text.encode(policy["encoding"])
            path.write_bytes(raw)
            roundtrip = path.read_bytes() == raw and path.read_text(encoding=policy["encoding"]) == text
        return {"passed": roundtrip, "candidate_digest": candidate["digest"],
                "checks": {"schema": True, "budget_bounds": True, "verified_file_roundtrip": roundtrip},
                "measurement_kind": "functional_policy_check",
                "measurement": "bounded file policy validation; no general skill claim"}


class LearningLab:
    def __init__(self, store, generator=None, evaluator=None):
        if generator is not None and not callable(generator):
            raise ValueError("Candidate generator must be callable")
        if evaluator is not None and (not callable(evaluator) or evaluator is generator):
            raise ValueError("An independent evaluator must be distinct from the generator")
        self.store, self.generator, self.evaluator = store, generator, evaluator

    def _evidence(self, refs, session_id, scope):
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("Existing experience evidence ids are required")
        events = {event["id"]: event for event in self.store.list_events(session_id, scope=scope)}
        evidence = []
        for ref in dict.fromkeys(refs):
            event = events.get(ref)
            if (event is None or event["origin"] in {"generated", "assistant_output", "reflection", "inference", "simulation", "design_seed"}
                    or event["status"] in {"generated", "partial", "cancelled", "failed", "unknown", "verified_failure"}):
                raise ValueError("Candidate evidence must reference completed source records, not self-evaluation")
            evidence.append(event)
        return evidence

    def propose(self, goal, evidence_refs, scope="strategy", *, strategy=None, session_id="owner", visibility="private"):
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 2000:
            raise ValueError("A short candidate objective is required")
        if scope not in {"strategy", "skill"}:
            raise ValueError("Lab may only propose data-only strategy or skill candidates")
        evidence = self._evidence(evidence_refs, session_id, visibility)
        if strategy is None:
            if self.generator is None:
                raise ValueError("Provide an explicit strategy or a configured candidate generator")
            strategy = self.generator(goal=goal, evidence=deepcopy(evidence))
        policy = validate_policy(strategy)
        candidate_id = "candidate_" + uuid.uuid4().hex
        value = {"id": candidate_id, "kind": scope, "goal": goal.strip(), "policy": policy,
                 "evidence_refs": list(dict.fromkeys(evidence_refs)), "session_id": session_id,
                 "visibility": visibility, "status": "proposed", "created_at": _now(),
                 "digest": _digest(policy), "affected": ["body.file_policy"],
                 "assessment": None}
        return self.store.write_document("candidates", candidate_id, value, expected_version=0)["value"]

    def evaluate(self, candidate_id, checks=POLICY_CHECKS):
        if self.evaluator is None:
            raise RuntimeError("No independent evaluator is configured; candidate is not approved")
        document = self.store.read_document("candidates", candidate_id)
        if document is None:
            raise KeyError(candidate_id)
        value = deepcopy(document["value"])
        if value["status"] != "proposed":
            raise ValueError("Only a proposed candidate can be evaluated")
        if not isinstance(checks, (tuple, list)) or not checks or any(not isinstance(check, str) or not check for check in checks):
            raise ValueError("Independent checks must be named explicitly")
        checks = tuple(dict.fromkeys(checks))
        if not set(POLICY_CHECKS).issubset(checks):
            raise ValueError("Evaluation must include all affected file-policy checks")
        validate_policy(value["policy"])
        if value["digest"] != _digest(value["policy"]):
            raise ValueError("Candidate changed after registration")
        self._evidence(value["evidence_refs"], value["session_id"], value["visibility"])
        result = self.evaluator(deepcopy(value), checks=checks)
        if (not isinstance(result, dict) or type(result.get("passed")) is not bool
                or result.get("candidate_digest") != value["digest"]
                or not isinstance(result.get("checks"), dict) or set(result["checks"]) != set(checks)
                or any(type(outcome) is not bool for outcome in result["checks"].values())):
            raise ValueError("Evaluator did not return independently scoped check results")
        passed = result["passed"] and all(result["checks"].values())
        value["status"] = "evaluated" if passed else "rejected"
        value["assessment"] = {"passed": passed, "checks": result["checks"], "candidate_digest": value["digest"],
                               "evaluator": type(self.evaluator).__module__ + "." + type(self.evaluator).__qualname__,
                               "measurement_kind": "functional_policy_check",
                               "evaluated_at": _now(), "measurement": str(result.get("measurement", ""))[:1000]}
        return self.store.write_document("candidates", candidate_id, value, expected_version=document["version"])["value"]

    def active_strategy(self):
        document = self.store.read_document("state", "active_strategy")
        return deepcopy(document["value"]) if document else {"candidate_id": None, "policy": deepcopy(DEFAULT_POLICY), "previous": None}

    def adopt(self, candidate_id):
        candidate = self.store.read_document("candidates", candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        value = candidate["value"]
        assessment = value.get("assessment")
        if (value.get("status") != "evaluated" or not assessment or assessment.get("passed") is not True
                or assessment.get("candidate_digest") != _digest(value["policy"])
                or not isinstance(assessment.get("checks"), dict)
                or not set(POLICY_CHECKS).issubset(assessment["checks"])
                or any(passed is not True for passed in assessment["checks"].values())):
            raise ValueError("An unchanged independently evaluated candidate is required")
        policy = validate_policy(value["policy"])
        self._evidence(value["evidence_refs"], value["session_id"], value["visibility"])
        prior = self.store.read_document("state", "active_strategy")
        if prior and prior["value"].get("candidate_id") == candidate_id:
            return deepcopy(prior["value"])
        active = {"candidate_id": candidate_id, "policy": policy, "adopted_at": _now(),
                  "previous": {**prior["value"], "previous": None} if prior else self.active_strategy(), "assessment": assessment}
        # One atomic document chooses the actual policy; candidate status is not
        # a second authority that could disagree after an interrupted adoption.
        return self.store.write_document("state", "active_strategy", active,
                                         expected_version=prior["version"] if prior else 0)["value"]

    def apply_candidate(self, record):
        candidate_id = record if isinstance(record, str) else record.get("id")
        return self.adopt(candidate_id)

    def rollback(self):
        current = self.store.read_document("state", "active_strategy")
        if current is None or current["value"].get("previous") is None:
            raise ValueError("No previous strategy is available")
        previous = deepcopy(current["value"]["previous"])
        validate_policy(previous["policy"])
        return self.store.write_document("state", "active_strategy", previous,
                                         expected_version=current["version"])["value"]
