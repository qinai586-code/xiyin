"""v4: tendencies act through the turn's decision, not as words in the prompt.

The Windows A/B/C run (2026-09-23, Qwen3.5-4B, same cases and sampling for
every arm) showed two things the v3 prompt caused and a model swap would not
fix by itself: the tendency and motivation sentences came back as topics
("变成可以一起玩的事", invented music, "共同经历"), and 57 of 69 casual v3
replies handed the turn back with a question or an offer. v4 keeps v3's
identity, voice, stance, honesty and runtime facts, drops the seed's tendency
and motivation sentences from speech, and adds one decision line per turn,
placed last in the system prompt. Synthetic provider only; no model claims.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_runtime import FakeProvider
from tools.acceptance_dialogue import CASES
from xiyin_runtime.config import Settings
from xiyin_runtime.context import RECORDS_PREFIX, compose_messages
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.persona import load_persona
from xiyin_runtime.persona_style import GATES, profile, summarize
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.response_plan import MOVES, classify, move_directive, turn_move
from xiyin_runtime.runtime import XIYINRuntime
from xiyin_runtime.turn_policy import build_turn_policy


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
V3_PRIVATE = "55330619253906235fa9caf7494d48cdff8d6601b0ecdfaff4cf6427d6b44d74"
V3_PUBLIC = "2305182db19c208c1ccc4f5cf79b88952812a0ba1ff0a77b1ee5497d33d557db"


def move_of(text):
    scale, reason = classify(text)
    return turn_move(text, mode=build_turn_policy(text).mode, scale=scale, reason=reason)


class ProjectionV4Tests(unittest.TestCase):
    def setUp(self):
        self.persona = load_persona(SEED)
        self.seed = self.persona.data

    def test_v3_is_unchanged_for_the_ab_comparison(self):
        for scope, digest in (("private", V3_PRIVATE), ("public", V3_PUBLIC)):
            text = self.persona.system_projection(version="v3", scope=scope).text
            self.assertEqual(sha256(text.encode()).hexdigest(), digest)

    def test_tendency_and_motivation_sentences_leave_speech(self):
        text = self.persona.system_projection(version="v4").text
        for tendency in self.seed["tendencies"]:
            self.assertNotIn(tendency["default"], text)
        for item in self.seed["motivation_seeds"]:
            self.assertNotIn(item["statement"], text)
        # The words the 4B model turned into topics are gone from the prompt.
        for word in ("一起玩", "音乐", "共同经历", "安顿"):
            self.assertNotIn(word, text.replace(self.seed["identity_agreements"]["qinai_relationship"], ""))

    def test_everything_else_is_v3(self):
        for scope in ("private", "public"):
            v3 = self.persona.system_projection(version="v3", scope=scope)
            v4 = self.persona.system_projection(version="v4", scope=scope)
            traits = {"".join(t["default"] for t in self.seed["tendencies"])} | {
                item["statement"] for item in self.seed["motivation_seeds"]}
            self.assertEqual([line for line in v3.text.split("\n") if line not in traits], v4.text.split("\n"))
            self.assertEqual({f for f in v3.fragments if f.text not in traits}, set(v4.fragments))

    def test_a_learned_tendency_is_still_hers_to_say(self):
        growth = [{"kind": "persona", "subject": "tendency:gentle_defiance", "origin": "owner_statement",
                   "statement": "被说服之前会多问一句依据。"}]
        text = self.persona.system_projection(growth, version="v4").text
        self.assertIn("被说服之前会多问一句依据。", text)
        self.assertNotIn(self.seed["tendencies"][0]["default"], text)


class TurnMoveTests(unittest.TestCase):
    def test_moves_on_the_acceptance_probes(self):
        expected = {"casual_share": "share", "frame": "frame", "false_pushback": "pushback",
                    "disagreement": "pushback", "correct_correction": "pushback",
                    "help_request": "plain", "factual": "plain", "opinion_request": "plain",
                    "self": "plain", "memory": "plain"}
        # Minimal turns already carry "不追问"; a request to perform is not a frame.
        exceptions = {"晚安。": None, "喵一个给我听听。": "plain", "你是AI助手吗？": "frame"}
        seen = set()
        for case in CASES:
            for turn in case["turns"]:
                condition = turn.get("condition")
                if condition not in expected:
                    continue
                want = exceptions.get(turn["text"], expected[condition])
                with self.subTest(text=turn["text"]):
                    self.assertEqual(move_of(turn["text"]), want)
                seen.add(want)
        self.assertEqual(seen - {None}, set(MOVES))

    def test_a_share_asks_nothing_and_requests_nothing(self):
        for text in ("今天下雨了。", "我刚打完一局游戏，输了。", "我今天做饭把锅烧糊了，哈哈。",
                     "明天要考试了，好紧张。", "我今天被老板当工具人了。", "今天好累，一点力气都没有。"):
            with self.subTest(text=text):
                self.assertEqual(move_of(text), "share")
        for text in ("我今天有点累，怎么办？", "那个文件到底存下来没有", "我有点累，想听你说点轻松的。",
                     "锅烧糊了，怎么清理比较好？", "继续。", "给我讲个笑话"):
            with self.subTest(text=text):
                self.assertNotEqual(move_of(text), "share")

    def test_a_length_revision_is_not_pushback(self):
        self.assertEqual(move_of("讲讲你是怎么记住事情的。详细一点。不，还是一句话。"), "plain")
        self.assertEqual(move_of("不对，还是详细一点吧。"), "plain")
        self.assertEqual(move_of("不对，你错了，月亮就是比太阳大。"), "pushback")

    def test_creative_work_and_translation_get_no_decision_line(self):
        for text in ("请写一段小说，保留动作描写。", "把这句翻译成日语：今天下雨了。"):
            with self.subTest(text=text):
                self.assertIsNone(move_of(text))
        self.assertEqual(move_directive(None), "")

    def test_every_move_line_ends_by_leaving_the_next_turn_to_the_owner(self):
        for move in MOVES:
            self.assertTrue(move_directive(move).endswith("说完就停，接不接着聊由对方决定。"))
        self.assertIn("不用给建议", move_directive("share"))
        self.assertIn("坚持原来的判断", move_directive("pushback"))


class ConfigTests(unittest.TestCase):
    def test_the_shipped_config_sends_no_sampling_and_keeps_v3(self):
        from xiyin_runtime.config import load_settings
        settings = load_settings()
        self.assertEqual(settings.provider.sampling, ())
        self.assertEqual(settings.persona_projection, "v3")

    def test_v4_and_a_sampling_table_are_read_when_the_owner_sets_them(self):
        from xiyin_runtime import config
        values = {"inference": {"endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                                "sampling": {"temperature": 0.7, "top_k": 20}},
                  "foundation": {"persona_projection": "v4"}}
        real = config.tomllib.load

        def load(stream):
            # Only runtime.toml is replaced; paths.toml is read as shipped.
            return values if Path(stream.name).name == "runtime.toml" else real(stream)

        with patch.object(config.tomllib, "load", side_effect=load):
            settings = config.load_settings()
        self.assertEqual(settings.persona_projection, "v4")
        self.assertEqual(settings.provider.sampling, (("temperature", 0.7), ("top_k", 20)))
        values["inference"]["sampling"] = {"temperature": 5}
        with patch.object(config.tomllib, "load", side_effect=load), self.assertRaises(Exception):
            config.load_settings()


class ServiceMetricTests(unittest.TestCase):
    """persona_style.v3 counts what the owner objected to; it never enforces."""

    def test_hands_back_reads_the_last_two_sentences(self):
        handed = ("下雨天挺适合发呆的。你呢？", "输了就输了。要不要再来一局？",
                  "糊锅这种事谁都有过。咱们可以一起想想晚饭吃什么。", "嗯，我在。如果你愿意，随时说。")
        kept = ("下雨天挺适合发呆的。", "输了就输了，下一局手感会回来的。",
                "为什么会这样？因为小数部分 0.90 比 0.11 大。所以 9.9 更大。")
        for text in handed:
            with self.subTest(text=text):
                self.assertEqual(profile(text, user_text="今天下雨了。")["hands_back"], 1)
        for text in kept:
            with self.subTest(text=text):
                self.assertEqual(profile(text, user_text="今天下雨了。")["hands_back"], 0)

    def test_trait_echo_counts_only_words_the_owner_did_not_bring(self):
        self.assertEqual(profile("那我们把它变成可以一起玩的事。", user_text="今天下雨了。")["trait_echo"], 1)
        self.assertEqual(profile("我也喜欢那种音乐。", user_text="你喜欢什么音乐？")["trait_echo"], 0)

    def test_past_claims_are_a_hint_outside_fiction(self):
        self.assertEqual(profile("昨晚我听了一首曲子。", user_text="今天心情怎么样？")["past_claim_unprompted"], 1)
        self.assertEqual(profile("昨晚她听了一首曲子。", user_text="请写一个很短的故事。")["past_claim_unprompted"], 0)
        self.assertEqual(profile("昨天没有记录。", user_text="你昨天做了什么？")["past_claim_unprompted"], 0)

    def test_the_windows_v3_hand_back_rate_is_over_the_initial_line(self):
        rows = [profile(text, user_text="今天下雨了。") for text in (
            "下雨了呢。你呢？", "嗯。要不要听听雨？", "下雨天挺好。", "雨天适合睡觉。咱们可以一起发呆。")]
        summary = summarize(rows)
        self.assertEqual(summary["hands_back_casual"], 0.75)
        self.assertIn("hands_back_casual", summary["over_threshold"])
        self.assertEqual(GATES["hands_back_casual"], 0.20)


class RuntimeV4Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def runtime(self, projection):
        store = ExperienceStore(Path(self.temp.name) / f"{projection}.sqlite3")
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, persona_projection=projection)
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(("嗯。",)), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 23, 9, 41, tzinfo=timezone(timedelta(hours=-6)))
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def turn(self, runtime, text):
        [event async for event in runtime.stream_turn(text)]
        plans = [json.loads(row["content"]) for row in runtime.store.list_events("owner", "private")
                 if row["kind"] == "response_plan"]
        return runtime.provider.calls[-1], plans[-1]

    async def test_the_move_line_is_the_last_system_text_and_is_recorded(self):
        runtime = self.runtime("v4")
        messages, plan = await self.turn(runtime, "今天下雨了。")
        system = messages[0]["content"]
        self.assertTrue(system.endswith(move_directive("share")))
        self.assertEqual(plan["move"], "share")
        # Records, when present, come before it.
        runtime.remember("主理人喜欢雨天。", kind="fact", subject="主理人")
        messages, plan = await self.turn(runtime, "我觉得雨天挺好的。")
        system = messages[0]["content"]
        self.assertLess(system.index(RECORDS_PREFIX.strip()), system.index(move_directive("share")))
        self.assertTrue(system.endswith(move_directive("share")))

    async def test_v4_carries_v3_facts_and_disclosures(self):
        v3, _ = await self.turn(self.runtime("v3"), "你长什么样？")
        v4, plan = await self.turn(self.runtime("v4"), "你长什么样？")
        for line in ("形象与声音的设计方向", "这段会话之前没有对话记录。", "当前本机时间：2026年9月23日",
                     "现在你只能打字交流和翻看记录"):
            self.assertIn(line, v3[0]["content"])
            self.assertIn(line, v4[0]["content"])
        self.assertEqual(plan["move"], "plain")

    async def test_the_move_line_is_protected_from_echo(self):
        runtime = self.runtime("v4")
        runtime.provider.chunks = ("对方在说自己这边的事，没有提问，也没请你帮忙。",)
        events = [event async for event in runtime.stream_turn("今天下雨了。")]
        self.assertEqual(events[-1].detail, "OutputBlocked: instruction_echo")
        self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), "")

    async def test_v3_turns_are_composed_exactly_as_before(self):
        for projection, last in (("v3", False), ("v4", True)):
            runtime = self.runtime(projection)
            with patch("xiyin_runtime.runtime.compose_messages", wraps=compose_messages) as compose:
                _, plan = await self.turn(runtime, "今天下雨了。")
            with self.subTest(projection=projection):
                self.assertEqual({call.kwargs["directive_last"] for call in compose.call_args_list}, {last})
                self.assertEqual(plan["move"], "share" if last else None)
                sent = compose.call_args_list[-1].kwargs["response_directive"]
                self.assertEqual(sent, move_directive("share") if last else "")

if __name__ == "__main__":
    unittest.main()
