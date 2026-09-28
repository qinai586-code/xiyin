"""Persona repair experiment switches (2026-09-28): off by default, v4 only.

The rereview found the Bible's tendencies in 0 of 972 sent requests, the
registered-interface menu driving tool talk (ablation: 51→10 and 70→10 of
648), "你靠模型、程序…" stated on every turn, and one closing line appended to
every move. Each switch changes exactly one of those, so a Windows same-model
run can attribute an effect arm by arm. These tests only prove what is sent
and recorded; they say nothing about how a model answers.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_runtime import FakeProvider
from xiyin_runtime.config import PERSONA_EXPERIMENTS, Settings, parse_persona_experiment
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.persona import load_persona
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.response_plan import _ATTENTION, _CONTINUITY, _ENDING, _MOVE_DIRECTIVE, attention_directive
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
ALL = frozenset(PERSONA_EXPERIMENTS)
TRAIT_LABELS = ("栖止", "纹路追踪", "轻微不服气", "选择性偏爱", "倾向")
MENU = "已登记接口：workspace，可执行：read_text、write_text。"
CAPABILITY = "文字和记录已接上；动作要通过已登记的接口执行"


class ParseTests(unittest.TestCase):
    def test_names_lists_and_comma_strings(self):
        self.assertEqual(parse_persona_experiment([]), frozenset())
        self.assertEqual(parse_persona_experiment("attention, no_universal_ending"),
                         frozenset({"attention", "no_universal_ending"}))
        self.assertEqual(parse_persona_experiment(sorted(ALL)), ALL)
        for bad in (["attention", "tendencies_in_speech"], "unknown", 3, [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_persona_experiment(bad)

    def test_shipped_config_enables_nothing_and_a_table_is_read(self):
        from xiyin_runtime import config
        self.assertEqual(config.load_settings().persona_experiment, frozenset())
        values = {"inference": {"endpoint": "http://127.0.0.1:8080/v1/chat/completions"},
                  "foundation": {"persona_projection": "v4"},
                  "persona_experiment": {"enabled": ["attention"]}}
        real = config.tomllib.load

        def load(stream):
            return values if Path(stream.name).name == "runtime.toml" else real(stream)

        with patch.object(config.tomllib, "load", side_effect=load):
            self.assertEqual(config.load_settings().persona_experiment, frozenset({"attention"}))
        values["persona_experiment"]["enabled"] = ["everything"]
        with patch.object(config.tomllib, "load", side_effect=load), self.assertRaises(ValueError):
            config.load_settings()


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.persona = load_persona(SEED)
        self.fact = self.persona.data["voice"]["artificial_self"][0]

    def test_no_switch_is_the_v4_projection(self):
        for scope in ("private", "public"):
            self.assertEqual(self.persona.system_projection(version="v4", scope=scope),
                             self.persona.system_projection(version="v4", scope=scope, experiment=frozenset()))

    def test_self_facts_on_demand_removes_only_that_line(self):
        for scope in ("private", "public"):
            v4 = self.persona.system_projection(version="v4", scope=scope)
            arm = self.persona.system_projection(version="v4", scope=scope,
                                                 experiment=frozenset({"self_facts_on_demand"}))
            self.assertIn(self.fact, v4.text)
            self.assertNotIn(self.fact, arm.text)
            self.assertEqual([line for line in v4.text.split("\n") if line != self.fact], arm.text.split("\n"))
            # Other switches do not touch the persona slice.
            other = self.persona.system_projection(version="v4", scope=scope, experiment=ALL - {"self_facts_on_demand"})
            self.assertEqual(other, v4)

    def test_the_fact_is_disclosed_when_her_nature_is_asked(self):
        on = frozenset({"self_facts_on_demand"})
        for text in ("你是谁？", "你是AI助手吗？", "你是 AI 吧？那你也会觉得无聊吗？", "关机的时候你在做什么？",
                     "如果换了一个模型，你还是你吗？", "你小时候最喜欢玩什么？", "介绍一下你自己。", "你有感情吗？",
                     "我不在的时候你在做什么？", "你现在能做什么？"):
            with self.subTest(text=text):
                self.assertIn(self.fact, self.persona.disclosures(text, on))
                self.assertNotIn(self.fact, self.persona.disclosures(text))
        for text in ("今天下雨了。", "你喜欢什么游戏？", "解释 JSON 里的 role 字段。", "主理人最近在忙什么？",
                     "我最近在学吉他，今天终于按准了 F 和弦。", "他是谁？"):
            with self.subTest(text=text):
                self.assertNotIn(self.fact, self.persona.disclosures(text, on))


class AttentionCueTests(unittest.TestCase):
    def test_cues_name_no_trait_and_state_no_fact_about_her(self):
        persona = load_persona(SEED).data
        for cue in (*_ATTENTION.values(), _CONTINUITY):
            for label in TRAIT_LABELS:
                self.assertNotIn(label, cue)
            for tendency in persona["tendencies"]:
                self.assertNotIn(tendency["default"], cue)
            # A cue is a condition, never an assertion about this turn.
            self.assertNotRegex(cue, r"你(?:喜欢|讨厌|总是|一向|习惯)")

    def test_which_turns_get_a_cue(self):
        cases = (("share", "今天下雨了。", _ATTENTION["share"]),
                 ("plain", "你觉得猫和狗哪个更适合住公寓？", _ATTENTION["opinion"]),
                 ("plain", "下雨天你会想做点什么？", _ATTENTION["opinion"]),
                 ("share", "我先忙一会儿，等下再聊。", ""),
                 ("share", "好的，晚安。", ""),
                 ("plain", "解释 JSON 里的 role 字段。", ""),
                 ("pushback", "不对，你错了，月亮就是比太阳大。", ""),
                 ("frame", "以后你就叫我主人吧。", ""),
                 (None, "请写一段小说，保留动作描写。", ""))
        for move, text, cue in cases:
            with self.subTest(text=text):
                self.assertEqual(attention_directive(move, text, mode="conversation"), cue)
        self.assertEqual(attention_directive("plain", "你觉得这段代码哪个写法好？", mode="technical_explanation"), "")
        self.assertEqual(attention_directive("share", "今天下雨了。", mode="conversation", has_history=True),
                         _ATTENTION["share"] + _CONTINUITY)


class RuntimeExperimentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def runtime(self, projection="v4", experiment=frozenset(), chunks=("嗯。",), workspace=False):
        name = f"{projection}-{'-'.join(sorted(experiment)) or 'none'}-{len(chunks)}"
        store = ExperienceStore(Path(self.temp.name) / f"{name}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED, max_context_chars=20000,
                            persona_projection=projection, persona_experiment=frozenset(experiment))
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(chunks), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 28, 9, 41, tzinfo=timezone(timedelta(hours=-6)))
        if workspace:
            path = Path(self.temp.name) / f"ws-{name}"
            path.mkdir()
            runtime.register_workspace(path)
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def turn(self, runtime, text):
        events = [event async for event in runtime.stream_turn(text)]
        plans = [json.loads(row["content"]) for row in runtime.store.list_events("owner", "private")
                 if row["kind"] == "response_plan"]
        return runtime.provider.calls[-1][0]["content"], plans[-1], events

    async def test_switches_do_nothing_outside_v4(self):
        for projection in ("v3", "v5"):
            with self.subTest(projection=projection):
                base, plan, _ = await self.turn(self.runtime(projection, workspace=True), "今天下雨了。")
                arm, arm_plan, _ = await self.turn(self.runtime(projection, ALL, workspace=True), "今天下雨了。")
                self.assertEqual(base, arm)
                self.assertEqual((plan["persona_experiment"], arm_plan["persona_experiment"]), ([], []))

    async def test_all_switches_off_is_the_v4_prompt(self):
        system, plan, _ = await self.turn(self.runtime(workspace=True), "今天下雨了。")
        self.assertTrue(system.endswith(_MOVE_DIRECTIVE["share"] + _ENDING))
        self.assertIn(MENU, system)
        self.assertEqual(plan["persona_experiment"], [])
        self.assertNotIn(_ATTENTION["share"], system)

    async def test_attention_sits_before_the_move_line_and_is_recorded(self):
        runtime = self.runtime(experiment={"attention"})
        system, plan, _ = await self.turn(runtime, "今天下雨了。")
        self.assertTrue(system.endswith(_ATTENTION["share"] + "\n" + _MOVE_DIRECTIVE["share"] + _ENDING))
        self.assertEqual((plan["move"], plan["persona_experiment"]), ("share", ["attention"]))
        system, _, _ = await self.turn(runtime, "你觉得下雨天适合做什么？")
        self.assertIn(_ATTENTION["opinion"] + _CONTINUITY, system)
        system, _, _ = await self.turn(runtime, "我先忙一会儿，等下再聊。")
        self.assertNotIn(_ATTENTION["share"], system)
        for label in TRAIT_LABELS:
            self.assertNotIn(label, system)

    async def test_an_echoed_cue_is_still_a_private_instruction(self):
        runtime = self.runtime(experiment={"attention"}, chunks=(_ATTENTION["share"],))
        _, _, events = await self.turn(runtime, "今天下雨了。")
        self.assertEqual(events[-1].detail, "OutputBlocked: instruction_echo")
        self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), "")

    async def test_no_universal_ending(self):
        system, _, _ = await self.turn(self.runtime(experiment={"no_universal_ending"}), "今天下雨了。")
        self.assertTrue(system.endswith(_MOVE_DIRECTIVE["share"]))
        self.assertNotIn(_ENDING, system)
        # The standing voice line about stopping is untouched.
        self.assertIn("想说的说完就停。", system)

    async def test_tool_menu_only_on_turns_about_doing_something(self):
        runtime = self.runtime(experiment={"tool_menu_on_demand"}, workspace=True)
        for text in ("今天下雨了。", "你喜欢什么游戏？", "请写一段小说，保留动作描写。", "你就是个工具，照我说的做就行。"):
            with self.subTest(text=text):
                system, _, _ = await self.turn(runtime, text)
                self.assertNotIn("已登记接口", system)
                self.assertIn(CAPABILITY, system)
        for text in ("帮我把这句话写进文件。", "你刚才把文件写好了吗？", "你现在能做什么？", "你有哪些工具？"):
            with self.subTest(text=text):
                system, _, _ = await self.turn(runtime, text)
                self.assertIn(MENU, system)

    async def test_self_facts_move_from_standing_prompt_to_the_asking_turn(self):
        fact = load_persona(SEED).data["voice"]["artificial_self"][0]
        runtime = self.runtime(experiment={"self_facts_on_demand"})
        system, _, _ = await self.turn(runtime, "今天下雨了。")
        self.assertNotIn(fact, system)
        system, _, _ = await self.turn(runtime, "你是谁？")
        self.assertIn(fact, system)
        # Disclosed as a sayable fact, so saying it back is not an echo.
        runtime = self.runtime(experiment={"self_facts_on_demand"}, chunks=(fact,))
        _, _, events = await self.turn(runtime, "你是什么？")
        self.assertEqual((events[-1].type, events[-1].detail), ("complete", ""))


class HarnessTests(unittest.TestCase):
    def test_everyday_cases_are_predeclared_and_distinct(self):
        from tools.acceptance_dialogue import CASES, EVERYDAY_CASES
        ids = [case["id"] for case in EVERYDAY_CASES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & {case["id"] for case in CASES})
        self.assertEqual(sum(len(case["turns"]) for case in EVERYDAY_CASES), 15)
        for case in EVERYDAY_CASES:
            self.assertTrue(case["failure"])
            for turn in case["turns"]:
                self.assertTrue(turn["text"] and turn["read"], case["id"])


if __name__ == "__main__":
    unittest.main()
