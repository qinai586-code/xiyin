import json
import os
import re
import sys
import threading
import unicodedata
import copy


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULE_PATH = os.path.join(BASE_DIR, "..", "C4_OUTPUT_CHECK", "c4_persona_rule.txt")
RULE_PATH = os.path.abspath(RULE_PATH)

_CACHE_LOCK = threading.Lock()
_RULE_CACHE = {"stat_id": "", "basic": [], "deformed": []}


def _lazy_audit(step: str, message: str, details: dict = None):
    try:
        import l5_audit_logger
        l5_audit_logger.write_audit_log(step, message, details or {})
    except Exception as e:
        print(f"[AUDIT_FAIL] {step}: {message} | Err: {e}", file=sys.stderr)


def qinai_sanitize(text: str) -> str:
    """[预处理] 剔除零宽字符，封堵 C3 穿透输入。"""
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", text).strip()


def qinai_normalize(text: str) -> str:
    """统一物理归一化管道：仅做 NFKC 转换与清洗，保留大小写语义，供 C6 物理落盘使用。"""
    return unicodedata.normalize("NFKC", qinai_sanitize(text))


def _get_file_stat_id(path):
    stat = os.stat(path)
    try:
        return f"{stat.st_mtime_ns}_{stat.st_size}"
    except AttributeError:
        return f"{stat.st_mtime}_{stat.st_size}"


def _load_unified_rules():
    global _RULE_CACHE
    audit_events = []

    with _CACHE_LOCK:
        try:
            if not os.path.exists(RULE_PATH):
                return [], []
            stat_id = _get_file_stat_id(RULE_PATH)
            if stat_id == _RULE_CACHE.get("stat_id"):
                return copy.deepcopy(_RULE_CACHE["basic"]), copy.deepcopy(_RULE_CACHE["deformed"])

            basic, deformed = [], []
            allowed_types = {"身份泄露", "语气生硬", "情感疏离", "陪伴越界", "变形"}

            with open(RULE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    r_type, pattern = line.split(":", 1)
                    r_type, pattern = r_type.strip(), pattern.strip()

                    if not pattern:
                        raise ValueError(f"空规则模式: {r_type}")

                    if r_type == "变形":
                        try:
                            deformed.append(re.compile(pattern, re.IGNORECASE))
                        except re.error as e:
                            raise ValueError(f"非法正则表达式 '{pattern}': {e}")
                    elif r_type in allowed_types:
                        basic.append({"type": r_type, "keyword": pattern.casefold()})
                    else:
                        raise ValueError(f"未知的规则类型: {r_type}")

            _RULE_CACHE.update({"basic": basic, "deformed": deformed, "stat_id": stat_id})
        except Exception as e:
            audit_events.append(("RULE_LOAD_FATAL", str(e), {}))
            _RULE_CACHE.update({"basic": [], "deformed": [], "stat_id": ""})

    for event in audit_events:
        _lazy_audit(*event)

    return copy.deepcopy(_RULE_CACHE["basic"]), copy.deepcopy(_RULE_CACHE["deformed"])


def check_rules_engine(text: str, caller: str = None) -> tuple:
    if not text:
        return (True, {})

    if len(text) > 5000:
        _lazy_audit("TEXT_TOO_LONG", "触发超长拒绝防 ReDoS", {"len": len(text), "caller": caller or "UNKNOWN"})
        return (False, {"type": "SYS_ERR", "keyword": "TEXT_TOO_LONG"})

    safe_text = unicodedata.normalize("NFKC", qinai_normalize(text).casefold())

    basic, deformed = _load_unified_rules()
    if not basic and not deformed:
        return (False, {"type": "SYS_ERR", "keyword": "RULE_LOAD_FAIL"})

    for r in basic:
        if r["keyword"] in safe_text:
            return (False, r)

    for p in deformed:
        if p.search(safe_text):
            return (False, {"type": "变形拦截", "keyword": "REGEX_HIT"})

    return (True, {})


def check_c4_rules_for_c6(text: str) -> bool:
    is_safe, _ = check_rules_engine(text, caller="C6")
    return is_safe


def bridge_audit_chain() -> None:
    try:
        import l5_audit_logger
    except Exception:
        return

    if not os.path.exists(l5_audit_logger.AUDIT_LOG):
        return

    bridge_err = None
    try:
        with open(l5_audit_logger.AUDIT_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            if pos == 0:
                return
            # Skip trailing newlines before seeking to last record boundary
            while pos > 0:
                pos -= 1
                f.seek(pos)
                ch = f.read(1)
                if ch != b"\n":
                    pos += 1
                    break
            # Now seek backwards to find the newline before the last record
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
            l5_audit_logger.write_audit_log(
                f"[SYSTEM_REBOOT] 架构师授权合法重启，断点前尾部哈希: {old_hash}",
                "下一条日志将从当前桥接条目继续合法衔接",
                {"STATUS": "BRIDGED"},
            )
    except Exception as e:
        bridge_err = str(e)

    if bridge_err:
        print(f"[BRIDGE_FAIL] bridge_audit_chain error: {bridge_err}", file=sys.stderr)
