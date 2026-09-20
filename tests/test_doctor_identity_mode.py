"""Read-only doctor reporting with simulated authorization, never a model run."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import xiyin_identity
from xiyin_runtime import cli


class DoctorIdentityModeTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(cli, "load_settings", return_value=SimpleNamespace(persona_path="unused")))
        stack.enter_context(patch.object(cli, "load_persona", return_value=SimpleNamespace(name="栖音")))
        stack.enter_context(patch.object(cli.xiyin_paths, "project_root", return_value="synthetic-code-root"))
        stack.enter_context(patch.object(cli.xiyin_paths, "data_root", return_value="synthetic-data-root"))
        stack.enter_context(patch.object(cli.xiyin_paths, "data_root_id", return_value="synthetic-data-id"))
        stack.enter_context(patch.object(cli.importlib.metadata, "version", return_value="test-installed"))
        self.policy = stack.enter_context(patch.object(xiyin_identity, "load_policy", return_value={"mode": "single_user"}))
        self.authorize = stack.enter_context(patch.object(cli, "authorize_runtime"))
        self.token = stack.enter_context(patch.object(xiyin_identity, "current_token_sid", side_effect=AssertionError("doctor must not read a second token")))
        self.provider = stack.enter_context(patch.object(cli, "LocalModelClient", side_effect=AssertionError("unexpected model I/O")))
        self.runtime = stack.enter_context(patch.object(cli.FoundationRuntime, "open", side_effect=AssertionError("unexpected runtime open")))

    def test_single_user_is_reported_without_claiming_an_os_boundary_or_complete_readiness(self):
        report, ready = cli.doctor()
        identity = report["checks"]["windows_identity"]
        self.assertTrue(identity["ok"])
        self.assertEqual(identity["mode"], "single_user")
        self.assertIn("not OS isolation", identity["account_boundary"])
        self.authorize.assert_called_once_with()
        self.token.assert_not_called()
        self.provider.assert_not_called()
        self.runtime.assert_not_called()
        self.assertFalse(ready)
        self.assertEqual(report["runtime_session"], "not_started")
        self.assertEqual(report["filesystem_write_access"], "not_tested_read_only")

    def test_separate_accounts_retains_its_reported_boundary(self):
        self.policy.return_value = {"mode": "separate_accounts"}
        report, _ = cli.doctor()
        self.assertEqual(report["checks"]["windows_identity"]["mode"], "separate_accounts")
        self.assertIn("SID policy", report["checks"]["windows_identity"]["account_boundary"])
        self.authorize.assert_called_once_with()

    def test_policy_failure_and_authorization_failure_never_probe_the_model(self):
        self.policy.side_effect = xiyin_identity.IdentityConfigError("invalid policy")
        report, ready = cli.doctor(probe_model=True)
        self.assertFalse(ready)
        self.assertFalse(report["checks"]["windows_identity"]["ok"])
        self.assertNotIn("mode", report["checks"]["windows_identity"])
        self.authorize.assert_not_called()
        self.policy.side_effect = None
        self.authorize.side_effect = PermissionError("current account cannot access allowed cwd")
        report, ready = cli.doctor(probe_model=True)
        self.assertFalse(ready)
        self.assertEqual(report["checks"]["windows_identity"]["mode"], "single_user")
        self.assertIn("cannot access", report["checks"]["windows_identity"]["detail"])
        self.provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
