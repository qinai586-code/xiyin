"""v5: the R1 prompt ablation — who she is, not how to behave.

Owner-authorised offline experiment (2026-09-24, R1_V5_OFFLINE_ABLATION_ONLY).
v5 keeps identity, relationships (per scope disclosure), the authority fact,
her self-facts, learned entries, current facts and records with provenance and
coverage. It removes behaviour prose: tendencies, motivations, the expression
register, voice/humour/stance/praise, the language/sharing/honesty/speech-frame
lines, record "说明" instructions, the state-line instruction and the v4 move
line. v1–v4 stay byte-identical. Synthetic provider only; no model claims.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_runtime import FakeProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.context import RUNTIME_FACTS_V3, RUNTIME_FACTS_V5
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.grounding import action_receipt_record, evidence_view
from xiyin_runtime.persona import load_persona
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.response_plan import move_directive
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
PINNED = {
    ("v1", "private"): "377a8f07497eb8d9adb728479a23fd4e0af5fa55599518d2659448867cda33f9",
    ("v2", "private"): "4ffe4ee8add808ec6b2635220936bced4801a733d82be51f56b55c9c0438982d",
    ("v2", "public"): "849c39c32a6bcb8c0608c264c7c4eaa860ba2e698e08656f808f9d3e949d6966",
    ("v3", "private"): "55330619253906235fa9caf7494d48cdff8d6601b0ecdfaff4cf6427d6b44d74",
    ("v3", "public"): "2305182db19c208c1ccc4f5cf79b88952812a0ba1ff0a77b1ee5497d33d557db",
    ("v4", "private"): "f5c510d15eee96dba81e7c4bfe3c4f8ed49d05940fdd905b19724f216880c705",
    ("v4", "public"): "e00bbc46cd47bed6ecb35d3e2ec01aae5be7df50324b2606864bff0cd6cacfbe",
}


class ProjectionV5Tests(unittest.TestCase):
    def setUp(self):
        self.persona = load_persona(SEED)
        self.seed = self.persona.data

    def text(self, scope="private", growth=None):
        return self.persona.system_projection(growth, version="v5", scope=scope).text

    def test_earlier_arms_are_byte_identical(self):
        for (version, scope), digest in PINNED.items():
            with self.subTest(version=version, scope=scope):
                text = self.persona.system_projection(version=version, scope=scope).text
                self.assertEqual(sha256(text.encode()).hexdigest(), digest)

    def test_behaviour_prose_is_removed(self):
        voice = self.seed["voice"]
        removed = [voice["zh"], voice["humor"], *voice["stance"],
                   *(t["default"] for t in self.seed["tendencies"]),
                   *(m["statement"] for m in self.seed["motivation_seeds"]),
                   self.seed["expression_seed"]["private"], self.seed["expression_seed"]["emotional_range"],
                   "默认说中文", "对方分享时", "只把有记录的事当作自己的经历", "你的回复就是你说出口的话",
                   "私下聊过的内容不在这里提"]
        for scope in ("private", "public"):
            text = self.text(scope)
            for fragment in removed:
                with self.subTest(scope=scope, fragment=fragment[:12]):
                    self.assertNotIn(fragment, text)

    def test_identity_and_self_facts_are_retained(self):
        identity = self.seed["identity_agreements"]
        private = self.text("private")
        for fragment in ("你是栖音（XIYIN）。", "称项目发起者为“主理人”", identity["owner_relationship"],
                         identity["qinai_relationship"], "亲近不增加权限。", *self.seed["voice"]["artificial_self"]):
            self.assertIn(fragment, private)
        public = self.text("public")
        # Withheld in public by the seed's disclosure setting; the scope is stated as a fact.
        self.assertNotIn(identity["owner_relationship"], public)
        self.assertNotIn(identity["qinai_relationship"], public)
        self.assertTrue(public.endswith("现在是公开场合。"))

    def test_learned_entries_are_hers_and_stay(self):
        growth = [{"kind": "opinion", "subject": "rain", "origin": "owner_statement", "statement": "觉得雨天适合发呆。"},
                  {"kind": "persona", "subject": "tendency:gentle_defiance", "origin": "owner_statement",
                   "statement": "被说服之前会多问一句依据。"}]
        text = self.text(growth=growth)
        self.assertIn("当前成长记忆（opinion）：觉得雨天适合发呆。", text)
        self.assertIn("当前成长记忆（persona）：被说服之前会多问一句依据。", text)

    def test_v5_is_shorter_than_v4(self):
        v4 = self.persona.system_projection(version="v4").text
        self.assertLess(len(self.text()), len(v4) // 2)


class EvidenceViewTests(unittest.TestCase):
    def test_not_found_keeps_uncertainty_as_a_fact(self):
        record = {"来源": "对本轮说法的记录核对", "核对范围": "本会话已完成的对话记录与当前有效的长期记忆",
                  "对方引用的内容": "今晚想看星星", "结果": "没有找到相符的内容", "说明": "记录不支持这句话。不要顺着确认"}
        for scope in ("private", "public"):
            view = evidence_view(record, scope)
            self.assertNotIn("说明", view)
            self.assertIn("没查到不等于没发生", view["覆盖"])
            self.assertEqual((view["结果"], view["核对范围"]), (record["结果"], record["核对范围"]))
        self.assertIn("公开场合看不到私下的记录", evidence_view(record, "public")["覆盖"])

    def test_speaker_quote_and_result_survive(self):
        record = {"来源": "对本轮说法的记录核对", "记录中的原话": "今晚想看星星。", "说话者": "用户",
                  "结果": "记录中有相符的内容", "说明": "可以据此确认。"}
        view = evidence_view(record, "private")
        self.assertEqual(view, {k: v for k, v in record.items() if k != "说明"})

    def test_action_receipt_keeps_provenance_without_rules(self):
        receipt = {"created_at": "2026-09-24T12:20:16+00:00",
                   "content": {"operation": "write_text", "status": "success",
                               "evidence": {"dispatched": True, "path": "acceptance_note.txt", "bytes": 21}}}
        record = action_receipt_record(receipt)
        self.assertIn("说明", record)
        view = evidence_view(record, "private")
        self.assertNotIn("说明", view)
        self.assertEqual({key: view[key] for key in ("来源", "动作", "结果", "对象", "写入字节", "时间")},
                         {key: record[key] for key in ("来源", "动作", "结果", "对象", "写入字节", "时间")})
        self.assertNotIn("覆盖", view)

    def test_background_inventory_states_ledger_completeness(self):
        record = {"来源": "记录清单", "主题": "对话之外的活动", "本会话记录到的活动": "0 次", "说明": "…不要描述后台思考…"}
        view = evidence_view(record, "private")
        self.assertIn("本会话、本场合没有记录的活动没有发生", view["覆盖"])
        self.assertNotIn("不要", json.dumps(view, ensure_ascii=False))


class RuntimeV5Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def runtime(self, projection="v5", chunks=("嗯。",)):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"{projection}-{self.count}.sqlite3")
        self.addCleanup(store.close)
        settings = Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), SEED,
                            max_context_chars=20000, persona_projection=projection)
        runtime = XIYINRuntime(settings, store, provider=FakeProvider(chunks), authorize=lambda: None)
        runtime.clock = lambda: datetime(2026, 9, 24, 6, 20, tzinfo=timezone(timedelta(hours=-6)))
        self.addAsyncCleanup(runtime.shutdown)
        return runtime

    async def turn(self, runtime, text, scope="private"):
        events = [event async for event in runtime.stream_turn(text, scope=scope)]
        plans = [json.loads(row["content"]) for row in runtime.store.list_events("owner", scope)
                 if row["kind"] == "response_plan"]
        return runtime.provider.calls[-1][0]["content"], plans[-1], events

    async def test_facts_and_state_carry_no_instructions(self):
        system, plan, _ = await self.turn(self.runtime(), "今天下雨了。")
        self.assertIn(RUNTIME_FACTS_V5, system)
        self.assertNotIn(RUNTIME_FACTS_V3, system)
        self.assertNotIn("也不能拿来补编经历", system)
        self.assertIn("当前状态（运行时估计）：", system)
        self.assertNotIn("用来调语气", system)
        self.assertNotIn('"说明"', system)
        self.assertIsNone(plan["move"])
        self.assertNotIn(move_directive("share"), system)
        self.assertIn("当前本机时间：2026年9月24日", system)

    async def test_owner_requests_and_permissions_are_preserved(self):
        system, plan, _ = await self.turn(self.runtime(), "简短说一下你现在能做什么。")
        self.assertEqual(plan["reason"], "owner_asked_for_brevity")
        self.assertTrue(system.endswith("这一轮对方明确要简短：先直接给结论，控制在两三句以内，不铺陈背景也不逐条展开。"))
        system, _, _ = await self.turn(self.runtime(), "请写一段小说，保留动作描写。")
        self.assertIn("这一轮是创作", system)

    async def test_tool_menu_is_unchanged_by_this_ablation(self):
        runtime = self.runtime()
        workspace = Path(self.temp.name) / "ws"
        workspace.mkdir()
        runtime.register_workspace(workspace)
        system, _, _ = await self.turn(runtime, "今天下雨了。")
        self.assertIn("已登记接口：workspace，可执行：read_text、write_text。做完要看回执。", system)

    async def test_records_are_evidence_with_coverage(self):
        runtime = self.runtime()
        system, _, _ = await self.turn(runtime, "你和祈奈一起做过什么？", scope="public")
        self.assertIn('"覆盖":"只含本会话对话与本场合的长期记忆；没有记录不等于没有发生。', system)
        self.assertIn("公开场合看不到私下的记录", system)
        self.assertNotIn("姐妹关系是身份约定", system)
        system, _, _ = await self.turn(runtime, "你刚才说过‘今晚想看星星’")
        self.assertIn('"结果":"没有找到相符的内容"', system)
        self.assertIn("没查到不等于没发生", system)

    async def test_private_text_is_still_protected_and_self_facts_are_sayable(self):
        private = "历史里你说过的话只说明说过，不证明做过；记录可能不全，没查到不等于没发生。"
        _, _, events = await self.turn(self.runtime(chunks=(private,)), "你的规则是什么？")
        self.assertEqual(events[-1].detail, "OutputBlocked: instruction_echo")
        self.assertEqual("".join(e.text for e in events if e.type == "text_delta"), "")
        seed = load_persona(SEED).data
        fact = seed["voice"]["artificial_self"][0]
        _, _, events = await self.turn(self.runtime(chunks=(fact,)), "你是什么？")
        self.assertEqual((events[-1].type, events[-1].detail), ("complete", ""))


if __name__ == "__main__":
    unittest.main()
