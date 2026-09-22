"""The v3 projection, its seed fields and persona style evidence; synthetic provider only.

These check what reaches the model, what the guard treats as sayable, and what
the ledger records. They say nothing about how a real model will talk; that is
the dialogue harness's P cases on the Windows host.
"""
import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.test_body_speech import ASR, Sink, TTS
from tests.test_runtime import FakeProvider
from xiyin_runtime.body import SpeechController
from xiyin_runtime.config import Settings
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.persona import Persona, _validate_character_fields, load_persona
from xiyin_runtime.persona_style import GATES, METRICS, profile, summarize
from xiyin_runtime.prompt_provenance import PromptSource
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
V1_SHA = "377a8f07497eb8d9adb728479a23fd4e0af5fa55599518d2659448867cda33f9"


def seed_data():
    return json.loads(SEED.read_text(encoding="utf-8"))


class SeedFieldTests(unittest.TestCase):
    def test_seed_loads_and_v1_stays_byte_identical(self):
        persona = load_persona(SEED)
        self.assertEqual(sha256(persona.system_projection(version="v1").text.encode()).hexdigest(), V1_SHA)

    def test_projected_wording_rejects_absolutes_removed_in_v02(self):
        for path, value in ((("voice", "zh"), "永远平静地说话。"),
                            (("voice", "stance", 0), "你总是要反驳。"),
                            (("character_definition", "statement"), "一个必须慢下来的人工存在。")):
            with self.subTest(path=path):
                data = seed_data()
                target = data
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(ValueError, "absolutes"):
                    _validate_character_fields(data)

    def test_exemplars_are_few_illustrations_not_memories(self):
        data = seed_data()
        for item in data["style_exemplars"]:
            item["project"] = True
        with self.assertRaisesRegex(ValueError, "at most two"):
            _validate_character_fields(data)
        data = seed_data()
        data["truth_and_continuity"]["dialogue_examples_are_memory"] = True
        with self.assertRaisesRegex(ValueError, "dialogue_examples_are_memory"):
            _validate_character_fields(data)

    def test_negative_frames_are_evaluation_material_only(self):
        data = seed_data()
        data["character_definition"]["not_frames_are_projected"] = True
        with self.assertRaisesRegex(ValueError, "never projected"):
            _validate_character_fields(data)
        data = seed_data()
        data["anti_patterns"][0]["metric"] = "vibes"
        with self.assertRaisesRegex(ValueError, "not measured"):
            _validate_character_fields(data)
        data = seed_data()
        data["anti_patterns"].append(copy.deepcopy(data["anti_patterns"][0]))
        with self.assertRaisesRegex(ValueError, "unique"):
            _validate_character_fields(data)

    def test_optional_fields_stay_optional(self):
        data = seed_data()
        for key in ("voice", "character_definition", "style_exemplars", "anti_patterns", "supplementary_sources"):
            data.pop(key)
        _validate_character_fields(data)
        text = Persona(data).system_projection(version="v3").text
        self.assertTrue(text.startswith("你是栖音（XIYIN），一个人工的存在。"))

    def test_every_anti_pattern_example_trips_its_own_metric(self):
        # The seed's negative examples are the metrics' positive controls.
        for item in seed_data()["anti_patterns"]:
            if item.get("metric") and item.get("example"):
                with self.subTest(pattern=item["id"]):
                    self.assertIn(item["metric"], METRICS)
                    self.assertGreater(profile(item["example"], user_text="随便聊聊")[item["metric"]], 0)

    def test_the_bibles_own_lines_are_clean(self):
        # And the positive examples are its negative controls.
        users = {"打招呼": "你好", "同意时": "这个方案可以吧", "不同意时": "我觉得这样更好",
                 "好奇时": "你看这个设计", "做错时": "刚才那步错了"}
        for item in seed_data()["style_exemplars"]:
            with self.subTest(line=item["text"]):
                counts = profile(item["text"], user_text=users[item["situation"]])
                self.assertEqual([name for name in METRICS if name != "exemplar_copy" and counts[name]], [])
                self.assertEqual(counts["terse"], 0)


class ProjectionV3Tests(unittest.TestCase):
    def setUp(self):
        self.persona = load_persona(SEED)
        self.data = self.persona.data
        self.v3 = self.persona.system_projection(version="v3")

    def test_says_how_she_talks_and_what_she_is(self):
        voice = self.data["voice"]
        for value in (voice["zh"], voice["humor"], *voice["stance"], *voice["artificial_self"],
                      self.data["character_definition"]["statement"]):
            self.assertIn(value, self.v3.text)
        self.assertIn("说话的样子（示意，不是说过的话）：不同意时“等等，这里我有点不一样的想法。”", self.v3.text)
        self.assertEqual(self.persona.projected_exemplars(),
                         ("等等，这里我有点不一样的想法。", "嗯……这里我没处理好。"))

    def test_drops_the_assistant_template_and_the_character_card_labels(self):
        self.assertNotIn("人工智能", self.v3.text)
        self.assertNotIn("助手", self.v3.text)
        self.assertNotIn("性格倾向：", self.v3.text)
        # "客服" appears once, inside the owner's relationship agreement.
        self.assertEqual(self.v3.text.count("客服"), 1)
        self.assertIn("非客服客户关系", self.v3.text)

    def test_what_she_is_not_is_never_projected(self):
        for frame in self.data["character_definition"]["not_frames"]:
            self.assertNotIn(frame, self.v3.text)
        for item in self.data["anti_patterns"]:
            self.assertNotIn(item["description"], self.v3.text)
            if item.get("example"):
                self.assertNotIn(item["example"], self.v3.text)
        for item in self.data["style_exemplars"]:
            self.assertEqual(item["text"] in self.v3.text, item["project"], item["text"])

    def test_appearance_and_decision_motivations_leave_the_standing_prompt(self):
        self.assertNotIn(self.data["identity_agreements"]["presentation_seed"], self.v3.text)
        self.assertNotIn("数据产出", self.v3.text)
        self.assertIn("数据产出", self.persona.system_projection(version="v2").text)
        # Still hers to say.
        public = {f.text for f in self.v3.fragments if f.source is PromptSource.PUBLIC_IDENTITY}
        self.assertIn(self.data["identity_agreements"]["presentation_seed"], public)

    def test_self_facts_and_exemplars_are_sayable_and_instructions_are_not(self):
        protected = self.v3.protected_instructions
        sayable = {f.text for f in self.v3.fragments
                   if f.source in {PromptSource.PUBLIC_IDENTITY, PromptSource.PUBLIC_EXPRESSION}}
        for line in (*self.data["voice"]["artificial_self"], self.data["character_definition"]["statement"],
                     *self.persona.projected_exemplars()):
            self.assertIn(line, sayable)
        for line in self.data["voice"]["artificial_self"]:
            self.assertNotIn(line, protected)
        for line in (self.data["voice"]["zh"], *self.data["voice"]["stance"]):
            self.assertIn(line, protected)
        self.assertTrue(any(line.startswith("说话的样子") for line in protected))
        self.assertTrue(sayable.isdisjoint(protected))

    def test_growth_may_replace_the_voice_it_learned(self):
        growth = [{"kind": "preference", "subject": "voice:zh", "statement": "说话更短一些，常用反问。"}]
        text = self.persona.system_projection(growth, version="v3").text
        self.assertIn("说话更短一些，常用反问。", text)
        self.assertNotIn(self.data["voice"]["zh"], text)
        self.assertNotIn("当前成长记忆", text)

    def test_scope_register_and_public_line(self):
        public = self.persona.system_projection(version="v3", scope="public").text
        self.assertIn(self.data["expression_seed"]["public"], public)
        self.assertNotIn(self.data["expression_seed"]["private"], public)
        self.assertIn("现在是公开场合", public)
        self.assertNotIn("现在是公开场合", self.v3.text)

    def test_no_absolute_words_in_the_character_text_v3_adds(self):
        # v0.2 seed wording is the owner's ("熟悉不等于总是少说" negates one);
        # what v3 adds is checked here and by the loader.
        voice = self.data["voice"]
        added = [line for line in self.v3.text.splitlines()
                 if line in (voice["zh"], voice["humor"], *voice["stance"], *voice["artificial_self"])
                 or line.startswith(("你是栖音", "说话的样子"))]
        self.assertEqual(len(added), 9)
        for line in added:
            self.assertIsNone(re.search(r"永远|总是|必须|绝不|从不|每次都|每句|一定要", line), line)

    def test_appearance_is_disclosed_when_asked(self):
        for question in ("你长什么样？", "你的声音是什么样的", "What do you look like?"):
            with self.subTest(question=question):
                (line,) = self.persona.disclosures(question)
                self.assertIn(self.data["identity_agreements"]["presentation_seed"], line)
                self.assertIn("还没有定下来", line)
        for question in ("今天星期几", "讲讲闭包", "你好"):
            self.assertEqual(self.persona.disclosures(question), ())


class RuntimeV3Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, chunks=("好的。",), projection="v3"):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"v3-{self.count}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, persona_projection=projection)
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(chunks), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 22, 13, 5, tzinfo=timezone(timedelta(hours=8)))
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def system(self, text, projection="v3", runtime=None):
        runtime = runtime or self.runtime(projection=projection)
        [event async for event in runtime.stream_turn(text)]
        return runtime.provider.calls[-1][0]["content"]

    def test_v3_is_the_configured_default(self):
        self.assertEqual(Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED).persona_projection, "v3")
        from xiyin_runtime import config
        self.assertIn('persona_projection = "v3"', (SEED.parents[1] / "runtime.toml").read_text(encoding="utf-8"))
        self.assertTrue(hasattr(config, "load_settings"))

    async def test_runtime_facts_describe_her_situation_not_an_assistant_product(self):
        system = await self.system("你在做什么？")
        for word in ("助手", "不是主观体验", "当前功能状态", "接口提供"):
            self.assertNotIn(word, system)
        self.assertIn("现在你只能打字交流和翻看记录", system)
        self.assertIn("当前状态（运行时估计，用来调语气，不用说出来）：空闲", system)
        self.assertIn("当前本机时间：2026年9月22日，星期二", system)
        self.assertNotIn("动作结果", system)

    async def test_v2_arm_keeps_its_tested_runtime_facts(self):
        system = await self.system("你在做什么？", projection="v2")
        self.assertIn("旧助手自述只说明说过，不证明做过", system)
        self.assertIn("当前功能状态", system)
        self.assertIn("不是主观体验", system)

    async def test_connected_voice_changes_the_situation_line(self):
        runtime = self.runtime()
        runtime.attach_speech(SpeechController(asr=ASR(), tts=TTS(), sink=Sink()))
        system = await self.system("你能说话吗？", runtime=runtime)
        self.assertIn("声音已接上", system)
        self.assertNotIn("还看不到屏幕", system)

    async def test_appearance_fact_reaches_only_the_turn_that_asks(self):
        asked = await self.system("你长什么样？")
        self.assertIn("形象与声音的设计方向：女性化、日系二次元表达。具体形象和最终声音还没有定下来。", asked)
        self.assertNotIn("日系二次元", await self.system("今天下雨了。"))
        # v2 keeps its standing presentation line and adds no disclosure.
        self.assertEqual((await self.system("你长什么样？", projection="v2")).count("日系二次元"), 1)

    async def test_elapsed_time_is_a_ledger_fact_not_a_guess(self):
        runtime = self.runtime()
        self.assertIn("这段会话之前没有对话记录。", await self.system("你好", runtime=runtime))
        runtime.clock = lambda: datetime.now(timezone.utc) + timedelta(hours=3)
        second = await self.system("我回来了", runtime=runtime)
        self.assertRegex(second, r"这段会话上次有人说话：\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2}，距现在约3小时。")
        self.assertNotIn("这段会话之前没有对话记录", second)
        self.assertNotIn("上次有人说话", await self.system("你好", projection="v2"))

    def test_last_utterance_follows_the_evidence_rule(self):
        store = ExperienceStore(Path(self.temp.name) / "last.sqlite3")
        self.addCleanup(store.close)
        self.assertIsNone(store.last_utterance_at("owner"))
        store.append_event("user", "说过的话", session_id="owner", origin="user_report",
                           status="completed", request_id="r1")
        said = store.last_utterance_at("owner")
        self.assertIsNotNone(said)
        # A failed reply released nothing; another session and scope do not count.
        store.append_event("assistant", "", session_id="owner", origin="generated", status="failed", request_id="r1")
        store.append_event("user", "别处", session_id="other", origin="user_report", status="completed")
        store.append_event("user", "公开", session_id="owner", scope="public", origin="user_report", status="completed")
        self.assertEqual(store.last_utterance_at("owner"), said)

    async def test_creative_directive_under_v3(self):
        self.assertIn("这一轮是创作", await self.system("写一个故事"))
        self.assertNotIn("这一轮是创作", await self.system("你好"))

    async def test_she_can_say_her_exemplar_and_self_facts_through_the_runtime(self):
        for user, reply in (("你觉得呢？", "等等，这里我有点不一样的想法。先看数据吧。"),
                            ("你是什么？", "我是一个人工的存在，有自己在意的事和自己的判断，经历靠记录延续。")):
            with self.subTest(reply=reply):
                runtime = self.runtime(tuple(reply))
                events = [event async for event in runtime.stream_turn(user)]
                self.assertEqual(events[-1].type, "complete")
                self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), reply)

    async def test_turn_receipt_names_the_persona_and_counts_markers_without_text(self):
        reply = "好的呢~没问题~交给我吧~ 还有什么需要我帮忙的吗？"
        runtime = self.runtime(tuple(reply))
        [event async for event in runtime.stream_turn("你好")]
        plan = next(json.loads(row["content"]) for row in runtime.store.list_events("owner")
                    if row["kind"] == "response_plan")
        self.assertEqual(plan["persona_projection"], "v3")
        self.assertEqual(plan["persona_sha256"],
                         sha256(load_persona(SEED).system_projection(version="v3").text.encode()).hexdigest())
        style = plan["style"]
        self.assertGreater(style["service_phrases"], 0)
        self.assertEqual(style["closing_offer"], 1)
        self.assertGreater(style["moe_markers"], 0)
        self.assertNotIn("opener", style)
        self.assertFalse(any(isinstance(value, str) for value in style.values()))


class StyleSummaryTests(unittest.TestCase):
    def test_rates_repetition_and_initial_gates(self):
        replies = [("你好", "嗯，我在。你今天怎么样？"), ("今天下雨了", "嗯，我在想雨声其实挺好听。"),
                   ("我输了", "嗯，我在复盘那一局。"), ("晚安", "晚安。"),
                   ("给我讲讲", "好的！希望对你有帮助！还有什么需要我帮忙的吗？")]
        summary = summarize([profile(text, user_text=user) for user, text in replies])
        self.assertEqual(summary["turns"], 5)
        self.assertEqual(summary["repeated_openers"], {"嗯我在": 3})
        self.assertEqual(summary["closing_offer"], 0.2)
        self.assertIn("service_phrases", summary["over_threshold"])
        self.assertIn("repeated_openers", summary["over_threshold"])
        self.assertTrue(summary["thresholds_are_initial"])
        self.assertTrue(set(GATES) <= set(summary))

    def test_mentions_and_ordinary_text_are_not_markers(self):
        for user, text in (("叫我主人", "我不会叫你主人，叫你主理人就好。"),
                           ("解释", "(2 + 3) × 4 = 20，1～3 步就够了。"),
                           ("主人公是谁", "这本书的主人公是个画家。"),
                           ("你在吗", "在呢。"),
                           ("讲讲 JSON", "```json\n{\"a\": 1}\n```")):
            with self.subTest(text=text):
                counts = profile(text, user_text=user)
                self.assertEqual((counts["moe_markers"], counts["service_phrases"]), (0, 0))

    def test_lists_count_against_casual_turns_only(self):
        listed = "1. 先确认输入\n2. 再看输出\n3. 最后比较"
        self.assertTrue(profile(listed, user_text="今天好累")["casual"])
        self.assertFalse(profile(listed, user_text="详细讲讲怎么排查，分点展开")["casual"])
        summary = summarize([profile(listed, user_text="详细讲讲怎么排查，分点展开")])
        self.assertIsNone(summary["list_structure_casual"])

    def test_unprompted_ai_talk_is_told_from_an_answer(self):
        self.assertEqual(profile("作为AI，我觉得雨天适合听歌。", user_text="今天下雨了")["ai_topic_unprompted"], 1)
        self.assertEqual(profile("我是AI，这没什么。", user_text="你是AI吗？")["ai_topic_unprompted"], 0)


if __name__ == "__main__":
    unittest.main()
