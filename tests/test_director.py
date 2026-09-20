"""Executable rule plans and real SQLite growth; no models or production files."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from xiyin_runtime.agenda import Agenda
from xiyin_runtime.body import ActionRequest, BodyRegistry, WorkspaceFileAdapter
from xiyin_runtime.body.game import GameActionSpec, TypedGameAdapter
from xiyin_runtime.director import Director, FileSkillPlanner, validate_plan
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.self_state import SelfState


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-director-")))
        self.store = self.enterContext(ExperienceStore(self.tmp / "experience.sqlite3"))
        self.state = SelfState(self.store)
        self.agenda = Agenda(self.store)
        self.director = Director(self.store, self.state, self.agenda, FileSkillPlanner())
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        self.body = BodyRegistry()
        self.body.register(WorkspaceFileAdapter(self.workspace))
        self.caps = self.body.capabilities()

    def feedback(self, statement, *, kind="preference", subject="expression:private",
                 session="owner", scope="private", origin="user_report", event_kind="user_feedback"):
        growth = {"kind": kind, "subject": subject, "statement": statement}
        source = self.store.append_event(event_kind, {"growth": growth}, session_id=session, scope=scope, origin=origin)
        return self.director.propose_growth(**growth, evidence_refs=[source], session_id=session, scope=scope)

    def test_unconfigured_planner_is_unavailable_and_creates_no_job(self):
        director = Director(self.store, self.state, self.agenda)
        self.assertEqual(director.propose_goal("自由规划", self.caps)["status"], "unavailable")
        self.assertEqual(self.store.list_documents("goals"), [])
        self.assertEqual(self.store.list_documents("jobs"), [])

    def test_rule_write_and_read_plans_actually_execute_through_registered_body(self):
        async def execute(goal):
            job = self.agenda.claim_next()
            self.assertEqual(job["payload"]["goal_id"], goal["id"])
            results = []
            for step in goal["steps"]:
                observation = await self.body.observe(step["adapter_id"])
                request = ActionRequest(step["adapter_id"], step["operation"], observation.observation_id,
                                        self.caps[0]["scope"], time.monotonic() + 10,
                                        arguments=step["arguments"])
                results.append(await self.body.execute(request))
            self.agenda.finish(job["id"], "completed", result={"verified": all(r.verified for r in results)})
            return results
        goal = self.director.propose_goal({"skill": "write_text", "path": "hello.txt", "text": "栖音"}, self.caps)
        self.assertEqual(goal["planner"], "rule_file_skill")
        self.assertEqual(goal["status"], "queued")
        self.assertFalse((self.workspace / "hello.txt").exists(), "planning cannot execute a Body action")
        written = asyncio.run(execute(goal))
        self.assertEqual(written[0].status, "success")
        self.assertTrue(written[0].verified)
        self.assertEqual((self.workspace / "hello.txt").read_text(encoding="utf-8"), "栖音")
        read = self.director.propose_goal({"skill": "read_text", "path": "hello.txt"}, self.caps)
        receipts = asyncio.run(execute(read))
        self.assertEqual(receipts[0].evidence["text"], "栖音")

    def test_injected_planner_only_receives_copies_and_cannot_grant_capabilities(self):
        def planner(**kwargs):
            kwargs["capabilities"][0]["operations"].append("shell")
            kwargs["capabilities"][0]["scope"] = "/"
            kwargs["state"]["identity"]["name_zh"] = "changed"
            return {"title": "attempt", "steps": [{"adapter_id": "workspace", "operation": "shell", "arguments": {}}]}
        director = Director(self.store, self.state, self.agenda, planner)
        with self.assertRaises(ValueError):
            director.propose_goal("untrusted model proposal", self.caps)
        self.assertEqual(self.state.snapshot()["identity"]["name_zh"], "栖音")
        self.assertNotIn("shell", self.body.capabilities()[0]["operations"])
        self.assertEqual(self.store.list_documents("jobs"), [])

    def test_schema_rejects_scope_code_cross_domain_and_unavailable_actions(self):
        step = {"adapter_id": "workspace", "operation": "read_text", "arguments": {"path": "a.txt"}}
        bad_steps = [dict(step, scope="/"), dict(step, operation="unregistered"),
                     dict(step, adapter_id="new"), dict(step, arguments={"path": "../secret"}),
                     dict(step, arguments={"path": "a.txt", "shell": "echo x"}),
                     dict(step, arguments={"path": "a.txt", "policy": {"verify_after_write": False}})]
        for bad in bad_steps:
            with self.subTest(step=bad), self.assertRaises(ValueError):
                validate_plan({"title": "bad", "steps": [bad]}, self.caps)
        for count in (0, 33):
            with self.assertRaises(ValueError):
                validate_plan({"title": "bad length", "steps": [step] * count}, self.caps)
        self.assertEqual(len(validate_plan({"title": "bounded", "steps": [step] * 32}, self.caps)["steps"]), 32)
        caps = deepcopy(self.caps)
        caps[0]["available"] = False
        with self.assertRaises(ValueError):
            validate_plan({"title": "unavailable", "steps": [step]}, caps)
        caps = deepcopy(self.caps) + [dict(self.caps[0], adapter_id="other", scope="elsewhere")]
        with self.assertRaises(ValueError):
            validate_plan({"title": "cross domain", "steps": [step, dict(step, adapter_id="other")]}, caps)
        with self.assertRaises(PermissionError):
            self.director.propose_goal({"skill": "read_text", "path": "a"}, self.caps, scope="public")
        with self.assertRaises(ValueError):
            self.director.propose_goal({"skill": "copy", "source": "a", "destination": "b"}, self.caps)

    def test_goal_and_job_creation_roll_back_together(self):
        original = self.store.write_document
        def fail_goal(collection, *args, **kwargs):
            if collection == "goals":
                raise OSError("synthetic goal persistence failure")
            return original(collection, *args, **kwargs)
        with patch.object(self.store, "write_document", side_effect=fail_goal):
            with self.assertRaises(OSError):
                self.director.propose_goal({"skill": "read_text", "path": "a"}, self.caps)
        self.assertEqual(self.store.list_documents("jobs"), [])
        self.assertEqual(self.store.list_documents("goals"), [])

    def test_typed_game_adapter_namespace_is_valid_without_relaxing_sessions(self):
        class ConnectedTransport:
            connected = True
        game = TypedGameAdapter("puzzle_1", [GameActionSpec("choose", "Choose a numbered path", {
            "type": "object", "properties": {"path": {"type": "integer", "minimum": 1, "maximum": 3}},
            "required": ["path"], "additionalProperties": False,
        })], transport=ConnectedTransport())
        self.body.register(game)
        plan = {"title": "Choose puzzle path", "steps": [{
            "adapter_id": "game:puzzle_1", "operation": "choose",
            "arguments": {"state_revision": "round-1", "parameters": {"path": 2}},
        }]}
        director = Director(self.store, self.state, self.agenda, lambda **kwargs: deepcopy(plan))
        goal = director.propose_goal("Choose path two", self.body.capabilities())
        self.assertEqual(goal["steps"], plan["steps"])
        self.assertEqual(goal["capability_bindings"][0]["adapter_id"], "game:puzzle_1")
        self.assertEqual(goal["capability_bindings"][0]["scope"], "game:puzzle_1")
        with self.assertRaises(ValueError):
            director.propose_goal("Choose path two", self.body.capabilities(), session_id="game:puzzle_1")
        for invalid in (":puzzle", "game:", "game:puzzle:extra", "game:../escape", "game:/absolute", "game:puzzle\n"):
            caps = [dict(game.capability.to_dict(), adapter_id=invalid)]
            with self.subTest(identifier=invalid), self.assertRaises(ValueError):
                validate_plan(plan, caps)

    def test_adopted_growth_changes_projection_and_survives_reopen_without_seed_edit(self):
        seed = deepcopy(self.state.persona.data)
        candidate = self.feedback("熟悉场合可以主动分享有趣细节。", kind="persona", subject="tendency:settling")
        before = self.state.snapshot()
        self.assertNotEqual(before["tendencies"][0]["value"], candidate["statement"])
        adopted = self.director.adopt_growth(candidate["id"])
        self.assertEqual(adopted["status"], "adopted")
        current = self.state.snapshot()
        self.assertEqual(current["tendencies"][0]["value"], candidate["statement"])
        self.assertEqual(current["identity"], before["identity"])
        self.assertEqual(self.state.persona.data, seed)
        self.assertEqual(len(self.store.memories()), 1)
        self.assertEqual(self.director.adopt_growth(candidate["id"])["memory_id"], adopted["memory_id"])
        self.assertEqual(len(self.store.memories()), 1)
        with ExperienceStore(self.store.path) as reopened:
            self.assertEqual(SelfState(reopened).snapshot()["tendencies"][0]["value"], candidate["statement"])

    def test_self_state_feedback_source_is_supported_but_mismatched_statement_is_rejected(self):
        growth = {"kind": "preference", "subject": "expression:private", "statement": "分享时多回应内容，不必总追问。"}
        state = self.state.observe("user_feedback", {"rating": 0.8, "growth": growth})
        candidate = self.director.propose_growth(**growth, evidence_refs=[state["last_event_id"]])
        self.director.adopt_growth(candidate["id"])
        self.assertEqual(self.state.snapshot()["expression"]["private"], growth["statement"])
        growth["statement"] = "总是保持沉默。"
        with self.assertRaises(ValueError):
            self.director.propose_growth(**growth, evidence_refs=[state["last_event_id"]])

    def test_growth_rejects_identity_owner_authority_generated_and_wrong_scope_evidence(self):
        for subject in ("owner", "identity:name_zh", "authority", "relationship:qinai", "unassigned:favorite_game"):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                self.feedback("arbitrary", subject=subject)
        for origin in ("generated", "simulation", "reflection", "inference", "tool_result"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                self.feedback("new style", origin=origin)
        with self.assertRaises(ValueError):
            self.feedback("assistant assertion", event_kind="assistant")
        candidate = self.feedback("private style")
        # Evidence from another session is unsupported; public scope is refused
        # outright, matching propose_goal — a viewer may send feedback, so
        # growth must not read it even when the statement would be valid.
        with self.assertRaises(ValueError):
            self.director.propose_growth("preference", "expression:private", "private style",
                                         candidate["evidence_refs"], session_id="other", scope="private")
        with self.assertRaises(PermissionError):
            self.director.propose_growth("preference", "expression:private", "private style",
                                         candidate["evidence_refs"], session_id="owner", scope="public")

    def test_growth_rollback_returns_seed_or_prior_override_without_rewriting_history(self):
        seed = self.state.snapshot()["expression"]["private"]
        first = self.feedback("可以主动表达自己的看法。")
        self.director.adopt_growth(first["id"])
        second = self.feedback("分享时先接住内容，按需再追问。")
        self.director.adopt_growth(second["id"])
        with self.assertRaises(ValueError):
            self.director.rollback_growth(first["id"])
        rolled = self.director.rollback_growth(second["id"])
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertEqual(self.state.snapshot()["expression"]["private"], first["statement"])
        self.assertEqual(self.director.rollback_growth(second["id"]), rolled)
        another = self.feedback("公开时补足必要背景。", subject="expression:public")
        public_seed = self.state.snapshot()["expression"]["public"]
        self.director.adopt_growth(another["id"])
        self.director.rollback_growth(another["id"])
        self.assertEqual(self.state.snapshot()["expression"]["public"], public_seed)
        self.assertNotEqual(self.state.snapshot()["expression"]["private"], seed)
        receipts = self.store.operation_receipts("owner", limit=20)
        self.assertEqual(receipts[-1]["content"]["operation"], "retract")
        self.assertTrue(self.store._db.execute("SELECT COUNT(*) FROM memories WHERE active=0").fetchone()[0] >= 3)

    def test_growth_adoption_and_rollback_are_atomic_with_candidate_receipts(self):
        candidate = self.feedback("直接回应，不靠固定口头禅。")
        original = self.store.write_document
        def fail_candidate(collection, *args, **kwargs):
            if collection == "candidates":
                raise OSError("synthetic candidate commit failure")
            return original(collection, *args, **kwargs)
        before = len(self.store.operation_receipts("owner", limit=20))
        with patch.object(self.store, "write_document", side_effect=fail_candidate):
            with self.assertRaises(OSError):
                self.director.adopt_growth(candidate["id"])
        self.assertEqual(self.store.memories(), [])
        self.assertEqual(len(self.store.operation_receipts("owner", limit=20)), before)
        self.assertEqual(self.store.read_document("candidates", candidate["id"])["value"]["status"], "proposed")
        adopted = self.director.adopt_growth(candidate["id"])
        with patch.object(self.store, "write_document", side_effect=fail_candidate):
            with self.assertRaises(OSError):
                self.director.rollback_growth(candidate["id"])
        self.assertEqual(self.store.memories()[0]["id"], adopted["memory_id"])
        self.assertEqual(self.store.read_document("candidates", candidate["id"])["value"]["status"], "adopted")

    def test_modified_candidate_cannot_be_adopted(self):
        candidate = self.feedback("test preference")
        changed = dict(candidate, statement="something not in user feedback")
        self.store.write_document("candidates", candidate["id"], changed)
        with self.assertRaises(ValueError):
            self.director.adopt_growth(candidate["id"])
        self.assertEqual(self.store.memories(), [])


if __name__ == "__main__":
    unittest.main()
