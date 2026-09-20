"""Runtime dispatch integration with temporary storage and a disabled model.

These verify wiring/persistence and real sandbox file receipts, not model
behavior, native account authentication or a real game connection.
"""
from pathlib import Path
import tempfile
import unittest

from xiyin_runtime.architecture import DisabledModelProvider
from xiyin_runtime.config import Settings
from xiyin_runtime.context import RECORDS_PREFIX
from xiyin_runtime.contracts import InputEvent
from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.provider import ProviderConfig
from xiyin_runtime.runtime import XIYINRuntime


SEED = Path(__file__).resolve().parents[1] / "config/persona/character.seed.json"


class RuntimeGrowthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-growth-flow-")))
        self.path = self.tmp / "experience.sqlite3"
        self.settings = Settings(ProviderConfig("http://localhost:8080/v1", "disabled-test"),
                                 SEED, max_context_chars=20000, history_messages=12)

    def runtime(self):
        store = ExperienceStore(self.path)
        self.addCleanup(store.close)
        return XIYINRuntime(self.settings, store, provider=DisabledModelProvider(), authorize=lambda: None)

    @staticmethod
    def current_projection(runtime, session="owner", scope="private"):
        # Historical operation receipts may still quote a retired preference;
        # only the active character projection is an instruction for this turn.
        return runtime._messages("继续交流", session, scope)[0]["content"].split(RECORDS_PREFIX, 1)[0]

    async def test_feedback_grow_projection_restart_and_rollback_restore_seed(self):
        seed_bytes = SEED.read_bytes()
        runtime = self.runtime()
        seed = runtime.persona.data["expression_seed"]["private"]
        growth = {"kind": "preference", "subject": "expression:private",
                  "statement": "遇到分享时先回应内容，再按话题需要展开。"}
        self.assertIn(seed, self.current_projection(runtime))
        feedback = await runtime.dispatch(InputEvent("feedback", {"rating": 0.8, "growth": growth}))
        self.assertNotIn(growth["statement"], self.current_projection(runtime))
        adopted = await runtime.dispatch(InputEvent("grow", dict(growth, evidence_refs=[feedback["last_event_id"]])))
        self.assertEqual(adopted["status"], "adopted")
        self.assertIn(growth["statement"], self.current_projection(runtime))
        self.assertNotIn(seed, self.current_projection(runtime))
        self.assertNotIn(growth["statement"], self.current_projection(runtime, "audience", "public"))
        identity = runtime.self_state.snapshot()["persistent_id"]
        await runtime.shutdown()

        resumed = self.runtime()
        self.assertEqual(resumed.self_state.snapshot()["persistent_id"], identity)
        self.assertIn(growth["statement"], self.current_projection(resumed))
        rolled_back = await resumed.dispatch(InputEvent("rollback_growth", {"candidate_id": adopted["id"]}))
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertIn(seed, self.current_projection(resumed))
        self.assertNotIn(growth["statement"], self.current_projection(resumed))
        self.assertEqual(resumed.store.memories(kind="preference"), [])
        receipt = resumed.store.operation_receipts("owner")[-1]
        self.assertEqual(receipt["content"]["operation"], "retract")
        self.assertEqual(receipt["status"], "verified_success")
        self.assertTrue(resumed.store.list_events("owner"), "Rollback preserves the real feedback history")
        self.assertEqual(SEED.read_bytes(), seed_bytes)
        await resumed.shutdown()

        reopened = self.runtime()
        self.assertIn(seed, self.current_projection(reopened))
        self.assertNotIn(growth["statement"], self.current_projection(reopened))
        self.assertEqual(reopened.store.read_document("candidates", adopted["id"])["value"]["status"], "rolled_back")
        await reopened.shutdown()

    async def test_dispatch_plan_then_tick_executes_verified_file_write_and_read(self):
        runtime = self.runtime()
        workspace = self.tmp / "workspace"
        workspace.mkdir()
        runtime.register_workspace(workspace)
        target = workspace / "roundtrip.txt"
        planned = await runtime.dispatch(InputEvent("plan", {"objective": {
            "skill": "write_text", "path": target.name, "text": "栖音真实文件闭环"}}))
        self.assertEqual(planned["status"], "queued")
        self.assertFalse(target.exists())
        completed = await runtime.dispatch(InputEvent("tick"))
        self.assertEqual(completed["id"], planned["job_id"])
        self.assertEqual(completed["status"], "completed")
        receipt = completed["result"]["receipts"][0]
        self.assertEqual(receipt["status"], "success")
        self.assertTrue(receipt["verified"])
        self.assertEqual(target.read_text(encoding="utf-8"), "栖音真实文件闭环")
        goal = runtime.store.read_document("goals", planned["id"])["value"]
        self.assertEqual((goal["status"], goal["completed_steps"]), ("completed", 1))

        read = await runtime.dispatch(InputEvent("plan", {"objective": {"skill": "read_text", "path": target.name}}))
        result = await runtime.dispatch(InputEvent("tick"))
        self.assertEqual(result["id"], read["job_id"])
        self.assertEqual(result["result"]["receipts"][0]["evidence"]["text"], "栖音真实文件闭环")
        action_events = [event for event in runtime.store.list_events("owner") if event["kind"] == "action_result"]
        self.assertEqual(len(action_events), 2)
        self.assertTrue(all(event["status"] == "verified_success" for event in action_events))
        self.assertEqual((await runtime.dispatch(InputEvent("tick")))["status"], "idle")
        self.assertEqual(len([event for event in runtime.store.list_events("owner") if event["kind"] == "action_result"]), 2)
        self.assertEqual(runtime.store.history("owner"), [], "Rules and operations do not invent model dialogue")
        await runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
