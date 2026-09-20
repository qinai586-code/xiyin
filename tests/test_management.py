"""Current management authority/confirmation contract on synthetic trees only.

Legacy administrators are retired; Supervisor operations have their own tests.
Mocked token/console calls do not establish a same-user OS security boundary.
"""
from contextlib import ExitStack
import ctypes
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


SOURCE = Path(__file__).resolve().parents[1]


class ManagementTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-management-test-"))).resolve()
        shutil.copyfile(SOURCE / "xiyin_management.py", self.root / "xiyin_management.py")
        stack.enter_context(patch.dict(sys.modules))
        for name in ("xiyin_identity", "xiyin_management"):
            sys.modules.pop(name, None)
        self.mode, self.role = "single_user", "runtime"
        self.identity = SimpleNamespace(
            __file__=str(self.root / "xiyin_identity.py"),
            load_policy=Mock(side_effect=lambda root: {"mode": self.mode}),
            current_role=Mock(side_effect=lambda policy: (self.role, "S-1-5-21-1")),
            reviewer_display_name=Mock(return_value="Windows user S-1-5-21-1"),
        )
        sys.modules["xiyin_identity"] = self.identity
        self.management = self.load("xiyin_management", self.root / "xiyin_management.py")
        self.console = stack.enter_context(patch.object(self.management, "_console_answer", side_effect=self.confirm))
        self.target = self.root / "data/synthetic.txt"
        self.targets = {"destination": self.target}

    @staticmethod
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def confirm(prompt):
        return next(line for line in prompt.splitlines() if line.startswith("CONFIRM "))

    def records(self):
        files = list(self.root.rglob("management_actions.jsonl"))
        self.assertEqual(len(files), 1)
        return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]

    def operation(self, action="SNAPSHOT_CREATE", *, detail=None):
        return self.management.management_action(self.root, action, self.targets, detail=detail)

    def write(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("synthetic result", encoding="utf-8")

    def test_single_user_and_legacy_identity_cannot_be_supplied_by_operator(self):
        self.assertEqual(self.management.verified_operator(self.root), "Windows user S-1-5-21-1")
        self.mode = "separate_accounts"
        with self.assertRaises(PermissionError):
            self.management.verified_operator(self.root)
        self.role = "reviewer"
        self.assertEqual(self.management.verified_operator(self.root), "Windows user S-1-5-21-1")
        with self.assertRaises(PermissionError):
            self.management.verified_operator(self.root, "SJ_Admin")
        self.role = "unknown"
        with self.assertRaises(PermissionError):
            self.management.verified_operator(self.root, "Windows user S-1-5-21-1")
        self.identity.current_role.side_effect = RuntimeError("synthetic token failure")
        with self.assertRaises(RuntimeError):
            self.management.verified_operator(self.root)
        self.console.assert_not_called()

    def test_specific_confirmation_records_action_targets_and_real_result(self):
        with self.operation(detail={"reason": "synthetic snapshot"}) as lease:
            self.management.require_scope(lease, self.root, {"SNAPSHOT_CREATE"}, self.targets)
            self.write()
        self.assertEqual(self.target.read_text(), "synthetic result")
        self.console.assert_called_once()
        prompt = self.console.call_args.args[0]
        displayed, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
        self.assertEqual(displayed["action"], "SNAPSHOT_CREATE")
        self.assertEqual(displayed["targets"], {"destination": str(self.target)})
        records = self.records()
        self.assertEqual([r["status"] for r in records], ["REQUESTED", "CONFIRMED", "SUCCEEDED"])
        self.assertEqual(len({r["request_id"] for r in records}), 1)
        self.assertEqual(records[-1]["detail"], {"reason": "synthetic snapshot"})
        self.assertEqual(records[-1]["targets"], displayed["targets"])

    def test_declined_confirmation_prevents_body_and_records_cancellation(self):
        self.console.side_effect = lambda prompt: "yes"
        with self.assertRaises(self.management.ManagementCancelled):
            with self.operation():
                self.write()
        self.assertFalse(self.target.exists())
        self.assertEqual([r["status"] for r in self.records()], ["REQUESTED", "CANCELLED"])
        self.assertFalse(self.records()[-1]["data_may_have_changed"])

    def test_missing_console_stops_even_with_environment_and_stdin(self):
        self.console.side_effect = PermissionError("synthetic no console")
        with patch.dict("os.environ", {"XIYIN_APPROVED": "1", "USERNAME": "SJ_Admin"}), patch("sys.stdin", io.StringIO("yes\n")):
            with self.assertRaises(PermissionError):
                with self.operation():
                    self.write()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.records()[-1]["status"], "CONFIRMATION_FAILED")

    def test_unsupported_action_and_root_cannot_enter_confirmation(self):
        with self.assertRaises(ValueError):
            with self.operation("RUN_ANYTHING"):
                self.fail("unsupported operation executed")
        with self.assertRaises(PermissionError):
            self.management.verified_operator(SOURCE)
        self.console.assert_not_called()

    def test_request_or_confirmation_audit_failure_prevents_body(self):
        original = self.management._append_audit
        for failed_status in ("REQUESTED", "CONFIRMED"):
            with self.subTest(failed_status=failed_status):
                def append(root, record):
                    if record["status"] == failed_status:
                        raise self.management.ManagementAuditError("synthetic audit failure")
                    return original(root, record)
                with patch.object(self.management, "_append_audit", side_effect=append):
                    with self.assertRaises(self.management.ManagementAuditError):
                        with self.operation():
                            self.write()
                self.assertFalse(self.target.exists())
                self.assertEqual(self.management._ACTIVE, {})

    def test_operation_and_post_write_audit_failure_never_report_success(self):
        with self.assertRaises(OSError):
            with self.operation():
                raise OSError("synthetic operation failure")
        self.assertEqual(self.records()[-1]["status"], "FAILED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])
        original = self.management._append_audit
        def append(root, record):
            if record["status"] == "SUCCEEDED":
                raise self.management.ManagementAuditError("synthetic final audit failure")
            return original(root, record)
        with patch.object(self.management, "_append_audit", side_effect=append):
            with self.assertRaises(self.management.ManagementAuditError):
                with self.operation():
                    self.write()
        self.assertTrue(self.target.exists(), "completion audit failure does not imply rollback")
        self.assertNotIn("SUCCEEDED", [r["status"] for r in self.records()])
        self.assertEqual(self.management._ACTIVE, {})

    def test_interrupt_after_write_marks_possible_change(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.operation():
                self.write()
                raise KeyboardInterrupt
        self.assertTrue(self.target.exists())
        self.assertEqual(self.records()[-1]["status"], "CANCELLED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])
        self.assertEqual(self.management._ACTIVE, {})

    def test_scopes_reject_forged_expired_mismatched_and_reused_leases(self):
        scope = self.management.require_scope
        for forged in (object(), {}, None):
            with self.assertRaises(PermissionError):
                scope(forged, self.root, {"SNAPSHOT_CREATE"}, self.targets)
        with self.operation() as lease:
            with self.assertRaises(PermissionError):
                scope(lease, self.root, {"SNAPSHOT_RESTORE"}, self.targets)
            with self.assertRaises(PermissionError):
                scope(lease, self.root, {"SNAPSHOT_CREATE"}, {"destination": self.root / "other"})
            scope(lease, self.root, {"SNAPSHOT_CREATE"}, self.targets)
            with self.assertRaises(PermissionError):
                scope(lease, self.root, {"SNAPSHOT_CREATE"}, self.targets)
        with self.assertRaises(PermissionError):
            scope(lease, self.root, {"SNAPSHOT_CREATE"}, self.targets)

    def test_link_target_and_spoofed_identity_fail_before_confirmation(self):
        self.write()
        link = self.root / "link.txt"
        try:
            link.symlink_to(self.target)
        except OSError:
            self.skipTest("platform cannot create an unprivileged symlink")
        with self.assertRaises(PermissionError):
            self.management._targets(self.root, {"source": str(link)})
        with patch.dict(sys.modules, {"xiyin_identity": SimpleNamespace(__file__=str(self.root / "impostor.py"))}):
            with self.assertRaises(RuntimeError):
                self.management.verified_operator(self.root)
        self.console.assert_not_called()

    def test_windows_console_uses_devices_and_does_not_consume_stdin(self):
        # Exercise the real console adapter with fake Win32 API calls.
        kernel = SimpleNamespace(**{name: Mock() for name in (
            "CreateFileW", "GetConsoleMode", "FlushConsoleInputBuffer", "WriteConsoleW", "ReadConsoleW", "CloseHandle")})
        kernel.CreateFileW.side_effect = [10, 11]
        def mode(handle, output):
            output._obj.value = 3
            return True
        kernel.GetConsoleMode.side_effect = mode
        kernel.FlushConsoleInputBuffer.return_value = True
        def write(handle, text, length, output, reserved):
            output._obj.value = length
            return True
        kernel.WriteConsoleW.side_effect = write
        def read(handle, buffer, limit, output, reserved):
            buffer.value = "CONFIRM SNAPSHOT_CREATE abc123\r\n"
            output._obj.value = len(buffer.value)
            return True
        kernel.ReadConsoleW.side_effect = read
        kernel.CloseHandle.return_value = True
        # The patched module function has an independent original in its source.
        spec = importlib.util.spec_from_file_location("_management_console_test", self.root / "xiyin_management.py")
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        with patch.object(original.os, "name", "nt"), patch.object(ctypes, "WinDLL", return_value=kernel, create=True), patch("sys.stdin", io.StringIO("malicious piped yes\n")) as stdin:
            self.assertEqual(original._console_answer("synthetic prompt"), "CONFIRM SNAPSHOT_CREATE abc123")
            self.assertEqual(stdin.read(), "malicious piped yes\n")
        self.assertEqual([call.args[0] for call in kernel.CreateFileW.call_args_list], ["CONIN$", "CONOUT$"])
        self.assertEqual(kernel.CloseHandle.call_count, 2)


if __name__ == "__main__":
    unittest.main()
