"""Archived predecessor code cannot enter the current XIYIN execution path."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "legacy/qinai"


def python_files(directory):
    return sorted(path for path in directory.rglob("*.py") if not path.name.startswith("._"))


class LegacyBoundaryTests(unittest.TestCase):
    def test_formal_tree_keeps_only_identity_and_compatibility_entry(self):
        children = {p.name for p in (ROOT / "L2_CENTRAL").iterdir()
                    if not p.name.startswith(".") and p.name != "__pycache__"}
        self.assertEqual(children, {"C1_Auth", "L2_MAIN"})
        self.assertEqual([p.name for p in python_files(ROOT / "L2_CENTRAL/L2_MAIN")], ["l2_central.py"])
        for name in ("L3", "L4", "L5_SAFE", "module_config.json"):
            self.assertFalse((ROOT / name).exists(), name)
            self.assertTrue((ARCHIVE / name).exists(), name)
        for retained in ("L2_CENTRAL/C7_PLUGINS/manifest.json", "L2_CENTRAL/hardware_profile.json",
                         "L5_SAFE/RULE_DOCS/AGENTS.md", "L5_SAFE/DEPLOY_BACKUP",
                         "L5_SAFE/L5_DATA/EVAL_SETS/QINAI_CORE_16_EVAL.jsonl"):
            self.assertTrue((ARCHIVE / retained).exists(), retained)

    def test_previously_active_modules_refuse_execution_before_side_effects(self):
        entries = [path for path in python_files(ARCHIVE) if "DEPLOY_BACKUP" not in path.parts]
        self.assertGreater(len(entries), 0)
        for path in entries:
            with self.subTest(path=path.relative_to(ARCHIVE)), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, "-B", str(path), "--yes"], cwd=directory,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("archived and disabled; use the current xiyin.py entry", result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_legacy_administrator_import_is_disabled(self):
        path = ARCHIVE / "L5_SAFE/ADMIN_TOOLS/snapshot_tool.py"
        spec = importlib.util.spec_from_file_location("_xiyin_disabled_snapshot_test", path)
        module = importlib.util.module_from_spec(spec)
        with self.assertRaisesRegex(RuntimeError, "archived and disabled"):
            spec.loader.exec_module(module)
        self.assertFalse(hasattr(module, "create_memory_snapshot"))

    def test_compatibility_exports_share_new_runtime_without_opening_it(self):
        # A clean interpreter catches unintended import-time startup and legacy imports.
        source = """
import importlib.util
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('xiyin_l2_compat', root / 'L2_CENTRAL/L2_MAIN/l2_central.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from xiyin_runtime import bridge
assert module.submit_to_chain is bridge.submit_to_chain
assert module.submit_to_chain_result is bridge.submit_to_chain_result
assert bridge._runtime is None
assert not any(name.startswith(('legacy.', 'c2_retrieve', 'c3_filter', 'c4_verify', 'c5_llm_gatekeeper', 'c6_submit')) for name in sys.modules)
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", source, str(ROOT)], cwd=directory,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_active_modules_do_not_import_retired_pipeline(self):
        retired = {"legacy", "c2_retrieve", "c3_filter", "c4_verify", "c5_llm_gatekeeper",
                   "c5_persona_prompt", "p1_hash_generator", "c6_submit", "c7_manifest_guard",
                   "qinai_security_check", "utils_guard", "l3_protocol_contract", "l4_gateway_contract",
                   "memory_review_tool", "review_cli", "rollback_tool", "snapshot_tool",
                   "g2_regression_runner", "qinai_l2_eval_helpers", "qinai_phase3_eval_runner",
                   "g4_executor", "l5_audit_logger"}
        files = list(ROOT.glob("*.py")) + python_files(ROOT / "xiyin_runtime") + python_files(ROOT / "L2_CENTRAL")
        for path in files:
            if path.name.startswith("._"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in modules:
                    self.assertFalse(set(name.split(".")) & retired, f"{path.relative_to(ROOT)} imports {name}")


if __name__ == "__main__":
    unittest.main()
