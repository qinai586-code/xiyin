"""Real temporary SQLite checks; none of these tests call models or devices."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from xiyin_runtime.agenda import Agenda
from xiyin_runtime.experience import DocumentConflict, DocumentCorruptionError, ExperienceStore
from xiyin_runtime.self_state import SelfState


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-core-"))
        self.path = Path(self.tmp) / "experience.sqlite3"
        self.store = self.enterContext(ExperienceStore(self.path))


class DocumentTests(StoreCase):
    def test_versions_cas_order_and_detached_values(self):
        value = {"items": [1], "scope": "private"}
        first = self.store.write_document("goals", "one", value, expected_version=0)
        value["items"].append(99)
        self.assertEqual(self.store.read_document("goals", "one")["value"]["items"], [1])
        with self.assertRaises(DocumentConflict):
            self.store.write_document("goals", "one", {}, expected_version=0)
        second = self.store.write_document("goals", "one", {"done": True}, expected_version=first["version"])
        self.assertEqual(second["version"], 2)
        self.store.write_document("goals", "two", {})
        self.assertEqual([item["key"] for item in self.store.list_documents("goals")], ["one", "two"])
        self.assertIsNone(self.store.read_document("state", "missing"))

    def test_document_and_ledger_are_one_transaction(self):
        before = self.store.write_document("jobs", "one", {"status": "queued"})
        with patch.object(self.store, "_insert_event", side_effect=RuntimeError("ledger unavailable")):
            with self.assertRaises(RuntimeError):
                self.store.write_document("jobs", "one", {"status": "running"}, expected_version=1)
        self.assertEqual(self.store.read_document("jobs", "one"), before)
        records = self.store.list_events("system")
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0]["content"]), {"collection": "jobs", "key": "one", "version": 1})
        with self.assertRaises(RuntimeError), self.store.document_transaction():
            self.store.write_document("state", "a", {})
            self.store.write_document("state", "b", {})
            raise RuntimeError("batch failed")
        self.assertEqual(self.store.list_documents("state"), [])
        self.assertEqual(len(self.store.list_events("system")), 1)

    def test_reopen_adds_documents_without_resetting_legacy_memories(self):
        event = self.store.append_event("user", "旧事实", session_id="one", origin="user_report")
        memory = self.store.remember("旧事实", evidence_refs=[event])
        with self.store._db:
            self.store._db.execute("DROP TABLE documents")
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            self.assertEqual(reopened.memories()[0]["id"], memory)
            self.assertEqual(reopened.history("one")[0]["event_id"], event)
            reopened.write_document("checkpoints", "new", {"cursor": 1})
            self.assertEqual(reopened.read_document("checkpoints", "new")["version"], 1)

    def test_corrupt_json_is_not_treated_as_an_empty_default(self):
        self.store.write_document("state", "one", {})
        for raw in ('{broken', '[1]', '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e400}'):
            with self.store._db:
                self.store._db.execute("UPDATE documents SET value=? WHERE key='one'", (raw,))
            with self.subTest(raw=raw):
                for read in (lambda: self.store.read_document("state", "one"),
                             lambda: self.store.list_documents("state"),
                             lambda: self.store.write_document("state", "one", {})):
                    with self.assertRaises(DocumentCorruptionError):
                        read()

    def test_invalid_writes_do_not_leave_records(self):
        for value in ([], {1: "lossy key"}, {"x": float("nan")}, {"x": object()}, {"x": (1, 2)}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.write_document("state", "one", value)
        with self.assertRaises(ValueError):
            self.store.write_document("arbitrary", "one", {})
        for version in (-1, True, "1"):
            with self.assertRaises(ValueError):
                self.store.write_document("state", "one", {}, expected_version=version)
        self.assertEqual(self.store.list_events("system"), [])

    def test_competing_connections_only_one_cas_winner(self):
        self.store.write_document("goals", "one", {"n": 0})
        second = self.enterContext(ExperienceStore(self.path))
        barrier = threading.Barrier(2)
        def update(store):
            prior = store.read_document("goals", "one")
            barrier.wait(timeout=5)
            try:
                store.write_document("goals", "one", {"n": 1}, expected_version=prior["version"])
                return "updated"
            except DocumentConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(update, (self.store, second)))
        self.assertCountEqual(outcomes, ["updated", "conflict"])
        self.assertEqual(self.store.read_document("goals", "one")["version"], 2)


class AgendaTests(StoreCase):
    def test_priority_creation_order_and_no_terminal_rewrite(self):
        agenda = Agenda(self.store)
        low = agenda.enqueue("work", {}, priority=1)
        high = agenda.enqueue("work", {}, priority=2)
        last = agenda.enqueue("work", {}, priority=2)
        self.assertEqual(agenda.claim_next()["id"], high["id"])
        self.assertIsNone(agenda.claim_next())
        finished = agenda.finish(high["id"], "completed", result={"done": True})
        before = len(self.store.list_events("system"))
        self.assertEqual(agenda.finish(high["id"], "completed"), finished)
        self.assertEqual(len(self.store.list_events("system")), before)
        with self.assertRaises(ValueError):
            agenda.finish(high["id"], "failed")
        self.assertEqual(agenda.claim_next()["id"], last["id"])
        agenda.finish(last["id"], "completed")
        self.assertEqual(agenda.claim_next()["id"], low["id"])

    def test_two_agendas_cannot_claim_two_running_jobs(self):
        agenda = Agenda(self.store)
        agenda.enqueue("a", {})
        agenda.enqueue("b", {})
        second = self.enterContext(ExperienceStore(self.path))
        barrier = threading.Barrier(2)
        def claim(store):
            barrier.wait(timeout=5)
            return Agenda(store).claim_next()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, (self.store, second)))
        self.assertEqual(sum(result is not None for result in outcomes), 1)
        self.assertEqual(sum(doc["value"]["status"] == "running" for doc in self.store.list_documents("jobs")), 1)

    def test_resume_after_restart_keeps_cursor_and_does_not_autorun(self):
        agenda = Agenda(self.store)
        job = agenda.enqueue("sleep", {"since": 10}, resumable=True)
        agenda.claim_next()
        agenda.checkpoint(job["id"], {"event_seq": 14})
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            restored = Agenda(reopened)
            changed = restored.recover()
            self.assertEqual(changed[0]["status"], "paused")
            self.assertEqual(changed[0]["cursor"], {"event_seq": 14})
            self.assertIsNone(restored.claim_next())
            self.assertEqual(restored.recover(), [])
            restored.resume(job["id"])
            resumed = restored.claim_next()
            self.assertEqual(resumed["attempts"], 2)
            self.assertEqual(resumed["cursor"], {"event_seq": 14})

    def test_external_unknown_is_never_automatically_repeated(self):
        agenda = Agenda(self.store)
        job = agenda.enqueue("device_action", {"action": "submit"})
        agenda.claim_next()
        recovered = agenda.recover()[0]
        self.assertEqual(recovered["status"], "unknown")
        self.assertIsNone(agenda.claim_next())
        with self.assertRaises(ValueError):
            agenda.resume(job["id"])
        with self.assertRaises(ValueError):
            agenda.finish(job["id"], "completed")

    def test_foreground_preempts_internal_job_then_explicitly_resumes(self):
        agenda = Agenda(self.store)
        sleepy = agenda.enqueue("sleep", {}, resumable=True)
        agenda.claim_next()
        agenda.checkpoint(sleepy["id"], {"done": 3})
        agenda.pause_active("owner returned")
        foreground = agenda.enqueue("conversation", {}, priority=100)
        self.assertEqual(agenda.claim_next()["id"], foreground["id"])
        agenda.finish(foreground["id"], "completed")
        agenda.resume(sleepy["id"])
        self.assertEqual(agenda.claim_next()["cursor"], {"done": 3})
        agenda.stop()
        self.assertEqual(agenda.get(sleepy["id"])["status"], "cancelled")
        self.assertIsNone(agenda.claim_next())


class SelfStateTests(StoreCase):
    def test_observations_change_bounded_scoped_state_and_survive_restart(self):
        state = SelfState(self.store)
        first = state.snapshot("one", "private")
        state.observe("user_input", {"text": "你好"}, session_id="one")
        for _ in range(15):
            current = state.observe("user_feedback", {"rating": 1}, session_id="one")
        self.assertEqual(current["affect"]["valence"], 1)
        self.assertGreater(current["affect"]["arousal"], 0)
        self.assertEqual(current["origin"], "inference")
        self.assertEqual(state.snapshot("one", "public")["affect"]["valence"], 0)
        self.assertEqual(state.snapshot("two")["observation_count"], 0)
        self.store.close()
        with ExperienceStore(self.path) as reopened:
            loaded = SelfState(reopened).snapshot("one")
            self.assertEqual(loaded["persistent_id"], first["persistent_id"])
            self.assertEqual(loaded["affect"], current["affect"])
            self.assertEqual(loaded["observation_count"], current["observation_count"])

    def test_real_source_replay_is_idempotent_even_after_another_observation(self):
        state = SelfState(self.store)
        source = self.store.append_event("user", "不错", session_id="owner", origin="user_report")
        state.observe("user_feedback", {"rating": 1, "event_id": source})
        current = state.observe("user_input", {"text": "继续"})
        replay = state.observe("user_feedback", {"rating": 1, "event_id": source})
        self.assertEqual(replay["version"], current["version"])
        self.assertEqual(replay["affect"], current["affect"])
        generated = self.store.append_event("assistant", "我赢了", session_id="owner", origin="generated", status="completed")
        with self.assertRaises(ValueError):
            state.observe("action_result", {"status": "verified_success", "event_id": generated})
        with self.assertRaises(ValueError):
            state.observe("user_input", {"event_id": source}, scope="public")

    def test_growth_overrides_without_rewriting_identity_or_seed(self):
        state = SelfState(self.store)
        before = state.snapshot()
        source = self.store.append_event("user", "更愿意主动交流", session_id="owner", origin="user_report")
        self.store.remember("熟悉场合更愿意主动交流", kind="persona", subject="tendency:settling", evidence_refs=[source])
        after = state.snapshot()
        self.assertEqual(after["tendencies"][0]["value"], "熟悉场合更愿意主动交流")
        self.assertEqual(after["tendencies"][0]["evidence_refs"], [source])
        self.assertEqual(after["identity"], before["identity"])
        self.assertEqual(state.persona.data["tendencies"][0]["default"], before["tendencies"][0]["value"])
        self.assertEqual(state.snapshot(scope="public")["tendencies"][0]["value"], before["tendencies"][0]["value"])

    def test_rest_wake_and_stop_are_explicit_functional_states(self):
        state = SelfState(self.store)
        self.assertEqual(state.observe("rest", {})["mode"], "sleep")
        self.assertEqual(state.observe("wake", {})["mode"], "awake")
        self.assertEqual(state.observe("stop", {})["mode"], "stopped")
        self.assertEqual(state.observe("user_input", {"text": "消息"})["mode"], "stopped")
        self.assertEqual(state.observe("wake", {})["mode"], "awake")
        before = len(self.store.list_events("owner"))
        for kind, payload in (("user_feedback", {"rating": float("nan")}), ("action_result", {"status": "said_done"}),
                              ("activity", {"name": ""}), ("identity", {"character_id": "different"})):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                state.observe(kind, payload)
        self.assertEqual(len(self.store.list_events("owner")), before)


if __name__ == "__main__":
    unittest.main()
