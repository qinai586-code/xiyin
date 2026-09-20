# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


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


def _management():
    import importlib.util
    import sys
    expected = Path(_XIYIN_ROOT) / "xiyin_management.py"
    module = sys.modules.get("xiyin_management")
    if module is not None:
        if Path(getattr(module, "__file__", "")).resolve() != expected.resolve():
            raise RuntimeError("xiyin_management import source mismatch")
        return module
    spec = importlib.util.spec_from_file_location("xiyin_management", expected)
    module = importlib.util.module_from_spec(spec)
    sys.modules["xiyin_management"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("xiyin_management", None)
        raise
    return module


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


# F6: TARGET_DIRS 与 rollback_tool 一样，由同一受信数据根派生。
_XIYIN_DATA = _paths.resolve_path("data")
TARGET_DIRS = {
    "wait_check": str(_XIYIN_DATA / "wait_check"),
    "passed": str(_XIYIN_DATA / "passed"),
}

# P4: 快照/审计目录由同一受信运行根派生（治理数据同根；不迁移历史快照）
_XIYIN_SNAPSHOT_ROOT = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "G1_SNAPSHOT", "memory")
_XIYIN_AUDIT_DIR = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "review_audit")
SNAPSHOT_ROOT = _XIYIN_SNAPSHOT_ROOT
AUDIT_DIR = _XIYIN_AUDIT_DIR
SNAPSHOT_ID_PATTERN = re.compile(r"^\d{8}_\d{6}$")
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


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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
    log_path = os.path.join(AUDIT_DIR, f"snapshot_audit_{day}.jsonl")
    record = {
        "time": _now(),
        "action": action,
        "detail": detail,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _validate_tree(path):
    """Preflight recursive snapshot operations without following reparse points."""
    path = Path(path)
    _paths._inside(_XIYIN_ROOT, path)
    if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("snapshot tree root is a reparse point")
    if not path.exists():
        # Existing behavior creates absent target areas, but only after the
        # operation's explicit confirmation rather than during preflight.
        return
    def fail(error):
        raise error
    for base, dirs, files in os.walk(path, followlinks=False, onerror=fail):
        for name in dirs + files:
            child = Path(base) / name
            if child.is_symlink() or getattr(child.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("snapshot tree contains a reparse point")


def create_memory_snapshot(operator: str = None) -> str:
    safe_operator = _validate_operator(operator)
    _validate_dirs()
    for directory in TARGET_DIRS.values():
        _validate_tree(directory)
    snap_id = _stamp()
    snap_dir = _resolve_snapshot_dir(snap_id)
    with _management().management_action(
            _XIYIN_ROOT, "SNAPSHOT_CREATE", {**TARGET_DIRS, "created_snapshot": snap_dir},
            operator=safe_operator) as lease:
        return _create_confirmed_snapshot(lease, safe_operator, snap_id)


def _create_confirmed_snapshot(lease, safe_operator, snap_id):
    """The restore path reuses its already-confirmed, scope-bound operation."""
    snap_dir = _resolve_snapshot_dir(snap_id)
    _management().require_scope(lease, _XIYIN_ROOT, {"SNAPSHOT_CREATE", "SNAPSHOT_RESTORE"},
                                {**TARGET_DIRS, "created_snapshot": snap_dir})
    safe_operator = _management().verified_operator(_XIYIN_ROOT, safe_operator)
    _ensure_dirs()
    for directory in TARGET_DIRS.values():
        _validate_tree(directory)
    os.makedirs(snap_dir, exist_ok=False)

    for key, src_dir in TARGET_DIRS.items():
        dst_dir = os.path.join(snap_dir, key)
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

    metadata = {
        "snapshot_id": snap_id,
        "operator": safe_operator,
        "time": _now(),
        "targets": TARGET_DIRS,
    }

    with open(os.path.join(snap_dir, "snapshot_meta.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    _audit("SNAPSHOT_CREATE", metadata)
    return str(_paths._inside(_XIYIN_ROOT, Path(snap_dir)))


def list_snapshots():
    _require_admin_user()
    _validate_dirs()
    if not os.path.isdir(SNAPSHOT_ROOT):
        return []
    items = []
    for name in os.listdir(SNAPSHOT_ROOT):
        if not SNAPSHOT_ID_PATTERN.fullmatch(name):
            continue
        full = _resolve_snapshot_dir(name)
        if os.path.isdir(full):
            items.append(name)
    return sorted(items, reverse=True)


if __name__ == "__main__":
    path = create_memory_snapshot()
    print(f"SNAPSHOT_CREATED: {path}")
