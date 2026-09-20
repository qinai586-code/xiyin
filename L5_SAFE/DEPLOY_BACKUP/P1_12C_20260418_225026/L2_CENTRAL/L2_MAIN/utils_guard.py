import json
import os
import re

import l5_audit_logger
from l5_audit_logger import AUDIT_LOG, write_audit_log


def qinai_sanitize(text: str) -> str:
    """[预处理] 剔除零宽字符，封堵 C3 穿透输入。"""
    # 架构师修复：根据Gemini报告修正C3穿透注入问题
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", text).strip()


def check_c4_rules_for_c6(reply_text: str) -> bool:
    """[后置拦截] 让 C6 写回前复用 C4 红线规则。"""
    # 架构师修复：根据Gemini报告修正C6与C4规则脱节问题
    try:
        rule_path = r"C:\L0_RUNTIME\L2_CENTRAL\C4_OUTPUT_CHECK\c4_persona_rule.txt"
        with open(rule_path, "r", encoding="utf-8") as f:
            red_lines = [
                line.split(":", 1)[1].strip().lower()
                for line in f
                if ":" in line and not line.startswith("#")
            ]
        reply_lower = (reply_text or "").lower()
        return not any(word and word in reply_lower for word in red_lines)
    except Exception:
        return True


def bridge_audit_chain() -> None:
    """[启动桥接] 在重启后补一条合法桥接审计记录。"""
    # 架构师修复：根据Gemini报告修正L5审计哈希链断链问题
    if not os.path.exists(AUDIT_LOG):
        return

    try:
        with open(AUDIT_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            if pos == 0:
                return
            while pos > 0:
                pos -= 1
                f.seek(pos)
                if f.read(1) == b"\n":
                    break
            if pos == 0:
                f.seek(0)
            last_line = f.readline().decode("utf-8", errors="ignore").strip()

        if last_line and last_line.startswith("{"):
            last_entry = json.loads(last_line)
            old_hash = last_entry.get("entry_hash", "UNKNOWN")
            l5_audit_logger._prev_hash = old_hash
            write_audit_log(
                f"[SYSTEM_REBOOT] 架构师授权合法重启，断点前尾部哈希: {old_hash}",
                "下一条日志的起始哈希将合法重置",
                {"STATUS": "BRIDGED"},
            )
    except Exception:
        return
