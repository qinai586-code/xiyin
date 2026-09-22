"""Request-linked history and explicit brevity regressions, without a model."""

from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.response_plan import classify, plan_response


class TurnContinuityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "experience.sqlite3"
        self.store = ExperienceStore(self.path)
        self.addCleanup(self.store.close)

    def event(self, kind, text, *, request_id=None, status="completed",
              session="owner", scope="private", origin=None):
        return self.store.append_event(
            kind, text, session_id=session, scope=scope, request_id=request_id,
            status=status, origin=origin or ("user_report" if kind == "user" else "generated"))

    def test_unfinished_turns_do_not_leave_user_in_completed_history(self):
        for index, status in enumerate(("failed", "cancelled", "partial", "generated", "unknown")):
            request = f"unfinished-{index}"
            self.event("user", f"question-{index}", request_id=request)
            self.event("assistant", f"answer-{index}", request_id=request, status=status)
        # Only truncated/interrupted turns that released text form closed pairs;
        # blocked/failed and never-terminated generations leave no dangling ask.
        self.assertEqual([(item["role"], item["content"]) for item in self.store.history("owner")],
                         [("user", "question-1"), ("assistant", "answer-1"),
                          ("user", "question-2"), ("assistant", "answer-2")])
        self.assertEqual(len(self.store.list_events("owner")), 10)

    def test_interrupted_turn_with_nothing_released_is_left_out_on_both_sides(self):
        for status in ("cancelled", "partial"):
            self.event("user", f"asked-{status}", request_id=f"empty-{status}")
            self.event("assistant", "", request_id=f"empty-{status}", status=status)
        self.assertEqual(self.store.history("owner"), [])

    def test_released_text_needs_a_real_request_pair_and_generated_origin(self):
        # Defense in depth: an orphan or foreign-origin partial row never surfaces.
        self.event("assistant", "orphan partial", request_id="orphan", status="partial")
        self.event("user", "asked", request_id="foreign")
        self.event("assistant", "foreign partial", request_id="foreign", status="cancelled",
                   origin="assistant_output")
        self.assertEqual(self.store.history("owner"), [])

    def test_premise_evidence_keeps_user_words_from_failed_turns(self):
        self.event("user", "我的猫叫团子，是一只三花猫", request_id="blocked")
        self.event("assistant", "", request_id="blocked", status="failed")
        self.assertEqual(self.store.history("owner"), [])
        self.assertEqual([item["content"] for item in self.store.utterances("owner")],
                         ["我的猫叫团子，是一只三花猫"])
        from xiyin_runtime.grounding import premise_records
        record = premise_records(self.store, "我们之前聊过“我的猫叫团子，是一只三花猫”，对吧？",
                                 session_id="owner", scope="private")[0]
        self.assertEqual(record["结果"], "记录中有相符的内容")

    def test_history_request_filter_is_indexed(self):
        plan = " ".join(str(tuple(row)) for row in self.store._db.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM events WHERE request_id = 'x'"))
        self.assertIn("events_request", plan)

    def test_no_terminal_event_is_not_a_completed_turn(self):
        self.event("user", "interrupted before terminal event", request_id="interrupted")
        self.assertEqual(self.store.history("owner"), [])

    def test_filter_runs_before_limit_and_survives_restart(self):
        self.event("user", "completed question", request_id="good")
        self.event("assistant", "completed answer", request_id="good")
        for index in range(5):
            self.event("user", "later failed question", request_id=f"bad-{index}")
            self.event("assistant", "", request_id=f"bad-{index}", status="failed")
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            self.assertEqual([item["content"] for item in reopened.history("owner", limit=2)],
                             ["completed question", "completed answer"])
            self.assertEqual(len(reopened.list_events("owner")), 12)

    def test_completion_must_match_request_session_and_scope(self):
        self.event("user", "unanswered", request_id="matching-id")
        self.event("assistant", "different request", request_id="other-id")
        self.event("assistant", "different session", request_id="matching-id", session="other")
        self.event("assistant", "different scope", request_id="matching-id", scope="public")
        self.event("assistant", "imagined answer", request_id="matching-id", origin="simulation")
        history = self.store.history("owner")
        self.assertFalse(any(item["role"] == "user" for item in history))

    def test_legacy_unlinked_observations_keep_existing_semantics(self):
        self.event("user", "legacy observation", status="recorded")
        self.event("assistant", "legacy failure", status="failed")
        self.event("assistant", "legacy completion", status="complete")
        self.assertEqual([item["content"] for item in self.store.history("owner")],
                         ["legacy observation", "legacy completion"])

    def test_user_turn_and_assistant_turn_aliases_are_paired(self):
        self.event("user_turn", "question", request_id="alias", origin="user_report")
        self.event("assistant_turn", "answer", request_id="alias", status="complete")
        self.assertEqual([item["role"] for item in self.store.history("owner")], ["user", "assistant"])

    def test_action_memory_receipts_and_user_evidence_remain_available(self):
        source = self.event("user", "I prefer blue", request_id="failed")
        self.event("assistant", "", request_id="failed", status="failed")
        memory = self.store.remember("I prefer blue", kind="preference", evidence_refs=[source],
                                     receipt_session_id="owner")
        action = self.event("action_result", {"success": True, "path": "example.txt"},
                            request_id="failed", origin="tool_result", status="verified_success")
        self.assertEqual(self.store.history("owner"), [])
        self.assertEqual(self.store.operation_receipts("owner")[0]["content"]["memory_id"], memory)
        self.assertEqual(self.store.action_receipts("owner")[0]["id"], action)
        # Cancellation does not invalidate what the user actually said.
        self.assertIn(source, [item["id"] for item in self.store.search("blue", session_id="owner")])


class ExplicitBrevityTests(unittest.TestCase):
    def test_simple_explanation_requests_are_brief(self):
        for text in ("给我简单解释一下这个原理", "简单讲一下怎么做", "简要解释一下",
                     "请简单地解释一下这个机制", "简单讲讲区别", "简单说一下"):
            with self.subTest(text=text):
                self.assertEqual(classify(text, engagement=1.0), ("brief", "owner_asked_for_brevity"))

    def test_simple_subject_or_negated_brevity_does_not_force_brief(self):
        for text in ("这是一个简单问题，请详细解释", "请分析这个简单方案的优缺点",
                     "不要简单讲一下，请详细解释", "别简单解释，我需要完整说明"):
            with self.subTest(text=text):
                self.assertEqual(classify(text)[0], "detailed")

    def test_brief_request_uses_corresponding_budget_and_directive(self):
        arguments = dict(prompt_tokens=200, context_tokens=4096, ceiling=1792,
                         default_rate=10, max_timeout=300)
        brief = plan_response("给我简单解释一下原理", **arguments)
        detail = plan_response("详细解释原理", **arguments)
        self.assertEqual(brief.scale, "brief")
        self.assertLess(brief.max_tokens, detail.max_tokens)
        self.assertLess(brief.timeout_seconds, detail.timeout_seconds)
        self.assertIn("两三句", brief.directive)


if __name__ == "__main__":
    unittest.main()
