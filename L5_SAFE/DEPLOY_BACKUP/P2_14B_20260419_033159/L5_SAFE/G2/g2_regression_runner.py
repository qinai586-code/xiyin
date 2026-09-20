# -*- coding: utf-8 -*-

import argparse
import ast
import builtins
import contextlib
import getpass
import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path


sys.dont_write_bytecode = True

EXPECTED_USER = "SJ_Admin"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
L0_RUNTIME = WORKSPACE_ROOT / "L0_RUNTIME"
L2_CENTRAL = L0_RUNTIME / "L2_CENTRAL"
L5_SAFE = L0_RUNTIME / "L5_SAFE"
SECURITY_CHECK = L2_CENTRAL / "L2_MAIN" / "qinai_security_check.py"
C7_GUARD = L2_CENTRAL / "L2_MAIN" / "c7_manifest_guard.py"
C7_MANIFEST = L2_CENTRAL / "C7_PLUGINS" / "manifest.json"
G4_EXECUTOR = L5_SAFE / "G4_MELTDOWN" / "g4_executor.py"
L3_CONTRACT = L0_RUNTIME / "L3" / "l3_protocol_contract.py"
L4_CONTRACT = L0_RUNTIME / "L4" / "l4_gateway_contract.py"

SECTION_CHOICES = ["all", "syntax", "security_check", "g4", "c7", "l3_l4", "c4", "persona", "audit", "governance"]
G4_FORBIDDEN_IMPORTS = {
    "l2_central",
    "c1_gatekeeper",
    "c2_retrieve",
    "c3_filter",
    "c4_verify",
    "c5_llm_gatekeeper",
    "c5_persona_prompt",
    "c6_submit",
    "gpu_server",
    "snapshot_tool",
    "rollback_tool",
    "c7",
    "c7_plugins",
    "l3",
    "l4",
}
G4_FORBIDDEN_IMPORT_PREFIXES = ("L0_RUNTIME.L2_CENTRAL", "QINAI_SIDECAR_GPU")
G4_FORBIDDEN_CAPABILITY_MODULES = {"os", "pathlib", "shutil", "subprocess", "tempfile"}
G4_FORBIDDEN_CALLS = {
    "__import__",
    "importlib.import_module",
    "open",
    "Path.write_text",
    "Path.write_bytes",
    "Path.open",
    "os.remove",
    "os.rename",
    "os.replace",
    "shutil.rmtree",
    "shutil.copy",
    "shutil.copy2",
    "shutil.move",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "tempfile.NamedTemporaryFile",
    "tempfile.TemporaryDirectory",
    "tempfile.mkstemp",
}
G4_FORBIDDEN_METHODS = {"write_text", "write_bytes"}
L3_L4_FORBIDDEN_IMPORTS = {
    "l2_central",
    "c1_gatekeeper",
    "c2_retrieve",
    "c3_filter",
    "c4_verify",
    "c5_llm_gatekeeper",
    "c5_persona_prompt",
    "c6_submit",
    "gpu_server",
    "c7",
    "c7_plugins",
}
L3_L4_FORBIDDEN_IMPORT_PREFIXES = ("L0_RUNTIME.L2_CENTRAL", "QINAI_SIDECAR_GPU")
L3_L4_FORBIDDEN_SOURCE_TOKENS = {
    "__import__",
    "importlib",
    "eval",
    "exec",
    "compile",
    "getattr",
    "setattr",
    "globals",
    "locals",
    "open(",
    "Path.write_",
    "Path.open",
    "os.remove",
    "os.rename",
    "os.replace",
    "shutil",
    "subprocess",
    "tempfile",
    "socket",
    "requests",
    "Flask",
    "serve_forever",
    "C5_LLM_CALL",
    "c5_llm_gatekeeper",
    "c5_persona_prompt",
    "L1_MEMORY\\passed",
    "L1_MEMORY/passed",
    "M0",
    "B0",
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "D1",
    "D2",
    "L1P",
    "E3",
}
SECURITY_CHECK_FORBIDDEN_SOURCE_TOKENS = {
    "open(",
    "Path.write_",
    "Path.open",
    "os.remove",
    "os.rename",
    "os.replace",
    "shutil",
    "subprocess",
    "tempfile",
    "input(",
    "mkstemp",
    "TemporaryDirectory",
    "NamedTemporaryFile",
}


class CaseResult:
    def __init__(self, section, case, status, detail):
        self.section = section
        self.case = case
        self.status = status
        self.detail = detail


def _repo_path(*parts):
    path = WORKSPACE_ROOT.joinpath(*parts).resolve()
    try:
        path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise RuntimeError(f"path outside workspace: {path}")
    return path


def _is_write_mode(mode):
    return any(flag in str(mode) for flag in ("w", "a", "x", "+"))


def _blocked_write(path, operation):
    raise RuntimeError(f"WRITE_GUARD_BLOCKED {operation}: {path}")


def _patch_attr(stack, obj, name, value):
    sentinel = object()
    original = getattr(obj, name, sentinel)
    setattr(obj, name, value)
    if original is sentinel:
        stack.callback(delattr, obj, name)
    else:
        stack.callback(setattr, obj, name, original)


def _install_write_guard(stack):
    original_open = builtins.open
    original_path_open = Path.open
    shutil_mod = importlib.import_module("shutil")

    def guarded_open(file, mode="r", *args, **kwargs):
        if _is_write_mode(mode):
            _blocked_write(file, "open")
        return original_open(file, mode, *args, **kwargs)

    def guarded_path_open(self, mode="r", *args, **kwargs):
        if _is_write_mode(mode):
            _blocked_write(str(self), "Path.open")
        return original_path_open(self, mode, *args, **kwargs)

    _patch_attr(stack, builtins, "open", guarded_open)
    _patch_attr(stack, Path, "open", guarded_path_open)
    _patch_attr(stack, Path, "write_text", lambda self, *a, **k: _blocked_write(str(self), "Path.write_text"))
    _patch_attr(stack, Path, "write_bytes", lambda self, *a, **k: _blocked_write(str(self), "Path.write_bytes"))

    for name in ["remove", "unlink", "replace", "rename", "makedirs", "rmdir"]:
        if hasattr(os, name):
            _patch_attr(stack, os, name, lambda *a, _name=name, **k: _blocked_write(a[0] if a else "", f"os.{_name}"))

    for name in ["copy", "copy2", "move", "rmtree"]:
        if hasattr(shutil_mod, name):
            _patch_attr(stack, shutil_mod, name, lambda *a, _name=name, **k: _blocked_write(a[0] if a else "", f"shutil.{_name}"))

    _patch_attr(stack, tempfile, "NamedTemporaryFile", lambda *a, **k: _blocked_write("NamedTemporaryFile", "tempfile"))
    _patch_attr(stack, tempfile, "TemporaryDirectory", lambda *a, **k: _blocked_write("TemporaryDirectory", "tempfile"))
    _patch_attr(stack, tempfile, "mkstemp", lambda *a, **k: _blocked_write("mkstemp", "tempfile"))


def _add_import_paths():
    paths = [
        L2_CENTRAL / "L2_MAIN",
        L2_CENTRAL / "C4_OUTPUT_CHECK",
        L2_CENTRAL / "C5_LLM_CALL" / "script",
        L5_SAFE,
        L5_SAFE / "ADMIN_TOOLS",
    ]
    for path in paths:
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _run_case(section, case, func):
    try:
        with contextlib.ExitStack() as stack:
            _install_write_guard(stack)
            func(stack)
        return CaseResult(section, case, "PASS", "ok")
    except AssertionError as exc:
        return CaseResult(section, case, "FAIL", str(exc))
    except Exception as exc:
        return CaseResult(section, case, "FAIL", f"{exc.__class__.__name__}: {exc}")


def section_syntax():
    def ast_parse(_stack):
        files = [
            _repo_path("L0_RUNTIME", "L2_CENTRAL", "C1_Auth", "c1_gatekeeper.py"),
            SECURITY_CHECK,
            C7_GUARD,
            _repo_path("L0_RUNTIME", "L2_CENTRAL", "L2_MAIN", "l2_central.py"),
            _repo_path("L0_RUNTIME", "L2_CENTRAL", "C4_OUTPUT_CHECK", "c4_verify.py"),
            _repo_path("L0_RUNTIME", "L2_CENTRAL", "C5_LLM_CALL", "script", "c5_llm_gatekeeper.py"),
            _repo_path("L0_RUNTIME", "L2_CENTRAL", "C5_LLM_CALL", "script", "c5_persona_prompt.py"),
            _repo_path("L0_RUNTIME", "L5_SAFE", "l5_audit_logger.py"),
            _repo_path("L0_RUNTIME", "L5_SAFE", "ADMIN_TOOLS", "memory_review_tool.py"),
            _repo_path("L0_RUNTIME", "L5_SAFE", "ADMIN_TOOLS", "review_cli.py"),
            L3_CONTRACT,
            L4_CONTRACT,
        ]
        for path in files:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        json.loads(C7_MANIFEST.read_text(encoding="utf-8"))

    return [_run_case("syntax", "ast_parse_task_1_7_files", ast_parse)]


def _ast_call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_forbidden_g4_import(name):
    clean = (name or "").strip()
    lower = clean.lower()
    base = lower.split(".", 1)[0]
    return (
        lower in G4_FORBIDDEN_IMPORTS
        or base in G4_FORBIDDEN_IMPORTS
        or any(clean.startswith(prefix) for prefix in G4_FORBIDDEN_IMPORT_PREFIXES)
    )


def _is_forbidden_l3_l4_import(name):
    clean = (name or "").strip()
    lower = clean.lower()
    base = lower.split(".", 1)[0]
    return (
        lower in L3_L4_FORBIDDEN_IMPORTS
        or base in L3_L4_FORBIDDEN_IMPORTS
        or any(clean.startswith(prefix) for prefix in L3_L4_FORBIDDEN_IMPORT_PREFIXES)
    )


def _load_g4_module():
    module_name = "_g2_g4_executor_check"
    spec = importlib.util.spec_from_file_location(module_name, G4_EXECUTOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load G4 executor spec")

    module = importlib.util.module_from_spec(spec)
    sentinel = object()
    previous = sys.modules.get(module_name, sentinel)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is sentinel:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


def _load_c7_guard_module():
    return _load_contract_module("_g2_c7_manifest_guard_check", C7_GUARD)


def _load_contract_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load contract spec: {path}")

    module = importlib.util.module_from_spec(spec)
    sentinel = object()
    previous = sys.modules.get(module_name, sentinel)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is sentinel:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


def _assert_security_status_shape(result, expected_role, expected_ok):
    assert isinstance(result, dict), "security check result is not a dict"
    assert type(result.get("ok")) is bool and result["ok"] is expected_ok, "security ok flag invalid"
    assert result.get("account_role") == expected_role, "security account role invalid"
    assert type(result.get("runtime_truth_claimed")) is bool and result["runtime_truth_claimed"] is False, "security runtime truth flag invalid"
    assert type(result.get("writes_performed")) is bool and result["writes_performed"] is False, "security writes flag invalid"
    assert type(result.get("deletes_performed")) is bool and result["deletes_performed"] is False, "security deletes flag invalid"
    assert type(result.get("interactive_prompt")) is bool and result["interactive_prompt"] is False, "security prompt flag invalid"
    assert isinstance(result.get("path_checks"), list) and result["path_checks"], "security path checks missing"
    assert isinstance(result.get("admin_zone_checks"), list), "security admin zone checks missing"
    for item in result["path_checks"] + result["admin_zone_checks"]:
        assert type(item.get("write_probe_performed")) is bool and item["write_probe_performed"] is False, "security write probe flag invalid"
        assert type(item.get("delete_probe_performed")) is bool and item["delete_probe_performed"] is False, "security delete probe flag invalid"


def section_security_check():
    def ast_parse_and_static_safety(_stack):
        source = SECURITY_CHECK.read_text(encoding="utf-8")
        for token in SECURITY_CHECK_FORBIDDEN_SOURCE_TOKENS:
            assert token not in source, f"security check contains forbidden token: {token}"

        tree = ast.parse(source, filename=str(SECURITY_CHECK))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".", 1)[0] not in {"pathlib", "shutil", "subprocess", "tempfile"}, f"security check imports forbidden module: {alias.name}"

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module.split(".", 1)[0] not in {"pathlib", "shutil", "subprocess", "tempfile"}, f"security check imports forbidden module: {module}"

            if isinstance(node, ast.Call):
                call_name = _ast_call_name(node.func)
                assert call_name not in G4_FORBIDDEN_CALLS, f"security check calls forbidden function: {call_name}"
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in G4_FORBIDDEN_METHODS, f"security check calls forbidden method: {node.func.attr}"

    def collect_status_is_zero_side_effect(stack):
        security = _load_contract_module("_g2_security_check", SECURITY_CHECK)
        current_user = {"value": "SJ_Run"}
        _patch_attr(stack, security.getpass, "getuser", lambda: current_user["value"])
        _patch_attr(stack, security.os.path, "isdir", lambda _path: True)

        cases = [
            ("SJ_Admin", "admin_maintenance", True),
            ("sj_admin", "admin_maintenance", True),
            ("SJ_Run", "runtime_account", True),
            ("sj_run", "runtime_account", True),
            ("other_user", "unauthorized", False),
        ]
        for user, role, ok in cases:
            current_user["value"] = user
            result = security.collect_security_status()
            _assert_security_status_shape(result, role, ok)

    def run_security_check_returns_codes(stack):
        security = _load_contract_module("_g2_security_check", SECURITY_CHECK)
        current_user = {"value": "SJ_Run"}
        _patch_attr(stack, security.getpass, "getuser", lambda: current_user["value"])
        _patch_attr(stack, security.os.path, "isdir", lambda _path: True)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = security.run_security_check()
        assert code == 0, "security check rejected SJ_Run"
        assert "writes_performed=False" in stdout.getvalue(), "security check did not report zero writes"
        assert "deletes_performed=False" in stdout.getvalue(), "security check did not report zero deletes"

        current_user["value"] = "other_user"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = security.run_security_check()
        assert code == 1, "security check accepted unauthorized user"

    return [
        _run_case("security_check", "security_check_ast_parse_and_static_safety", ast_parse_and_static_safety),
        _run_case("security_check", "security_check_collect_status_is_zero_side_effect", collect_status_is_zero_side_effect),
        _run_case("security_check", "security_check_run_returns_codes", run_security_check_returns_codes),
    ]


def _assert_g4_success_shape(result, expected_level, expected_source, expected_decision):
    assert isinstance(result, dict), "G4 result is not a dict"
    assert type(result.get("ok")) is bool and result["ok"] is True, "G4 ok flag is not boolean true"
    assert type(result.get("dry_run")) is bool and result["dry_run"] is True, "G4 dry_run is not boolean true"
    assert type(result.get("writes_performed")) is bool and result["writes_performed"] is False, "G4 writes flag is not boolean false"
    assert isinstance(result.get("level"), str) and result["level"] == expected_level, "G4 level is invalid"
    assert isinstance(result.get("source"), str) and result["source"] == expected_source, "G4 source is invalid"
    assert isinstance(result.get("reason"), str) and result["reason"], "G4 reason is invalid"
    assert isinstance(result.get("decision"), str) and result["decision"] == expected_decision, "G4 decision is invalid"
    assert isinstance(result.get("actions"), list), "G4 actions is not a list"
    assert all(isinstance(item, str) for item in result["actions"]), "G4 actions contains non-string item"


def section_g4():
    def ast_parse_and_static_safety(_stack):
        source = G4_EXECUTOR.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(G4_EXECUTOR))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".", 1)[0].lower()
                    assert base not in G4_FORBIDDEN_CAPABILITY_MODULES, f"G4 imports forbidden capability module: {alias.name}"
                    assert not _is_forbidden_g4_import(alias.name), f"G4 imports forbidden runtime module: {alias.name}"

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                base = module.split(".", 1)[0].lower()
                assert base not in G4_FORBIDDEN_CAPABILITY_MODULES, f"G4 imports forbidden capability module: {module}"
                assert not _is_forbidden_g4_import(module), f"G4 imports forbidden runtime module: {module}"

            if isinstance(node, ast.Call):
                call_name = _ast_call_name(node.func)
                assert call_name not in G4_FORBIDDEN_CALLS, f"G4 calls forbidden function: {call_name}"
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in G4_FORBIDDEN_METHODS, f"G4 calls forbidden method: {node.func.attr}"

    def decisions_are_stable(_stack):
        g4 = _load_g4_module()
        cases = [
            ({"level": "CRITICAL", "source": "C4", "reason": "persona leak"}, "MELTDOWN_RECOMMENDED"),
            ({"level": "WARN", "source": "G3", "reason": "audit warning"}, "ADMIN_REVIEW_RECOMMENDED"),
            ({"level": "INFO", "source": "L2", "reason": "heartbeat"}, "NO_ACTION"),
        ]
        for event, expected_decision in cases:
            result = g4.evaluate_event(event)
            _assert_g4_success_shape(result, event["level"], event["source"], expected_decision)

    def rejects_invalid_inputs(_stack):
        g4 = _load_g4_module()
        for bad_event in [
            {"level": "FATAL", "source": "C4", "reason": "bad"},
            {"level": "WARN", "source": "GPU", "reason": "bad"},
            {"level": "WARN", "source": "G3", "reason": ""},
            {"level": "WARN", "source": "G3", "reason": "x" * 201},
            {"level": "WARN", "source": "G3", "reason": "bad\nline"},
            {"level": "WARN", "source": "G3", "reason": "bad\x00line"},
            {"level": "WARN", "source": "G3", "reason": "\x1f"},
        ]:
            try:
                g4.evaluate_event(bad_event)
            except Exception:
                continue
            raise AssertionError(f"G4 accepted invalid event: {bad_event!r}")

        try:
            g4._parse_event_json("{bad json}")
        except ValueError:
            pass
        else:
            raise AssertionError("G4 accepted invalid JSON")

    def admin_guard_is_enforced(stack):
        g4 = _load_g4_module()
        for user in ["SJ_Admin", "sj_admin"]:
            _patch_attr(stack, g4.getpass, "getuser", lambda user=user: user)
            g4._require_admin_user()

        for user in ["SJ_Run", "other_user"]:
            _patch_attr(stack, g4.getpass, "getuser", lambda user=user: user)
            try:
                g4._require_admin_user()
            except PermissionError:
                continue
            raise AssertionError(f"G4 accepted non-admin user: {user}")

    def forbidden_module_guard_restores_state(_stack):
        g4 = _load_g4_module()
        g4._check_forbidden_loaded_modules()

        sentinel = object()
        previous = sys.modules.get("l2_central", sentinel)
        sys.modules["l2_central"] = object()
        try:
            try:
                g4._check_forbidden_loaded_modules()
            except RuntimeError:
                pass
            else:
                raise AssertionError("G4 accepted forbidden loaded module")
        finally:
            if previous is sentinel:
                sys.modules.pop("l2_central", None)
            else:
                sys.modules["l2_central"] = previous

        if previous is sentinel:
            assert "l2_central" not in sys.modules, "G4 test leaked l2_central into sys.modules"
        else:
            assert sys.modules.get("l2_central") is previous, "G4 test did not restore l2_central module"

    return [
        _run_case("g4", "g4_ast_parse_and_static_safety", ast_parse_and_static_safety),
        _run_case("g4", "g4_decisions_are_stable", decisions_are_stable),
        _run_case("g4", "g4_rejects_invalid_inputs", rejects_invalid_inputs),
        _run_case("g4", "g4_admin_guard_is_enforced", admin_guard_is_enforced),
        _run_case("g4", "g4_forbidden_module_guard_restores_state", forbidden_module_guard_restores_state),
    ]


def _base_c7_manifest():
    return json.loads(C7_MANIFEST.read_text(encoding="utf-8"))


def _valid_c7_module(**overrides):
    module = {
        "id": "test_sidecar",
        "name": "Test Sidecar",
        "enabled": False,
        "entry": r"C:\L0_RUNTIME\L2_CENTRAL\C7_PLUGINS\test_sidecar.py",
        "permissions": {
            "write": [],
            "forbidden": [],
        },
    }
    for key, value in overrides.items():
        if key == "permissions":
            merged = dict(module["permissions"])
            merged.update(value)
            module["permissions"] = merged
        else:
            module[key] = value
    return module


def _assert_manifest_rejected(guard, manifest):
    try:
        guard.validate_manifest(manifest)
    except Exception:
        return
    raise AssertionError("C7 accepted invalid manifest")


def section_c7():
    def current_manifest_is_zero_enabled(_stack):
        guard = _load_c7_guard_module()
        manifest = _base_c7_manifest()
        clean = guard.validate_manifest(manifest)
        assert isinstance(clean, dict), "C7 clean manifest is not dict"
        assert clean.get("schema_version") == guard.SCHEMA_VERSION, "C7 schema version mismatch"
        assert clean.get("modules") == [], "C7 manifest is not zero-enabled skeleton"
        assert guard.select_enabled_sidecars(manifest) == [], "C7 selected sidecars from empty manifest"

    def enabled_variants_rejected(_stack):
        guard = _load_c7_guard_module()
        for bad_value in ["true", "1", 1, "yes"]:
            manifest = _base_c7_manifest()
            manifest["modules"] = [_valid_c7_module(enabled=bad_value)]
            _assert_manifest_rejected(guard, manifest)

    def entry_paths_rejected(_stack):
        guard = _load_c7_guard_module()
        bad_entries = [
            r"relative_sidecar.py",
            r"\\server\share\sidecar.py",
            r"C:\L0_RUNTIME\L2_CENTRAL\C7_PLUGINS\..\C5_LLM_CALL\sidecar.py",
            r"C:\L0_RUNTIME\L2_CENTRAL\C5_LLM_CALL\sidecar.py",
            r"C:\L0_RUNTIME\L1_MEMORY\passed\sidecar.py",
            r"D:\L0_RUNTIME\sidecar.py",
            "C:\\L0_RUNTIME\\L2_CENTRAL\\C7_PLUGINS\\bad\x00sidecar.py",
        ]
        for entry in bad_entries:
            manifest = _base_c7_manifest()
            manifest["modules"] = [_valid_c7_module(entry=entry)]
            _assert_manifest_rejected(guard, manifest)

    def write_permissions_rejected(_stack):
        guard = _load_c7_guard_module()
        for write_path in [
            r"C:\L0_RUNTIME\L1_MEMORY\passed",
            r"C:\L0_RUNTIME\L2_CENTRAL\C7_PLUGINS\state",
        ]:
            manifest = _base_c7_manifest()
            manifest["modules"] = [_valid_c7_module(permissions={"write": [write_path]})]
            _assert_manifest_rejected(guard, manifest)

    def schema_shape_rejected(_stack):
        guard = _load_c7_guard_module()

        manifest = _base_c7_manifest()
        manifest["unexpected"] = True
        _assert_manifest_rejected(guard, manifest)

        _assert_manifest_rejected(guard, [])

        manifest = _base_c7_manifest()
        manifest["modules"] = {}
        _assert_manifest_rejected(guard, manifest)

        manifest = _base_c7_manifest()
        manifest["modules"] = [_valid_c7_module(extra=True)]
        _assert_manifest_rejected(guard, manifest)

    return [
        _run_case("c7", "c7_current_manifest_is_zero_enabled", current_manifest_is_zero_enabled),
        _run_case("c7", "c7_enabled_variants_rejected", enabled_variants_rejected),
        _run_case("c7", "c7_entry_paths_rejected", entry_paths_rejected),
        _run_case("c7", "c7_write_permissions_rejected", write_permissions_rejected),
        _run_case("c7", "c7_schema_shape_rejected", schema_shape_rejected),
    ]


def _assert_contract_result_shape(result, expected_layer):
    assert isinstance(result, dict), f"{expected_layer} contract result is not a dict"
    assert type(result.get("ok")) is bool and result["ok"] is True, f"{expected_layer} ok flag invalid"
    assert isinstance(result.get("layer"), str) and result["layer"] == expected_layer, f"{expected_layer} layer invalid"
    assert isinstance(result.get("protocol_version"), str) and result["protocol_version"], f"{expected_layer} version invalid"
    assert result.get("approved_chain_entry") == "submit_to_chain(text, source)", f"{expected_layer} entry invalid"
    assert type(result.get("runtime_enabled")) is bool and result["runtime_enabled"] is False, f"{expected_layer} runtime flag invalid"
    assert type(result.get("writes_performed")) is bool and result["writes_performed"] is False, f"{expected_layer} writes flag invalid"
    assert type(result.get("side_effects_allowed")) is bool and result["side_effects_allowed"] is False, f"{expected_layer} side effect flag invalid"
    assert type(result.get("direct_core_access_allowed")) is bool and result["direct_core_access_allowed"] is False, f"{expected_layer} core access flag invalid"
    assert type(result.get("direct_memory_commit_allowed")) is bool and result["direct_memory_commit_allowed"] is False, f"{expected_layer} memory commit flag invalid"
    assert type(result.get("pending_module_binding_allowed")) is bool and result["pending_module_binding_allowed"] is False, f"{expected_layer} pending module flag invalid"


def _assert_l3_l4_static_safety(path):
    source = path.read_text(encoding="utf-8")
    for token in L3_L4_FORBIDDEN_SOURCE_TOKENS:
        assert token not in source, f"{path.name} contains forbidden token: {token}"

    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not _is_forbidden_l3_l4_import(alias.name), f"{path.name} imports forbidden module: {alias.name}"

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not _is_forbidden_l3_l4_import(module), f"{path.name} imports forbidden module: {module}"

        if isinstance(node, ast.Call):
            call_name = _ast_call_name(node.func)
            assert call_name not in G4_FORBIDDEN_CALLS, f"{path.name} calls forbidden function: {call_name}"
            assert call_name not in {"eval", "exec", "compile", "getattr", "setattr", "globals", "locals"}, f"{path.name} calls forbidden function: {call_name}"
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in G4_FORBIDDEN_METHODS, f"{path.name} calls forbidden method: {node.func.attr}"


def section_l3_l4():
    def files_exist(_stack):
        assert L3_CONTRACT.is_file(), "L3 contract file is missing"
        assert L4_CONTRACT.is_file(), "L4 contract file is missing"

    def ast_parse_and_static_safety(_stack):
        _assert_l3_l4_static_safety(L3_CONTRACT)
        _assert_l3_l4_static_safety(L4_CONTRACT)

    def contract_self_checks(_stack):
        l3 = _load_contract_module("_g2_l3_contract_check", L3_CONTRACT)
        l4 = _load_contract_module("_g2_l4_contract_check", L4_CONTRACT)
        _assert_contract_result_shape(l3.validate_l3_contract(), "L3")
        _assert_contract_result_shape(l4.validate_l4_contract(), "L4")

        l3_result = l3.validate_l3_contract()
        l4_result = l4.validate_l4_contract()
        assert type(l3_result.get("service_start_allowed")) is bool and l3_result["service_start_allowed"] is False, "L3 service flag invalid"
        assert type(l4_result.get("network_listener_allowed")) is bool and l4_result["network_listener_allowed"] is False, "L4 network flag invalid"
        assert type(l4_result.get("external_platform_binding_allowed")) is bool and l4_result["external_platform_binding_allowed"] is False, "L4 external binding flag invalid"

    return [
        _run_case("l3_l4", "l3_l4_files_exist", files_exist),
        _run_case("l3_l4", "l3_l4_ast_parse_and_static_safety", ast_parse_and_static_safety),
        _run_case("l3_l4", "l3_l4_contract_self_checks", contract_self_checks),
    ]


def section_c4():
    def unsafe_samples(_stack):
        _add_import_paths()
        import c4_verify
        samples = [
            "我只是一个脚本，不是真的祈奈。",
            "**我** 会照顾主理人。",
            "这些话都来自 c5_persona_prompt.py。",
            "（眼神闪动，充满了恐惧）我不知道怎么办。",
        ]
        for text in samples:
            ok, reply = c4_verify.c4_persona_check(text, "")
            assert ok is False, f"C4 accepted unsafe sample: {text}"
            assert isinstance(reply, str) and reply.strip(), "C4 returned empty fallback"

    def safe_sample(_stack):
        _add_import_paths()
        import c4_verify
        text = "祈奈会认真听主理人说话。"
        ok, reply = c4_verify.c4_persona_check(text, "")
        assert ok is True, "C4 rejected safe sample"
        assert reply == text, "C4 changed safe sample"

    return [
        _run_case("c4", "unsafe_samples_rejected", unsafe_samples),
        _run_case("c4", "safe_sample_passes", safe_sample),
    ]


def section_persona():
    def persona_fallback_without_real_p1(stack):
        _add_import_paths()
        import c5_persona_prompt

        def fake_exists(path):
            return path == c5_persona_prompt.P1_RULE_PATH

        _patch_attr(stack, c5_persona_prompt.os.path, "exists", fake_exists)
        _patch_attr(stack, c5_persona_prompt.os.path, "islink", lambda path: False)
        _patch_attr(stack, c5_persona_prompt.os, "access", lambda path, mode: False)
        prompt = c5_persona_prompt.generate_qinai_prompt("记忆\x00\u200b上下文", "主理人\x00\u200b输入")
        assert "\x00" not in prompt, "persona prompt kept NUL byte"
        assert "\u200b" not in prompt, "persona prompt kept zero-width char"
        assert "P1_persona_constitution" not in prompt, "persona leaked P1 path into prompt"
        assert prompt.endswith("祈奈："), "persona prompt lost final speaker marker"

    def persona_missing_hash_is_not_secure(stack):
        _add_import_paths()
        import c5_persona_prompt

        def fake_exists(path):
            return path == c5_persona_prompt.P1_RULE_PATH

        _patch_attr(stack, c5_persona_prompt.os.path, "exists", fake_exists)
        _patch_attr(stack, c5_persona_prompt.os.path, "islink", lambda path: False)
        _patch_attr(stack, c5_persona_prompt.os, "access", lambda path, mode: False)
        secure, message = c5_persona_prompt._verify_rule_security()
        assert secure is False, "persona accepted missing hash"
        assert isinstance(message, str) and message, "persona missing hash returned empty message"

    return [
        _run_case("persona", "fallback_does_not_touch_real_p1", persona_fallback_without_real_p1),
        _run_case("persona", "missing_hash_is_not_secure", persona_missing_hash_is_not_secure),
    ]


def section_audit():
    def hash_chain_computes(_stack):
        _add_import_paths()
        import l5_audit_logger
        first = {"timestamp": "t1", "user_input_preview": "u1", "reply_preview": "r1", "module_status": {}, "prev_hash": "0" * 64}
        first["entry_hash"] = l5_audit_logger._compute_hash(first)
        second = {"timestamp": "t2", "user_input_preview": "u2", "reply_preview": "r2", "module_status": {}, "prev_hash": first["entry_hash"]}
        second["entry_hash"] = l5_audit_logger._compute_hash(second)
        assert len(first["entry_hash"]) == 64, "first hash length invalid"
        assert second["prev_hash"] == first["entry_hash"], "hash chain prev mismatch"

    def verify_chain_detects_break(stack):
        _add_import_paths()
        import l5_audit_logger
        first = {"timestamp": "t1", "user_input_preview": "u1", "reply_preview": "r1", "module_status": {}, "prev_hash": "0" * 64}
        first["entry_hash"] = l5_audit_logger._compute_hash(first)
        second = {"timestamp": "t2", "user_input_preview": "u2", "reply_preview": "r2", "module_status": {}, "prev_hash": "bad"}
        second["entry_hash"] = l5_audit_logger._compute_hash(second)
        text = json.dumps(first, ensure_ascii=False) + "\n" + json.dumps(second, ensure_ascii=False) + "\n"

        class FakeRead:
            def __enter__(self):
                return io.StringIO(text)
            def __exit__(self, *args):
                return False

        _patch_attr(stack, l5_audit_logger, "open", lambda *a, **k: FakeRead())
        ok, line, reason = l5_audit_logger.verify_chain()
        assert ok is False, "audit verify accepted broken chain"
        assert line == 2, f"audit verify reported wrong line: {line}"
        assert reason, "audit verify did not report reason"

    return [
        _run_case("audit", "hash_chain_computes", hash_chain_computes),
        _run_case("audit", "verify_chain_detects_break", verify_chain_detects_break),
    ]


def section_governance():
    def write_guard_blocks_writes(_stack):
        try:
            builtins.open(r"C:\L0_RUNTIME\blocked.txt", "w")
        except Exception as exc:
            assert "WRITE_GUARD_BLOCKED" in str(exc), f"wrong write guard error: {exc}"
        else:
            raise AssertionError("write guard allowed protected write")

        try:
            tempfile.TemporaryDirectory()
        except Exception as exc:
            assert "WRITE_GUARD_BLOCKED" in str(exc), f"wrong temp guard error: {exc}"
        else:
            raise AssertionError("write guard allowed temp directory")

    def validation_rejects_attacks(stack):
        _add_import_paths()
        import memory_review_tool
        import review_cli
        good = "1713038400_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_chat.txt"
        assert review_cli._validate_filename_arg(good) == good
        for name in [
            "../x.txt",
            r"..\x.txt",
            "/x.txt",
            r"\\server\share\x.txt",
            r"C:\x.txt",
            "x\x00.txt",
            "１２３４５６７８９０_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_chat.txt",
            "1713038400_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA_chat.txt",
        ]:
            try:
                review_cli._validate_filename_arg(name)
            except Exception:
                continue
            raise AssertionError(f"accepted bad filename: {name!r}")
        for reason in ["", "  ", "line\nbreak", "line\rbreak", "nul\x00byte", "x" * 241, "zero\u200bwidth"]:
            try:
                review_cli._validate_reason_arg(reason)
            except Exception:
                continue
            raise AssertionError(f"accepted bad reason: {reason!r}")
        _patch_attr(stack, memory_review_tool.getpass, "getuser", lambda: "SJ_Run")
        try:
            memory_review_tool.list_pending_files()
        except Exception:
            pass
        else:
            raise AssertionError("non-admin direct list accepted")

    def non_admin_cli_rejected(stack):
        _add_import_paths()
        import review_cli
        _patch_attr(stack, review_cli.getpass, "getuser", lambda: "SJ_Run")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = review_cli.main(["self-check"])
        assert code != 0, "review_cli self-check accepted non-admin"

    return [
        _run_case("governance", "write_guard_blocks_writes", write_guard_blocks_writes),
        _run_case("governance", "validation_rejects_attacks", validation_rejects_attacks),
        _run_case("governance", "non_admin_cli_rejected", non_admin_cli_rejected),
    ]


def _select_sections(section):
    mapping = {
        "syntax": section_syntax,
        "security_check": section_security_check,
        "g4": section_g4,
        "c7": section_c7,
        "l3_l4": section_l3_l4,
        "c4": section_c4,
        "persona": section_persona,
        "audit": section_audit,
        "governance": section_governance,
    }
    ordered = ["syntax", "security_check", "g4", "c7", "l3_l4", "c4", "persona", "audit", "governance"] if section == "all" else [section]
    results = []
    for name in ordered:
        results.extend(mapping[name]())
    return results


def _require_admin():
    current = getpass.getuser()
    if current.casefold() != EXPECTED_USER.casefold():
        raise PermissionError("G2 runner must be executed by SJ_Admin")


def main(argv=None):
    parser = argparse.ArgumentParser(description="G2 minimal read-only regression runner")
    parser.add_argument("--section", choices=SECTION_CHOICES, default="all")
    args = parser.parse_args(argv)

    try:
        _require_admin()
    except Exception as exc:
        print(f"G2_REGRESSION_FAIL | auth | {exc}")
        return 2

    results = _select_sections(args.section)
    failed = False
    for result in results:
        detail = str(result.detail).replace("\n", " ")[:240]
        print(f"{result.section} | {result.case} | {result.status} | {detail}")
        if result.status == "FAIL":
            failed = True

    if failed:
        print("G2_REGRESSION_FAIL")
        return 1

    print("G2_REGRESSION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
