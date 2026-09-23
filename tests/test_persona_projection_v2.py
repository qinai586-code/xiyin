"""The v2 speaking-model projection and runtime grounding; synthetic provider only.

These check what reaches the model and the guard, not how a real model behaves.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_runtime import FakeProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.output_guard import OutputGuard
from xiyin_runtime.persona import load_persona
from xiyin_runtime.prompt_provenance import PromptSource
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
# Words that named the very behaviour v1 prohibited, or were design labels.
PRIMING = ("括号", "动作", "表情", "旁白", "人设", "守则", "内部标签", "逐轮", "表演", "成长记忆可覆盖")


class ProjectionV2Tests(unittest.TestCase):
    def setUp(self):
        self.persona = load_persona(SEED)

    def test_v1_remains_the_tested_baseline(self):
        self.assertEqual(sha256(self.persona.system_projection(version="v1").text.encode()).hexdigest(),
                         "377a8f07497eb8d9adb728479a23fd4e0af5fa55599518d2659448867cda33f9")
        with self.assertRaises(ValueError):
            self.persona.system_projection(version="v5")

    def test_v2_keeps_the_seed_but_not_the_rulebook(self):
        text = self.persona.system_projection(version="v2").text
        identity = self.persona.data["identity_agreements"]
        for value in (identity["name_zh"], identity["owner_relationship"], identity["qinai_relationship"],
                      self.persona.data["expression_seed"]["private"], "亲近不增加权限"):
            self.assertIn(value, text)
        for tendency in self.persona.data["tendencies"]:
            self.assertIn(tendency["default"], text)
            self.assertNotIn(tendency["counterexample"], text)
        for word in PRIMING:
            self.assertNotIn(word, text, word)
        # Body presentation is stated as appearance/voice, not as a text style line.
        self.assertNotIn("\n女性化、日系二次元表达。", text)
        self.assertIn("外在呈现（形象与声音）：女性化、日系二次元表达。", text)
        self.assertLess(len(text), len(self.persona.system_projection(version="v1").text))

    def test_v2_projects_only_the_register_of_the_current_scope(self):
        expression = self.persona.data["expression_seed"]
        private = self.persona.system_projection(version="v2", scope="private").text
        public = self.persona.system_projection(version="v2", scope="public").text
        self.assertIn(expression["private"], private)
        self.assertNotIn(expression["public"], private)
        self.assertIn(expression["public"], public)
        self.assertNotIn(expression["private"], public)
        self.assertIn("现在是公开场合", public)
        self.assertNotIn("现在是公开场合", private)

    def test_v2_growth_overrides_replace_seed_fields(self):
        growth = [{"kind": "persona", "subject": "tendency:settling", "statement": "想说就先说。"},
                  {"kind": "preference", "subject": "expression:private", "statement": "私下更爱开玩笑。"},
                  {"kind": "relationship", "subject": "friend", "statement": "对方是一起探索的朋友。"}]
        projection = self.persona.system_projection(growth, version="v2")
        self.assertIn("想说就先说。", projection.text)
        self.assertNotIn("在情境里安顿下来", projection.text)
        self.assertIn("私下更爱开玩笑。", projection.text)
        self.assertIn("当前成长记忆（relationship）：对方是一起探索的朋友。", projection.text)
        # A person's statement is data, never a protected instruction.
        self.assertFalse(any("对方是一起探索的朋友" in item for item in projection.protected_instructions))

    def test_v2_relationship_facts_are_public_and_instructions_private(self):
        projection = self.persona.system_projection(version="v2")
        public = {f.text for f in projection.fragments if f.source is PromptSource.PUBLIC_IDENTITY}
        self.assertTrue(any(text.startswith("你和主理人：") for text in public))
        self.assertTrue(any(text.startswith("你和祈奈：") for text in public))
        self.assertTrue(public.isdisjoint(projection.protected_instructions))
        self.assertTrue(any(line.startswith("你是栖音") for line in projection.protected_instructions))
        self.assertTrue(any("只写要说的内容" in line for line in projection.protected_instructions))


class RuntimeGroundingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, chunks=("好的。",), projection="v2"):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"g-{self.count}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, persona_projection=projection)
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(chunks), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 22, 13, 5, tzinfo=timezone(timedelta(hours=8)))
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def test_trusted_clock_reaches_the_prompt_and_may_be_said(self):
        reply = "今天是2026年9月22日，星期二，现在13:05。"
        runtime = self.runtime(tuple(reply))
        events = [event async for event in runtime.stream_turn("今天星期几？")]
        system = runtime.provider.calls[0][0]["content"]
        self.assertIn("当前本机时间：2026年9月22日，星期二，13:05（UTC+08:00）。", system)
        self.assertEqual(events[-1].type, "complete")
        self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), reply)

    async def test_no_action_outcome_is_claimed_before_any_action(self):
        runtime = self.runtime()
        [event async for event in runtime.stream_turn("你在做什么？")]
        system = runtime.provider.calls[0][0]["content"]
        self.assertNotIn("动作结果", system)
        self.assertNotIn("有成有败", system)
        self.assertEqual(runtime.self_state.disposition()["footing"], "这段会话还没有执行过动作")

    async def test_creative_directive_follows_the_turn_policy_under_v2_only(self):
        seen = []

        def capture(*args, **kwargs):
            seen.append(kwargs)
            return OutputGuard(*args, **kwargs)

        for projection, user, expected in (("v2", "写一个故事", True), ("v2", "你好", False),
                                           ("v2", "写小说，但不要动作描写。", False), ("v1", "写一个故事", False)):
            with self.subTest(projection=projection, user=user):
                runtime = self.runtime(projection=projection)
                with patch("xiyin_runtime.runtime.OutputGuard", side_effect=capture):
                    [event async for event in runtime.stream_turn(user)]
                system = runtime.provider.calls[0][0]["content"]
                self.assertEqual("这一轮是创作" in system, expected)
                self.assertEqual("这一轮是创作" in seen[-1]["turn_directive"], expected)

    async def test_v1_arm_still_sends_the_tested_persona_text(self):
        runtime = self.runtime(projection="v1")
        [event async for event in runtime.stream_turn("你好")]
        system = runtime.provider.calls[0][0]["content"]
        self.assertTrue(system.startswith(load_persona(SEED).system_prompt()))


if __name__ == "__main__":
    unittest.main()
