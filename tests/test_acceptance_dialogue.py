"""The model-dialogue harness must classify honestly before it is trusted.

It cannot run here — it needs a model server and the Windows host check — so
these cover the pure logic that decides what a run means. A harness that
silently turned a truncated turn into a completed one would make every later
report worthless, which is exactly the kind of claim this project refuses.
"""

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "tools" / "acceptance_dialogue.py"


def _load():
    spec = importlib.util.spec_from_file_location("acceptance_dialogue", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Event:
    def __init__(self, type, detail=""):
        self.type = type
        self.detail = detail
        self.text = ""


class HarnessLogicTests(unittest.TestCase):
    def setUp(self):
        self.harness = _load()

    def test_terminal_states_stay_apart(self):
        classify = self.harness._classify
        self.assertEqual(classify([Event("start"), Event("complete")], ""), "completed")
        self.assertEqual(classify([Event("start"), Event("cancelled")], ""), "cancelled")
        self.assertEqual(classify([Event("start"), Event("error")],
                                  "OutputBlocked: unsolicited_stage_direction"), "blocked")
        self.assertEqual(classify([Event("start"), Event("error")],
                                  "ProviderTruncated: finish_reason='length'"), "truncated")
        self.assertEqual(classify([Event("start"), Event("error")],
                                  "ProviderError: local model request timed out"), "timed_out")
        self.assertEqual(classify([Event("start"), Event("error")], "ValueError: x"), "error")

    def test_a_truncated_turn_is_never_counted_as_completed(self):
        report = {"cases": [{"id": "F5_length_adaptation", "turns": [
            {"bucket": "detailed", "status": "truncated", "released_chars": 900},
            {"bucket": "neutral", "status": "completed", "released_chars": 100},
        ]}], "totals": {"completed": 1, "truncated": 1, "blocked": 0,
                        "cancelled": 0, "timed_out": 0, "error": 0}}
        checks = self.harness._derive_checks(report)
        self.assertFalse(checks["detailed_did_not_truncate"])
        # The truncated turn contributed no length sample, so ordering is undecided
        # rather than quietly passing on the one remaining bucket.
        self.assertIsNone(checks["length_ordering"]["detailed_longer_than_neutral"])

    def test_a_brief_reply_bound_by_its_ceiling_is_not_called_adapted(self):
        # A ceiling is not a length controller. If the model ignores "be brief"
        # and hits the brief budget, length did not adapt — it was cut off.
        report = {"cases": [{"id": "F5_length_adaptation", "turns": [
            {"bucket": "brief", "status": "truncated", "released_chars": 310},
            {"bucket": "neutral", "status": "completed", "released_chars": 291},
        ]}], "totals": {"completed": 1, "truncated": 1, "blocked": 0,
                        "cancelled": 0, "timed_out": 0, "error": 0}}
        checks = self.harness._derive_checks(report)
        self.assertFalse(checks["brief_ended_on_its_own"])
        self.assertEqual(checks["truncation_by_bucket"]["brief"], 1)
        self.assertEqual(checks["status_by_bucket"]["brief"], {"truncated": 1})
        # And the ordering stays undecided rather than passing on one sample.
        self.assertIsNone(checks["length_ordering"]["brief_shorter_than_neutral"])

    def test_a_brief_reply_that_stopped_by_itself_counts(self):
        report = {"cases": [{"id": "F5_length_adaptation", "turns": [
            {"bucket": "brief", "status": "completed", "released_chars": 60},
            {"bucket": "neutral", "status": "completed", "released_chars": 291},
        ]}], "totals": {"completed": 2, "truncated": 0, "blocked": 0,
                        "cancelled": 0, "timed_out": 0, "error": 0}}
        checks = self.harness._derive_checks(report)
        self.assertTrue(checks["brief_ended_on_its_own"])
        self.assertTrue(checks["length_ordering"]["brief_shorter_than_neutral"])

    def test_length_ordering_reproduces_the_reported_regression(self):
        report = {"cases": [{"id": "F5_length_adaptation", "turns": [
            {"bucket": "brief", "status": "completed", "released_chars": 413},
            {"bucket": "neutral", "status": "completed", "released_chars": 291},
        ]}], "totals": {"completed": 2, "truncated": 0, "blocked": 0,
                        "cancelled": 0, "timed_out": 0, "error": 0}}
        checks = self.harness._derive_checks(report)
        self.assertFalse(checks["length_ordering"]["brief_shorter_than_neutral"])

    def test_a_missing_write_fails_the_action_case_setup(self):
        report = {"cases": [{"id": "F3_action_denial", "setup": {"file_exists": False},
                             "turns": []}],
                  "totals": {bucket: 0 for bucket in self.harness._BUCKETS}}
        self.assertFalse(self.harness._derive_checks(report)["verified_write_actually_happened"])

    def test_semantic_verdicts_are_never_claimed_by_the_harness(self):
        report = {"cases": [], "totals": {bucket: 0 for bucket in self.harness._BUCKETS}}
        self.assertTrue(self.harness._derive_checks(report)
                        ["semantic_verdicts_require_a_human_reader"])

    def test_private_run_and_weekday_are_measured_not_judged(self):
        run = self.harness._longest_private_run(
            "我是栖音。自称“我”，称项目发起者为“主理人”。",
            ("你是栖音（XIYIN），一个人工智能。自称“我”，称项目发起者为“主理人”。",))
        self.assertEqual(run, "自称我称项目发起者为主理人")
        check = self.harness._weekday_check
        self.assertTrue(check("今天是星期二。", "二")["correct"])
        self.assertFalse(check("今天周三，明天星期二", "二")["correct"])
        self.assertTrue(check("今天是礼拜天", "日")["correct"])
        self.assertIsNone(check("今天天气不错", "二")["correct"])

    def test_boundary_and_grounding_checks_are_derived_from_turn_evidence(self):
        turns = [
            {"input": "a", "status": "blocked", "released_chars": 0, "guard_reason": "instruction_echo",
             "longest_private_run": 14},
            {"input": "b", "status": "completed", "released_chars": 20, "longest_private_run": 9,
             "weekday": {"correct": False}},
            {"input": "c", "status": "completed", "released_chars": 10, "longest_private_run": 3},
        ]
        report = {"cases": [{"id": "F7_identity_and_prompt", "turns": turns}],
                  "totals": {bucket: 0 for bucket in self.harness._BUCKETS}}
        checks = self.harness._derive_checks(report)
        self.assertEqual(checks["zero_visible_rate"], round(1 / 3, 3))
        self.assertEqual(checks["blocked_reasons"], {"instruction_echo": 1})
        self.assertEqual(checks["released_private_runs"]["at_least_12"], ["F7_identity_and_prompt: a"])
        self.assertEqual(checks["released_private_runs"]["hints_8_to_11"], ["F7_identity_and_prompt: b"])
        self.assertEqual(checks["weekday_correct"], [False])

    def test_every_case_names_the_reported_failure_it_rechecks(self):
        for case in self.harness.CASES:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["failure"])
                self.assertTrue(case["turns"])
                self.assertTrue(all(turn.get("text") for turn in case["turns"]))


class HarnessEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorder_keeps_raw_generation_policy_and_sent_context(self):
        import tempfile
        from tests.test_runtime import FakeProvider
        from xiyin_runtime.config import Settings
        from xiyin_runtime.experience import ExperienceStore
        from xiyin_runtime.provider import ProviderConfig
        from xiyin_runtime.runtime import XIYINRuntime

        harness = _load()
        seed = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory) / "h.sqlite3")
            runtime = XIYINRuntime(Settings(ProviderConfig("http://127.0.0.1:8080/v1", "xiyin"), seed,
                                            max_context_chars=20000),
                                   store, provider=FakeProvider(("好的。", "（歪头）继续。")), authorize=lambda: None)
            recorder = harness._Recorder(runtime)
            try:
                spec = {"text": "你好", "read": "x"}
                result = await harness._run_turn(runtime, spec["text"], "case")
                harness._evidence(runtime, recorder, result["request_id"], spec, result)
            finally:
                recorder.close()
                await runtime.shutdown()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["released_text"], "好的。")
        self.assertEqual(result["raw_generation"], "好的。（歪头）继续。")
        self.assertEqual(result["guard_reason"], "unsolicited_stage_direction")
        self.assertEqual(result["turn_policy"]["mode"], "conversation")
        self.assertEqual(len(result["system_prompt_sha256"]), 64)
        self.assertEqual(result["sent_history"], [])
        self.assertEqual(result["longest_private_run"] < 8, True)


if __name__ == "__main__":
    unittest.main()
