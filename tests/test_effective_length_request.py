"""The effective length request of a turn, not a keyword race between words.

A quoted or defined word is a mention; a later correction replaces an earlier
request; "先…再…" asks for two sections; "不需要简短" lifts a limit while "别只
简单讲讲" asks for more. A ceiling is a resource limit, so an inferred task gets
room but never a directive claiming the owner asked for detail.
"""
import unittest

from xiyin_runtime.response_plan import classify, plan_response


def plan(text):
    return plan_response(text, prompt_tokens=500, context_tokens=4096, ceiling=1792,
                         default_rate=8.0, max_timeout=600.0)


class EffectiveRequestTests(unittest.TestCase):
    def test_the_six_reported_requests(self):
        for text, scale, reason in (
                ("详细一点。不，还是一句话。", "brief", "owner_asked_for_brevity+corrected"),
                ("不需要简短，正常聊就好。", "normal", "owner_declined_brevity"),
                ("请解释“详细”这个词，一句话就够。", "brief", "owner_asked_for_brevity"),
                ("先一句话总结，然后详细说明。", "detailed", "owner_asked_for_summary_then_detail"),
                ("给我简单解释一下。", "brief", "owner_asked_for_brevity"),
                ("不用展开。", "brief", "owner_asked_for_brevity")):
            with self.subTest(text=text):
                self.assertEqual(classify(text), (scale, reason))

    def test_a_mention_of_a_length_word_is_not_a_request(self):
        for text in ("“简短”是什么意思？", "“详细”这个词怎么写？", "简短是什么意思", "解释一下“一句话”的用法"):
            with self.subTest(text=text):
                self.assertFalse(classify(text)[1].startswith("owner_"), classify(text))
        # Quotation used for emphasis is still a request.
        self.assertEqual(classify("请“简短”回答")[0], "brief")

    def test_a_later_revision_wins_and_a_plain_negation_is_not_a_revision(self):
        for text, scale in (("一句话说完。不对，详细讲讲。", "detailed"), ("简短点，还是详细点吧", "detailed"),
                            ("算了，详细点讲吧。", "detailed"), ("详细讲。算了，一句话就行。", "brief")):
            with self.subTest(text=text):
                self.assertEqual(classify(text)[0], scale)
                self.assertTrue(classify(text)[1].endswith("+corrected"))
        for text in ("不用展开。", "不需要太详细", "不要简单讲一下，请详细解释"):
            with self.subTest(text=text):
                self.assertFalse(classify(text)[1].endswith("+corrected"))

    def test_sentence_length_is_a_topic_not_a_short_answer_request(self):
        for text in ("详细解释一下你是怎么判断一句话该说多长的。",
                     "详细讲讲一句话应该写多长。", "详细说明一句话的长度如何确定。"):
            with self.subTest(text=text):
                result = plan(text)
                self.assertEqual((result.scale, result.reason), ("detailed", "owner_asked_for_detail"))
                self.assertNotIn("先一句话总结", result.directive)
        self.assertFalse(classify("你怎么判断一句话该说多长？")[1].startswith("owner_"))
        # An explicit output constraint still applies, even on this topic.
        self.assertEqual(classify("请用一句话解释你怎么判断句子长短。"),
                         ("brief", "owner_asked_for_brevity"))

    def test_negation_means_what_it_says(self):
        for text, scale in (("不需要简短，正常聊就好。", "normal"), ("别太简短", "normal"),
                            ("别只简单讲讲，详细一点", "detailed"), ("我不想听简单解释", "detailed"),
                            ("不用展开", "brief"), ("不需要太详细", "brief")):
            with self.subTest(text=text):
                self.assertEqual(classify(text)[0], scale)

    def test_two_sections_keep_their_order_in_the_directive(self):
        first = plan("先一句话总结，然后详细说明。")
        self.assertEqual(first.scale, "detailed")
        self.assertTrue(first.directive.startswith("这一轮对方要先一句话总结，再展开"))
        last = plan("先详细讲，最后一句话总结。")
        self.assertEqual(last.reason, "owner_asked_for_detail_then_summary")
        self.assertIn("结尾一句话收住", last.directive)

    def test_an_inferred_task_gets_room_but_no_claim_about_the_owner(self):
        inferred = plan("为什么天是蓝的？")
        self.assertEqual((inferred.scale, inferred.reason, inferred.directive), ("detailed", "task_needs_room", ""))
        self.assertGreater(inferred.max_tokens, plan("今天下雨了").max_tokens)
        record = inferred.to_dict()
        self.assertFalse(record["requested_by_owner"])
        self.assertFalse(record["directive_sent"])
        self.assertFalse(record["is_length_cap"])
        asked = plan("详细讲讲为什么天是蓝的").to_dict()
        self.assertTrue(asked["requested_by_owner"] and asked["directive_sent"])


if __name__ == "__main__":
    unittest.main()
