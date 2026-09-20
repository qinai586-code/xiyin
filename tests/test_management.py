"""Management confirmation and operations on synthetic trees only.

Windows tokens and console APIs are explicitly mocked; no test grants authority
to production data or claims to establish a same-user OS security boundary.
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
FILENAME = "1700000000_chat1.txt"


class ManagementTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-management-test-"))).resolve()
        (self.root / "config").mkdir()
        (self.root / "config/paths.toml").write_text('[paths]\ndata="L1_MEMORY"\n', encoding="utf-8")
        (self.root / ".xiyin_root").write_text("test\n", encoding="utf-8")
        (self.root / "L2_CENTRAL").mkdir()
        (self.root / "L2_CENTRAL/hardware_profile.json").write_text(
            '{"memory_policy":{"snapshot_required_before_restore":true}}', encoding="utf-8")
        self.admin = self.root / "L5_SAFE/ADMIN_TOOLS"
        self.admin.mkdir(parents=True)
        for name in ("xiyin_paths.py", "xiyin_management.py"):
            shutil.copyfile(SOURCE / name, self.root / name)
        for name in ("snapshot_tool.py", "rollback_tool.py", "memory_review_tool.py", "review_cli.py"):
            shutil.copyfile(SOURCE / "L5_SAFE/ADMIN_TOOLS" / name, self.admin / name)
        stack.enter_context(patch.dict(sys.modules))
        for name in ("xiyin_paths", "xiyin_identity", "xiyin_management", "snapshot_tool",
                     "rollback_tool", "memory_review_tool", "review_cli"):
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
        self.snapshot = self.load("snapshot_tool", self.admin / "snapshot_tool.py")
        self.rollback = self.load("rollback_tool", self.admin / "rollback_tool.py")
        self.memory = self.load("memory_review_tool", self.admin / "memory_review_tool.py")
        self.cli = self.load("review_cli", self.admin / "review_cli.py")
        self.console = stack.enter_context(patch.object(self.management, "_console_answer", side_effect=self.confirm))

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

    def pending(self):
        path = self.root / "L1_MEMORY/wait_check" / FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic pending memory", encoding="utf-8")
        return path

    def records(self):
        path = self.root / "L5_SAFE/review_audit/management_actions.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_single_user_and_legacy_identity_checks_cannot_be_supplied_by_operator(self):
        for module in (self.memory, self.snapshot, self.rollback, self.cli):
            with self.subTest(module=module.__name__):
                self.assertEqual(module._require_admin_user(), "Windows user S-1-5-21-1")
        self.mode = "separate_accounts"
        with self.assertRaises(PermissionError):
            self.memory._require_admin_user()
        self.role = "reviewer"
        self.assertEqual(self.memory._require_admin_user(), "Windows user S-1-5-21-1")
        with self.assertRaises(PermissionError):
            self.memory._validate_operator("SJ_Admin")
        self.role = "unknown"
        with self.assertRaises(PermissionError):
            self.memory._validate_operator("Windows user S-1-5-21-1")
        self.identity.current_role.side_effect = RuntimeError("synthetic token failure")
        with self.assertRaises(RuntimeError):
            self.snapshot._require_admin_user()

    def test_approve_requires_one_specific_confirmation_and_records_real_result(self):
        src = self.pending()
        dst = Path(self.memory.approve_memory(FILENAME))
        self.assertEqual(dst.read_text(encoding="utf-8"), "synthetic pending memory")
        self.assertFalse(src.exists())
        self.console.assert_called_once()
        prompt = self.console.call_args.args[0]
        self.assertIn("MEMORY_APPROVE", prompt)
        displayed, _ = json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])
        self.assertEqual(displayed["action"], "MEMORY_APPROVE")
        self.assertEqual({key: Path(value) for key, value in displayed["targets"].items()},
                         {"source": src, "destination": dst})
        records = self.records()
        self.assertEqual([record["status"] for record in records], ["REQUESTED", "CONFIRMED", "SUCCEEDED"])
        self.assertEqual(len({record["request_id"] for record in records}), 1)
        self.assertEqual({key: Path(value) for key, value in records[-1]["targets"].items()},
                         {"source": src, "destination": dst})

    def test_reject_has_a_distinct_action_reason_and_one_confirmation(self):
        src = self.pending()
        dst = Path(self.memory.reject_memory(FILENAME, "synthetic rejection"))
        self.assertFalse(src.exists())
        self.assertTrue(dst.is_file())
        self.assertEqual(self.records()[-1]["action"], "MEMORY_REJECT")
        self.assertEqual(self.records()[-1]["detail"]["reason"], "synthetic rejection")
        self.console.assert_called_once()

    def test_declined_confirmation_keeps_data_and_records_cancellation(self):
        src = self.pending()
        self.console.side_effect = lambda prompt: "yes"
        with self.assertRaises(self.management.ManagementCancelled):
            self.memory.approve_memory(FILENAME)
        self.assertTrue(src.exists())
        self.assertFalse(Path(self.memory.PASSED_DIR).exists())
        self.assertEqual([r["status"] for r in self.records()], ["REQUESTED", "CANCELLED"])
        self.assertFalse(self.records()[-1]["data_may_have_changed"])

    def test_missing_console_stops_before_data_changes_even_with_environment_and_stdin(self):
        src = self.pending()
        self.console.side_effect = PermissionError("synthetic no console")
        with patch.dict("os.environ", {"XIYIN_APPROVED": "1", "USERNAME": "SJ_Admin"}), patch("sys.stdin", io.StringIO("yes\n")):
            with self.assertRaises(PermissionError):
                self.memory.approve_memory(FILENAME)
        self.assertTrue(src.exists())
        self.assertFalse(Path(self.memory.PASSED_DIR).exists())
        self.assertEqual(self.records()[-1]["status"], "CONFIRMATION_FAILED")

    def test_cli_does_not_accept_yes_bypass(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.cli.main(["approve", FILENAME, "--yes"])
        self.assertEqual(caught.exception.code, 2)
        self.console.assert_not_called()

    def test_request_or_confirmation_audit_failure_prevents_data_change(self):
        src = self.pending()
        original = self.management._append_audit
        for failed_status in ("REQUESTED", "CONFIRMED"):
            with self.subTest(failed_status=failed_status):
                def append(root, record):
                    if record["status"] == failed_status:
                        raise self.management.ManagementAuditError("synthetic audit failure")
                    return original(root, record)
                with patch.object(self.management, "_append_audit", side_effect=append):
                    with self.assertRaises(self.management.ManagementAuditError):
                        self.memory.approve_memory(FILENAME)
                self.assertTrue(src.exists())
                self.assertFalse(Path(self.memory.PASSED_DIR).exists())

    def test_operation_failure_and_post_write_audit_failure_do_not_report_success(self):
        src = self.pending()
        with patch.object(self.memory.shutil, "copy2", side_effect=OSError("synthetic copy failure")):
            with self.assertRaises(OSError):
                self.memory.approve_memory(FILENAME)
        self.assertTrue(src.exists())
        self.assertEqual(self.records()[-1]["status"], "FAILED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])
        original = self.management._append_audit
        def append(root, record):
            if record["status"] == "SUCCEEDED":
                raise self.management.ManagementAuditError("synthetic final audit failure")
            return original(root, record)
        with patch.object(self.management, "_append_audit", side_effect=append):
            with self.assertRaises(self.management.ManagementAuditError):
                self.memory.approve_memory(FILENAME)
        self.assertFalse(src.exists(), "a failed completion audit must not imply rollback")
        self.assertTrue((Path(self.memory.PASSED_DIR) / FILENAME).exists())
        self.assertEqual(self.management._ACTIVE, {})

    def test_snapshot_is_confirmed_and_read_only_list_does_not_initialize_dirs(self):
        self.assertEqual(self.snapshot.list_snapshots(), [])
        self.assertEqual(self.memory.list_pending_files(), [])
        self.assertFalse((self.root / "L1_MEMORY").exists())
        self.assertFalse((self.root / "L5_SAFE/G1_SNAPSHOT").exists())
        self.console.assert_not_called()
        src = self.pending()
        snap = Path(self.snapshot.create_memory_snapshot())
        self.assertEqual((snap / "wait_check" / FILENAME).read_bytes(), src.read_bytes())
        self.console.assert_called_once()
        self.assertEqual(self.records()[-1]["action"], "SNAPSHOT_CREATE")

    def test_interrupt_after_writes_marks_possible_data_change(self):
        src = self.pending()
        def interrupted_copy(source, destination):
            Path(destination).write_text("partial synthetic copy", encoding="utf-8")
            raise KeyboardInterrupt
        with patch.object(self.memory.shutil, "copy2", side_effect=interrupted_copy):
            with self.assertRaises(KeyboardInterrupt):
                self.memory.approve_memory(FILENAME)
        self.assertTrue(src.exists())
        self.assertTrue((Path(self.memory.PASSED_DIR) / FILENAME).exists())
        self.assertEqual(self.records()[-1]["status"], "CANCELLED")
        self.assertTrue(self.records()[-1]["data_may_have_changed"])
        self.assertEqual(self.management._ACTIVE, {})

    def test_restore_and_protective_snapshot_share_one_scope_bound_confirmation(self):
        current = self.pending()
        source = Path(self.rollback.SNAPSHOT_ROOT) / "20200101_010101"
        for area in ("wait_check", "passed"):
            (source / area).mkdir(parents=True)
        (source / "passed" / FILENAME).write_text("restored synthetic memory", encoding="utf-8")
        with patch.object(self.rollback, "_stamp", return_value="20200102_010101"):
            self.assertTrue(self.rollback.restore_memory_snapshot("20200101_010101"))
        self.console.assert_called_once()
        self.assertFalse(current.exists())
        self.assertEqual((Path(self.memory.PASSED_DIR) / FILENAME).read_text(encoding="utf-8"), "restored synthetic memory")
        protective = Path(self.rollback.SNAPSHOT_ROOT) / "20200102_010101/wait_check" / FILENAME
        self.assertEqual(protective.read_text(encoding="utf-8"), "synthetic pending memory")
        self.assertEqual([r["status"] for r in self.records()], ["REQUESTED", "CONFIRMED", "SUCCEEDED"])
        self.assertEqual(self.records()[-1]["action"], "SNAPSHOT_RESTORE")

    def test_private_operations_reject_forged_expired_mismatched_and_reused_leases(self):
        operator = self.management.verified_operator(self.root)
        with self.assertRaises(PermissionError):
            self.snapshot._create_confirmed_snapshot(object(), operator, "20200101_010101")
        targets = {**self.snapshot.TARGET_DIRS, "created_snapshot": str(Path(self.snapshot.SNAPSHOT_ROOT) / "20200101_010101")}
        with self.management.management_action(self.root, "SNAPSHOT_CREATE", targets) as lease:
            with self.assertRaises(PermissionError):
                self.snapshot._create_confirmed_snapshot(lease, operator, "20200102_010101")
            self.snapshot._create_confirmed_snapshot(lease, operator, "20200101_010101")
            with self.assertRaises(PermissionError):
                self.snapshot._create_confirmed_snapshot(lease, operator, "20200101_010101")
            with self.assertRaises(PermissionError):
                self.rollback._restore_confirmed_snapshot(lease, operator, "20200101_010101", None)
        with self.assertRaises(PermissionError):
            self.snapshot._create_confirmed_snapshot(lease, operator, "20200101_010101")

    def test_link_target_and_spoofed_management_module_fail_before_confirmation(self):
        src = self.pending()
        link = src.parent / "1700000001_chat1.txt"
        try:
            link.symlink_to(src)
        except OSError:
            self.skipTest("platform cannot create an unprivileged symlink")
        with self.assertRaises(PermissionError):
            self.management._targets(self.root, {"source": str(link)})
        with patch.dict(sys.modules, {"xiyin_management": SimpleNamespace(__file__=str(self.root / "impostor.py"))}):
            with self.assertRaises(RuntimeError):
                self.memory._management()
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
