# =============================================================================
# 祈奈 AI L0-L5 架构 | L5 安全兜底层 G3 审计黑匣子模块
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
# 存放路径: C:\L0_RUNTIME\L5_SAFE\l5_audit_logger.py
# 运行权限: SJ_Run (仅追加写入 G3_AUDIT，禁止删除)
# 核心功能: 全链路审计日志写入 + 权限自检
# 对齐安全加固方案：SHA-256 哈希链结构（当前为基础版，后续可升级 HMAC）
# =============================================================================

import os
import time
import hashlib
import json
import sys
import threading


def _xiyin_init_root():
    """A4/P4 (L5_SAFE) 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块
    （cwd/PYTHONPATH 注入）直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "xiyin_paths.py")
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

# G3 审计目录与日志路径（对齐架构路径定义）
# P4: 审计根由同一受信运行根派生（链式日志格式/校验保持，不重置生产审计链）
G3_AUDIT_DIR = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "G3_AUDIT")
AUDIT_LOG    = os.path.join(G3_AUDIT_DIR, "l2_central_audit.log")
AUDIT_TMP    = os.path.join(G3_AUDIT_DIR, "audit.tmp")

_write_lock   = threading.Lock()
_prev_hash    = "0" * 64  # 哈希链起始值（Genesis Hash）

G4_AUDIT_SCHEMA_VERSION = "phase2.g4_audit.v1"
G4_DECISION_KEYS = {
    "ok",
    "level",
    "source",
    "reason",
    "decision",
    "actions",
    "dry_run",
    "writes_performed",
}
G4_AUDIT_ALLOWED_LEVELS = {"CRITICAL", "WARN", "INFO"}
G4_AUDIT_ALLOWED_SOURCES = {"C1", "C4", "G3", "M0", "L2", "REVIEW", "UNKNOWN"}
G4_AUDIT_ALLOWED_DECISIONS = {
    "MELTDOWN_RECOMMENDED",
    "ADMIN_REVIEW_RECOMMENDED",
    "NO_ACTION",
}

CONTROL_PLANE_SCHEMA_VERSION = "phase2.control_plane.v1"
CONTROL_PLANE_ALLOWED_ACTIONS = {
    "GPU_AUTHORIZE",
    "GPU_START",
    "GPU_STOP",
    "L2_START",
    "L2_STOP",
    "RESOURCE_WARN",
    "RESOURCE_BLOCK",
    "STARTUP_TIMEOUT",
    "ORPHAN_DETECTED",
}
CONTROL_PLANE_ALLOWED_TARGETS = {
    "GPU_SERVER",
    "GPU_AUTHORIZE",
    "L2_WORKER",
    "QINAI_LAUNCHER",
    "RESOURCE_GUARD",
}
CONTROL_PLANE_ALLOWED_STATUSES = {
    "REQUEST",
    "SUCCESS",
    "FAIL",
    "BLOCKED",
    "WARN",
    "STOPPED",
}


def _is_valid_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def _read_last_entry_hash(default_hash: str) -> str:
    """Read the last valid JSON audit hash so process restarts continue the chain."""
    last_hash = None
    try:
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                entry_hash = entry.get("entry_hash")
                if _is_valid_hash(entry_hash):
                    last_hash = entry_hash
        return last_hash or default_hash
    except FileNotFoundError:
        return default_hash
    except Exception:
        return default_hash


def check_audit_permission() -> bool:
    """
    G3 权限自检：
    1. 目录必须存在
    2. SJ_Run 必须能追加写入 audit.tmp
    3. SJ_Run 不得删除审计文件（NTFS ACL 层面保障，此处仅验证追加能力）
    返回 True = 审计可用；False = 审计离线（不阻断主链）
    """
    try:
        if not os.path.exists(G3_AUDIT_DIR):
            os.makedirs(G3_AUDIT_DIR, exist_ok=True)
        # 尝试追加写入 tmp 缓冲（不写正式日志）
        with open(AUDIT_TMP, "a", encoding="utf-8") as f:
            f.write("")
        return True
    except Exception:
        return False


def _compute_hash(entry: dict) -> str:
    """对日志条目计算 SHA-256，用于哈希链完整性验证"""
    canonical = json.dumps(entry, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_hash_chained_entry_unlocked(entry: dict) -> dict:
    global _prev_hash

    _prev_hash = _read_last_entry_hash(_prev_hash)
    clean_entry = dict(entry)
    clean_entry["prev_hash"] = _prev_hash

    entry_hash = _compute_hash(clean_entry)
    clean_entry["entry_hash"] = entry_hash
    _prev_hash = entry_hash

    log_line = json.dumps(clean_entry, ensure_ascii=False) + "\n"

    with open(AUDIT_TMP, "w", encoding="utf-8") as f:
        f.write(log_line)

    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(log_line)

    open(AUDIT_TMP, "w").close()
    return clean_entry


def write_audit_log(user_input: str, reply: str, module_status: dict) -> None:
    """
    全链路审计写入接口（线程安全）。
    日志格式：JSON 单行，含 prev_hash 构成哈希链。
    写入路径：audit.tmp → 原子 flush → l2_central_audit.log
    SJ_Run 权限：追加写入，禁止删除（由 NTFS ACL 强制执行）。
    """
    global _prev_hash

    with _write_lock:
        try:
            _prev_hash = _read_last_entry_hash(_prev_hash)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")

            # 构建日志条目（不记录完整回复内容，仅记录摘要和状态）
            entry = {
                "timestamp":     ts,
                "input_len":     len(user_input),
                "input_preview": user_input[:40],
                "reply_len":     len(reply),
                "reply_preview": reply[:40],
                "module_status": {k: bool(v) for k, v in module_status.items()},
                "prev_hash":     _prev_hash,
            }

            _append_hash_chained_entry_unlocked(entry)

        except Exception:
            # 审计写入失败静默处理，不阻断主链
            pass


def _has_control_char(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)

def _validate_text_field(value, label: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    clean = value.strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if len(clean) > max_length:
        raise ValueError(f"{label} is too long")
    if _has_control_char(clean):
        raise ValueError(f"{label} contains forbidden control character")
    return clean


def _validate_g4_decision(decision: dict) -> dict:
    if not isinstance(decision, dict):
        raise ValueError("G4 decision must be an object")
    if set(decision) != G4_DECISION_KEYS:
        raise ValueError("G4 decision schema mismatch")

    if decision.get("ok") is not True:
        raise ValueError("G4 decision ok must be true")
    if decision.get("level") not in G4_AUDIT_ALLOWED_LEVELS:
        raise ValueError("G4 decision level is invalid")
    if decision.get("source") not in G4_AUDIT_ALLOWED_SOURCES:
        raise ValueError("G4 decision source is invalid")
    if decision.get("decision") not in G4_AUDIT_ALLOWED_DECISIONS:
        raise ValueError("G4 decision value is invalid")

    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("G4 decision reason must be a non-empty string")
    if len(reason.strip()) > 200 or _has_control_char(reason):
        raise ValueError("G4 decision reason is invalid")

    actions = decision.get("actions")
    if not isinstance(actions, list) or not all(isinstance(item, str) and item for item in actions):
        raise ValueError("G4 decision actions must be a string list")

    if decision.get("dry_run") is not True:
        raise ValueError("G4 decision dry_run must be true")
    if decision.get("writes_performed") is not False:
        raise ValueError("G4 decision writes_performed must be false")

    return {
        "ok": True,
        "level": decision["level"],
        "source": decision["source"],
        "reason": reason.strip(),
        "decision": decision["decision"],
        "actions": list(actions),
        "dry_run": True,
        "writes_performed": False,
    }


def write_g4_audit_log(decision: dict) -> dict:
    """
    Persist a normalized G4 dry-run decision into the G3 hash chain.
    Unlike the main-chain audit writer, this function raises on failure so
    the G4 CLI cannot silently claim an unaudited decision succeeded.
    """
    clean = _validate_g4_decision(decision)
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "schema_version": G4_AUDIT_SCHEMA_VERSION,
        "event_type": "G4_DECISION",
        "ok": clean["ok"],
        "level": clean["level"],
        "source": clean["source"],
        "reason": clean["reason"],
        "decision": clean["decision"],
        "actions": clean["actions"],
        "dry_run": clean["dry_run"],
        "writes_performed": clean["writes_performed"],
    }

    with _write_lock:
        return _append_hash_chained_entry_unlocked(entry)

def _validate_control_plane_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("control plane event must be an object")

    action = event.get("action")
    target = event.get("target")
    status = event.get("status")
    actor = event.get("actor")
    detail = event.get("detail")
    metadata = event.get("metadata", {})

    if action not in CONTROL_PLANE_ALLOWED_ACTIONS:
        raise ValueError("control plane action is invalid")
    if target not in CONTROL_PLANE_ALLOWED_TARGETS:
        raise ValueError("control plane target is invalid")
    if status not in CONTROL_PLANE_ALLOWED_STATUSES:
        raise ValueError("control plane status is invalid")
    if not isinstance(metadata, dict):
        raise ValueError("control plane metadata must be an object")

    metadata_blob = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if len(metadata_blob) > 2048:
        raise ValueError("control plane metadata is too large")

    return {
        "action": action,
        "target": target,
        "status": status,
        "actor": _validate_text_field(actor, "actor", max_length=64),
        "detail": _validate_text_field(detail, "detail", max_length=200),
        "metadata": metadata,
    }


def write_control_plane_audit_log(event: dict) -> dict:
    """
    Persist launcher/control-plane events into the same append-only G3 hash chain.
    This is used for GUI-managed lifecycle actions and resource-guard events.
    """
    clean = _validate_control_plane_event(event)
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "event_type": "CONTROL_PLANE",
        "action": clean["action"],
        "target": clean["target"],
        "status": clean["status"],
        "actor": clean["actor"],
        "detail": clean["detail"],
        "metadata": clean["metadata"],
    }

    with _write_lock:
        return _append_hash_chained_entry_unlocked(entry)


def verify_chain() -> tuple:
    """
    哈希链完整性校验（SJ_Admin 维护工具调用）。
    返回 (True, line_count, None) 或 (False, line_num, reason)
    """
    expected_prev = "0" * 64
    try:
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("prev_hash") != expected_prev:
                    return False, line_num, "哈希链断裂，疑似日志被篡改"
                # 重建条目（去掉 entry_hash 字段）重新计算
                check_entry = {k: v for k, v in entry.items() if k != "entry_hash"}
                computed = _compute_hash(check_entry)
                if computed != entry.get("entry_hash"):
                    return False, line_num, "条目哈希不匹配，疑似被篡改"
                expected_prev = entry["entry_hash"]
        return True, line_num if 'line_num' in dir() else 0, None
    except FileNotFoundError:
        return False, 0, "审计日志文件不存在"
    except Exception as e:
        return False, 0, str(e)


def _safe_console_print(message: str) -> None:
    text = str(message)
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
        sys.stdout.write(safe_text + "\n")
        sys.stdout.flush()
        return
    except Exception:
        pass

    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write((text + "\n").encode("utf-8", errors="backslashreplace"))
            buffer.flush()
            return
    except Exception:
        pass

    try:
        sys.stdout.write(text.encode("ascii", errors="backslashreplace").decode("ascii") + "\n")
        sys.stdout.flush()
    except Exception:
        pass


if __name__ == "__main__":
    # SJ_Admin 维护调用：验证哈希链完整性
    ok, line, reason = verify_chain()
    if ok:
        _safe_console_print(f"审计日志完整性校验通过，共 {line} 条记录")
    else:
        _safe_console_print(f"警告：第 {line} 条记录异常 — {reason}")