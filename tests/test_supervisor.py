"""Actual SQLite backup/restore on temporary marked data; no live user data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xiyin_runtime.experience import ExperienceStore
from xiyin_runtime.lifecycle import RuntimeLease
from xiyin_runtime.supervisor import Supervisor, restore_backup, validate_backup, set_stop_marker
from xiyin_runtime import supervisor as implementation


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="xiyin-maintenance-test-"))
        self.base = Path(self.temporary).resolve()
        self.root = self.base / "data"
        self.root.mkdir()
        self.marker = self.root / ".xiyin_data"
        self.marker.write_text("xiyin-data-root v1\nid=maintenance-test\n", encoding="utf-8")
        self.store = ExperienceStore(self.root / "experience.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.supervisor = Supervisor(self.store, self.root, "maintenance-test", min_free_bytes=0)

    def test_backup_includes_wal_documents_and_restore_preserves_identity(self):
        marker = self.marker.read_bytes()
        self.store.write_document("state", "example", {"value": "before"}, expected_version=0)
        backup = self.base / "backup"
        manifest = self.supervisor.create_backup(backup)
        self.assertEqual(validate_backup(backup, "maintenance-test"), manifest)
        self.store.write_document("state", "example", {"value": "after"}, expected_version=1)
        self.store.close()
        receipt = restore_backup(backup, self.root, "maintenance-test", store=self.store)
        self.assertTrue(receipt["restored"])
        self.assertEqual(self.marker.read_bytes(), marker)
        self.store = ExperienceStore(self.root / "experience.sqlite3")
        self.assertEqual(self.store.read_document("state", "example")["value"], {"value": "before"})
        rollback = ExperienceStore(Path(receipt["rollback_database"]))
        try:
            self.assertEqual(rollback.read_document("state", "example")["value"], {"value": "after"})
        finally:
            rollback.close()

    def test_open_store_and_foreground_lease_block_restore(self):
        backup = self.base / "backup"
        self.supervisor.create_backup(backup)
        with self.assertRaisesRegex(RuntimeError, "Close"):
            restore_backup(backup, self.root, "maintenance-test", store=self.store)
        self.store.close()
        lease = RuntimeLease(self.root / "runtime.lock")
        try:
            with self.assertRaisesRegex(RuntimeError, "Another"):
                restore_backup(backup, self.root, "maintenance-test")
        finally:
            lease.close()

    def test_corruption_root_mismatch_and_resource_budget_refuse_without_replacing(self):
        backup = self.base / "backup"
        self.supervisor.create_backup(backup)
        with self.assertRaises(ValueError):
            validate_backup(backup, "another-root")
        with (backup / "experience.sqlite3").open("ab") as stream:
            stream.write(b"corruption")
        self.store.close()
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_backup(backup, self.root, "maintenance-test")
        self.assertTrue(self.marker.is_file())
        other = Supervisor(self.store, self.root, "maintenance-test", min_free_bytes=0, max_backup_bytes=1)
        with self.assertRaisesRegex(RuntimeError, "budget"):
            other.create_backup(self.base / "too-large")
        self.assertFalse((self.base / "too-large").exists())

    def test_failed_post_replace_validation_rolls_back_database(self):
        self.store.write_document("state", "example", {"value": "before"})
        backup = self.base / "backup"
        self.supervisor.create_backup(backup)
        self.store.write_document("state", "example", {"value": "after"})
        self.store.close()
        target = self.root / "experience.sqlite3"
        original_replace = implementation.os.replace
        original_info = implementation._database_info
        replaced = False
        def replace(source, destination):
            nonlocal replaced
            result = original_replace(source, destination)
            if Path(source).name.startswith("restore-stage-"):
                replaced = True
            return result
        def info(path):
            if replaced and Path(path) == target:
                raise ValueError("synthetic post-replacement validation failure")
            return original_info(path)
        with patch.object(implementation.os, "replace", side_effect=replace), patch.object(implementation, "_database_info", side_effect=info):
            with self.assertRaisesRegex(ValueError, "synthetic"):
                restore_backup(backup, self.root, "maintenance-test")
        self.store = ExperienceStore(target)
        self.assertEqual(self.store.read_document("state", "example")["value"], {"value": "after"})

    def test_independent_stop_marker_remains_available_when_store_is_closed(self):
        self.store.close()
        receipt = self.supervisor.request_stop("foreground user stop")
        self.assertEqual(self.supervisor.stop_requested(), receipt)
        self.assertTrue(self.supervisor.health()["stop_requested"])
        self.supervisor.stop_path.write_text("broken json", encoding="utf-8")
        self.assertTrue(self.supervisor.stop_requested()["invalid"])
        self.supervisor.clear_stop()
        self.assertIsNone(self.supervisor.stop_requested())

    def test_separate_stop_command_needs_no_database_or_runtime_lease(self):
        lease = RuntimeLease(self.root / "runtime.lock")
        try:
            with patch.object(implementation.sqlite3, "connect", side_effect=AssertionError("No database access")):
                stopped = set_stop_marker(self.root, "maintenance-test", reason="separate owner console")
                self.assertEqual(self.supervisor.stop_requested(), stopped)
                resumed = set_stop_marker(self.root, "maintenance-test", stopped=False)
                self.assertFalse(resumed["stopped"])
                self.assertIsNone(self.supervisor.stop_requested())
                with self.assertRaises(ValueError):
                    set_stop_marker(self.root, "wrong-id")
                with self.assertRaises(ValueError):
                    set_stop_marker(self.root, "maintenance-test", stopped="false")
        finally:
            lease.close()

    def test_release_selection_and_rollback_verify_local_artifacts_without_execution(self):
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        for name in ("first", "second"):
            file = artifacts / (name + ".gguf")
            file.write_bytes(("synthetic artifact " + name).encode())
            self.supervisor.register_release({"id": name, "kind": "model", "runtime_api": 1,
                                               "artifact": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
            self.supervisor.adopt_release(name)
        selected = self.supervisor.rollback_release("model")["value"]
        self.assertEqual(selected["release_id"], "first")
        self.assertEqual(selected["activation"], "manifest_selection_only")
        (artifacts / "second.gguf").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.supervisor.adopt_release("second")


if __name__ == "__main__":
    unittest.main()
