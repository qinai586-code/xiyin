"""CLI and role gates using temporary roots and simulated Windows identities.

These tests never read the real token, change ACLs, contact a model, or initialize
the repository's own persistent data directory.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from xiyin_runtime import authorization, cli, config
from xiyin_runtime.provider import ProviderError
from xiyin_runtime.runtime import TurnEvent


PATHS_SOURCE = Path(__file__).resolve().parents[1] / "xiyin_paths.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-cli-test-"))).resolve()
        self.root = self.tmp / "code root"
        (self.root / "config").mkdir(parents=True)
        (self.root / ".xiyin_root").write_text("xiyin-portable-root-v1.1\n", encoding="utf-8")
        (self.root / "config" / "paths.toml").write_text(
            '[paths]\ndata="L1_MEMORY"\ncharacter_seed="config/seed.json"\n', encoding="utf-8")
        (self.root / "config" / "runtime.toml").write_text(
            '[inference]\nendpoint="http://127.0.0.1:8080/v1/chat/completions"\nmodel="xiyin"\n', encoding="utf-8")
        shutil.copyfile(PATHS_SOURCE, self.root / "xiyin_paths.py")
        spec = importlib.util.spec_from_file_location(
            f"xiyin_cli_paths_{uuid.uuid4().hex}", self.root / "xiyin_paths.py")
        self.paths = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.paths)
        stack.enter_context(patch.dict(os.environ))
        os.environ.pop(self.paths.DATA_ENV, None)
        stack.enter_context(patch.object(cli, "xiyin_paths", self.paths))
        stack.enter_context(patch.object(config, "xiyin_paths", self.paths))
        self.authorize = stack.enter_context(patch.object(cli, "authorize_runtime"))
        # Persona rendering is tested elsewhere; this suite exercises the CLI.
        stack.enter_context(patch.object(cli, "load_persona", return_value=SimpleNamespace(name="栖音")))
        stack.enter_context(patch.object(cli.importlib.metadata, "version", return_value="test-installed"))
        self.provider = stack.enter_context(patch.object(cli, "LocalModelClient", side_effect=AssertionError("unexpected model I/O")))
        self.open_runtime = stack.enter_context(patch.object(cli.FoundationRuntime, "open", side_effect=AssertionError("unexpected runtime open")))
        self.data = self.root / "L1_MEMORY"

    def snapshot(self):
        return {
            path.relative_to(self.tmp).as_posix(): None if path.is_dir() else path.read_bytes()
            for path in self.tmp.rglob("*")
        }

    def mark_data(self, root=None, identity="existing-identity"):
        root = root or self.data
        root.mkdir(parents=True, exist_ok=True)
        marker = root / self.paths.DATA_MARKER
        marker.write_text(f"{self.paths.DATA_MARKER_HEADER}\nid={identity}\n", encoding="utf-8")
        return marker

    @staticmethod
    def run_cli(*args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def test_doctor_defaults_to_offline_and_does_not_create_missing_data(self):
        before = self.snapshot()
        code, output, errors = self.run_cli("doctor")
        report = json.loads(output)
        self.assertEqual(code, 2)
        self.assertEqual(errors, "")
        self.assertTrue(report["checks"]["configuration"]["ok"])
        self.assertFalse(report["checks"]["data"]["ok"])
        self.assertEqual(report["checks"]["model"]["detail"], "not_probed")
        self.assertFalse(report["ready_for_text_runtime"])
        self.assertEqual(report["audio_and_gpu_performance"], "not_measured")
        self.assertFalse(self.data.exists())
        self.assertEqual(self.snapshot(), before)
        self.provider.assert_not_called()
        self.open_runtime.assert_not_called()

    def test_doctor_does_not_turn_existing_marked_data_into_model_readiness(self):
        self.mark_data()
        (self.data / "retained.txt").write_text("existing", encoding="utf-8")
        before = self.snapshot()
        code, output, _ = self.run_cli("doctor")
        report = json.loads(output)
        self.assertEqual(code, 2)
        self.assertTrue(report["checks"]["data"]["ok"])
        self.assertIsNone(report["checks"]["model"]["ok"])
        self.assertEqual(self.snapshot(), before)
        self.provider.assert_not_called()

    def test_doctor_requested_probe_requires_authorization(self):
        self.mark_data()
        self.authorize.side_effect = authorization.AuthorizationError("not registered")
        before = self.snapshot()
        code, output, _ = self.run_cli("doctor", "--probe-model")
        self.assertEqual(code, 2)
        report = json.loads(output)
        self.assertFalse(report["checks"]["windows_identity"]["ok"])
        self.assertEqual(report["checks"]["model"]["detail"], "not_probed")
        self.provider.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_init_data_is_explicit_and_creates_only_the_identity_marker(self):
        self.assertFalse(self.data.exists())
        code, output, errors = self.run_cli("init-data")
        result = json.loads(output)
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(result["created"])
        self.assertEqual(result["data_root"], str(self.data))
        self.assertEqual(result["data_root_id"], self.paths.data_root_id())
        self.assertEqual([p.name for p in self.data.iterdir()], [self.paths.DATA_MARKER])
        self.authorize.assert_called_once_with()
        self.provider.assert_not_called()
        self.open_runtime.assert_not_called()

    def test_init_data_cannot_bypass_authorization(self):
        self.authorize.side_effect = authorization.AuthorizationError("runtime SID required")
        before = self.snapshot()
        code, output, errors = self.run_cli("init-data")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("runtime SID required", errors)
        self.assertEqual(self.snapshot(), before)

    def test_init_data_preserves_existing_marker_and_records(self):
        marker = self.mark_data(identity="stable-before-restart")
        record = self.data / "retained.txt"
        record.write_text("do not overwrite", encoding="utf-8")
        before = self.snapshot()
        code, output, errors = self.run_cli("init-data")
        self.assertEqual((code, errors), (0, ""))
        result = json.loads(output)
        self.assertFalse(result["created"])
        self.assertEqual(result["data_root_id"], "stable-before-restart")
        self.assertEqual(marker.read_bytes(), before[marker.relative_to(self.tmp).as_posix()])
        self.assertEqual(self.snapshot(), before)

    def test_init_data_rejects_nonempty_unmarked_directory_without_adoption(self):
        self.data.mkdir()
        (self.data / "legacy.txt").write_text("retained legacy evidence", encoding="utf-8")
        before = self.snapshot()
        code, output, errors = self.run_cli("init-data")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("--adopt-existing", errors)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_adoption_preserves_records_without_importing_them(self):
        self.data.mkdir()
        legacy = self.data / "legacy.txt"
        legacy.write_bytes(b"do not reinterpret as a lived memory")
        original = legacy.read_bytes()
        code, output, errors = self.run_cli("init-data", "--adopt-existing")
        self.assertEqual((code, errors), (0, ""))
        self.assertTrue(json.loads(output)["created"])
        self.assertEqual(legacy.read_bytes(), original)
        self.assertEqual({p.name for p in self.data.iterdir()}, {self.paths.DATA_MARKER, "legacy.txt"})

    def test_invalid_marker_is_never_replaced_even_with_adoption(self):
        self.data.mkdir()
        marker = self.data / self.paths.DATA_MARKER
        marker.write_bytes(b"broken marker that must survive")
        before = self.snapshot()
        code, output, errors = self.run_cli("init-data", "--adopt-existing")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertTrue(errors)
        self.assertEqual(self.snapshot(), before)

    def test_external_empty_data_root_is_initialized_without_creating_default(self):
        external = self.tmp / "separate data root"
        external.mkdir()
        os.environ[self.paths.DATA_ENV] = str(external)
        code, output, errors = self.run_cli("init-data")
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(json.loads(output)["data_root"], str(external))
        self.assertFalse(self.data.exists())
        self.assertTrue((external / self.paths.DATA_MARKER).is_file())

    def test_invalid_environment_override_never_falls_back_to_marked_default(self):
        self.mark_data(identity="must-not-use-this-fallback")
        missing = self.tmp / "missing external root"
        before = self.snapshot()
        for value in ("", "relative/root", str(missing), str(self.root / ".xiyin_root")):
            with self.subTest(value=value):
                os.environ[self.paths.DATA_ENV] = value
                code, output, _ = self.run_cli("doctor")
                self.assertEqual(code, 2)
                self.assertFalse(json.loads(output)["checks"]["data"]["ok"])
                code, output, errors = self.run_cli("init-data")
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertTrue(errors)
                self.assertEqual(self.snapshot(), before)
        self.assertFalse(missing.exists())

    def test_ask_open_failure_produces_system_error_and_no_character_reply(self):
        self.open_runtime.side_effect = authorization.AuthorizationError("unregistered SID")
        before = self.snapshot()
        code, output, errors = self.run_cli("ask", "hello")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("系统：AuthorizationError: unregistered SID", errors)
        self.assertEqual(self.snapshot(), before)
        self.provider.assert_not_called()

    def test_ask_stream_exception_has_no_fallback_and_closes_runtime(self):
        class FailedRuntime:
            closed = False

            async def stream_turn(self, text, **kwargs):
                raise ProviderError("model unavailable")
                yield  # Make this an async generator without producing text.

            def close(self):
                self.closed = True

        runtime = FailedRuntime()
        self.open_runtime.side_effect = None
        self.open_runtime.return_value = runtime
        with patch.object(cli.signal, "getsignal"), patch.object(cli.signal, "signal"):
            code, output, errors = self.run_cli("ask", "hello")
        self.assertEqual(code, 1)
        self.assertEqual(output.strip(), "")
        self.assertIn("model unavailable", errors)
        self.assertTrue(runtime.closed)

    def test_ask_partial_output_then_error_is_failure_not_invented_completion(self):
        class PartialRuntime:
            closed = False

            async def stream_turn(self, text, **kwargs):
                yield TurnEvent("text_delta", "request", "owner", text="已有片段")
                yield TurnEvent("error", "request", "owner", detail="model connection lost")

            def close(self):
                self.closed = True

        runtime = PartialRuntime()
        self.open_runtime.side_effect = None
        self.open_runtime.return_value = runtime
        with patch.object(cli.signal, "getsignal"), patch.object(cli.signal, "signal"):
            code, output, errors = self.run_cli("ask", "hello")
        self.assertEqual(code, 1)
        self.assertEqual(output.strip(), "已有片段")
        self.assertIn("model connection lost", errors)
        self.assertTrue(runtime.closed)


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-auth-test-"))).resolve()
        self.root = self.tmp / "registered"
        self.root.mkdir()
        self.runtime_sid = "S-1-5-21-100-200-300-1001"
        self.reviewer_sid = "S-1-5-21-100-200-300-1002"
        self.sid = self.runtime_sid
        self.policy = {
            "runtime_sids": [self.runtime_sid], "reviewer_sids": [self.reviewer_sid],
            "allowed_cwd_roots": [str(self.root)],
        }
        # Replace this module's OS reference, not the process-wide os.name:
        # pathlib must keep using native paths on both Mac and Windows CI.
        stack.enter_context(patch.object(authorization, "os", SimpleNamespace(name="nt")))
        self.project_root = stack.enter_context(patch.object(authorization.xiyin_paths, "project_root", return_value=self.root))
        self.load_policy = stack.enter_context(patch.object(authorization.xiyin_identity, "load_policy", return_value=self.policy))
        self.current_role = stack.enter_context(patch.object(
            authorization.xiyin_identity, "current_role",
            side_effect=lambda policy: (authorization.xiyin_identity.role_for_sid(policy, self.sid), self.sid)))
        self.token = stack.enter_context(patch.object(
            authorization.xiyin_identity, "current_token_sid", side_effect=AssertionError("real token access forbidden")))
        self.cwd = stack.enter_context(patch.object(authorization.Path, "cwd", return_value=self.root))
        self.disk = stack.enter_context(patch.object(
            authorization.shutil, "disk_usage", return_value=SimpleNamespace(free=2 * 1024**3)))

    def test_only_registered_runtime_role_at_registered_cwd_is_accepted(self):
        self.assertIsNone(authorization.authorize_runtime())
        self.load_policy.assert_called_once_with(self.root)
        self.current_role.assert_called_once_with(self.policy)
        self.token.assert_not_called()

    def test_registered_cwd_descendant_is_accepted(self):
        child = self.root / "nested"
        child.mkdir()
        self.cwd.return_value = child
        self.assertIsNone(authorization.authorize_runtime())

    def test_non_windows_is_rejected_before_policy_or_token_access(self):
        with patch.object(authorization, "os", SimpleNamespace(name="posix")):
            with self.assertRaisesRegex(authorization.AuthorizationError, "Windows"):
                authorization.authorize_runtime()
        self.load_policy.assert_not_called()
        self.current_role.assert_not_called()
        self.disk.assert_not_called()

    def test_reviewer_and_unknown_sids_cannot_act_as_runtime(self):
        for sid in (self.reviewer_sid, "S-1-5-21-100-200-300-9999"):
            with self.subTest(sid=sid):
                self.sid = sid
                with self.assertRaisesRegex(authorization.AuthorizationError, "runtime identity"):
                    authorization.authorize_runtime()
        self.disk.assert_not_called()
        self.token.assert_not_called()

    def test_outside_and_same_prefix_sibling_cwd_are_rejected(self):
        for folder in (self.tmp / "outside", self.tmp / "registered-but-not-allowed"):
            folder.mkdir()
            self.cwd.return_value = folder
            with self.subTest(folder=folder), self.assertRaisesRegex(authorization.AuthorizationError, "Working directory"):
                authorization.authorize_runtime()
        self.disk.assert_not_called()

    def test_empty_cwd_allowlist_is_not_an_unrestricted_fallback(self):
        self.policy["allowed_cwd_roots"] = []
        with self.assertRaisesRegex(authorization.AuthorizationError, "Working directory"):
            authorization.authorize_runtime()

    def test_policy_load_failure_is_wrapped_and_fails_closed(self):
        self.load_policy.side_effect = ValueError("invalid identity configuration")
        with self.assertRaisesRegex(authorization.AuthorizationError, "invalid identity configuration"):
            authorization.authorize_runtime()
        self.current_role.assert_not_called()
        self.disk.assert_not_called()

    def test_token_resolution_failure_is_not_replaced_by_an_assumed_role(self):
        self.current_role.side_effect = RuntimeError("token unavailable")
        with self.assertRaisesRegex(authorization.AuthorizationError, "token unavailable"):
            authorization.authorize_runtime()
        self.disk.assert_not_called()

    def test_code_root_failure_does_not_fall_back_to_current_directory(self):
        self.project_root.side_effect = ValueError("missing code marker")
        with self.assertRaisesRegex(authorization.AuthorizationError, "missing code marker"):
            authorization.authorize_runtime()
        self.load_policy.assert_not_called()

    def test_disk_budget_and_disk_probe_failure_fail_closed(self):
        self.disk.return_value = SimpleNamespace(free=1024**3 - 1)
        with self.assertRaisesRegex(authorization.AuthorizationError, "1 GiB"):
            authorization.authorize_runtime()
        self.disk.return_value = SimpleNamespace(free=1024**3)
        self.assertIsNone(authorization.authorize_runtime())
        self.disk.side_effect = OSError("volume unavailable")
        with self.assertRaisesRegex(authorization.AuthorizationError, "volume unavailable"):
            authorization.authorize_runtime()


if __name__ == "__main__":
    unittest.main()
