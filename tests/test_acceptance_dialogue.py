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

    def test_every_case_names_the_reported_failure_it_rechecks(self):
        for case in self.harness.CASES:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["failure"])
                self.assertTrue(case["turns"])
                self.assertTrue(all(turn.get("text") for turn in case["turns"]))


if __name__ == "__main__":
    unittest.main()
