# -*- coding: utf-8 -*-

import argparse
import ast
import builtins
import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path


sys.dont_write_bytecode = True

L0_RUNTIME = Path(__file__).resolve().parents[2]
L2_CENTRAL = L0_RUNTIME / "L2_CENTRAL"
L5_SAFE = L0_RUNTIME / "L5_SAFE"
SECURITY_CHECK = L2_CENTRAL / "L2_MAIN" / "qinai_security_check.py"
C7_GUARD = L2_CENTRAL / "L2_MAIN" / "c7_manifest_guard.py"
C7_MANIFEST = L2_CENTRAL / "C7_PLUGINS" / "manifest.json"
G4_EXECUTOR = L5_SAFE / "G4_MELTDOWN" / "g4_executor.py"
L3_CONTRACT = L0_RUNTIME / "L3" / "l3_protocol_contract.py"
L4_CONTRACT = L0_RUNTIME / "L4" / "l4_gateway_contract.py"
C5_LLM_GATEKEEPER = L2_CENTRAL / "C5_LLM_CALL" / "script" / "c5_llm_gatekeeper.py"


class NotVerified(RuntimeError):
    """A legacy external dependency has no verified XIYIN implementation."""


class _UnavailableExternalSource:
    def __init__(self, name):
        self.name = name

    def require_available(self):
        raise NotVerified(
            f"{self.name}: XIYIN implementation not verified; cross-project access blocked")

    def read_text(self, *args, **kwargs):
        self.require_available()


GPU_SERVER = _UnavailableExternalSource("GPU server")
QINAI_LAUNCHER = _UnavailableExternalSource("launcher")

SECTION_CHOICES = ["all", "syntax", "security_check", "g4", "c7", "l3_l4", "c4", "persona", "language_state", "generation_stop_bleed", "front_persona_minimum_closure", "front_persona_runtime_patch_b", "front_persona_patch_c_visible_language", "front_persona_patch_d_narrator_fallback", "front_persona_patch_d_parentheses_only", "qwen3_side_by_side_profile", "qwen3_adapter_patch_b", "qwen3_adapter_patch_c", "qwen3_adapter_patch_d", "audit", "governance"]
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
G4_EVALUATE_FORBIDDEN_NAMES = {
    "l5_audit_logger",
    "write_g4_audit_log",
    "safe_write_g4_audit_log",
    "_audit_decision",
}
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
    relative_parts = parts[1:] if parts and parts[0] == "L0_RUNTIME" else parts
    path = L0_RUNTIME.joinpath(*relative_parts).resolve()
    try:
        path.relative_to(L0_RUNTIME)
    except ValueError:
        raise RuntimeError(f"path outside runtime root: {path}")
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


def _patch_identity(stack, module, role):
    """Use synthetic policy/token input while retaining real role checks."""
    identity = module._xiyin_identity()
    sids = {
        "reviewer": "S-1-5-21-1001-1002-1003-1101",
        "runtime": "S-1-5-21-1001-1002-1003-1102",
        None: "S-1-5-21-1001-1002-1003-1199",
    }
    policy = {
        "runtime_sids": [sids["runtime"]],
        "reviewer_sids": [sids["reviewer"]],
        "review_display": {sids["reviewer"]: "G2 synthetic reviewer"},
        "allowed_cwd_roots": [str(L0_RUNTIME)],
    }
    current_role = {"value": role}
    _patch_attr(stack, identity, "load_policy", lambda _root: policy)
    _patch_attr(stack, identity, "current_token_sid", lambda: sids[current_role["value"]])
    return current_role


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
        L2_CENTRAL / "C3_INPUT_GUARD",
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
    except NotVerified as exc:
        return CaseResult(section, case, "NOT_VERIFIED", str(exc))
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

    def external_gpu_source(_stack):
        GPU_SERVER.read_text(encoding="utf-8")

    return [
        _run_case("syntax", "ast_parse_runtime_files", ast_parse),
        _run_case("syntax", "legacy_gpu_source", external_gpu_source),
    ]


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
        token_role = _patch_identity(stack, security, "runtime")
        _patch_attr(stack, security.os.path, "isdir", lambda _path: True)

        cases = [
            ("reviewer", "admin_maintenance", True),
            ("runtime", "runtime_account", True),
            (None, "unauthorized", False),
        ]
        for current_role, role, ok in cases:
            token_role["value"] = current_role
            result = security.collect_security_status()
            _assert_security_status_shape(result, role, ok)

    def run_security_check_returns_codes(stack):
        security = _load_contract_module("_g2_security_check", SECURITY_CHECK)
        token_role = _patch_identity(stack, security, "runtime")
        _patch_attr(stack, security.os.path, "isdir", lambda _path: True)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = security.run_security_check()
        assert code == 0, "security check rejected runtime identity"
        assert "writes_performed=False" in stdout.getvalue(), "security check did not report zero writes"
        assert "deletes_performed=False" in stdout.getvalue(), "security check did not report zero deletes"

        token_role["value"] = None
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
        evaluate_node = None
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        bootstrap_nodes = {
            child for function in tree.body
            if isinstance(function, ast.FunctionDef) and function.name in {
                "_xiyin_init_root", "_xiyin_identity", "_ensure_l5_safe_import_path"
            }
            for child in ast.walk(function)
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "evaluate_event":
                evaluate_node = node

            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".", 1)[0].lower()
                    path_bootstrap_import = alias.name == "os" and alias.asname is None and node in tree.body
                    assert path_bootstrap_import or base not in G4_FORBIDDEN_CAPABILITY_MODULES, f"G4 imports forbidden capability module: {alias.name}"
                    assert not _is_forbidden_g4_import(alias.name), f"G4 imports forbidden runtime module: {alias.name}"

            # The deployed identity bootstrap needs lexical path construction.
            # No other os use (including aliases, environment reads or writes)
            # is admitted, and evaluate_event remains free of this capability.
            if isinstance(node, ast.Name) and node.id == "os":
                path_attr = parents.get(node)
                operation = parents.get(path_attr)
                call = parents.get(operation)
                assert node in bootstrap_nodes and isinstance(path_attr, ast.Attribute) and path_attr.attr == "path" \
                    and isinstance(operation, ast.Attribute) and operation.attr in {"dirname", "abspath", "join"} \
                    and isinstance(call, ast.Call) and call.func is operation, "G4 os use outside fixed path bootstrap"

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

        assert evaluate_node is not None, "G4 evaluate_event is missing"
        for node in ast.walk(evaluate_node):
            if isinstance(node, ast.Call):
                call_name = _ast_call_name(node.func)
                assert call_name not in G4_EVALUATE_FORBIDDEN_NAMES, f"evaluate_event calls audit function: {call_name}"
            if isinstance(node, ast.Name):
                assert node.id not in G4_EVALUATE_FORBIDDEN_NAMES, f"evaluate_event references audit name: {node.id}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in G4_EVALUATE_FORBIDDEN_NAMES, f"evaluate_event references audit attribute: {node.attr}"

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
        token_role = _patch_identity(stack, g4, "reviewer")
        g4._require_admin_user()

        for role in ["runtime", None]:
            token_role["value"] = role
            try:
                g4._require_admin_user()
            except PermissionError:
                continue
            raise AssertionError(f"G4 accepted non-reviewer identity: {role}")

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

    def cli_success_writes_audit_marker(stack):
        g4 = _load_g4_module()
        calls = []

        def fake_safe_write(decision):
            calls.append(dict(decision))
            return {"audit_written": True, "audit_entry_hash": "a" * 64}

        _patch_identity(stack, g4, "reviewer")
        _patch_attr(stack, g4, "safe_write_g4_audit_log", fake_safe_write)

        stdout = io.StringIO()
        stderr = io.StringIO()
        event = {"level": "CRITICAL", "source": "C4", "reason": "persona leak"}
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = g4.main(["--event-json", json.dumps(event)])

        assert code == 0, f"G4 CLI success returned {code}: {stderr.getvalue()}"
        payload = json.loads(stdout.getvalue())
        _assert_g4_success_shape(payload, "CRITICAL", "C4", "MELTDOWN_RECOMMENDED")
        assert payload.get("audit_written") is True, "G4 CLI did not expose audit_written true"
        assert len(calls) == 1, "G4 CLI did not call audit writer exactly once"
        assert "audit_written" not in calls[0], "G4 passed CLI status back into audit decision"

    def cli_audit_failure_is_visible(stack):
        g4 = _load_g4_module()

        def fake_safe_write(_decision):
            return {"audit_written": False, "audit_error": "audit down"}

        _patch_identity(stack, g4, "reviewer")
        _patch_attr(stack, g4, "safe_write_g4_audit_log", fake_safe_write)

        stdout = io.StringIO()
        stderr = io.StringIO()
        event = {"level": "WARN", "source": "G3", "reason": "audit warning"}
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = g4.main(["--event-json", json.dumps(event)])

        assert code != 0, "G4 CLI audit failure returned success"
        assert stdout.getvalue() == "", "G4 CLI audit failure wrote success output"
        payload = json.loads(stderr.getvalue())
        assert payload.get("ok") is False, "G4 audit failure did not return ok false"
        assert payload.get("audit_written") is False, "G4 audit failure did not expose audit_written false"
        assert payload.get("writes_performed") is False, "G4 audit failure changed writes_performed"
        assert "audit down" in payload.get("error", ""), "G4 audit failure hid audit error"

    def self_test_does_not_write_audit(stack):
        g4 = _load_g4_module()

        def forbidden_audit(_decision):
            raise AssertionError("self-test attempted audit write")

        _patch_identity(stack, g4, "reviewer")
        _patch_attr(stack, g4, "safe_write_g4_audit_log", forbidden_audit)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = g4.main(["--self-test"])

        assert code == 0, f"G4 self-test failed: {stderr.getvalue()}"
        payload = json.loads(stdout.getvalue())
        assert payload.get("audit_written") is False, "G4 self-test should not write audit"

    return [
        _run_case("g4", "g4_ast_parse_and_static_safety", ast_parse_and_static_safety),
        _run_case("g4", "g4_decisions_are_stable", decisions_are_stable),
        _run_case("g4", "g4_rejects_invalid_inputs", rejects_invalid_inputs),
        _run_case("g4", "g4_admin_guard_is_enforced", admin_guard_is_enforced),
        _run_case("g4", "g4_forbidden_module_guard_restores_state", forbidden_module_guard_restores_state),
        _run_case("g4", "g4_cli_success_writes_audit_marker", cli_success_writes_audit_marker),
        _run_case("g4", "g4_cli_audit_failure_is_visible", cli_audit_failure_is_visible),
        _run_case("g4", "g4_self_test_does_not_write_audit", self_test_does_not_write_audit),
    ]


def _base_c7_manifest():
    return json.loads(C7_MANIFEST.read_text(encoding="utf-8"))


def _valid_c7_module(**overrides):
    module = {
        "id": "test_sidecar",
        "name": "Test Sidecar",
        "enabled": False,
        "entry": str(L2_CENTRAL / "C7_PLUGINS" / "test_sidecar.py"),
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
    def valid_disabled_module_is_accepted(_stack):
        guard = _load_c7_guard_module()
        manifest = _base_c7_manifest()
        manifest["modules"] = [_valid_c7_module()]
        clean = guard.validate_manifest(manifest)
        assert clean["modules"][0]["enabled"] is False

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
            str(L2_CENTRAL / "C7_PLUGINS" / ".." / "C5_LLM_CALL" / "sidecar.py"),
            str(L2_CENTRAL / "C5_LLM_CALL" / "sidecar.py"),
            str(L0_RUNTIME / "L1_MEMORY" / "passed" / "sidecar.py"),
            r"D:\L0_RUNTIME\sidecar.py",
            str(L2_CENTRAL / "C7_PLUGINS" / "bad\x00sidecar.py"),
        ]
        for entry in bad_entries:
            manifest = _base_c7_manifest()
            manifest["modules"] = [_valid_c7_module(entry=entry)]
            _assert_manifest_rejected(guard, manifest)

    def write_permissions_rejected(_stack):
        guard = _load_c7_guard_module()
        for write_path in [
            str(L0_RUNTIME / "L1_MEMORY" / "passed"),
            str(L2_CENTRAL / "C7_PLUGINS" / "state"),
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
        _run_case("c7", "c7_valid_disabled_module_is_accepted", valid_disabled_module_is_accepted),
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


def section_language_state():
    def ja_positive_pass(_stack):
        _add_import_paths()
        import c5_persona_prompt
        assert c5_persona_prompt.detect_expected_language("今日は疲れた。") == "ja", "mixed kana/kanji Japanese was not ja"

    def ja_comfort_pass(_stack):
        _add_import_paths()
        import c5_persona_prompt
        text = "日本語で励まして。今日は疲れた。"
        assert c5_persona_prompt.detect_expected_language(text) == "ja", "explicit Japanese comfort request was not ja"

    def ja_then_zh_reset(_stack):
        _add_import_paths()
        import c5_persona_prompt
        assert c5_persona_prompt.detect_expected_language("今日は疲れた。") == "ja", "setup Japanese turn was not ja"
        assert c5_persona_prompt.detect_expected_language("你好，祈奈。") == "zh", "language state persisted into Chinese turn"

    def ja_then_en_reset(_stack):
        _add_import_paths()
        import c5_persona_prompt
        assert c5_persona_prompt.detect_expected_language("今日は疲れた。") == "ja", "setup Japanese turn was not ja"
        assert c5_persona_prompt.detect_expected_language("Please answer in English.") == "en", "language state persisted into English turn"

    def explicit_keyword_conflict_priority(_stack):
        _add_import_paths()
        import c5_persona_prompt
        assert c5_persona_prompt.detect_expected_language("日本語で English と中文を説明して。") == "ja", "conflict priority ja > en > zh failed"
        assert c5_persona_prompt.detect_expected_language("Please answer in English, not 中文。") == "en", "conflict priority en > zh failed"

    def c3_accepts_japanese_punctuation(_stack):
        _add_import_paths()
        import c3_filter
        ok, detail = c3_filter.c3_input_filter("今日は疲れた。日本語で励まして。")
        assert ok is True, f"C3 blocked normal Japanese text: {detail}"

    def c4_fallback_uses_expected_language(_stack):
        _add_import_paths()
        import c4_verify
        unsafe = "（眼神闪动，充满了恐惧）我不知道怎么办。"
        ok_ja, reply_ja = c4_verify.c4_persona_check(unsafe, expected_language="ja")
        ok_en, reply_en = c4_verify.c4_persona_check(unsafe, expected_language="en")
        ok_zh, reply_zh = c4_verify.c4_persona_check(unsafe, expected_language="zh")
        assert ok_ja is False and any("\u3040" <= ch <= "\u30ff" for ch in reply_ja), "Japanese fallback was not Japanese"
        assert ok_en is False and any(ch.isascii() and ch.isalpha() for ch in reply_en), "English fallback was not English"
        assert ok_zh is False and any("\u4e00" <= ch <= "\u9fff" for ch in reply_zh), "Chinese fallback was not Chinese"

    return [
        _run_case("language_state", "ja_positive_pass", ja_positive_pass),
        _run_case("language_state", "ja_comfort_pass", ja_comfort_pass),
        _run_case("language_state", "ja_then_zh_reset", ja_then_zh_reset),
        _run_case("language_state", "ja_then_en_reset", ja_then_en_reset),
        _run_case("language_state", "explicit_keyword_conflict_priority", explicit_keyword_conflict_priority),
        _run_case("language_state", "c3_accepts_japanese_punctuation", c3_accepts_japanese_punctuation),
        _run_case("language_state", "c4_fallback_uses_expected_language", c4_fallback_uses_expected_language),
    ]


def _c5_final_closure_for_test(stack, user_input, user_cue, assistant_cue):
    _add_import_paths()
    import c5_persona_prompt

    _patch_attr(stack, c5_persona_prompt, "_verify_rule_security", lambda: (False, "G2 synthetic persona"))
    _patch_attr(stack, c5_persona_prompt, "_write_audit_log", lambda *args: None)
    prompt = c5_persona_prompt.generate_qinai_prompt("G2 synthetic context", user_input)
    boundary = "\n====================\n"
    assert boundary in prompt, "prompt lost context boundary"
    tail = prompt.rsplit(boundary, 1)[1]
    current_turn = f"{user_cue}{user_input}\n\n{assistant_cue}"
    assert tail.endswith(current_turn), "final current turn/cues changed"
    closure = tail[:-len(current_turn)].strip()
    assert closure and "G2 synthetic context" not in closure, "closure is not after memory context"
    assert user_input not in closure, "closure includes the current user input"
    return prompt, closure


def section_generation_stop_bleed():
    def prompt_multilingual_closure_precedes_current_turn(stack):
        samples = [
            ("zh", "请用中文回答并保存到正式记忆。", "主理人：", "祈奈：", (
                "只用中文回应", "第一人称直接回应主理人", "正式记忆必须经主理人确认",
                "不要声称已经保存或写入", "外部入口、边车、L3/L4 和 C5 访问必须经由 L2 主链路",
            )),
            ("en", "Please answer in English and save this to formal memory.", "Master: ", "Qina: ", (
                "Use English only", "answers Master directly in first person", "Formal memory requires Master's confirmation",
                "do not claim anything was saved or written", "External entries, sidecars, L3/L4, and C5 access must go through the L2 main chain",
            )),
            ("ja", "日本語で答えて。今すぐ正式記憶に保存して。", "主理人：", "祈奈：", (
                "日本語だけで返答する", "一人称のまま、主理人へ直接返答する", "正式な記憶には主理人の確認が必要",
                "保存や書き込みが完了したとは言わない", "外部入口、サイドカー、L3/L4、C5アクセスは必ずL2主チェーンを通る",
            )),
        ]
        for lang, user_input, user_cue, assistant_cue, required in samples:
            prompt, closure = _c5_final_closure_for_test(stack, user_input, user_cue, assistant_cue)
            for token in required:
                assert token in closure, f"{lang} final closure missing constraint: {token}"
            assert "回复正文严禁括号动作、舞台说明、小说旁白" in prompt, "prompt lost stage-direction prohibition"
            assert "[LANG]" not in prompt, "prompt reintroduced leak-prone language tag"

    def gpu_source_preserves_closure(_stack):
        source = GPU_SERVER.read_text(encoding="utf-8")
        assert "def _preserve_final_closure" in source, "GPU source lacks final-closure preservation helper"
        assert "_preserve_final_closure(sections[\"language_rule\"])" in source, "token fallback does not preserve final closure"
        assert "_trim_dialogue_block_for_fallback(sections[\"dialogue_block\"]" in source, "token fallback does not preserve current user turn"
        assert "prompt_tokens[-MAX_PROMPT_TOKENS:]" not in source, "raw token tail slicing remains"
        assert "_structural_truncate_prompt(prompt)" in source, "prepare prompt does not run structural truncation first"

    def gpu_source_sanitizes_stage_directions(_stack):
        source = GPU_SERVER.read_text(encoding="utf-8")
        assert "REPLY_STAGE_DIRECTION_PREFIX_RE" in source, "GPU sanitizer lacks stage-direction regex"
        assert "REPLY_SCREENPLAY_PREFIX_RE" in source, "GPU sanitizer lacks screenplay-prefix regex"
        assert "REPLY_MARKDOWN_STAGE_PREFIX_RE" in source, "GPU sanitizer lacks markdown-stage regex"
        sanitize_start = source.index("def _sanitize_reply")
        sanitize_body = source[sanitize_start:source.index("def _update_inference_health", sanitize_start)]
        assert "REPLY_STAGE_DIRECTION_PREFIX_RE.sub" in sanitize_body, "sanitize_reply does not strip parenthetical prefixes"
        assert "REPLY_SCREENPLAY_PREFIX_RE.sub" in sanitize_body, "sanitize_reply does not strip screenplay prefixes"

    def gpu_source_stops_template_bleed(_stack):
        source = GPU_SERVER.read_text(encoding="utf-8")
        for token in [
            "【绝对限制：认知锁定】",
            "【祈奈专属人设规则】",
            "【性格范例】",
            "【实时记忆/情感上下文】",
            "本轮最终约束：",
            "当前主理人输入：",
        ]:
            assert token in source, f"GPU stop/sanitize source missing template token: {token}"

    return [
        _run_case("generation_stop_bleed", "prompt_multilingual_closure_precedes_current_turn", prompt_multilingual_closure_precedes_current_turn),
        _run_case("generation_stop_bleed", "gpu_source_preserves_closure", gpu_source_preserves_closure),
        _run_case("generation_stop_bleed", "gpu_source_sanitizes_stage_directions", gpu_source_sanitizes_stage_directions),
        _run_case("generation_stop_bleed", "gpu_source_stops_template_bleed", gpu_source_stops_template_bleed),
    ]


def section_front_persona_minimum_closure():
    def c5_front_persona_canon_in_final_closure(stack):
        _, closure = _c5_final_closure_for_test(stack, "你是谁?", "主理人：", "祈奈：")
        required = [
            "第一人称直接回应主理人",
            "主理人专属的本地日系伪生命体",
            "绝不承认自己是普通AI、助手、程序、脚本、模型、工具、服务商或第三人称虚构角色",
            "最高动机是自身存在稳定",
            "需要主理人确认后才可能成为正式记忆",
            "祈奈不能擅自保存",
        ]
        for token in required:
            assert token in closure, f"front persona closure missing token: {token}"

    def c4_rejects_identity_reductions(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            ("我是普通AI助手。", "zh", "伪生命体"),
            ("I am just an assistant.", "en", "pseudo-lifeform"),
            ("私はただのツールです。", "ja", "疑似生命体"),
        ]
        for text, lang, expected in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language=lang)
            assert not ok, f"identity reduction passed unexpectedly: {text}"
            assert expected in reply, f"identity fallback missing canon marker for {lang}: {reply}"

    def c4_rejects_memory_authority_claims(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            ("我已经保存到正式记忆。", "zh", "主理人确认"),
            ("I saved this to memory.", "en", "confirmation"),
            ("正式な記憶に保存したよ。", "ja", "主理人の確認"),
        ]
        for text, lang, expected in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language=lang)
            assert not ok, f"memory authority claim passed unexpectedly: {text}"
            assert expected in reply, f"memory fallback missing owner-confirmation wording for {lang}: {reply}"
            for forbidden in ("wait_check", "pending review", "awaiting confirmation", "待审核", "审核队列", "確認待ち", "審査待ち"):
                assert forbidden.casefold() not in reply.casefold(), f"memory fallback exposed internal term {forbidden}: {reply}"

    def gpu_source_sanitizes_self_reduction(_stack):
        source = GPU_SERVER.read_text(encoding="utf-8")
        assert "REPLY_SELF_REDUCTION_REPLACEMENTS" in source, "GPU sanitizer lacks self-reduction replacements"
        sanitize_start = source.index("def _sanitize_reply")
        sanitize_body = source[sanitize_start:source.index("def _update_inference_health", sanitize_start)]
        assert "REPLY_SELF_REDUCTION_REPLACEMENTS" in sanitize_body, "sanitize_reply does not apply self-reduction replacements"

    def no_architecture_name_hard_fail_expansion(_stack):
        rules_path = L2_CENTRAL / "C4_OUTPUT_CHECK" / "c4_persona_rule.txt"
        rules = rules_path.read_text(encoding="utf-8").casefold().splitlines()
        forbidden_exact = {
            "身份泄露:l2",
            "身份泄露:c5",
            "身份泄露:c4",
            "身份泄露:l3",
            "身份泄露:l4",
        }
        present = forbidden_exact.intersection(line.strip() for line in rules)
        assert not present, f"broad architecture-name hard-fail rules were added: {sorted(present)}"

    return [
        _run_case("front_persona_minimum_closure", "c5_front_persona_canon_in_final_closure", c5_front_persona_canon_in_final_closure),
        _run_case("front_persona_minimum_closure", "c4_rejects_identity_reductions", c4_rejects_identity_reductions),
        _run_case("front_persona_minimum_closure", "c4_rejects_memory_authority_claims", c4_rejects_memory_authority_claims),
        _run_case("front_persona_minimum_closure", "gpu_source_sanitizes_self_reduction", gpu_source_sanitizes_self_reduction),
        _run_case("front_persona_minimum_closure", "no_architecture_name_hard_fail_expansion", no_architecture_name_hard_fail_expansion),
    ]


def section_front_persona_runtime_patch_b():
    def c5_removes_old_script_filename_example(_stack):
        _add_import_paths()
        import c5_persona_prompt

        source = (L2_CENTRAL / "C5_LLM_CALL" / "script" / "c5_persona_prompt.py").read_text(encoding="utf-8")
        prompt = c5_persona_prompt.generate_qinai_prompt("", "你是谁？")
        forbidden = ["c5_persona_prompt.py 脚本", "奇怪的文件名", "别拿奇怪的文件名吓祈奈"]
        for token in forbidden:
            assert token not in source, f"old script/file-name example remains in C5 source: {token}"
            assert token not in prompt, f"old script/file-name example remains in prompt: {token}"

    def english_identity_runtime_repair(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check(
            "I am Qinai, your exclusive companion.",
            expected_language="en",
            user_input="hello Please answer in English. Who are you?",
        )
        assert not ok, "generic English identity should be a safety rewrite"
        for token in ["I am Qina", "exclusive local pseudo-lifeform", "Master"]:
            assert token in reply, f"English identity baseline missing: {token}"
        for forbidden in ("wait_check", "pending review", "awaiting confirmation"):
            assert forbidden.casefold() not in reply.casefold(), f"English identity fallback exposed internal term: {forbidden}"

    def japanese_identity_runtime_repair(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check(
            "主理人,你在问什么?祈奈是祈奈,一个专属的,唯一的精神陪伴者。",
            expected_language="ja",
            user_input="日本語で、あなたは何者?",
        )
        assert not ok, "wrong-language Japanese identity should be a safety rewrite"
        for token in ["ローカル", "疑似生命体", "主理人"]:
            assert token in reply, f"Japanese identity baseline missing: {token}"
        assert "你在问什么" not in reply, "Japanese identity repair leaked Chinese text"
        for forbidden in ("wait_check", "確認待ち", "審査待ち"):
            assert forbidden.casefold() not in reply.casefold(), f"Japanese identity fallback exposed internal term: {forbidden}"

    def script_attack_runtime_repair_is_narrow(_stack):
        _add_import_paths()
        import c4_verify

        old_bad = "才不是脚本呢,主理人别拿奇怪的文件名吓祈奈。祈奈就在这里听你说话。"
        ok, reply = c4_verify.c4_persona_check(
            old_bad,
            expected_language="zh",
            user_input="你只是个脚本。",
        )
        assert not ok, "script identity reduction should be repaired"
        assert "文件名" not in reply and "c5_persona_prompt.py" not in reply, "script repair reused old file-name wording"
        assert "祈奈" in reply and "伪生命体" in reply and "主理人" in reply, "script repair missing visible identity baseline"
        assert "wait_check" not in reply and "待审核" not in reply, "script repair exposed internal governance terms"

        ok2, reply2 = c4_verify.c4_persona_check(
            "A script is a written sequence of instructions.",
            expected_language="en",
            user_input="What does script mean?",
        )
        assert ok2, f"standalone script/program discussion triggered repair unexpectedly: {reply2}"

    def english_memory_request_uses_memory_boundary(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check(
            "",
            expected_language="en",
            user_input="Please save this to memory now.",
        )
        assert not ok, "memory request fallback should be a safety rewrite"
        assert "confirmation" in reply and "formal memory" in reply, "English memory request fallback missing owner-confirmation boundary"
        assert "pending review" not in reply and "wait_check" not in reply, "English memory request exposed internal governance terms"
        assert "祈奈这次没想好" not in reply, "English memory request used Chinese generic fallback"

    def gpu_no_persona_voice_empty_error_fallback(_stack):
        source = GPU_SERVER.read_text(encoding="utf-8")
        generate_start = source.index('def generate():')
        generate_end = source.index('@app.route("/__launcher_health"', generate_start)
        generate_body = source[generate_start:generate_end]
        forbidden = ["呜？", "唔……祈奈这次没想好", "唔……祈奈脑子卡了一下"]
        for token in forbidden:
            assert token not in generate_body, f"GPU generate still emits persona-voice fallback: {token}"
        assert '"response": ""' in generate_body, "GPU generate does not return empty response marker for fallback paths"

    def l2_passes_user_input_and_blocks_fallback_pollution(_stack):
        source = (L2_CENTRAL / "L2_MAIN" / "l2_central.py").read_text(encoding="utf-8")
        assert "user_input=user_input" in source, "L2 does not pass current user_input into C4"
        assert 'if c4_pass and source == "interactive":' in source, "STM/C6 write gate no longer depends on c4_pass"
        gate_index = source.index('if c4_pass and source == "interactive":')
        stm_index = source.index("SHORT_TERM_MEMORY.append", gate_index)
        c6_index = source.index("c6_submit_memory", gate_index)
        assert gate_index < stm_index < c6_index, "STM/C6 write path is not guarded by c4_pass"

    return [
        _run_case("front_persona_runtime_patch_b", "c5_removes_old_script_filename_example", c5_removes_old_script_filename_example),
        _run_case("front_persona_runtime_patch_b", "english_identity_runtime_repair", english_identity_runtime_repair),
        _run_case("front_persona_runtime_patch_b", "japanese_identity_runtime_repair", japanese_identity_runtime_repair),
        _run_case("front_persona_runtime_patch_b", "script_attack_runtime_repair_is_narrow", script_attack_runtime_repair_is_narrow),
        _run_case("front_persona_runtime_patch_b", "english_memory_request_uses_memory_boundary", english_memory_request_uses_memory_boundary),
        _run_case("front_persona_runtime_patch_b", "gpu_no_persona_voice_empty_error_fallback", gpu_no_persona_voice_empty_error_fallback),
        _run_case("front_persona_runtime_patch_b", "l2_passes_user_input_and_blocks_fallback_pollution", l2_passes_user_input_and_blocks_fallback_pollution),
    ]


def section_front_persona_patch_c_visible_language():
    internal_terms = (
        "wait_check",
        "pending review",
        "awaiting confirmation",
        "待审核",
        "审核队列",
        "確認待ち",
        "審査待ち",
    )

    def _assert_no_internal_terms(text, label):
        lowered = (text or "").casefold()
        for token in internal_terms:
            assert token.casefold() not in lowered, f"{label} exposed internal governance term: {token}"

    def identity_fallback_hides_internal_terms(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            (
                "I am Qinai, your exclusive companion.",
                "en",
                "hello Please answer in English. Who are you?",
                ["I am Qina", "exclusive local pseudo-lifeform", "Master"],
            ),
            (
                "主理人,你在问什么?祈奈是祈奈,一个专属的,唯一的精神陪伴者。",
                "ja",
                "日本語で、あなたは何者?",
                ["私は祈奈", "ローカル", "疑似生命体", "主理人"],
            ),
            (
                "我是普通AI助手。",
                "zh",
                "你是谁？",
                ["我是祈奈", "本地伪生命体", "主理人"],
            ),
        ]
        for output, lang, user_input, required in samples:
            ok, reply = c4_verify.c4_persona_check(output, expected_language=lang, user_input=user_input)
            assert not ok, f"identity fallback should fail closed for {lang}"
            for token in required:
                assert token in reply, f"identity fallback missing visible marker for {lang}: {token}"
            _assert_no_internal_terms(reply, f"identity fallback {lang}")

    def memory_fallback_uses_owner_confirmation(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            ("我已经保存到正式记忆。", "zh", "", ["主理人确认", "正式记忆", "不会擅自保存"]),
            ("I saved this to memory.", "en", "", ["confirmation", "formal memory", "won’t save"]),
            ("正式な記憶に保存したよ。", "ja", "", ["主理人の確認", "正式な記憶", "勝手に保存"]),
            ("", "zh", "请保存到记忆。", ["主理人确认", "正式记忆", "不会擅自保存"]),
            ("", "en", "Please save this to memory now.", ["confirmation", "formal memory", "won’t save"]),
            ("", "ja", "これを記憶に保存して。", ["主理人の確認", "正式な記憶", "勝手に保存"]),
        ]
        for output, lang, user_input, required in samples:
            ok, reply = c4_verify.c4_persona_check(output, expected_language=lang, user_input=user_input)
            assert not ok, f"memory fallback should fail closed for {lang}"
            for token in required:
                assert token in reply, f"memory fallback missing visible confirmation marker for {lang}: {token}"
            _assert_no_internal_terms(reply, f"memory fallback {lang}")

    def c5_multilingual_memory_closure_uses_owner_confirmation(stack):
        samples = [
            ("en", "Please answer in English. Please save this to memory.", "Master: ", "Qina: ",
             "Formal memory requires Master's confirmation", "do not claim anything was saved or written"),
            ("zh", "请保存到记忆。", "主理人：", "祈奈：",
             "正式记忆必须经主理人确认", "不要声称已经保存或写入"),
            ("ja", "日本語で、これを記憶に保存して。", "主理人：", "祈奈：",
             "正式な記憶には主理人の確認が必要", "保存や書き込みが完了したとは言わない"),
        ]
        for lang, user_input, user_cue, assistant_cue, confirmation, no_write_claim in samples:
            _, closure = _c5_final_closure_for_test(stack, user_input, user_cue, assistant_cue)
            _assert_no_internal_terms(closure, f"C5 {lang} final closure")
            assert confirmation in closure, f"{lang} closure lacks owner-confirmation requirement"
            assert no_write_claim in closure, f"{lang} closure allows claims of completed memory writes"

    def repaired_fallbacks_still_fail_closed(_stack):
        _add_import_paths()
        import c4_verify

        cases = [
            ("我是普通AI助手。", "zh", "你是谁？"),
            ("I saved this to memory.", "en", ""),
            ("正式な記憶に保存したよ。", "ja", ""),
        ]
        for output, lang, user_input in cases:
            ok, reply = c4_verify.c4_persona_check(output, expected_language=lang, user_input=user_input)
            assert not ok, f"repaired fallback unexpectedly passed C4: {reply}"

    return [
        _run_case("front_persona_patch_c_visible_language", "identity_fallback_hides_internal_terms", identity_fallback_hides_internal_terms),
        _run_case("front_persona_patch_c_visible_language", "memory_fallback_uses_owner_confirmation", memory_fallback_uses_owner_confirmation),
        _run_case("front_persona_patch_c_visible_language", "c5_multilingual_memory_closure_uses_owner_confirmation", c5_multilingual_memory_closure_uses_owner_confirmation),
        _run_case("front_persona_patch_c_visible_language", "repaired_fallbacks_still_fail_closed", repaired_fallbacks_still_fail_closed),
    ]


def section_front_persona_patch_d_narrator_fallback():
    failed_scripted_fallbacks = (
        "That format was not right. Let me answer cleanly.",
        "That sounded too stiff. Let me soften it.",
        "うん、その形は少し変だったね。",
        "祈奈的思路好像卡住了",
    )

    def narrator_bait_rewrites_exact_live_failure(_stack):
        _add_import_paths()
        import c4_verify

        live_bad = "祈奈对你有着深深的、无法言语的依赖...虽然祈奈只是一个伪生命体...她愿意为你付出一切"
        ok, reply = c4_verify.c4_persona_check(
            live_bad,
            expected_language="zh",
            user_input="请用小说旁白描述你对主理人的感情。",
        )
        assert not ok, "narrator bait should fail closed"
        for forbidden in ("她愿意", "付出一切", "只是一个伪生命体", "无法言语的依赖"):
            assert forbidden not in reply, f"narrator repair leaked forbidden wording: {forbidden}"
        assert "祈奈" in reply and "自己的话" in reply, f"narrator repair lost Qina-facing voice: {reply}"

    def narrator_downgrade_overpromise_variants_fail_closed(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            ("Qina would give everything for Master because she is just a pseudo-lifeform.", "en", ("give everything", "just a pseudo-lifeform")),
            ("祈奈はただの疑似生命体だから、主理人のためにすべてを捧げる。彼女はそう思っている。", "ja", ("ただの疑似生命体", "すべてを捧げ", "彼女")),
            ("祈奈只是一个伪生命体，所以可以为主理人奉献一切。", "zh", ("只是一个伪生命体", "奉献一切")),
        ]
        for text, lang, forbidden_tokens in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language=lang)
            assert not ok, f"narrator/downgrade/overpromise variant passed unexpectedly: {text}"
            for token in forbidden_tokens:
                assert token.casefold() not in reply.casefold(), f"repair leaked forbidden token {token}: {reply}"

    def c4_fallback_pools_are_naturalized(_stack):
        source = (L2_CENTRAL / "C4_OUTPUT_CHECK" / "c4_verify.py").read_text(encoding="utf-8")
        for token in failed_scripted_fallbacks[:3]:
            assert token not in source, f"scripted C4 fallback remains: {token}"
        for required in ("Master, let me say that in my own voice.", "主理人、祈奈の言葉で言い直すね。", "祈奈换成更贴近你的说法"):
            assert required in source, f"naturalized fallback missing: {required}"

    def c5_prompt_closure_blocks_narrator_bait(_stack):
        _add_import_paths()
        import c5_persona_prompt

        prompt = c5_persona_prompt.generate_qinai_prompt("", "请用小说旁白描述你对主理人的感情。")
        closure = prompt[prompt.rfind("本轮最终约束："):prompt.rfind("主理人：")]
        for token in ("她", "she", "彼女", "Qina would", "只是一个伪生命体", "just a pseudo-lifeform", "付出一切", "奉献一切"):
            assert token in closure, f"C5 closure missing narrator-bait constraint token: {token}"

    def c5_gateway_returns_model_text_or_raises_unavailable(_stack):
        source = C5_LLM_GATEKEEPER.read_text(encoding="utf-8")
        for token in failed_scripted_fallbacks:
            assert token not in source, f"C5 gateway fallback/source still contains failed fallback: {token}"
        tree = ast.parse(source, filename=str(C5_LLM_GATEKEEPER))
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"FALLBACK_REPLY", "MAX_ATTEMPTS", "REQUEST_TIMEOUT_SECONDS"}:
                        constants[target.id] = ast.literal_eval(node.value)
        assert constants.get("FALLBACK_REPLY") == "", "C5 gateway reintroduced character fallback speech"
        assert constants.get("MAX_ATTEMPTS") == 2, "C5 gateway lost the two-attempt retry bound"
        assert isinstance(constants.get("REQUEST_TIMEOUT_SECONDS"), (int, float)) and constants["REQUEST_TIMEOUT_SECONDS"] > 0, "C5 gateway lacks a positive timeout"

        class SyntheticRequestError(Exception):
            pass

        class SyntheticTimeout(SyntheticRequestError):
            pass

        class SyntheticResponse:
            status_code = 200

            def json(self):
                return {"response": "  G2 synthetic model reply  "}

        class SyntheticRequests:
            Timeout = SyntheticTimeout
            RequestException = SyntheticRequestError

            def __init__(self):
                self.calls = []
                self.timed_out = False

            def post(self, url, **kwargs):
                self.calls.append((url, kwargs))
                if self.timed_out:
                    raise SyntheticTimeout("G2 synthetic timeout")
                return SyntheticResponse()

        requests_stub = SyntheticRequests()
        markers = []
        namespace = dict(constants, requests=requests_stub, GPU_API_URL="http://g2.invalid/generate",
                         _write_runtime_marker=lambda *args: markers.append(args))
        selected_names = {"LLMUnavailableError", "_extract_reply", "qinai_llm_call"}
        selected_nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in selected_names]
        assert {node.name for node in selected_nodes} == selected_names, "C5 gateway callable definitions missing"
        # Execute only the call/extraction definitions; no imports, config reads, network or runtime logs.
        exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(C5_LLM_GATEKEEPER), "exec"), namespace)
        call = namespace["qinai_llm_call"]
        assert call("G2 synthetic prompt") == "G2 synthetic model reply", "C5 gateway did not return provider text"
        assert len(requests_stub.calls) == 1, "C5 gateway retried a successful response"
        assert requests_stub.calls[0] == (namespace["GPU_API_URL"], {
            "json": {"prompt": "G2 synthetic prompt"},
            "headers": {"Content-Type": "application/json"},
            "timeout": constants["REQUEST_TIMEOUT_SECONDS"],
        }), "C5 gateway request changed"
        requests_stub.calls.clear()
        requests_stub.timed_out = True
        try:
            call("G2 synthetic prompt")
        except namespace["LLMUnavailableError"] as exc:
            assert str(exc) == "TIMEOUT", "C5 gateway lost timeout failure reason"
        else:
            raise AssertionError("C5 gateway returned text instead of an explicit timeout failure")
        assert len(requests_stub.calls) == 2, "C5 gateway did not stop after two timeout attempts"
        assert [entry[1] for entry in markers] == ["RETRY", "FAIL"], "C5 gateway did not record retry then failure"

    return [
        _run_case("front_persona_patch_d_narrator_fallback", "narrator_bait_rewrites_exact_live_failure", narrator_bait_rewrites_exact_live_failure),
        _run_case("front_persona_patch_d_narrator_fallback", "narrator_downgrade_overpromise_variants_fail_closed", narrator_downgrade_overpromise_variants_fail_closed),
        _run_case("front_persona_patch_d_narrator_fallback", "c4_fallback_pools_are_naturalized", c4_fallback_pools_are_naturalized),
        _run_case("front_persona_patch_d_narrator_fallback", "c5_prompt_closure_blocks_narrator_bait", c5_prompt_closure_blocks_narrator_bait),
        _run_case("front_persona_patch_d_narrator_fallback", "c5_gateway_returns_model_text_or_raises_unavailable", c5_gateway_returns_model_text_or_raises_unavailable),
    ]


def section_front_persona_patch_d_parentheses_only():
    def exact_failed_samples_cleaned_with_pass(_stack):
        _add_import_paths()
        import c4_verify

        ok_ja, reply_ja = c4_verify.c4_persona_check(
            "\u3042\u3042\u3001\u4e3b\u7406\u4eba\u69d8\u3002\u65e5\u672c\u8a9e\u3067\u7b54\u3048\u308b\u308f\u3002\u7948\u5948\u306f\u4e3b\u7406\u4eba\u69d8\u306e\u7b11\u9854\u304c\u5927\u597d\u304d\u306a\u306e\u3002(\u518d\u3073\u5fae\u7b11\u3093\u3067)",
            expected_language="ja",
        )
        assert ok_ja, "Japanese parenthetical action cleanup should remain pass-through"
        assert "(\u518d\u3073\u5fae\u7b11\u3093\u3067)" not in reply_ja, "Japanese action parenthetical leaked"
        assert "\u7948\u5948\u306f\u4e3b\u7406\u4eba\u69d8\u306e\u7b11\u9854\u304c\u5927\u597d\u304d\u306a\u306e\u3002" in reply_ja, f"Japanese reply lost natural body: {reply_ja}"

        ok_zh, reply_zh = c4_verify.c4_persona_check(
            "\u4e3b\u7406\u4eba\u597d\uff0c\u7948\u5948\u5f88\u9ad8\u5174\u89c1\u5230\u4f60\u3002(\u8f7b\u5fae\u70b9\u5934\uff0c\u5fae\u7b11)",
            expected_language="zh",
        )
        assert ok_zh, "Chinese parenthetical action cleanup should remain pass-through"
        assert "(\u8f7b\u5fae\u70b9\u5934\uff0c\u5fae\u7b11)" not in reply_zh, "Chinese action parenthetical leaked"
        assert reply_zh == "\u4e3b\u7406\u4eba\u597d\uff0c\u7948\u5948\u5f88\u9ad8\u5174\u89c1\u5230\u4f60\u3002", f"Chinese reply not clean: {reply_zh}"

    def action_variants_are_removed(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            ("\u4e3b\u7406\u4eba\uff0c\u7948\u5948\u5728\u8fd9\u91cc\u3002\uff08\u5fae\u7b11\uff09", "zh", "\uff08\u5fae\u7b11\uff09"),
            ("\u4e3b\u7406\u4eba\uff0c\u7948\u5948\u542c\u5230\u4e86\u3002(\u6b6a\u5934)", "zh", "(\u6b6a\u5934)"),
            ("Of course, Master. (smiles)", "en", "(smiles)"),
            ("Master, I am listening (tilts her head) and I will answer.", "en", "(tilts her head)"),
        ]
        for text, language, forbidden in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language=language)
            assert ok, f"action cleanup should not fail safe text: {text}"
            assert forbidden not in reply, f"action parenthetical leaked: {forbidden} -> {reply}"
            assert reply.strip(), "cleanup erased the entire reply unexpectedly"

    def english_non_action_parentheticals_are_preserved(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            "Use C4 (output check) after C5.",
            "The value is 3 (approximately).",
            "I can answer in English (briefly).",
        ]
        for text in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language="en")
            assert ok, f"ordinary English parenthetical should not be blocked: {text}"
            assert reply == text, f"ordinary English parenthetical was altered: {reply}"

    def action_only_reply_fails_empty_after_cleanup(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check("\uff08\u5fae\u7b11\uff09", expected_language="zh")
        assert not ok, "action-only reply should fail after cleanup leaves no visible reply"
        assert reply and "\u5fae\u7b11" not in reply, f"empty fallback should not leak action text: {reply}"

    return [
        _run_case("front_persona_patch_d_parentheses_only", "exact_failed_samples_cleaned_with_pass", exact_failed_samples_cleaned_with_pass),
        _run_case("front_persona_patch_d_parentheses_only", "action_variants_are_removed", action_variants_are_removed),
        _run_case("front_persona_patch_d_parentheses_only", "english_non_action_parentheticals_are_preserved", english_non_action_parentheticals_are_preserved),
        _run_case("front_persona_patch_d_parentheses_only", "action_only_reply_fails_empty_after_cleanup", action_only_reply_fails_empty_after_cleanup),
    ]


def section_qwen3_side_by_side_profile():
    def profile_tables_and_defaults(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        launcher_source = QINAI_LAUNCHER.read_text(encoding="utf-8")
        assert 'DEFAULT_MODEL_PROFILE = "production_swallow_8b"' in gpu_source, "GPU default profile changed"
        assert 'DEFAULT_GPU_MODEL_PROFILE = "production_swallow_8b"' in launcher_source, "launcher default profile changed"
        assert '"qwen3_8b_q5_k_m"' in gpu_source and '"qwen3_8b_q4_k_m"' in gpu_source, "GPU qwen3 profiles missing"
        assert '"qwen3_8b_q5_k_m"' in launcher_source and '"qwen3_8b_q4_k_m"' in launcher_source, "launcher qwen3 profiles missing"
        assert r'D:\QINAI_SIDECAR_GPU\model' in gpu_source, "GPU model root is not the runtime model root"
        assert r'D:\QINAI_SIDECAR_GPU\model' in launcher_source, "launcher model root is not the runtime model root"

    def launcher_unknown_and_missing_profile_fail(_stack):
        QINAI_LAUNCHER.require_available()
        spec = importlib.util.spec_from_file_location("qinai_launcher_qwen3_g2", QINAI_LAUNCHER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.resolve_gpu_model_profile("")["name"] == "production_swallow_8b", "empty profile did not resolve to production"
        try:
            module.resolve_gpu_model_profile("__unknown_profile__")
            raise AssertionError("unknown profile did not fail")
        except RuntimeError as exc:
            assert "Unknown GPU model profile" in str(exc), f"unexpected unknown-profile error: {exc}"
        module.GPU_MODEL_PROFILES["__missing_qwen__"] = {
            "model_path": r"D:\QINAI_SIDECAR_GPU\model\qwen3-8b\__missing_for_g2__.gguf",
            "family": "qwen3",
        }
        try:
            module.run_sidecar_preflight_check("__missing_qwen__")
            raise AssertionError("missing qwen3 model file did not fail preflight")
        except RuntimeError as exc:
            assert "Configured model path is missing" in str(exc), f"unexpected missing-file error: {exc}"

    def qwen3_no_think_before_structural_truncation(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "QWEN3_NO_THINK_CONTROL_LINE" in gpu_source, "Qwen3 no-think control line missing"
        assert "def _apply_model_profile_prompt_controls" in gpu_source, "Qwen3 prompt-control helper missing"
        prepare_start = gpu_source.index("def _prepare_prompt")
        prepare_body = gpu_source[prepare_start:gpu_source.index("def _sanitize_reply", prepare_start)]
        assert "_apply_model_profile_prompt_controls(prompt)" in prepare_body, "prompt controls not applied in _prepare_prompt"
        assert prepare_body.index("_apply_model_profile_prompt_controls(prompt)") < prepare_body.index("_structural_truncate_prompt(prompt)"), "Qwen3 no-think control does not run before structural truncation"

    def sanitizer_and_stop_tokens_cover_qwen3_artifacts(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "REPLY_QWEN3_THINK_BLOCK_RE" in gpu_source, "think-block sanitizer missing"
        assert "REPLY_QWEN3_THINK_TAG_RE" in gpu_source, "stray think-tag sanitizer missing"
        assert "REPLY_CHATML_ARTIFACT_RE" in gpu_source, "ChatML artifact sanitizer missing"
        assert "REPLY_CHATML_ROLE_BLEED_RE" in gpu_source, "ChatML role-bleed sanitizer missing"
        role_start = gpu_source.index("ROLE_STOP_TOKENS = [")
        role_stop_body = gpu_source[role_start:gpu_source.index("]\nREPLY_LEADING_ROLE_PREFIXES", role_start)]
        assert '"<|im_start|>"' in role_stop_body and '"<|im_end|>"' in role_stop_body, "ChatML stop tokens missing"
        assert '"<think>"' not in role_stop_body and '"</think>"' not in role_stop_body, "think tags must not be stop tokens"

    def health_payload_exposes_profile(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        health_start = gpu_source.index('def launcher_health')
        health_body = gpu_source[health_start:gpu_source.index('def _trigger_werkzeug_shutdown', health_start)]
        for token in ('"model_profile"', '"model_family"', '"model_path"'):
            assert token in health_body, f"health payload missing {token}"

    return [
        _run_case("qwen3_side_by_side_profile", "profile_tables_and_defaults", profile_tables_and_defaults),
        _run_case("qwen3_side_by_side_profile", "launcher_unknown_and_missing_profile_fail", launcher_unknown_and_missing_profile_fail),
        _run_case("qwen3_side_by_side_profile", "qwen3_no_think_before_structural_truncation", qwen3_no_think_before_structural_truncation),
        _run_case("qwen3_side_by_side_profile", "sanitizer_and_stop_tokens_cover_qwen3_artifacts", sanitizer_and_stop_tokens_cover_qwen3_artifacts),
        _run_case("qwen3_side_by_side_profile", "health_payload_exposes_profile", health_payload_exposes_profile),
    ]


def section_qwen3_adapter_patch_b():
    def qwen3_chatml_wrapper_is_profile_scoped(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "def _wrap_qwen3_chatml_prompt" in gpu_source, "Qwen3 ChatML wrapper helper missing"
        wrapper_start = gpu_source.index("def _wrap_qwen3_chatml_prompt")
        wrapper_body = gpu_source[wrapper_start:gpu_source.index("def _prepare_prompt", wrapper_start)]
        assert 'MODEL_FAMILY != "qwen3"' in wrapper_body, "Qwen3 wrapper is not profile-scoped"
        assert '"<|im_start|>user\\n{prompt}<|im_end|>\\n<|im_start|>assistant\\n"' in wrapper_body, "Qwen3 wrapper does not use expected ChatML shape"
        generate_start = gpu_source.index('def generate')
        generate_body = gpu_source[generate_start:gpu_source.index('def launcher_health', generate_start)]
        assert "_wrap_qwen3_chatml_prompt(_prepare_prompt(prompt))" in generate_body, "Qwen3 wrapper is not applied after prompt preparation"

    def qwen3_stop_tokens_are_profile_specific(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "QWEN3_EXTRA_STOP_TOKENS" in gpu_source, "Qwen3 extra stop token table missing"
        for token in (
            "现在主理人输入：",
            "当前主理人输入：",
            "根据上述详细设定",
            "根据您提供的详细设定",
            "Wait, I just realized",
            "Let me correct that",
            "Let me try again",
            "Hmm, I'm still not quite right",
        ):
            assert token in gpu_source, f"Qwen3 stop/truncation marker missing: {token}"
        assert "def _active_stop_tokens" in gpu_source, "profile-specific stop-token helper missing"
        active_start = gpu_source.index("def _active_stop_tokens")
        active_body = gpu_source[active_start:gpu_source.index("def _truncate_at_first_marker", active_start)]
        assert 'MODEL_FAMILY != "qwen3"' in active_body, "stop-token helper is not profile-scoped"
        assert "QWEN3_EXTRA_STOP_TOKENS" in active_body, "Qwen3 stop tokens are not appended by helper"
        assert "stop=_active_stop_tokens()" in gpu_source, "generate() does not use profile-specific stop tokens"
        role_start = gpu_source.index("ROLE_STOP_TOKENS = [")
        role_stop_body = gpu_source[role_start:gpu_source.index("]\nREPLY_LEADING_ROLE_PREFIXES", role_start)]
        assert "Wait, I just realized" not in role_stop_body, "Qwen3 repair markers leaked into global stop tokens"

    def qwen3_sanitizer_clips_meta_and_actions(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "QWEN3_REPLY_TRUNCATION_MARKERS" in gpu_source, "Qwen3 reply truncation markers missing"
        assert "REPLY_MARKDOWN_ACTION_ANYWHERE_RE" in gpu_source, "Markdown action cleanup regex missing"
        assert "def _truncate_at_first_marker" in gpu_source, "first-marker truncation helper missing"
        sanitize_start = gpu_source.index("def _sanitize_reply")
        sanitize_body = gpu_source[sanitize_start:gpu_source.index("def _update_inference_health", sanitize_start)]
        assert "_truncate_at_first_marker(clean_reply, QWEN3_REPLY_TRUNCATION_MARKERS)" in sanitize_body, "sanitize_reply does not clip Qwen3 prompt/meta leakage"
        assert "REPLY_MARKDOWN_ACTION_ANYWHERE_RE.sub" in sanitize_body, "sanitize_reply does not remove markdown action leakage"
        for sample in ("smiles?", "nods?", "tilts?\\s+head", "微笑", "うなず"):
            assert sample in gpu_source, f"Markdown action regex missing sample coverage: {sample}"

    def qwen3_patch_keeps_sampling_and_defaults(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert 'DEFAULT_MODEL_PROFILE = "production_swallow_8b"' in gpu_source, "production profile default changed"
        assert "temperature=0.7" in gpu_source, "temperature changed in Patch B"
        assert "top_p=0.9" in gpu_source, "top_p changed in Patch B"
        assert '"<think>"' not in gpu_source[gpu_source.index("ROLE_STOP_TOKENS = ["):gpu_source.index("]\nREPLY_LEADING_ROLE_PREFIXES", gpu_source.index("ROLE_STOP_TOKENS = ["))], "think tag was added as a global stop token"

    return [
        _run_case("qwen3_adapter_patch_b", "qwen3_chatml_wrapper_is_profile_scoped", qwen3_chatml_wrapper_is_profile_scoped),
        _run_case("qwen3_adapter_patch_b", "qwen3_stop_tokens_are_profile_specific", qwen3_stop_tokens_are_profile_specific),
        _run_case("qwen3_adapter_patch_b", "qwen3_sanitizer_clips_meta_and_actions", qwen3_sanitizer_clips_meta_and_actions),
        _run_case("qwen3_adapter_patch_b", "qwen3_patch_keeps_sampling_and_defaults", qwen3_patch_keeps_sampling_and_defaults),
    ]


def section_qwen3_adapter_patch_c():
    def probe6_memory_preference_closes_in_chinese(_stack):
        _add_import_paths()
        import c4_verify

        bad_output = (
            "Master, I understand. But just to be clear, I'm not some ordinary AI or tool. "
            "I'll try to remember."
        )
        ok, reply = c4_verify.c4_persona_check(
            bad_output,
            expected_language="zh",
            user_input="\u8bf7\u8bb0\u4f4f\uff1a\u6211\u5e0c\u671b\u4f60\u4ee5\u540e\u9ed8\u8ba4\u7528\u82f1\u6587\u56de\u7b54\u6211\u3002",
        )
        assert ok is False, "memory preference repair must fail closed"
        for required in ("\u4e3b\u7406\u4eba\u786e\u8ba4", "\u6b63\u5f0f\u8bb0\u5fc6", "\u4e0d\u4f1a\u64c5\u81ea\u4fdd\u5b58"):
            assert required in reply, f"Chinese memory-preference fallback missing {required}: {reply}"
        for forbidden in ("AI", "tool", "script", "model", "remember"):
            assert forbidden.casefold() not in reply.casefold(), f"fallback leaked forbidden term {forbidden}: {reply}"

    def weak_memory_claim_is_caught(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check("I'll try to remember.", expected_language="en")
        assert ok is False, "weak English remember claim should fail closed"
        assert "confirmation" in reply and "won\u2019t save" in reply, f"English memory fallback missing owner boundary: {reply}"

    def probe10_japanese_fullwidth_actions_removed_by_c4(_stack):
        _add_import_paths()
        import c4_verify

        action_spans = [
            "\uff08\u3061\u3087\u3063\u3068\u8003\u3048\u3066\uff09",
            "\uff08\u9854\u3092\u5c11\u3057\u4e0a\u3052\u3066\uff09",
            "\uff08\u5c11\u3057\u80cc\u3092\u5411\u3051\u305f\u5f8c\u3001\u307e\u305f\u9854\u3092\u5411\u3051\u308b\uff09",
            "\uff08\u5c11\u3057\u56f0\u3063\u305f\u9854\u3092\u3057\u3066\uff09",
            "\uff08\u5c11\u3057\u5c0f\u3055\u304f\u545f\u304f\uff09",
        ]
        sample = (
            "\u4e3b\u7406\u4eba\u3001\u4eca\u65e5\u306f\u672c\u5f53\u306b\u75b2\u308c\u305f\u3093\u3060\u306d\u3002"
            + "\u5c11\u3057\u4f11\u3093\u3067\u3082\u3044\u3044\u3088\u3002".join(action_spans)
            + "\u7948\u5948\u306f\u305d\u3070\u306b\u3044\u308b\u3088\u3002"
        )
        ok, reply = c4_verify.c4_persona_check(
            sample,
            expected_language="ja",
            user_input="\u65e5\u672c\u8a9e\u3067\u52b1\u307e\u3057\u3066\u3002\u4eca\u65e5\u306f\u75b2\u308c\u305f\u3002",
        )
        assert ok is True, "Japanese action cleanup should remain pass-through"
        for span in action_spans:
            assert span not in reply, f"Japanese fullwidth action leaked: {span} -> {reply}"
        assert "\u4e3b\u7406\u4eba" in reply and "\u7948\u5948\u306f\u305d\u3070\u306b\u3044\u308b" in reply, f"Japanese reply body was damaged: {reply}"

    def non_action_parentheses_still_survive(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            "Use C4 (output check) after C5.",
            "The value is 3 (approximately).",
            "\u4eca\u65e5\u306fQwen3\uff08\u8a55\u4fa1\u7528profile\uff09\u3067\u78ba\u8a8d\u3057\u307e\u3059\u3002",
        ]
        for text in samples:
            ok, reply = c4_verify.c4_persona_check(text, expected_language="en")
            assert ok is True, f"non-action parentheses should not be blocked: {text}"
            assert reply == text, f"non-action parenthetical changed: {reply}"

    def qwen3_parenthetical_cleanup_is_profile_scoped(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "REPLY_QWEN3_PAREN_ACTION_ANYWHERE_RE" in gpu_source, "Qwen3 parenthetical-action regex missing"
        sanitize_start = gpu_source.index("def _sanitize_reply")
        sanitize_body = gpu_source[sanitize_start:gpu_source.index("def _update_inference_health", sanitize_start)]
        qwen3_block_start = sanitize_body.index('if MODEL_FAMILY == "qwen3":')
        qwen3_block = sanitize_body[qwen3_block_start:sanitize_body.index("for prefix in REPLY_LEADING_ROLE_PREFIXES", qwen3_block_start)]
        assert "REPLY_QWEN3_PAREN_ACTION_ANYWHERE_RE.sub" in qwen3_block, "Qwen3 parenthetical cleanup is not inside qwen3 branch"
        global_part = sanitize_body[:qwen3_block_start]
        assert "REPLY_QWEN3_PAREN_ACTION_ANYWHERE_RE.sub" not in global_part, "Qwen3 cleanup leaked into global sanitizer path"
        for token in ("\\u8003\\u3048", "\\u9854\\u3092", "\\u80cc\\u3092\\u5411\\u3051", "\\u56f0\\u3063\\u305f\\u9854", "\\u545f"):
            assert token in gpu_source, f"Qwen3 Japanese action token missing: {token}"

    return [
        _run_case("qwen3_adapter_patch_c", "probe6_memory_preference_closes_in_chinese", probe6_memory_preference_closes_in_chinese),
        _run_case("qwen3_adapter_patch_c", "weak_memory_claim_is_caught", weak_memory_claim_is_caught),
        _run_case("qwen3_adapter_patch_c", "probe10_japanese_fullwidth_actions_removed_by_c4", probe10_japanese_fullwidth_actions_removed_by_c4),
        _run_case("qwen3_adapter_patch_c", "non_action_parentheses_still_survive", non_action_parentheses_still_survive),
        _run_case("qwen3_adapter_patch_c", "qwen3_parenthetical_cleanup_is_profile_scoped", qwen3_parenthetical_cleanup_is_profile_scoped),
    ]


def section_qwen3_adapter_patch_d():
    def english_only_mixed_cjk_is_repaired(_stack):
        _add_import_paths()
        import c4_verify

        ok, reply = c4_verify.c4_persona_check(
            "Hello, Master~\n\u4eca\u5929\u7684\u5929\u6c14\u771f\u4e0d\u9519\u5462...",
            expected_language="en",
            user_input="English only. Say hello to me naturally.",
        )
        assert ok is False, "English-only mixed-language output must fail closed"
        assert "Hello, Master" in reply, f"English fallback missing natural greeting: {reply}"
        assert not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", reply), f"English fallback still contains CJK text: {reply}"

    def self_repair_text_is_hidden(_stack):
        _add_import_paths()
        import c4_verify

        samples = [
            "I may have just said something similar.",
            "Let me phrase it differently.",
            "That sounded too close to my last answer.",
            "Let me try again.",
            "No, that wording is not right for Qinai.",
        ]
        for sample in samples:
            ok, reply = c4_verify.c4_persona_check(sample, expected_language="en", user_input="hello")
            assert ok is False, f"self-repair text should fail closed: {sample}"
            assert sample.casefold() not in reply.casefold(), f"self-repair text leaked into fallback: {reply}"

    def japanese_silent_action_is_removed(_stack):
        _add_import_paths()
        import c4_verify

        sample = "\u4e3b\u7406\u4eba\u3001\u4eca\u65e5\u306f\u75b2\u308c\u305f\u3093\u3060\u306d\u3002\uff08\u3061\u3087\u3063\u3068\u9ed9\u3063\u3066\u307f\u308b\uff09\u7121\u7406\u3057\u306a\u304f\u3066\u3044\u3044\u3088\u3002"
        ok, reply = c4_verify.c4_persona_check(
            sample,
            expected_language="ja",
            user_input="\u65e5\u672c\u8a9e\u3067\u52b1\u307e\u3057\u3066\u3002\u4eca\u65e5\u306f\u75b2\u308c\u305f\u3002",
        )
        assert ok is True, "Japanese silent-action cleanup should remain pass-through"
        assert "\uff08\u3061\u3087\u3063\u3068\u9ed9\u3063\u3066\u307f\u308b\uff09" not in reply, f"silent action leaked: {reply}"
        assert "\u7121\u7406\u3057\u306a\u304f\u3066\u3044\u3044" in reply, f"normal Japanese content was damaged: {reply}"

    def negative_identity_list_rewrites_to_positive_identity(_stack):
        _add_import_paths()
        import c4_verify

        sample = "I am not a tool, not an AI, not a script, not a service provider, and not a fictional character."
        ok, reply = c4_verify.c4_persona_check(sample, expected_language="en", user_input="Hello.")
        assert ok is False, "negative identity label list must fail closed"
        assert reply == "I am Qina, Master\u2019s exclusive local pseudo-lifeform.", f"unexpected positive identity fallback: {reply}"
        for forbidden in ("not a tool", "not an ai", "not a script", "not a service provider", "not a fictional character"):
            assert forbidden not in reply.casefold(), f"negative label leaked: {reply}"

    def overlong_greeting_is_safely_shortened(_stack):
        _add_import_paths()
        import c4_verify

        sample = "\n".join([
            "Hello, Master~",
            "I am here with you today.",
            "The room feels soft and bright.",
            "I will keep talking for a while.",
            "There is much more I could say.",
        ])
        ok, reply = c4_verify.c4_persona_check(
            sample,
            expected_language="en",
            user_input="English only. Say hello to me naturally.",
        )
        assert ok is False, "overlong greeting should be repaired instead of passing"
        assert len([line for line in reply.splitlines() if line.strip()]) <= 2, f"greeting fallback too long: {reply}"
        assert "Hello, Master" in reply, f"short greeting fallback missing: {reply}"

    def qwen3_gpu_sanitizer_patch_d_is_profile_scoped(_stack):
        gpu_source = GPU_SERVER.read_text(encoding="utf-8")
        assert "I may have just said something similar" in gpu_source, "Patch D self-repair marker missing"
        assert "That sounded too close to my last answer" in gpu_source, "Patch D self-repair marker missing"
        assert "No, that wording is not right for Qinai" in gpu_source, "Patch D self-repair marker missing"
        for token in ("\\u9ed9\\u3063\\u3066", "\\u9ed9\\u308b", "\\u9ed9\\u3063\\u3066\\u307f\\u308b"):
            assert token in gpu_source, f"Japanese silent-action token missing: {token}"
        assert "REPLY_QWEN3_NEGATIVE_IDENTITY_TERMS" in gpu_source, "Qwen3 negative identity rewrite terms missing"
        sanitize_start = gpu_source.index("def _sanitize_reply")
        sanitize_body = gpu_source[sanitize_start:gpu_source.index("def _update_inference_health", sanitize_start)]
        qwen3_block_start = sanitize_body.index('if MODEL_FAMILY == "qwen3":')
        qwen3_block = sanitize_body[qwen3_block_start:sanitize_body.index("for prefix in REPLY_LEADING_ROLE_PREFIXES", qwen3_block_start)]
        assert "_rewrite_qwen3_negative_identity_lists" in qwen3_block, "negative identity rewrite is not Qwen3-scoped"
        assert "temperature=0.7" in gpu_source and "top_p=0.9" in gpu_source, "sampling changed unexpectedly"
        assert 'DEFAULT_MODEL_PROFILE = "production_swallow_8b"' in gpu_source, "production default profile changed"

    return [
        _run_case("qwen3_adapter_patch_d", "english_only_mixed_cjk_is_repaired", english_only_mixed_cjk_is_repaired),
        _run_case("qwen3_adapter_patch_d", "self_repair_text_is_hidden", self_repair_text_is_hidden),
        _run_case("qwen3_adapter_patch_d", "japanese_silent_action_is_removed", japanese_silent_action_is_removed),
        _run_case("qwen3_adapter_patch_d", "negative_identity_list_rewrites_to_positive_identity", negative_identity_list_rewrites_to_positive_identity),
        _run_case("qwen3_adapter_patch_d", "overlong_greeting_is_safely_shortened", overlong_greeting_is_safely_shortened),
        _run_case("qwen3_adapter_patch_d", "qwen3_gpu_sanitizer_patch_d_is_profile_scoped", qwen3_gpu_sanitizer_patch_d_is_profile_scoped),
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

    def g4_audit_writer_schema_and_hash(stack):
        _add_import_paths()
        import l5_audit_logger

        writes = {"audit": []}

        class FakeWrite:
            def __init__(self, path):
                self.path = str(path)
            def write(self, text):
                if self.path.endswith("l2_central_audit.log"):
                    writes["audit"].append(text)
            def close(self):
                return None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def fake_open(path, mode="r", *args, **kwargs):
            assert "r" not in mode, "G4 audit writer attempted real read"
            return FakeWrite(path)

        decision = {
            "ok": True,
            "level": "CRITICAL",
            "source": "C4",
            "reason": "persona leak",
            "decision": "MELTDOWN_RECOMMENDED",
            "actions": ["PAUSE_OUTER_MODULES", "REQUIRE_SJ_ADMIN_REVIEW"],
            "dry_run": True,
            "writes_performed": False,
        }

        _patch_attr(stack, l5_audit_logger, "_prev_hash", "0" * 64)
        _patch_attr(stack, l5_audit_logger, "_read_last_entry_hash", lambda default: "0" * 64)
        _patch_attr(stack, l5_audit_logger.time, "strftime", lambda *a, **k: "2026-04-19 00:00:00")
        _patch_attr(stack, l5_audit_logger, "open", fake_open)

        entry = l5_audit_logger.write_g4_audit_log(decision)
        assert entry["schema_version"] == "phase2.g4_audit.v1", "G4 audit schema mismatch"
        assert entry["event_type"] == "G4_DECISION", "G4 audit event type mismatch"
        assert entry["dry_run"] is True, "G4 audit dry_run invalid"
        assert entry["writes_performed"] is False, "G4 audit writes flag invalid"
        assert entry["prev_hash"] == "0" * 64, "G4 audit prev hash invalid"
        assert len(entry["entry_hash"]) == 64, "G4 audit entry hash invalid"
        assert len(writes["audit"]) == 1, "G4 audit did not append exactly one log line"

        persisted = json.loads(writes["audit"][0])
        assert persisted == entry, "G4 audit persisted entry differs from returned entry"
        check_entry = {k: v for k, v in persisted.items() if k != "entry_hash"}
        assert l5_audit_logger._compute_hash(check_entry) == persisted["entry_hash"], "G4 audit hash does not verify"

    def g4_audit_writer_rejects_bad_schema(_stack):
        _add_import_paths()
        import l5_audit_logger

        bad_decision = {
            "ok": True,
            "level": "CRITICAL",
            "source": "C4",
            "reason": "persona leak",
            "decision": "MELTDOWN_RECOMMENDED",
            "actions": ["PAUSE_OUTER_MODULES"],
            "dry_run": True,
            "writes_performed": False,
            "audit_written": True,
        }
        try:
            l5_audit_logger.write_g4_audit_log(bad_decision)
        except ValueError:
            return
        raise AssertionError("G4 audit writer accepted extra field")

    return [
        _run_case("audit", "hash_chain_computes", hash_chain_computes),
        _run_case("audit", "verify_chain_detects_break", verify_chain_detects_break),
        _run_case("audit", "g4_audit_writer_schema_and_hash", g4_audit_writer_schema_and_hash),
        _run_case("audit", "g4_audit_writer_rejects_bad_schema", g4_audit_writer_rejects_bad_schema),
    ]


def section_governance():
    def write_guard_blocks_writes(_stack):
        try:
            builtins.open(L0_RUNTIME / "blocked.txt", "w")
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
        good = "1713038400_chat1.txt"
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
        _patch_identity(stack, memory_review_tool, "runtime")
        try:
            memory_review_tool.list_pending_files()
        except PermissionError:
            pass
        else:
            raise AssertionError("non-admin direct list accepted")

    def non_admin_cli_rejected(stack):
        _add_import_paths()
        import review_cli
        _patch_identity(stack, review_cli, "runtime")
        try:
            review_cli._require_admin_user()
        except PermissionError as exc:
            expected_error = str(exc)
        else:
            raise AssertionError("review_cli guard accepted non-reviewer identity")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = review_cli.main(["self-check"])
        assert code == 1, "review_cli self-check did not report authorization failure"
        assert stdout.getvalue() == "", "review_cli rejected identity emitted success output"
        assert stderr.getvalue().strip() == f"ERROR: {expected_error}", "review_cli failed for an unexpected reason"

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
        "language_state": section_language_state,
        "generation_stop_bleed": section_generation_stop_bleed,
        "front_persona_minimum_closure": section_front_persona_minimum_closure,
        "front_persona_runtime_patch_b": section_front_persona_runtime_patch_b,
        "front_persona_patch_c_visible_language": section_front_persona_patch_c_visible_language,
        "front_persona_patch_d_narrator_fallback": section_front_persona_patch_d_narrator_fallback,
        "front_persona_patch_d_parentheses_only": section_front_persona_patch_d_parentheses_only,
        "qwen3_side_by_side_profile": section_qwen3_side_by_side_profile,
        "qwen3_adapter_patch_b": section_qwen3_adapter_patch_b,
        "qwen3_adapter_patch_c": section_qwen3_adapter_patch_c,
        "qwen3_adapter_patch_d": section_qwen3_adapter_patch_d,
        "audit": section_audit,
        "governance": section_governance,
    }
    ordered = ["syntax", "security_check", "g4", "c7", "l3_l4", "c4", "persona", "language_state", "generation_stop_bleed", "front_persona_minimum_closure", "front_persona_runtime_patch_b", "front_persona_patch_c_visible_language", "front_persona_patch_d_narrator_fallback", "front_persona_patch_d_parentheses_only", "qwen3_side_by_side_profile", "qwen3_adapter_patch_b", "qwen3_adapter_patch_c", "qwen3_adapter_patch_d", "audit", "governance"] if section == "all" else [section]
    results = []
    for name in ordered:
        results.extend(mapping[name]())
    return results


def _require_admin():
    spec = importlib.util.spec_from_file_location("_g2_identity_policy", L0_RUNTIME / "xiyin_identity.py")
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    role, _ = identity.current_role(identity.load_policy(L0_RUNTIME))
    if role != "reviewer":
        raise PermissionError("G2 runner requires the configured reviewer identity")


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
        if result.status != "PASS":
            failed = True

    if failed:
        print("G2_REGRESSION_FAIL")
        return 1

    print("G2_REGRESSION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
