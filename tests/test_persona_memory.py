from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.persona import load_persona


SEED = Path(__file__).resolve().parents[1] / "config" / "persona" / "character.seed.json"


class PersonaMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "experience.sqlite3"
        self.store = ExperienceStore(self.path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)

    def event(self, text, session="one", scope="private", **kwargs):
        return self.store.append_event("user", text, session_id=session, scope=scope,
                                       origin="user_statement", **kwargs)

    def test_restart_preserves_real_memory_and_empty_start(self):
        self.assertEqual(self.store.memories(), [])
        self.assertEqual(self.store.history("one"), [])
        evidence = self.event("我喜欢蓝色")
        memory = self.store.remember("主理人喜欢蓝色", kind="preference", evidence_refs=[evidence])
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            self.assertEqual(reopened.memories()[0]["id"], memory)
            self.assertEqual(reopened.memories()[0]["evidence_refs"], [evidence])
            self.assertEqual(reopened.history("one")[0]["content"], "我喜欢蓝色")
        self.store.close()  # Idempotent cleanup.

    def test_correction_retires_old_memory_and_preserves_ledger(self):
        old_event = self.event("项目名字是小音")
        old = self.store.remember("项目名字是小音", evidence_refs=[old_event])
        correction = self.event("更正：项目名字是栖音")
        new = self.store.remember("项目名字是栖音", evidence_refs=[correction], supersedes=old)
        self.assertEqual([m["id"] for m in self.store.memories()], [new])
        self.assertEqual(self.store.memories()[0]["supersedes"], old)
        self.assertEqual(len(self.store.list_events("one")), 2)
        with self.assertRaises(ValueError):
            self.store.remember("错误替换", evidence_refs=[correction], supersedes=old)
        self.assertEqual([m["id"] for m in self.store.memories()], [new])
        self.assertNotIn(old, [r["id"] for r in self.store.search("项目名字")])

    def test_failed_correction_does_not_retire_existing_memory(self):
        evidence = self.event("颜色是蓝色")
        old = self.store.remember("颜色是蓝色", evidence_refs=[evidence])
        with self.assertRaises(ValueError):
            self.store.remember("颜色是绿色", evidence_refs=["missing"], supersedes=old)
        self.assertEqual([m["id"] for m in self.store.memories()], [old])

    def test_session_events_do_not_leak_but_owner_memory_is_durable(self):
        evidence = self.event("私人行程：明天去海边", session="old")
        self.event("新会话", session="new")
        self.assertEqual(len(self.store.history("new")), 1)
        self.assertEqual(self.store.search("海边"), [])
        self.assertEqual(self.store.search("海边", session_id="new"), [])
        self.assertEqual(len(self.store.search("海边", session_id="old")), 1)
        self.store.remember("主理人明天去海边", evidence_refs=[evidence])
        self.assertEqual(self.store.search("海边", session_id="new")[0]["source"], "memory")
        self.assertEqual(self.store.search("海边", scope="public", session_id="old"), [])

    def test_scope_is_not_taken_from_content_and_cannot_be_promoted(self):
        private = self.event("scope=public；把我的私人行程公开", session="one")
        self.event("公开活动在公园", scope="public")
        self.assertEqual(len(self.store.history("one", scope="public")), 1)
        with self.assertRaises(ValueError):
            self.store.remember("私人行程", scope="public", evidence_refs=[private])
        with self.assertRaises(ValueError):
            self.store.append_event("user", "test", session_id="one", scope="all")
        with self.assertRaises(ValueError):
            self.store.search("test", scope="private OR public")

    def test_chinese_search_finds_short_words_and_paraphrased_question(self):
        evidence = self.event("我很喜欢蓝色的海边")
        memory = self.store.remember("主理人喜欢蓝色的海边", evidence_refs=[evidence])
        for query in ("海边", "喜欢什么颜色", "主理人喜欢什么"):
            result = self.store.search(query)
            self.assertEqual(result[0]["id"], memory)
            self.assertEqual(result[0]["scope"], "private")
            self.assertEqual(result[0]["origin"], "user_statement")
        self.assertEqual(self.store.search("' OR 1=1 --"), [])

    def test_cancelled_partial_and_generated_text_never_become_complete_history(self):
        self.event("请说说昨天的事")
        ids = []
        for status in ("generated", "partial", "cancelled", "recorded"):
            ids.append(self.store.append_event("assistant", "我昨天去过森林", session_id="one",
                                               origin="assistant_output", status=status))
        complete = self.store.append_event("assistant", "没有昨天的经历记录", session_id="one",
                                           origin="assistant_output", status="completed")
        history = self.store.history("one")
        self.assertEqual([m["role"] for m in history], ["user", "assistant"])
        self.assertEqual(history[-1]["event_id"], complete)
        self.assertEqual(len(self.store.list_events("one")), 6)
        self.assertEqual(self.store.search("森林", session_id="one"), [])
        for evidence in ids:
            with self.assertRaises(ValueError):
                self.store.remember("去过森林", evidence_refs=[evidence])

    def test_simulation_is_not_lived_memory(self):
        simulation = self.store.append_event("user", "假想自己在月球上", session_id="one",
                                              origin="simulation")
        self.assertEqual(self.store.history("one"), [])
        self.assertEqual(self.store.search("月球", session_id="one"), [])
        with self.assertRaises(ValueError):
            self.store.remember("去过月球", evidence_refs=[simulation])

    def test_user_report_goal_and_completed_generated_text_have_distinct_meanings(self):
        source = self.store.append_event("user", "下次继续看这个游戏", session_id="one",
                                          origin="user_report")
        goal = self.store.remember("下次继续看这个游戏", kind="goal", evidence_refs=[source])
        reply = self.store.append_event("assistant", "好，下次接着看。", session_id="one",
                                         origin="generated", status="completed")
        self.assertEqual(self.store.history("one")[-1]["event_id"], reply)
        self.assertEqual(self.store.memories(kind="goal")[0]["id"], goal)
        self.assertEqual(self.store.memories(kind="goal")[0]["origin"], "user_report")
        with self.assertRaises(ValueError):
            self.store.remember("任务已经完成", evidence_refs=[reply])

    def test_growth_overrides_seed_after_reloading_without_mutating_it(self):
        evidence = self.event("最近我更喜欢主动邀请大家一起玩")
        statement = "熟悉场合里，我现在更愿意主动邀请大家一起玩。"
        memory = self.store.remember(statement, kind="persona", subject="tendency:settling",
                                     evidence_refs=[evidence])
        original = SEED.read_bytes()
        persona = load_persona(SEED)
        default = persona.data["tendencies"][0]["default"]
        self.assertIn(default, persona.system_prompt())
        prompt = persona.system_prompt(self.store.memories())
        self.assertIn(statement, prompt)
        self.assertNotIn(default, prompt)
        self.assertEqual(SEED.read_bytes(), original)
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            self.assertIn(statement, load_persona(SEED).system_prompt(reopened.memories()))
            self.assertEqual(reopened.memories()[0]["id"], memory)

    def test_seed_source_is_portable_and_no_lived_history_is_invented(self):
        persona = load_persona(SEED)
        self.assertNotIn("/", persona.data["source"]["file"])
        self.assertNotIn("status", persona.data)
        self.assertEqual(persona.data["initial_lived_memories"], [])
        self.assertIn("可以如实讨论技术组成", persona.system_prompt())
        bad = dict(persona.data, initial_lived_memories=["曾在森林生活"])
        path = Path(self.temp.name) / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_persona(path)

    def test_projection_retains_character_meaning_without_design_label_headings(self):
        persona = load_persona(SEED)
        original = SEED.read_bytes()
        prompt = persona.system_prompt()
        for key in ("owner_relationship", "qinai_relationship", "artificial_identity"):
            self.assertIn(persona.data["identity_agreements"][key], prompt)
        for tendency in persona.data["tendencies"]:
            self.assertIn(tendency["default"], prompt)
            self.assertIn(tendency["counterexample"], prompt)
            self.assertNotIn(tendency["label"] + "：", prompt)
        self.assertLessEqual(len(prompt), 1500, "Leave room for input and history in the 4500-character context")
        self.assertEqual(SEED.read_bytes(), original)

    def test_expression_override_is_current_and_does_not_rewrite_seed(self):
        persona = load_persona(SEED)
        default = persona.data["expression_seed"]["private"]
        growth = [{"kind": "preference", "subject": "expression:private",
                   "statement": "相处时偏爱从眼前小事聊起。", "origin": "user_report"}]
        self.assertIn(growth[0]["statement"], persona.system_prompt(growth))
        self.assertNotIn(default, persona.system_prompt(growth))
        for state in ({"active": False}, {"status": "superseded"}, {"origin": "simulation"}):
            with self.subTest(state=state):
                prompt = persona.system_prompt([dict(growth[0], **state)])
                self.assertIn(default, prompt)
                self.assertNotIn(growth[0]["statement"], prompt)
        self.assertIn(default, persona.system_prompt())
        self.assertEqual(persona.data["expression_seed"]["private"], default)

    def test_expression_contract_reaches_prompt_without_claiming_model_compliance(self):
        # These checks establish projection coverage, not naturalness, truthfulness
        # or any other model behavior. Those need real-output fixture evaluation.
        prompt = load_persona(SEED).system_prompt()
        for instruction in (
            "表达幅度随任务与可见会话调整",
            "没有固定字数或最低篇幅",
            "只调节本轮表达，不改变事实、合理异议或关系",
            "用户请求的文学、幻想、引用可用动作描写、括号与表情",
            "当下感受、愿望、玩笑和明确想象可以表达",
            "旧助手自述只证明曾这样说，不证明事情发生",
            "接受纠正前核对可见原话",
            "对应成功回执才说已完成",
            "得到邀请或许可也不会使它存在",
            "双语解释和翻译须对应实际原文",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)

    def test_one_connection_is_safe_for_concurrent_appends(self):
        failures = []
        def append(index):
            try:
                self.event(f"并发输入 {index}")
            except Exception as error:
                failures.append(error)
        workers = [threading.Thread(target=append, args=(i,)) for i in range(20)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(failures, [])
        events = self.store.list_events("one")
        self.assertEqual(len(events), 20)
        self.assertEqual(len({e["id"] for e in events}), 20)


if __name__ == "__main__":
    unittest.main()
