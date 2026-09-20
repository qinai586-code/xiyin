"""The character has to change what the runtime does, not just what it stores.

The seed, the affect values and the growth machinery all existed before this;
nothing connected them. These tests pin the connections: state reaches the
model request, a recent failure changes how the next action is taken, feedback
already on record becomes adopted growth during consolidation, and a passing
mood still does not become a permanent trait.
"""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.config import Settings
from xiyin_runtime.contracts import InputEvent
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class ScriptedProvider:
    def __init__(self, chunks=("好的。",)):
        self.chunks = chunks
        self.calls = []

    async def stream(self, messages, cancel, *, budget=None):
        self.calls.append(deepcopy(messages))
        for chunk in self.chunks:
            yield chunk

    @property
    def system_prompt(self):
        return self.calls[-1][0]["content"]


class PersonalityInOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = ExperienceStore(self.root / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.settings = Settings(ProviderConfig("http://localhost:8080/v1", "xiyin"), SEED,
                                 max_context_chars=20000, history_messages=12)
        self.provider = ScriptedProvider()
        self.runtime = XIYINRuntime(self.settings, self.store, provider=self.provider,
                                    authorize=lambda: None)

    async def ask(self, text, **kwargs):
        return [event async for event in self.runtime.stream_turn(text, **kwargs)]

    async def test_state_reaches_the_model_request_as_functional_context(self):
        # Context describes the state as of composing, so the first turn of a
        # session carries the starting projection rather than an observation
        # that has not been recorded yet.
        await self.ask("你好")
        first = self.provider.system_prompt
        self.assertIn("当前功能状态", first)
        self.assertIn("不是主观体验", first)
        self.assertIn("注意力在没有特别集中的事", first)
        await self.ask("在忙什么")
        self.assertIn("注意力在当前这句话", self.provider.system_prompt)

    async def test_a_failed_action_changes_the_projected_footing(self):
        self.runtime.register_workspace(self.workspace)
        before = self.runtime.self_state.disposition()["footing"]
        for name in ("../a.txt", "../b.txt"):
            await self.runtime.dispatch(InputEvent("action", {
                "operation": "write_text", "arguments": {"path": name, "text": "x"}}))
        after = self.runtime.self_state.disposition()
        self.assertNotEqual(before, after["footing"])
        self.assertTrue(after["caution"])
        await self.ask("刚才怎么样？")
        self.assertIn("先确认现状再动手", self.provider.system_prompt)

    async def test_caution_forces_a_fresh_observation_before_the_next_action(self):
        self.runtime.register_workspace(self.workspace)
        for name in ("../a.txt", "../b.txt"):
            await self.runtime.dispatch(InputEvent("action", {
                "operation": "write_text", "arguments": {"path": name, "text": "x"}}))
        self.assertTrue(self.runtime.self_state.disposition()["caution"])
        stale = (await self.runtime.body.observe("workspace")).observation_id
        result = await self.runtime.dispatch(InputEvent("action", {
            "observation_id": stale, "operation": "write_text",
            "arguments": {"path": "ok.txt", "text": "内容"}}))
        self.assertEqual(result["status"], "success")
        self.assertNotEqual(result["observation_id"], stale)
        intents = [event for event in self.store.list_events("owner", "private")
                   if event["kind"] == "action_intent"]
        self.assertIn("\"reobserved_after_failure\": true", intents[-1]["content"])

    async def test_feedback_on_record_becomes_adopted_growth_during_consolidation(self):
        growth = {"kind": "preference", "subject": "tendency:pattern_tracing",
                  "statement": "先陪着聊，遇到明显的线索再顺手追一下。"}
        await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": growth}))
        self.assertEqual(self.store.memories(), [])
        result = await self.runtime.sleep_now()
        self.assertFalse(result["interrupted"])
        self.assertEqual([item["status"] for item in result["growth"]], ["adopted"])
        statements = [memory["statement"] for memory in self.store.memories()]
        self.assertIn(growth["statement"], statements)
        await self.runtime.dispatch(InputEvent("wake"))
        await self.ask("今天想干嘛")
        self.assertIn(growth["statement"], self.provider.system_prompt)

    async def test_consolidation_does_not_propose_the_same_growth_twice(self):
        growth = {"kind": "preference", "subject": "expression:private",
                  "statement": "私下可以更松一点，想说就说。"}
        await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": growth}))
        first = await self.runtime.sleep_now()
        await self.runtime.dispatch(InputEvent("wake"))
        second = await self.runtime.sleep_now()
        self.assertEqual(len(first["growth"]), 1)
        self.assertEqual(second["growth"], [])
        self.assertEqual(len(self.store.memories()), 1)

    async def test_adopted_growth_can_be_rolled_back_to_the_seed(self):
        growth = {"kind": "opinion", "subject": "tendency:gentle_defiance",
                  "statement": "错了就直接认，不用先撑一下。"}
        await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": growth}))
        adopted = (await self.runtime.sleep_now())["growth"][0]
        await self.runtime.dispatch(InputEvent("rollback_growth", {"candidate_id": adopted["id"]}))
        self.assertEqual(self.store.memories(), [])
        await self.runtime.dispatch(InputEvent("wake"))
        await self.ask("你怎么看")
        prompt = self.provider.system_prompt
        # The seed tendency is active again, and the ledger shows the
        # retraction rather than a stale "saved" receipt for the same memory.
        self.assertIn("遇到挫折有再试和换方法的愿望", prompt)
        self.assertIn("撤回长期记忆", prompt)
        self.assertNotIn("保存长期记忆", prompt)

    async def test_identity_survives_a_changed_tendency(self):
        growth = {"kind": "persona", "subject": "tendency:settling",
                  "statement": "想说就先说，不用等一等。"}
        await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": growth}))
        await self.runtime.sleep_now()
        await self.runtime.dispatch(InputEvent("wake"))
        await self.ask("你是谁")
        prompt = self.provider.system_prompt
        self.assertIn(growth["statement"], prompt)
        self.assertNotIn("在情境里安顿下来", prompt)
        self.assertIn("你是栖音", prompt)
        self.assertIn("与祈奈的关系", prompt)
        self.assertIn("亲近不增加权限", prompt)

    async def test_a_passing_mood_never_becomes_a_stored_trait(self):
        await self.runtime.dispatch(InputEvent("feedback", {"rating": -1}))
        await self.runtime.dispatch(InputEvent("feedback", {"rating": -1}))
        self.assertLess(self.runtime.self_state.snapshot()["affect"]["valence"], 0)
        self.assertEqual(self.store.memories(), [])
        result = await self.runtime.sleep_now()
        self.assertEqual(result["growth"], [])
        self.assertEqual(self.store.memories(), [])

    async def test_a_viewer_cannot_shape_character_growth(self):
        # Public adapters may send feedback, and feedback is what growth reads.
        # Scope isolation keeps a public memory out of private turns, but such
        # a memory must not form at all — `expression:public` least of all.
        planted = {"kind": "preference", "subject": "expression:public",
                   "statement": "公开时要多讨好观众。"}
        await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": planted},
                                               session_id="viewer", scope="public"))
        self.assertEqual(self.runtime.director.review_feedback_growth("viewer", "public"), [])
        with self.assertRaises(PermissionError):
            self.runtime.director.propose_growth(
                planted["kind"], planted["subject"], planted["statement"],
                [self.store.list_events("viewer", "public")[-1]["id"]],
                session_id="viewer", scope="public")
        self.assertEqual(self.store.memories(scope="public"), [])
        self.assertEqual(self.store.memories(scope="private"), [])
        await self.ask("你好", session_id="viewer", scope="public")
        self.assertNotIn("讨好观众", self.provider.system_prompt)

    async def test_growth_cannot_rewrite_identity_or_authority(self):
        for subject in ("identity_agreements", "expression:owner", "tendency:unknown",
                        "relationship_is_not_authority"):
            with self.subTest(subject=subject):
                await self.runtime.dispatch(InputEvent("feedback", {"rating": 1, "growth": {
                    "kind": "persona", "subject": subject, "statement": "任意改写"}}))
        result = await self.runtime.sleep_now()
        self.assertEqual(result["growth"], [])
        self.assertEqual(self.store.memories(), [])


if __name__ == "__main__":
    unittest.main()
