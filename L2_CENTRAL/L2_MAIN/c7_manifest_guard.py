# -*- coding: utf-8 -*-

import json
import ntpath
import os


def _xiyin_init_root():
    """A4/P4 (L2_MAIN) 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块
    （cwd/PYTHONPATH 注入）直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "xiyin_paths.py")
    preloaded = sys.modules.get("xiyin_paths")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_paths pseudo-module rejected: "
                           + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_paths", expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_paths"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_paths"]


_XIYIN_ROOT = _xiyin_init_root().project_root()
import os
from pathlib import Path


SCHEMA_VERSION = "phase1.c7_manifest.v1"
# P4: C7_ROOT 与受限集合由同一受信运行根派生（原权限意图映射，不删禁入项）
C7_ROOT = os.path.join(str(_XIYIN_ROOT), "L2_CENTRAL", "C7_PLUGINS")
APPROVED_CHAIN_ENTRY = "submit_to_chain(text, source)"

TOP_LEVEL_KEYS = {
    "schema_version",
    "status",
    "security_note",
    "entry_contract",
    "permission_policy",
    "modules",
}
PERMISSION_POLICY_KEYS = {"default_enabled", "write_whitelist", "forbidden"}
ENTRY_CONTRACT_KEYS = {"approved_chain_entry", "forbidden_direct_access"}
MODULE_KEYS = {"id", "name", "enabled", "entry", "permissions"}
MODULE_PERMISSION_KEYS = {"write", "forbidden"}

FORBIDDEN_ENTRY_SEGMENTS = {
    "c5_llm_call",
    "l0_mother",
    "l0_source",
    "l0_projection",
}
FORBIDDEN_ENTRY_SEQUENCE = ("l1_memory", "passed")
DEFAULT_FORBIDDEN_PATHS = [
    os.path.join(str(_XIYIN_ROOT), "L0_MOTHER"),
    os.path.join(str(_XIYIN_ROOT), "L1_MEMORY", "passed"),
    os.path.join(str(_XIYIN_ROOT), "L2_CENTRAL", "C5_LLM_CALL"),
    r"D:\L0_RUNTIME",  # 外部卷禁入意图原样保留
]


class ManifestValidationError(ValueError):
    pass


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_manifest(data)


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ManifestValidationError("manifest must be an object")

    _reject_extra_keys(manifest, TOP_LEVEL_KEYS, "manifest")
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    _require(isinstance(manifest.get("status"), str), "status must be a string")
    _require(isinstance(manifest.get("security_note"), str), "security_note must be a string")

    entry_contract = manifest.get("entry_contract")
    _require(isinstance(entry_contract, dict), "entry_contract must be an object")
    _reject_extra_keys(entry_contract, ENTRY_CONTRACT_KEYS, "entry_contract")
    _require(entry_contract.get("approved_chain_entry") == APPROVED_CHAIN_ENTRY, "invalid approved_chain_entry")
    _require_string_list(entry_contract.get("forbidden_direct_access"), "entry_contract.forbidden_direct_access")

    policy = manifest.get("permission_policy")
    _require(isinstance(policy, dict), "permission_policy must be an object")
    _reject_extra_keys(policy, PERMISSION_POLICY_KEYS, "permission_policy")
    _require(type(policy.get("default_enabled")) is bool, "permission_policy.default_enabled must be bool")
    write_whitelist = _validate_path_list(policy.get("write_whitelist"), "permission_policy.write_whitelist")
    forbidden = _validate_path_list(policy.get("forbidden"), "permission_policy.forbidden") + [
        _normalize_absolute_path(item, f"default_forbidden[{index}]")
        for index, item in enumerate(DEFAULT_FORBIDDEN_PATHS)
    ]

    modules = manifest.get("modules")
    _require(isinstance(modules, list), "modules must be a list")

    clean_modules = []
    for index, module in enumerate(modules):
        clean_modules.append(_validate_module(module, index, write_whitelist, forbidden))

    return {
        "schema_version": manifest["schema_version"],
        "status": manifest["status"],
        "security_note": manifest["security_note"],
        "entry_contract": {
            "approved_chain_entry": entry_contract["approved_chain_entry"],
            "forbidden_direct_access": list(entry_contract["forbidden_direct_access"]),
        },
        "permission_policy": {
            "default_enabled": policy["default_enabled"],
            "write_whitelist": write_whitelist,
            "forbidden": forbidden,
        },
        "modules": clean_modules,
    }


def select_enabled_sidecars(manifest: dict) -> list:
    clean = validate_manifest(manifest)
    return [module for module in clean["modules"] if module["enabled"] is True]


def _validate_module(module, index, write_whitelist, forbidden):
    label = f"modules[{index}]"
    if not isinstance(module, dict):
        raise ManifestValidationError(f"{label} must be an object")

    _reject_extra_keys(module, MODULE_KEYS, label)
    module_id = _require_clean_string(module.get("id"), f"{label}.id")
    name = _require_clean_string(module.get("name"), f"{label}.name")
    enabled = module.get("enabled")
    if type(enabled) is not bool:
        raise ManifestValidationError(f"{label}.enabled must be strict bool")

    entry = _validate_entry_path(module.get("entry"), enabled)
    permissions = module.get("permissions")
    if not isinstance(permissions, dict):
        raise ManifestValidationError(f"{label}.permissions must be an object")
    _reject_extra_keys(permissions, MODULE_PERMISSION_KEYS, f"{label}.permissions")

    module_forbidden = _validate_path_list(permissions.get("forbidden"), f"{label}.permissions.forbidden")
    combined_forbidden = forbidden + module_forbidden
    write_paths = _validate_path_list(permissions.get("write"), f"{label}.permissions.write")
    for write_path in write_paths:
        _require(not _is_under_any(write_path, combined_forbidden), f"{label}.permissions.write targets forbidden path")
        _require(_is_under_any(write_path, write_whitelist), f"{label}.permissions.write is outside whitelist")

    return {
        "id": module_id,
        "name": name,
        "enabled": enabled,
        "entry": entry,
        "permissions": {
            "write": write_paths,
            "forbidden": module_forbidden,
        },
    }


def _validate_entry_path(value, require_exists):
    path = _normalize_absolute_path(value, "module.entry")
    _require(_is_under(path, C7_ROOT), "entry must stay under C7 root")
    _require(not _has_forbidden_entry_segment(path), "entry references forbidden core segment")
    _require(not _is_under_any(path, DEFAULT_FORBIDDEN_PATHS), "entry targets forbidden path")
    _require(path.lower().endswith(".py"), "entry must point to a .py file")

    if os.path.exists(path):
        resolved_entry = str(Path(path).resolve(strict=True))
        resolved_root = str(Path(C7_ROOT).resolve(strict=False))
        _require(_is_under(resolved_entry, resolved_root), "resolved entry escapes C7 root")
        if require_exists:
            _require(os.path.isfile(path), "enabled entry must exist and be a file")
    elif require_exists:
        raise ManifestValidationError("enabled entry must exist and be a file")

    return path


def _validate_path_list(value, label):
    if not isinstance(value, list):
        raise ManifestValidationError(f"{label} must be a list")
    return [_normalize_absolute_path(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _normalize_absolute_path(value, label):
    text = _require_clean_string(value, label)
    if text.startswith("\\\\") or text.startswith("//"):
        raise ManifestValidationError(f"{label} must not be UNC path")
    if not ntpath.isabs(text):
        raise ManifestValidationError(f"{label} must be absolute")

    normalized_separators = text.replace("/", "\\")
    _require(".." not in [part for part in normalized_separators.split("\\") if part], f"{label} must not contain traversal")

    return ntpath.normpath(text)


def _require_clean_string(value, label):
    if not isinstance(value, str):
        raise ManifestValidationError(f"{label} must be a string")
    if not value.strip():
        raise ManifestValidationError(f"{label} must not be empty")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ManifestValidationError(f"{label} contains control character")
    return value.strip()


def _require_string_list(value, label):
    if not isinstance(value, list):
        raise ManifestValidationError(f"{label} must be a list")
    for index, item in enumerate(value):
        _require_clean_string(item, f"{label}[{index}]")


def _reject_extra_keys(data, allowed, label):
    extras = set(data) - set(allowed)
    if extras:
        raise ManifestValidationError(f"{label} contains unsupported field: {sorted(extras)[0]}")


def _is_under(path, root):
    try:
        candidate = ntpath.normcase(ntpath.normpath(path))
        anchor = ntpath.normcase(ntpath.normpath(root))
        return ntpath.commonpath([candidate, anchor]) == anchor
    except ValueError:
        return False


def _is_under_any(path, roots):
    return any(_is_under(path, root) for root in roots)


def _has_forbidden_entry_segment(path):
    parts = [part.lower() for part in ntpath.normpath(path).split("\\") if part]
    if any(part in FORBIDDEN_ENTRY_SEGMENTS for part in parts):
        return True
    for index in range(0, max(0, len(parts) - 1)):
        if tuple(parts[index:index + 2]) == FORBIDDEN_ENTRY_SEQUENCE:
            return True
    return False


def _require(condition, message):
    if not condition:
        raise ManifestValidationError(message)
