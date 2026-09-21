"""Small synthetic probes; no model, network, or production memory is used.

Lexical similarity is a retrieval signal. Only a correctly attributed entire
utterance can be a verbatim-record match; semantic truth stays UNKNOWN.
"""
import unittest
import tempfile
from pathlib import Path

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.grounding import premise_records, topic_records


class SyntheticStore:
    def __init__(self, messages=(), memories=(), events=()):
        self.messages = list(messages)
        self.memory_rows = list(memories)
        self.events = list(events)
        self.calls = []

    def history(self, session_id, *, scope, limit):
        self.calls.append(("history", session_id, scope, limit))
        return self.messages[-limit:]

    def memories(self, *, scope):
        self.calls.append(("memories", scope))
        return self.memory_rows

    def list_events(self, session_id, scope):
        self.calls.append(("events", session_id, scope))
        return self.events


def message(role, content, record_id="synthetic-event-1"):
    return {"role": role, "content": content, "event_id": record_id,
            "origin": "generated" if role == "assistant" else "user_report", "status": "completed"}


class GroundingAttributionTests(unittest.TestCase):
    def check(self, text, messages=(), memories=()):
        records = premise_records(SyntheticStore(messages, memories), text,
                                  session_id="synthetic", scope="private")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["语义判断"], "UNKNOWN")
        return records[0]

    def test_past_marker_positions_and_negated_attribution_trigger(self):
        for text in ("你刚才说「今晚想看星星」", "你刚才不是说「今晚想看星星」",
                     "你不是刚才说「今晚想看星星」", "刚才你说「今晚想看星星」",
                     "之前你不是讲「今晚想看星星」", "你上次告诉我「今晚想看星星」"):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)["证据状态"], "NOT_FOUND")

    def test_nonpast_questions_do_not_scan_memory(self):
        for text in ("你说呢？", "你说吧，我听着", "说说今天的安排"):
            with self.subTest(text=text):
                store = SyntheticStore()
                self.assertEqual(premise_records(store, text, session_id="synthetic", scope="private"), [])
                self.assertEqual(store.calls, [])

    def test_user_utterance_does_not_confirm_assistant_attribution(self):
        result = self.check("你说过「今晚想看星星」", [message("user", "今晚想看星星。")])
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
        self.assertEqual(result["说话者"], "用户")
        self.assertNotIn("候选记录ID", result)
        self.assertNotIn("可以据此确认", result["说明"])

    def test_saved_statement_has_no_assistant_speaker_authority(self):
        result = self.check("你说过「今晚想看星星」", memories=[
            {"id": "synthetic-memory-1", "statement": "今晚想看星星。"}])
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
        self.assertEqual(result["候选来源"], "已保存的长期记忆")
        self.assertNotIn("候选记录ID", result)

    def test_whole_assistant_utterance_confirms_wording_only(self):
        result = self.check("你说过「今晚想看星星」", [message("assistant", "今晚想看星星。")])
        self.assertEqual(result["证据状态"], "EXACT_UTTERANCE")
        self.assertEqual(result["说话者"], "栖音")
        self.assertIn("不证明内容属实", result["说明"])
        self.assertIn("时间是否符合提问", result["说明"])

    def test_correct_speaker_exact_match_outranks_other_candidates(self):
        result = self.check("你说过「今晚想看星星」", [
            message("user", "今晚想看星星。", "synthetic-user"),
            message("assistant", "今晚想看星星的人很多，我想回家。", "synthetic-fuzzy"),
            message("assistant", "今晚想看星星。", "synthetic-exact")])
        self.assertEqual(result["证据状态"], "EXACT_UTTERANCE")
        self.assertEqual(result["候选数"], "3")
        self.assertEqual(result["记录中的原话"], "今晚想看星星。")

    def test_mutual_discussion_is_not_confirmed_from_one_utterance(self):
        result = self.check("我们上次聊过「今晚想看星星」", [message("assistant", "今晚想看星星。")])
        self.assertEqual(result["预期说话者"], "会话双方")
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")

    def test_substring_or_overlap_does_not_entail_claim(self):
        for original in ("今晚想看星星的人很多，我想回家。", "你说今晚想看星星，我没有这么说。",
                         "今晚想看星星吗？我想看电影。", "今晚我想看月亮，你想看星星。"):
            with self.subTest(original=original):
                result = self.check("你说过「今晚想看星星」", [message("assistant", original)])
                self.assertNotEqual(result["证据状态"], "EXACT_UTTERANCE")
                self.assertNotIn("记录中有相符的内容", result["结果"])

    def test_independent_negations_are_not_double_negation(self):
        result = self.check("你说过「今晚不想看星星也不想看月亮」", [
            message("assistant", "今晚想看星星也想看月亮。")])
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
        self.assertNotIn("相反", result["结果"])

    def test_negation_in_another_clause_does_not_establish_opposition(self):
        result = self.check("你说过「今晚想看星星」", [
            message("assistant", "今晚想看星星，不想看电影。")])
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
        self.assertNotIn("相反", result["结果"])

    def test_negated_exact_utterance_is_still_a_wording_match(self):
        result = self.check("你说过「今晚不想看星星」", [message("assistant", "今晚不想看星星。")])
        self.assertEqual(result["证据状态"], "EXACT_UTTERANCE")

    def test_question_and_quote_punctuation_do_not_become_verbatim_statement(self):
        for original in ("今晚想看星星？", "今晚想看星星?", "今晚想看星星！", "「今晚想看星星」"):
            with self.subTest(original=original):
                result = self.check("你说过「今晚想看星星」", [message("assistant", original)])
                self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")

    def test_claim_cannot_launder_itself_through_earlier_user_message(self):
        for original in ("你刚才说过「今晚想看星星」", "刚才你说「今晚想看星星」",
                         "你刚才不是说「今晚想看星星」"):
            with self.subTest(original=original):
                result = self.check("你说过「今晚想看星星」", [message("user", original)])
                self.assertEqual(result["证据状态"], "NOT_FOUND")

    def test_quote_before_attribution_is_not_treated_as_the_claim(self):
        result = self.check("先把「今天想看电影」放一边，你说过「今晚想看星星」", [
            message("assistant", "今晚想看星星。")])
        self.assertEqual(result["对方引用的内容"], "今晚想看星星")
        self.assertEqual(result["证据状态"], "EXACT_UTTERANCE")

    def test_tiny_claim_stays_undecided(self):
        result = self.check("你说过「好的」", [message("assistant", "好的。")])
        self.assertEqual(result["证据状态"], "INSUFFICIENT_CLAIM")

    def test_search_scope_is_passed_through_and_limit_is_disclosed(self):
        store = SyntheticStore()
        result = premise_records(store, "你说过「今晚想看星星」", session_id="synthetic-public",
                                 scope="public")[0]
        self.assertEqual(store.calls, [("history", "synthetic-public", "public", 60),
                                       ("memories", "public")])
        self.assertIn("60", result["核对范围"])
        self.assertIn("可能有漏检", result["说明"])

    def test_empty_qinai_inventory_does_not_mean_no_shared_experience(self):
        result = topic_records(SyntheticStore(), "你和祈奈有过什么共同经历", session_id="synthetic",
                               scope="private")[0]
        self.assertEqual(result["证据状态"], "NOT_FOUND")
        self.assertEqual(result["共同经历判断"], "UNKNOWN")
        self.assertIn("未检出也不证明从未共同经历", result["说明"])
        self.assertNotIn("还没有一起经历过什么", result["说明"])

    def test_named_topic_mention_is_not_a_shared_experience_fact(self):
        result = topic_records(SyntheticStore(memories=[{"statement": "主理人问过祈奈是不是喜欢星星"}]),
                               "你和祈奈做过什么", session_id="synthetic", scope="private")[0]
        self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
        self.assertEqual(result["共同经历判断"], "UNKNOWN")
        self.assertIn("不证明共同经历", result["说明"])

    def test_real_sqlite_history_preserves_speaker_and_completion_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory) / "synthetic.sqlite3")
            try:
                for role, status, origin, scope in (
                    ("user", "recorded", "user_report", "private"),
                    ("assistant", "partial", "generated", "private"),
                    ("assistant", "completed", "generated", "public"),
                ):
                    store.append_event(role, "今晚想看星星。", session_id="synthetic", scope=scope,
                                       origin=origin, status=status)
                result = premise_records(store, "你说过「今晚想看星星」", session_id="synthetic",
                                         scope="private")[0]
                self.assertEqual(result["证据状态"], "CANDIDATES_ONLY")
                self.assertEqual(result["说话者"], "用户")
                self.assertEqual(result["候选数"], "1")
                store.append_event("assistant", "今晚想看星星。", session_id="synthetic",
                                   origin="generated", status="completed")
                result = premise_records(store, "你说过「今晚想看星星」", session_id="synthetic",
                                         scope="private")[0]
                self.assertEqual(result["证据状态"], "EXACT_UTTERANCE")
                self.assertEqual(result["说话者"], "栖音")
                self.assertNotIn("候选记录ID", result)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
