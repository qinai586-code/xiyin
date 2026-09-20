"""Modern restore confirmation on synthetic external data and real SQLite.

Token and console seams are mocked; this does not claim native Windows input or
same-account process isolation. No live data, devices, or models are accessed.
"""
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.lifecycle import RuntimeLease
from xiyin_runtime.supervisor import Supervisor, restore_backup


SOURCE = Path(__file__).resolve().parents[1]


class RuntimeManagementTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-restore-confirmation-test-"))).resolve()
        self.code = self.base / "code"
        self.code.mkdir()
        self.data = self.base / "external-data"
        self.data.mkdir()
        self.root_id = "synthetic-restore-test"
        self.marker = self.data / ".xiyin_data"
        self.marker.write_text(f"xiyin-data-root v1\nid={self.root_id}\n", encoding="utf-8")
        self.backup = self.base / "backup"
        self.store = ExperienceStore(self.data / "experience.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.store.write_document("state", "example", {"text": "before"})
        Supervisor(self.store, self.data, self.root_id, min_free_bytes=0).create_backup(self.backup)
        self.store.write_document("state", "example", {"text": "after"})
        self.store.close()

        path = self.code / "xiyin_management.py"
        shutil.copyfile(SOURCE / "xiyin_management.py", path)
        stack.enter_context(patch.dict(sys.modules))
        sys.modules.pop("xiyin_management", None)
        self.role = "runtime"
        self.identity = SimpleNamespace(
            __file__=str(self.code / "xiyin_identity.py"),
            load_policy=Mock(return_value={"mode": "single_user"}),
            current_role=Mock(side_effect=lambda policy: (self.role, "S-1-5-21-1")),
            reviewer_display_name=Mock(return_value="Windows user S-1-5-21-1"),
        )
        sys.modules["xiyin_identity"] = self.identity
        spec = importlib.util.spec_from_file_location("xiyin_management", path)
        self.management = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_management"] = self.management
        spec.loader.exec_module(self.management)
        self.console = stack.enter_context(patch.object(self.management, "_console_answer", side_effect=self.confirm))

    @staticmethod
    def confirm(prompt):
        return next(line for line in prompt.splitlines() if line.startswith("CONFIRM "))

    def operation(self):
        return self.management.runtime_restore_action(self.code, self.data, self.root_id, self.backup)

    def records(self):
        return [json.loads(line) for line in (self.data / "management_actions.jsonl").read_text(encoding="utf-8").splitlines()]

    def current_value(self):
        with_store = ExperienceStore(self.data / "experience.sqlite3")
        try:
            return with_store.read_document("state", "example")["value"]["text"]
        finally:
            with_store.close()

    def test_external_data_restore_has_one_scoped_confirmation_and_own_audit(self):
        marker = self.marker.read_bytes()
        with self.operation() as scope:
            self.assertEqual(scope, {"backup_dir": self.backup, "data_root": self.data, "data_root_id": self.root_id})
            receipt = restore_backup(scope["backup_dir"], scope["data_root"], scope["data_root_id"])
        self.assertEqual(self.current_value(), "before")
        self.assertTrue(receipt["restored"])
        self.assertEqual(self.marker.read_bytes(), marker)
        self.assertTrue(Path(receipt["rollback_database"]).is_file())
        self.console.assert_called_once()
        prompt = self.console.call_args.args[0]
        displayed, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
        self.assertEqual(displayed["action"], "RUNTIME_RESTORE")
        self.assertEqual(Path(displayed["targets"]["data_root"]), self.data)
        self.assertEqual(Path(displayed["targets"]["backup_dir"]), self.backup)
        self.assertEqual(displayed["detail"]["data_root_id"], self.root_id)
        self.assertEqual([r["status"] for r in self.records()], ["REQUESTED", "CONFIRMED", "SUCCEEDED"])
        self.assertEqual(list(self.code.rglob("management_actions.jsonl")), [])

    def test_decline_and_unavailable_console_do_not_restore(self):
        for failure in (lambda prompt: "yes", PermissionError("synthetic unavailable console")):
            with self.subTest(failure=failure):
                self.console.side_effect = failure
                with self.assertRaises(PermissionError):
                    with self.operation():
                        self.fail("Unconfirmed body must not execute")
                self.assertEqual(self.current_value(), "after")
                self.assertFalse(self.records()[-1]["data_may_have_changed"])
        self.assertEqual(self.records()[-1]["status"], "CONFIRMATION_FAILED")

    def test_real_token_cannot_be_replaced_by_environment_or_stdin(self):
        self.role = "unknown"
        with patch.dict("os.environ", {"XIYIN_APPROVED": "1", "USERNAME": "administrator"}), patch("sys.stdin", io.StringIO("yes\n")):
            with self.assertRaises(PermissionError):
                with self.operation():
                    self.fail("Unverified identity")
        self.console.assert_not_called()
        self.assertFalse((self.data / "management_actions.jsonl").exists())
        self.identity.__file__ = str(self.base / "untrusted_identity.py")
        with self.assertRaisesRegex(RuntimeError, "source mismatch"):
            with self.operation():
                self.fail("Preloaded foreign identity module")

    def test_bad_root_or_backup_is_rejected_before_confirmation(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            with self.management.runtime_restore_action(self.code, self.data, "wrong", self.backup):
                self.fail("Wrong data identity")
        (self.backup / "experience.sqlite3").write_bytes(b"invalid sqlite")
        with self.assertRaises(ValueError):
            with self.operation():
                self.fail("Invalid backup")
        self.console.assert_not_called()
        self.assertEqual(self.records()[-1]["status"], "PREFLIGHT_FAILED")
        self.assertFalse(self.records()[-1]["data_may_have_changed"])
        self.assertEqual(self.current_value(), "after")

    def test_backup_altered_during_confirmation_does_not_enter_restore(self):
        def changed_backup(prompt):
            path = self.backup / "manifest.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["created_at"] = "changed while prompting"
            path.write_text(json.dumps(value), encoding="utf-8")
            return self.confirm(prompt)
        self.console.side_effect = changed_backup
        with self.assertRaisesRegex(ValueError, "changed during"):
            with self.operation():
                self.fail("Changed backup must need a new request")
        self.assertEqual(self.records()[-1]["status"], "PREFLIGHT_FAILED")
        self.assertEqual(self.current_value(), "after")

    def test_audit_failure_before_confirmation_prevents_all_restore_writes(self):
        with patch.object(self.management, "_persist_audit", side_effect=self.management.ManagementAuditError("synthetic full disk")):
            with self.assertRaises(self.management.ManagementAuditError):
                with self.operation():
                    self.fail("Unaudited operation")
        self.console.assert_not_called()
        self.assertEqual(self.current_value(), "after")

    def test_active_runtime_refusal_and_post_confirmation_failure_are_audited(self):
        lease = RuntimeLease(self.data / "runtime.lock")
        try:
            with self.assertRaisesRegex(RuntimeError, "Another"):
                with self.operation():
                    restore_backup(self.backup, self.data, self.root_id)
        finally:
            lease.close()
        self.assertEqual(self.records()[-1]["status"], "FAILED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])
        self.assertEqual(self.current_value(), "after")
        with self.assertRaises(KeyboardInterrupt):
            with self.operation():
                raise KeyboardInterrupt()
        self.assertEqual(self.records()[-1]["status"], "CANCELLED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])


if __name__ == "__main__":
    unittest.main()
