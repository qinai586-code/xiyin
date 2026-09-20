# -*- coding: utf-8 -*-
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")

import json
import os
import re
import shutil
import unicodedata
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


# P4: 治理目录由受信根统一派生（同一数据根映射；EXPECTED 仍为边界校验基准）
_XIYIN_DATA = _paths.resolve_path("data")
EXPECTED_WAIT_CHECK_DIR = str(_XIYIN_DATA / "wait_check")
EXPECTED_PASSED_DIR = str(_XIYIN_DATA / "passed")
EXPECTED_REJECTED_DIR = str(_XIYIN_DATA / "rejected")
EXPECTED_AUDIT_DIR = str(_XIYIN_ROOT / "L5_SAFE" / "review_audit")

WAIT_CHECK_DIR = EXPECTED_WAIT_CHECK_DIR
PASSED_DIR = EXPECTED_PASSED_DIR
REJECTED_DIR = EXPECTED_REJECTED_DIR
AUDIT_DIR = EXPECTED_AUDIT_DIR

# 仅作 operator 参数的显示默认值；授权完全取决于令牌 SID 与部署策略，
# 与该常量无关（P3/A2 解绑）。审核目录常量由 P4 批次统一同根重接线。
EXPECTED_OPERATOR = None  # F9: 默认取验证出的审核显示名。
FILENAME_PATTERN = re.compile(r"^[0-9]{10}_(?:chat[0-9]+|[0-9a-f]{32}_chat)\.txt$")
MAX_REASON_LENGTH = 240


def _canonical_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("Path is required")
    if "\x00" in path:
        raise ValueError("Path contains NUL byte")
    return os.path.normcase(os.path.abspath(os.path.realpath(os.path.normpath(path))))


def _same_path(left: str, right: str) -> bool:
    return _canonical_path(left) == _canonical_path(right)


def validate_config_paths():
    expected_pairs = [
        ("WAIT_CHECK_DIR", WAIT_CHECK_DIR, EXPECTED_WAIT_CHECK_DIR),
        ("PASSED_DIR", PASSED_DIR, EXPECTED_PASSED_DIR),
        ("REJECTED_DIR", REJECTED_DIR, EXPECTED_REJECTED_DIR),
        ("AUDIT_DIR", AUDIT_DIR, EXPECTED_AUDIT_DIR),
    ]
    for label, current, expected in expected_pairs:
        _paths._inside(_XIYIN_ROOT, Path(current))
        if not _same_path(current, expected):
            raise ValueError(f"{label} changed from expected governance path")

    # A6: the governance roots themselves must be plain dirs at their trusted
    # bases - area-root junction, subdirectory external link, or aliasing two
    # different governance dirs to the same directory are all refused.
    import sys as _sys
    _trusted = {
        "WAIT_CHECK_DIR": (_XIYIN_DATA, EXPECTED_WAIT_CHECK_DIR),
        "PASSED_DIR": (_XIYIN_DATA, EXPECTED_PASSED_DIR),
        "REJECTED_DIR": (_XIYIN_DATA, EXPECTED_REJECTED_DIR),
        "AUDIT_DIR": (_XIYIN_ROOT, EXPECTED_AUDIT_DIR),
    }
    for label, current, expected in expected_pairs:
        cur_path = os.path.abspath(current)
        if os.path.lexists(cur_path):
            st = os.lstat(cur_path)
            if getattr(st, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"{label} is a reparse point: {current}")
            base = os.path.abspath(_trusted[label][0])
            if os.path.commonpath([os.path.normcase(cur_path),
                                   os.path.normcase(os.path.abspath(base))]) !=                     os.path.normcase(os.path.abspath(base)):
                raise ValueError(f"{label} escapes its trusted base: {current}")
    resolved = {os.path.normcase(os.path.abspath(d)) for d in
                (WAIT_CHECK_DIR, PASSED_DIR, REJECTED_DIR)}
    if len(resolved) != 3:
        raise ValueError("governance dirs must be distinct "
                         "(wait_check/passed/rejected aliasing refused)")


def _ensure_dirs():
    validate_config_paths()
    for path in [WAIT_CHECK_DIR, PASSED_DIR, REJECTED_DIR, AUDIT_DIR]:
        os.makedirs(path, exist_ok=True)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _has_control_char(value: str) -> bool:
    return any(unicodedata.category(ch).startswith("C") for ch in value)


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise ValueError("Filename is required")
    if "\x00" in filename:
        raise ValueError("Invalid filename: NUL byte")
    if unicodedata.normalize("NFKC", filename) != filename:
        raise ValueError(f"Invalid filename: {filename}")
    if filename != filename.strip():
        raise ValueError(f"Invalid filename: {filename}")
    if os.path.isabs(filename) or filename.startswith(("\\\\", "//")):
        raise ValueError(f"Invalid filename: {filename}")
    if filename != os.path.basename(filename):
        raise ValueError(f"Invalid filename: {filename}")
    if any(token in filename for token in ("..", "/", "\\", ":")):
        raise ValueError(f"Invalid filename: {filename}")
    if _has_control_char(filename):
        raise ValueError(f"Invalid filename: {filename}")
    if not FILENAME_PATTERN.fullmatch(filename):
        raise ValueError(f"Invalid filename: {filename}")
    return filename


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


def _validate_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise ValueError("Reason is required")
    safe_reason = reason.strip()
    if not safe_reason:
        raise ValueError("Reason is required")
    if len(safe_reason) > MAX_REASON_LENGTH:
        raise ValueError("Reason is too long")
    if "\x00" in safe_reason or "\n" in safe_reason or "\r" in safe_reason:
        raise ValueError("Reason contains forbidden control character")
    if _has_control_char(safe_reason):
        raise ValueError("Reason contains forbidden control character")
    return safe_reason


def _resolve_under_root(root_dir: str, filename: str) -> str:
    safe_filename = _validate_filename(filename)
    root = _canonical_path(root_dir)
    path = _canonical_path(os.path.join(root_dir, safe_filename))
    try:
        if os.path.commonpath([root, path]) != root:
            raise ValueError(f"Path escaped root: {filename}")
    except ValueError:
        raise ValueError(f"Path escaped root: {filename}")
    return path


def _last_nonempty_json_line(path: str):
    last_line = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        raise ValueError("Audit log is empty after write")
    return json.loads(last_line)


def _audit(action: str, filename: str, operator: str, detail: str = ""):
    _ensure_dirs()
    safe_filename = _validate_filename(filename)
    safe_operator = _validate_operator(operator)
    safe_detail = _validate_reason(detail)

    day = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(AUDIT_DIR, f"memory_review_{day}.jsonl")
    record = {
        "time": _now(),
        "action": action,
        "filename": safe_filename,
        "operator": safe_operator,
        "detail": safe_detail,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    last_record = _last_nonempty_json_line(log_path)
    for key in ["action", "filename", "operator", "detail"]:
        if last_record.get(key) != record[key]:
            raise ValueError(f"Audit verification failed: {key}")
    return log_path


def list_pending_files():
    _require_admin_user()
    validate_config_paths()
    if not os.path.isdir(WAIT_CHECK_DIR):
        return []
    files = []
    for name in os.listdir(WAIT_CHECK_DIR):
        try:
            path = _resolve_under_root(WAIT_CHECK_DIR, name)
        except ValueError:
            continue
        if os.path.isfile(path):
            files.append(name)
    return sorted(files)


def read_pending_file(filename: str) -> str:
    _require_admin_user()
    validate_config_paths()
    safe_filename = _validate_filename(filename)
    path = _resolve_under_root(WAIT_CHECK_DIR, safe_filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Pending memory not found: {safe_filename}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def approve_memory(filename: str, operator: str = None) -> str:  # F9: 默认由验证结果决定
    safe_operator = _validate_operator(operator)
    safe_filename = _validate_filename(filename)
    validate_config_paths()
    src = _resolve_under_root(WAIT_CHECK_DIR, safe_filename)
    dst = _resolve_under_root(PASSED_DIR, safe_filename)

    if not os.path.isfile(src):
        raise FileNotFoundError(f"Pending memory not found: {safe_filename}")

    with _management().management_action(
            _XIYIN_ROOT, "MEMORY_APPROVE", {"source": src, "destination": dst},
            operator=safe_operator, detail={"removes_source": True}) as lease:
        _management().require_scope(lease, _XIYIN_ROOT, {"MEMORY_APPROVE"},
                                    {"source": src, "destination": dst})
        _ensure_dirs()
        _audit("APPROVE_BEGIN", safe_filename, safe_operator, "begin wait_check to passed")
        shutil.copy2(src, dst)
        os.remove(src)
        _audit("APPROVE_COMMIT", safe_filename, safe_operator, "moved wait_check to passed")
    return dst


def reject_memory(filename: str, reason: str, operator: str = None) -> str:  # F9: 默认由验证结果决定
    safe_operator = _validate_operator(operator)
    safe_filename = _validate_filename(filename)
    safe_reason = _validate_reason(reason)
    validate_config_paths()
    src = _resolve_under_root(WAIT_CHECK_DIR, safe_filename)
    dst = _resolve_under_root(REJECTED_DIR, safe_filename)

    if not os.path.isfile(src):
        raise FileNotFoundError(f"Pending memory not found: {safe_filename}")

    with _management().management_action(
            _XIYIN_ROOT, "MEMORY_REJECT", {"source": src, "destination": dst},
            operator=safe_operator, detail={"reason": safe_reason, "removes_source": True}) as lease:
        _management().require_scope(lease, _XIYIN_ROOT, {"MEMORY_REJECT"},
                                    {"source": src, "destination": dst})
        _ensure_dirs()
        _audit("REJECT_BEGIN", safe_filename, safe_operator, safe_reason)
        shutil.move(src, dst)
        _audit("REJECT_COMMIT", safe_filename, safe_operator, safe_reason)
    return dst


if __name__ == "__main__":
    _require_admin_user()
    pending = list_pending_files()
    print("=== WAIT_CHECK PENDING FILES ===")
    for name in pending:
        print(name)
