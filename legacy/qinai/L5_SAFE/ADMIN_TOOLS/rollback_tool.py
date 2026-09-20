# -*- coding: utf-8 -*-
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import snapshot_tool as _snapshot_tool
if Path(_snapshot_tool.__file__).resolve() != Path(__file__).resolve().with_name("snapshot_tool.py"):
    raise RuntimeError("snapshot_tool import source mismatch")
from snapshot_tool import _create_confirmed_snapshot, _validate_tree, _stamp, _management


def _xiyin_init_root():
    """A4/P2 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>\\xiyin_paths.py（本文件位于 <运行根>\\L5_SAFE\\ADMIN_TOOLS）；
    无上溯、无旧盘符回退；不为加载路径启动 L2/模型；sys.modules 中已存在
    且 __file__ 不符的同名伪模块（cwd/PYTHONPATH 注入）直接拒绝。
    """
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(here)),
                            "xiyin_paths.py")
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
    return sys.modules["xiyin_paths"].project_root()


_XIYIN_ROOT = _xiyin_init_root()
import xiyin_paths as _paths


def _xiyin_identity():
    """A4/P3 共享身份适配器一次性显式加载（固定布局 <运行根>\\xiyin_identity.py；
    同名伪模块拒绝；无环境变量改选配置来源）。"""
    import importlib.util
    import sys
    expected = os.path.join(str(_XIYIN_ROOT), "xiyin_identity.py")
    preloaded = sys.modules.get("xiyin_identity")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_identity pseudo-module rejected: "
                           + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_identity",
                                                      expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_identity"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_identity"]


# P4: 恢复目标与快照/审计根由同一受信运行根派生；恢复目标仅取当前树的
# 受信位置，快照元数据中的旧绝对路径不用于目标定位（A6）。
_XIYIN_DATA = _paths.resolve_path("data")
TARGET_DIRS = {
    "wait_check": str(_XIYIN_DATA / "wait_check"),
    "passed": str(_XIYIN_DATA / "passed"),
}

SNAPSHOT_ROOT = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "G1_SNAPSHOT", "memory")
AUDIT_DIR = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "review_audit")
SNAPSHOT_ID_PATTERN = re.compile(r"^\d{8}_\d{6}$")
HARDWARE_PROFILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "L2_CENTRAL", "hardware_profile.json")
)
# 仅作 operator 参数的显示默认值；授权完全取决于令牌 SID 与部署策略，
# 与该常量无关（P3/A2 解绑；审核+快照恢复共用 reviewer 身份集）。
EXPECTED_OPERATOR = None


def _validate_dirs():
    for directory in [SNAPSHOT_ROOT, AUDIT_DIR, *TARGET_DIRS.values()]:
        _paths._inside(_XIYIN_ROOT, Path(directory))
    if len({Path(p).resolve() for p in TARGET_DIRS.values()}) != len(TARGET_DIRS):
        raise ValueError("snapshot target directories must be distinct")
    return None


def _ensure_dirs():
    _validate_dirs()
    os.makedirs(SNAPSHOT_ROOT, exist_ok=True)
    os.makedirs(AUDIT_DIR, exist_ok=True)
    for _, path in TARGET_DIRS.items():
        os.makedirs(path, exist_ok=True)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_runtime_policy() -> dict:
    with open(HARDWARE_PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = json.load(f)
    return profile.get("memory_policy", {})


def _require_admin_user() -> str:
    """Verify the current Windows token under the selected account mode."""
    return _management().verified_operator(_XIYIN_ROOT)


def _validate_operator(operator: str) -> str:
    """operator 参数仅显示；审计主体取验证结果，不匹配显式报错（A2）。"""
    verified = _require_admin_user()
    if operator is None:
        return verified
    if not isinstance(operator, str):
        raise ValueError("Operator is required")
    if operator.casefold() != verified.casefold():
        raise PermissionError(
            f"Operator argument {operator!r} does not match verified "
            f"reviewer {verified!r}")
    return verified


def _validate_snapshot_id(snapshot_id: str) -> str:
    if not snapshot_id or not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
        raise ValueError(f"Invalid snapshot id: {snapshot_id}")
    return snapshot_id


def _resolve_snapshot_dir(snapshot_id: str) -> str:
    safe_snapshot_id = _validate_snapshot_id(snapshot_id)
    root = os.path.abspath(SNAPSHOT_ROOT)
    snap_dir = os.path.abspath(os.path.join(root, safe_snapshot_id))
    if os.path.commonpath([root, snap_dir]) != root:
        raise ValueError(f"Snapshot path escaped root: {snapshot_id}")
    return str(_paths._inside(_XIYIN_ROOT, Path(snap_dir)))


def _audit(action: str, detail: dict):
    day = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(AUDIT_DIR, f"rollback_audit_{day}.jsonl")
    record = {
        "time": _now(),
        "action": action,
        "detail": detail,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def restore_memory_snapshot(snapshot_id: str, operator: str = None) -> bool:
    safe_operator = _validate_operator(operator)
    _validate_dirs()
    memory_policy = _load_runtime_policy()
    safe_snapshot_id = _validate_snapshot_id(snapshot_id)
    snap_dir = _resolve_snapshot_dir(safe_snapshot_id)
    if not os.path.isdir(snap_dir):
        raise FileNotFoundError(f"Snapshot not found: {safe_snapshot_id}")

    # Validate every source before a protective snapshot or target replacement.
    for key in TARGET_DIRS:
        if not os.path.isdir(os.path.join(snap_dir, key)):
            raise FileNotFoundError(f"Snapshot missing target: {key}")

    # Validate all recursive inputs before any target deletion or backup.
    for key, target in TARGET_DIRS.items():
        _validate_tree(Path(snap_dir) / key)
        _validate_tree(target)

    protective_snapshot_id = _stamp() if memory_policy.get("snapshot_required_before_restore", True) else None
    scope = {**TARGET_DIRS, "snapshot_source": snap_dir}
    if protective_snapshot_id is not None:
        scope["created_snapshot"] = _resolve_snapshot_dir(protective_snapshot_id)
    with _management().management_action(
            _XIYIN_ROOT, "SNAPSHOT_RESTORE", scope, operator=safe_operator,
            detail={"snapshot_id": safe_snapshot_id, "replaces_existing_target_contents": True}) as lease:
        _restore_confirmed_snapshot(lease, safe_operator, safe_snapshot_id, protective_snapshot_id)
    return True


def _restore_confirmed_snapshot(lease, safe_operator, safe_snapshot_id, protective_snapshot_id):
    snap_dir = _resolve_snapshot_dir(safe_snapshot_id)
    scope = {**TARGET_DIRS, "snapshot_source": snap_dir}
    if protective_snapshot_id is not None:
        scope["created_snapshot"] = _resolve_snapshot_dir(protective_snapshot_id)
    _management().require_scope(lease, _XIYIN_ROOT, {"SNAPSHOT_RESTORE"}, scope)
    safe_operator = _management().verified_operator(_XIYIN_ROOT, safe_operator)
    # Recheck after human confirmation, before any tree is changed.
    _validate_dirs()
    for key, target in TARGET_DIRS.items():
        if not os.path.isdir(os.path.join(snap_dir, key)):
            raise FileNotFoundError(f"Snapshot missing target: {key}")
        _validate_tree(Path(snap_dir) / key)
        _validate_tree(target)
    if protective_snapshot_id is not None:
        _create_confirmed_snapshot(lease, safe_operator, protective_snapshot_id)
    _ensure_dirs()

    for key, target_dir in TARGET_DIRS.items():
        src_dir = os.path.join(snap_dir, key)
        if not os.path.isdir(src_dir):
            raise FileNotFoundError(f"Snapshot missing target: {key}")

        for name in os.listdir(target_dir):
            full = os.path.join(target_dir, name)
            if os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
            elif os.path.isdir(full):
                shutil.rmtree(full)

        for name in os.listdir(src_dir):
            src_item = os.path.join(src_dir, name)
            dst_item = os.path.join(target_dir, name)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
            else:
                shutil.copy2(src_item, dst_item)

    _audit("SNAPSHOT_RESTORE", {
        "snapshot_id": safe_snapshot_id,
        "operator": safe_operator,
        "protective_snapshot_id": protective_snapshot_id,
        "policy_snapshot_required_before_restore": protective_snapshot_id is not None,
    })
    return True


if __name__ == "__main__":
    print("Use restore_memory_snapshot(snapshot_id) explicitly from admin workflow.")
