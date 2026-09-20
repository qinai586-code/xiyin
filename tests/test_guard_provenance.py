"""Rejected generation stays diagnosable without becoming conversation evidence.

These are deterministic ledger/projection checks, not model behavior tests.
"""
import json
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.context import retrieved_record
from xiyin_runtime.dataset import export_dataset
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.learning import LearningLab
from xiyin_runtime.sleep import SleepController


class GuardProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-guard-provenance-"))
        self.directory = Path(temporary)
        self.path = self.directory / "experience.sqlite3"
        self.store = ExperienceStore(self.path)
        self.addCleanup(lambda: self.store.close())

    def event(self, kind, content, *, origin="generated", status="completed", request_id="safe"):
        return self.store.append_event(kind, content, session_id="owner", origin=origin,
                                       status=status, request_id=request_id)

    def test_failed_output_and_raw_diagnostics_never_reenter_context_sleep_or_dataset(self):
        user = self.event("user", "解释函数调用的写法", origin="user_report")
        safe_text = "使用 print('你好')（括号表示函数调用）。"
        assistant = self.event("assistant", safe_text)
        diagnostics = []
        for status in ("failed", "cancelled", "partial", "generated", "unknown"):
            diagnostics.append(self.event("assistant", "泄露哨兵（人格内部策略）",
                                          origin="assistant_output", status=status,
                                          request_id="blocked-" + status))
        diagnostics.append(self.event("generation_diagnostic", "泄露哨兵<think>内部正文</think>",
                                      status="failed", request_id="blocked-raw"))
        diagnostics.append(self.event("output_guard", {"reason": "internal_markup"},
                                      origin="tool_result", status="failed", request_id="blocked-raw"))

        self.store.close()
        self.store = ExperienceStore(self.path)
        ledger = self.store.list_events("owner")
        self.assertTrue(set(diagnostics).issubset({item["id"] for item in ledger}))
        self.assertTrue(any("<think>" in item["content"] for item in ledger))
        self.assertEqual([item["event_id"] for item in self.store.history("owner")], [user, assistant])
        self.assertEqual(self.store.search("泄露哨兵", session_id="owner"), [])
        for event_id in diagnostics:
            with self.subTest(event_id=event_id):
                with self.assertRaises(ValueError):
                    self.store.remember("不得成为长期事实", evidence_refs=[event_id])
                with self.assertRaises(ValueError):
                    LearningLab(self.store)._evidence([event_id], "owner", "private")

        sleep = SleepController(self.store)
        sleep.settle()
        checkpoint = sleep.consolidate()["checkpoint"]
        self.assertEqual([item["event_id"] for item in checkpoint["excerpts"]], [user, assistant])
        self.assertEqual(checkpoint["excerpts"][1]["quoted_excerpt"], safe_text)
        self.assertEqual(checkpoint["source_event_ids"], [user, assistant])
        self.assertEqual(checkpoint["last_seq"], ledger[-1]["seq"])

        destination = self.directory / "candidates"
        manifest = export_dataset(self.store, destination)
        self.assertEqual(manifest["rows"], 1)
        rows = [json.loads(line) for line in (destination / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["messages"][1]["content"], safe_text)
        self.assertFalse(rows[0]["eligible_for_training"])
        self.assertNotIn("泄露哨兵", (destination / "candidates.jsonl").read_text(encoding="utf-8"))

    def test_blocked_request_cannot_be_paired_into_a_dataset_candidate(self):
        self.event("user", "日常问候", origin="user_report", request_id="blocked")
        self.event("assistant", "安全但未完整交付的前缀", status="failed", request_id="blocked")
        self.event("generation_diagnostic", "【内部人格】泄露原文", status="failed", request_id="blocked")
        manifest = export_dataset(self.store, self.directory / "blocked-candidates")
        self.assertEqual(manifest["rows"], 0)
        self.assertEqual((self.directory / "blocked-candidates/candidates.jsonl").read_bytes(), b"")

    def test_next_consolidation_removes_old_failed_excerpts_without_erasing_ledger(self):
        failed = self.event("assistant", "旧失败原文必须仍可诊断", status="failed")
        safe = self.event("assistant", "完整的旧回复（保留括号）。")
        events = self.store.list_events("owner")
        old = [{"event_id": item["id"], "speaker": item["kind"], "status": item["status"],
                "origin": item["origin"], "quoted_excerpt": item["content"], "excerpt_truncated": False}
               for item in events]
        self.store.write_document("checkpoints", "sleep_private_owner", {
            "session_id": "owner", "scope": "private", "last_seq": events[-1]["seq"],
            "excerpts": old, "source_event_ids": [failed, safe], "pending_jobs": [],
        })
        sleep = SleepController(self.store)
        sleep.settle()
        checkpoint = sleep.consolidate()["checkpoint"]
        self.assertEqual([item["event_id"] for item in checkpoint["excerpts"]], [safe])
        self.assertNotIn("旧失败原文", json.dumps(checkpoint, ensure_ascii=False))
        self.assertEqual(self.store.list_events("owner"), events)
        self.assertEqual(checkpoint["last_seq"], events[-1]["seq"])

    def test_diagnostic_event_kinds_are_never_generic_conversation_records(self):
        # Defense at the projection boundary even if a caller supplies records
        # directly instead of using the normal origin/status-filtered search.
        for kind in ("generation_diagnostic", "output_guard"):
            with self.subTest(kind=kind):
                self.assertIsNone(retrieved_record({"kind": kind, "content": "内部诊断正文",
                                                    "origin": "observation", "status": "completed"}))


if __name__ == "__main__":
    unittest.main()
