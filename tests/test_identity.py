"""Deployment-policy regressions plus a Windows-only real-token runtime smoke test.

All data is temporary. No models, real memories, accounts or ACLs are modified.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import xiyin_identity as identity


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SID = "S-1-5-21-100-200-300-1001"
REVIEWER_SID = "S-1-5-21-100-200-300-1002"


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="xiyin-policy-"))
        self.tmp = Path(temporary).resolve()
        self.root = self.tmp / "code with spaces"
        (self.root / "config").mkdir(parents=True)
        (self.root / "L2_CENTRAL").mkdir()
        self.config = self.root / "config" / "deployment.toml"
        self.write_single()

    def write_single(self, cwd="L2_CENTRAL", extra=""):
        self.config.write_text(
            '[identity]\nmode = "single_user"\n' + extra
            + '\n[runtime]\nallowed_cwd_roots = [' + json.dumps(cwd) + ']\n', encoding="utf-8")

    def write_legacy(self, runtime=RUNTIME_SID, reviewer=REVIEWER_SID, mode=""):
        self.config.write_text(
            '[identity]\n' + mode
            + f'runtime_sids = ["{runtime}"]\nreviewer_sids = ["{reviewer}"]\n'
            + f'[identity.review_display]\n"{reviewer}" = "Local reviewer"\n'
            + '[runtime]\nallowed_cwd_roots = [' + json.dumps(str(self.root / "L2_CENTRAL")) + ']\n',
            encoding="utf-8")

    def test_single_user_has_no_machine_or_display_name_binding(self):
        policy = identity.load_policy(self.root)
        self.assertEqual(policy["mode"], "single_user")
        self.assertEqual(policy["allowed_cwd_roots"], [str(self.root / "L2_CENTRAL")])
        for sid in (RUNTIME_SID, REVIEWER_SID, "S-1-12-1-10-20-30-40"):
            with self.subTest(sid=sid), patch.object(identity, "current_token_sid", return_value=sid):
                with patch.dict(os.environ, {"USERNAME": "fake-name", "XIYIN_ROLE": "reviewer", "XIYIN_SID": "fake"}):
                    self.assertEqual(identity.current_role(policy), ("runtime", sid))
                    self.assertEqual(identity.reviewer_display_name(policy, sid), "Windows user " + sid)

    def test_token_failure_and_malformed_token_never_fall_back(self):
        policy = identity.load_policy(self.root)
        for value in ("", "SJ_Run", "S-1-05-12", "S-1-5-4294967296", None):
            with self.subTest(value=value), patch.object(identity, "current_token_sid", return_value=value):
                with self.assertRaises(identity.TokenReadError):
                    identity.current_role(policy)
        with patch.object(identity, "current_token_sid", side_effect=identity.TokenReadError("token unavailable")):
            with self.assertRaisesRegex(identity.TokenReadError, "token unavailable"):
                identity.current_role(policy)

    def test_legacy_mode_is_explicitly_compatible_and_disjoint(self):
        for mode in ("", 'mode = "separate_accounts"\n'):
            self.write_legacy(mode=mode)
            policy = identity.load_policy(self.root)
            self.assertEqual(policy["mode"], "separate_accounts")
            self.assertEqual(identity.role_for_sid(policy, RUNTIME_SID), "runtime")
            self.assertEqual(identity.role_for_sid(policy, REVIEWER_SID), "reviewer")
            self.assertIsNone(identity.role_for_sid(policy, "S-1-5-21-99-99-99-99"))
        self.write_legacy(reviewer=RUNTIME_SID)
        with self.assertRaisesRegex(identity.IdentityConfigError, "overlap"):
            identity.load_policy(self.root)

    def test_policy_never_silently_selects_single_user(self):
        invalid = (
            '[identity]\n[runtime]\nallowed_cwd_roots=["L2_CENTRAL"]',
            '[identity]\nmode="typo"',
            '[identity]\nmode="single_user"\nreviewer_sids=[]',
            '[identity]\nmode="single_user"\n[runtime]\nallowed_cwd_roots=[]',
            '[identity]\nmode="single_user"\n[runtime]\nallowed_cwd_roots=["L2_CENTRAL", "L2_CENTRAL"]',
            '[identity]\nmode="single_user"\n[unknown]\nx=1',
            'this is not toml',
        )
        for text in invalid:
            self.config.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(identity.IdentityConfigError):
                identity.load_policy(self.root)
        self.config.unlink()
        with patch.dict(os.environ, {"XIYIN_DEPLOYMENT": str(ROOT / "config/deployment.toml")}):
            with self.assertRaisesRegex(identity.IdentityConfigError, "missing"):
                identity.load_policy(self.root)

    def test_single_user_directories_must_be_portable_existing_and_contained(self):
        for value in ("", "..", "../outside", str(self.tmp), "C:/L0_RUNTIME", "C:relative",
                      "//server/share", "L2_CENTRAL/../config", "L2_CENTRAL//child", "missing", "CON"):
            self.write_single(cwd=value)
            with self.subTest(value=value), self.assertRaises(identity.IdentityConfigError):
                identity.load_policy(self.root)

    def test_single_user_code_root_is_an_explicit_portable_cwd(self):
        self.write_single(cwd=".")
        policy = identity.load_policy(self.root)
        identity.validate_runtime_cwd(policy, self.root)
        with self.assertRaises(identity.IdentityConfigError):
            identity.validate_runtime_cwd(policy, self.tmp)

    @staticmethod
    def link_directory(link, target):
        if os.name == "nt":
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                           check=True, capture_output=True)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_config_parent_and_runtime_links_are_rejected(self):
        real_config = self.tmp / "real-config"
        shutil.move(self.root / "config", real_config)
        self.link_directory(self.root / "config", real_config)
        with self.assertRaises(identity.IdentityConfigError):
            identity.load_policy(self.root)
        (self.root / "config").rmdir() if os.name == "nt" else (self.root / "config").unlink()
        shutil.move(real_config, self.root / "config")
        inside = self.root / "actual"
        outside = self.tmp / "outside"
        inside.mkdir()
        outside.mkdir()
        for name, target in (("alias", inside), ("escape", outside)):
            self.link_directory(self.root / name, target)
            self.write_single(cwd=name)
            with self.subTest(name=name), self.assertRaises(identity.IdentityConfigError):
                identity.load_policy(self.root)

    def test_cwd_existing_descendant_and_same_prefix_sibling(self):
        policy = identity.load_policy(self.root)
        child = self.root / "L2_CENTRAL" / "child"
        child.mkdir()
        self.assertEqual(identity.validate_runtime_cwd(policy, child), child)
        sibling = self.root / "L2_CENTRAL-not-allowed"
        sibling.mkdir()
        for cwd in (sibling, self.root, child / "missing"):
            with self.subTest(cwd=cwd), self.assertRaises(identity.IdentityConfigError):
                identity.validate_runtime_cwd(policy, cwd)
        policy["allowed_cwd_roots"] = []
        with self.assertRaises(identity.IdentityConfigError):
            identity.validate_runtime_cwd(policy, child)


@unittest.skipUnless(os.name == "nt", "Requires an actual Windows process token")
class WindowsSingleUserTests(unittest.TestCase):
    def test_real_token_and_runtime_memory_restart_without_fixed_account(self):
        # Run a child with the real code/policy/token; no authorization mocks or
        # model requests. Only XIYIN_DATA_ROOT points to an isolated empty dir.
        with tempfile.TemporaryDirectory(prefix="xiyin real account ") as temporary:
            data = Path(temporary).resolve()
            env = dict(os.environ, XIYIN_DATA_ROOT=str(data), PYTHONUTF8="1",
                       USERNAME="not-an-authentication-source", XIYIN_ROLE="reviewer")
            script = '''
import sys
sys.path.insert(0, sys.argv[1])
import json
from pathlib import Path
import xiyin_identity
from xiyin_runtime.cli import initialize_data
from xiyin_runtime.runtime import FoundationRuntime
root = Path(sys.argv[1])
policy = xiyin_identity.load_policy(root)
role, sid = xiyin_identity.current_role(policy)
assert policy['mode'] == 'single_user' and role == 'runtime'
assert initialize_data()['created']
runtime = FoundationRuntime.open()
try:
    memory = runtime.remember('account smoke marker', kind='preference', subject='owner')
finally:
    runtime.close()
runtime = FoundationRuntime.open()
try:
    assert any(m['id'] == memory and m['statement'] == 'account smoke marker'
               for m in runtime.store.memories(scope='private'))
finally:
    runtime.close()
print(json.dumps({'role':role, 'sid':sid, 'opened_twice':True, 'model_requests':0}))
'''
            completed = subprocess.run([sys.executable, "-c", script, str(ROOT)],
                                       cwd=ROOT / "L2_CENTRAL", env=env,
                                       capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(completed.stdout)
            sid_output = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                                        check=True, capture_output=True, text=True).stdout
            self.assertIn(report["sid"], sid_output)
            self.assertTrue(report["opened_twice"])
            self.assertEqual(report["model_requests"], 0)
            self.assertTrue((data / "experience.sqlite3").is_file())

    def test_legacy_c1_entry_uses_same_single_user_policy_by_absolute_path(self):
        script = ROOT / "L2_CENTRAL/C1_Auth/c1_gatekeeper.py"
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT / "L2_CENTRAL",
                                env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"C1_SUCCESS", result.stdout)


if __name__ == "__main__":
    unittest.main()
