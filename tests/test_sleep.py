"""Persistent phase transitions and foreground preemption without a model."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from xiyin_runtime.agenda import Agenda
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.sleep import SleepController


class SleepTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-sleep-test-"))
        self.path = Path(temporary) / "experience.sqlite3"
        self.store = ExperienceStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.agenda = Agenda(self.store)
        self.sleep = SleepController(self.store, self.agenda)
        self.event = self.store.append_event("assistant", "我昨天通关了（仅助手自述）", session_id="owner", origin="generated", status="completed")

    def test_phases_checkpoint_and_restart_preserve_actual_quotes_without_fact_promotion(self):
        self.sleep.settle()
        result = self.sleep.consolidate()
        self.assertFalse(result["interrupted"])
        self.assertEqual(result["checkpoint"]["excerpts"][0]["event_id"], self.event)
        self.assertEqual(result["checkpoint"]["excerpts"][0]["origin"], "generated")
        self.assertTrue(result["checkpoint"]["not_verified_facts"])
        self.assertEqual(self.store.memories(), [])
        self.sleep.sleep()
        self.store.close()
        self.store = ExperienceStore(self.path)
        resumed = SleepController(self.store, Agenda(self.store))
        self.assertEqual(resumed.state()["phase"], "sleeping")
        before = self.store.list_events("owner")
        resumed.wake("actual foreground input")
        self.assertEqual(self.store.list_events("owner"), before)
        self.assertEqual(resumed.state()["phase"], "awake")
        phases = {item["phase"] for item in resumed.state()["transitions"]}
        self.assertTrue({"settling", "consolidating", "sleeping", "waking", "awake"}.issubset(phases))

    def test_wake_preempts_consolidation_and_pauses_real_resumable_agenda_job(self):
        job = self.agenda.enqueue("sleep_consolidation", {}, resumable=True)
        self.agenda.claim_next()
        self.sleep.settle()
        entered, release = threading.Event(), threading.Event()
        original = self.store.list_events
        def wait_for_wake(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        result = []
        with patch.object(self.store, "list_events", side_effect=wait_for_wake):
            worker = threading.Thread(target=lambda: result.append(self.sleep.consolidate(job_id=job["id"])))
            worker.start()
            self.assertTrue(entered.wait(2))
            self.sleep.wake("new foreground input")
            release.set()
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertTrue(result[0]["interrupted"])
        self.assertEqual(self.sleep.state()["phase"], "awake")
        self.assertEqual(self.agenda.get(job["id"])["status"], "paused")
        self.assertIsNone(self.store.read_document("checkpoints", "sleep_private_owner"))

    def test_second_empty_batch_keeps_summary_and_pending_cursor(self):
        job = self.agenda.enqueue("internal_index", {}, resumable=True)
        self.agenda.claim_next()
        self.agenda.checkpoint(job["id"], {"row": 4})
        self.agenda.pause_active("sleep")
        self.sleep.settle()
        first = self.sleep.consolidate()["checkpoint"]
        second = self.sleep.consolidate()["checkpoint"]
        self.assertEqual(first["excerpts"], second["excerpts"])
        self.assertEqual(second["pending_jobs"][0]["cursor"], {"row": 4})
        self.assertEqual(first["last_seq"], second["last_seq"])

    def test_public_checkpoint_never_projects_private_job_cursor(self):
        self.agenda.enqueue("private_task", {"secret": "owner-only"}, scope="private", resumable=True)
        public = self.agenda.enqueue("public_task", {}, scope="public", resumable=True)
        self.sleep.settle()
        value = self.sleep.consolidate(session_id="visitor", scope="public")["checkpoint"]
        self.assertEqual([item["id"] for item in value["pending_jobs"]], [public["id"]])


if __name__ == "__main__":
    unittest.main()
