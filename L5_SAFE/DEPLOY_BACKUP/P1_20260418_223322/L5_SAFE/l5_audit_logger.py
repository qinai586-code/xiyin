# =============================================================================
# 祈奈 AI L0-L5 架构 | L5 安全兜底层 G3 审计黑匣子模块
# 存放路径: C:\L0_RUNTIME\L5_SAFE\l5_audit_logger.py
# 运行权限: SJ_Run (仅追加写入 G3_AUDIT，禁止删除)
# 核心功能: 全链路审计日志写入 + 权限自检
# 对齐安全加固方案：SHA-256 哈希链结构（当前为基础版，后续可升级 HMAC）
# =============================================================================

import os
import time
import hashlib
import json
import threading

# G3 审计目录与日志路径（对齐架构路径定义）
G3_AUDIT_DIR = r"C:\L0_RUNTIME\L5_SAFE\G3_AUDIT"
AUDIT_LOG    = os.path.join(G3_AUDIT_DIR, "l2_central_audit.log")
AUDIT_TMP    = os.path.join(G3_AUDIT_DIR, "audit.tmp")

_write_lock   = threading.Lock()
_prev_hash    = "0" * 64  # 哈希链起始值（Genesis Hash）


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

            entry_hash = _compute_hash(entry)
            entry["entry_hash"] = entry_hash
            _prev_hash = entry_hash

            log_line = json.dumps(entry, ensure_ascii=False) + "\n"

            # 原子写入：先写 tmp 缓冲，再 flush 到正式日志
            with open(AUDIT_TMP, "w", encoding="utf-8") as f:
                f.write(log_line)

            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(log_line)

            # 清空 tmp 缓冲（flush 完成标志）
            open(AUDIT_TMP, "w").close()

        except Exception:
            # 审计写入失败静默处理，不阻断主链
            pass


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


if __name__ == "__main__":
    # SJ_Admin 维护调用：验证哈希链完整性
    ok, line, reason = verify_chain()
    if ok:
        print(f"审计日志完整性校验通过，共 {line} 条记录")
    else:
        print(f"警告：第 {line} 条记录异常 — {reason}")
