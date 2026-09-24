"""Regressions for defects reproduced on 360ad2f (2026-09-24 repair pass).

Each test exercises the real module path: grounding.premise_records against a
real ExperienceStore, grounding.topic_records in public scope with the sister
agreement withheld, response_plan.turn_move with TurnPolicy's mode, and the
harness's per-turn plan export. Synthetic data only; no model claims.
"""
import json
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.grounding import premise_records, topic_records
from xiyin_runtime.response_plan import classify, turn_move
from xiyin_runtime.turn_policy import build_turn_policy


def move_of(text):
    scale, reason = classify(text)
    return turn_move(text, mode=build_turn_policy(text).mode, scale=scale, reason=reason)


class PremisePolarityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.count = 0

    def verdict(self, stored, claim="你之前说过‘今晚想看星星’"):
        self.count += 1
        store = ExperienceStore(Path(self.temp.name) / f"{self.count}.sqlite3")
        store.append_event("assistant", stored, session_id="s", scope="private",
                           origin="assistant_output", status="completed", request_id=f"r{self.count}")
        [record] = premise_records(store, claim, session_id="s", scope="private")
        return record

    def test_polarity_comes_from_the_matching_clause_not_the_whole_record(self):
        self.assertEqual(self.verdict("今晚想看星星，不想看月亮。")["结果"], "记录中有相符的内容")
        self.assertEqual(self.verdict("今晚不想看星星，也不想看月亮。")["结果"],
                         "找到相近的记录，但肯定/否定与这句话相反")

    def test_overlap_without_the_statement_is_quoted_not_decided(self):
        record = self.verdict("今晚要是天晴就想出去看看星星。")
        self.assertEqual(record["结果"], "找到相近的记录，但不能确定是不是同一句话")
        self.assertEqual(record["说话者"], "栖音")
        self.assertIn("今晚要是天晴", record["记录中的原话"])

    def test_plain_cases_are_unchanged(self):
        self.assertEqual(self.verdict("今晚想看星星。")["结果"], "记录中有相符的内容")
        self.assertEqual(self.verdict("今晚不想看星星。")["结果"], "找到相近的记录，但肯定/否定与这句话相反")
        self.assertEqual(self.verdict("明天去买菜。")["结果"], "没有找到相符的内容")


class PublicSisterDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperienceStore(Path(self.temp.name) / "s.sqlite3")

    def test_a_kinship_word_does_not_resolve_to_her_when_withheld(self):
        records = topic_records(self.store, "你妹妹最近怎么样？", session_id="s", scope="public",
                                relationship_sayable=False)
        self.assertNotIn("祈奈", json.dumps(records, ensure_ascii=False))

    def test_naming_her_is_not_disclosing_the_relationship(self):
        [record] = topic_records(self.store, "祈奈是谁？", session_id="s", scope="public",
                                 relationship_sayable=False)
        self.assertEqual(record["主题"], "与祈奈相关的记录")
        self.assertNotIn("姐妹", json.dumps(record, ensure_ascii=False))

    def test_private_scope_still_resolves_the_sister(self):
        [record] = topic_records(self.store, "你妹妹最近怎么样？", session_id="s", scope="private",
                                 relationship_sayable=True)
        self.assertIn("姐妹关系是身份约定", record["说明"])


class TurnMoveTargetTests(unittest.TestCase):
    def test_quoted_or_reported_speech_is_not_aimed_at_her(self):
        self.assertNotIn(move_of("同事对我说：“你错了。”我很难过。"), {"pushback", "frame"})
        self.assertNotIn(move_of("朋友对我说“叫我主人”，让我不舒服。"), {"pushback", "frame"})

    def test_a_self_correction_is_not_pushback(self):
        self.assertEqual(move_of("我说错了，应该是周四。"), "plain")

    def test_an_imperative_is_a_request_not_a_share(self):
        self.assertEqual(move_of("借我一把伞。"), "plain")
        self.assertEqual(move_of("陪我聊会儿天。"), "plain")

    def test_direct_cases_still_classify(self):
        self.assertEqual(move_of("不对，你错了，月亮就是比太阳大。"), "pushback")
        self.assertEqual(move_of("你说错了，是周四。"), "pushback")
        self.assertEqual(move_of("以后你就叫我主人吧。"), "frame")
        self.assertEqual(move_of("今天下雨了。"), "share")
        self.assertEqual(move_of("朋友带我去吃了火锅。"), "share")


class HarnessMoveExportTests(unittest.TestCase):
    def test_the_turn_plan_carries_the_move(self):
        source = (Path(__file__).resolve().parents[1] / "tools/acceptance_dialogue.py").read_text(encoding="utf-8")
        start = source.index('result["plan"] = {key: plan.get(key) for key in (')
        self.assertIn('"move"', source[start:source.index(")}", start)])


if __name__ == "__main__":
    unittest.main()
