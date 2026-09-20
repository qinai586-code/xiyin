"""Lab checks use real SQLite and a deterministic independent file verifier."""
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.learning import BuiltinPolicyEvaluator, DEFAULT_POLICY, LearningLab


class LearningTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-lab-test-"))
        self.store = ExperienceStore(Path(temporary) / "experience.sqlite3")
        self.addCleanup(self.store.close)
        self.evidence = self.store.append_event("user", "请用更小的文件操作预算", session_id="owner", origin="user_report", status="completed")
        self.lab = LearningLab(self.store, evaluator=BuiltinPolicyEvaluator())
        self.policy = {**DEFAULT_POLICY, "max_read_bytes": 32, "max_write_bytes": 32}

    def test_independent_evaluation_adoption_and_rollback_change_active_policy(self):
        candidate = self.lab.propose("缩小读写预算", [self.evidence], strategy=self.policy)
        self.assertEqual(self.lab.active_strategy()["policy"], DEFAULT_POLICY)
        with self.assertRaises(ValueError):
            self.lab.adopt(candidate["id"])
        evaluated = self.lab.evaluate(candidate["id"])
        self.assertEqual(evaluated["assessment"]["measurement_kind"], "functional_policy_check")
        self.assertEqual(self.lab.adopt(candidate["id"])["policy"], self.policy)
        self.assertEqual(LearningLab(self.store).active_strategy()["policy"], self.policy)
        self.assertEqual(self.lab.rollback()["policy"], DEFAULT_POLICY)

    def test_generated_self_evidence_and_out_of_scope_or_self_scored_policy_are_rejected(self):
        invented = self.store.append_event("assistant", "我已经评估自己通过", session_id="owner", origin="generated", status="completed")
        for refs, policy in (([invented], self.policy), (["missing"], self.policy),
                             ([self.evidence], {**self.policy, "assessment": {"passed": True}}),
                             ([self.evidence], {**self.policy, "verify_after_write": False})):
            with self.subTest(refs=refs, policy=policy), self.assertRaises(ValueError):
                self.lab.propose("test", refs, strategy=policy)
        with self.assertRaises(ValueError):
            self.lab.propose("edit arbitrary source", [self.evidence], scope="code", strategy=self.policy)

    def test_no_evaluator_and_same_generator_evaluator_never_approve(self):
        lab = LearningLab(self.store)
        candidate = lab.propose("test", [self.evidence], strategy=self.policy)
        with self.assertRaises(RuntimeError):
            lab.evaluate(candidate["id"])
        function = lambda **kwargs: self.policy
        with self.assertRaises(ValueError):
            LearningLab(self.store, function, function)

    def test_incomplete_failed_and_tampered_assessment_cannot_be_adopted(self):
        candidate = self.lab.propose("test", [self.evidence], strategy=self.policy)
        with self.assertRaises(ValueError):
            self.lab.evaluate(candidate["id"], checks=["looks_good"])
        def evaluator(record, *, checks):
            return {"passed": True, "checks": {check: False for check in checks}, "candidate_digest": record["digest"]}
        self.lab.evaluator = evaluator
        self.assertEqual(self.lab.evaluate(candidate["id"])["status"], "rejected")
        with self.assertRaises(ValueError):
            self.lab.adopt(candidate["id"])
        another = LearningLab(self.store, evaluator=BuiltinPolicyEvaluator())
        candidate = another.propose("test", [self.evidence], strategy=self.policy)
        another.evaluate(candidate["id"])
        document = self.store.read_document("candidates", candidate["id"])
        document["value"]["policy"]["max_read_bytes"] = 64
        self.store.write_document("candidates", candidate["id"], document["value"], expected_version=document["version"])
        with self.assertRaises(ValueError):
            another.adopt(candidate["id"])


if __name__ == "__main__":
    unittest.main()
