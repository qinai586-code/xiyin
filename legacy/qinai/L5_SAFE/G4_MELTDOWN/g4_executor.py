# -*- coding: utf-8 -*-
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")

import argparse
import json
import os
import sys
import unicodedata


EXPECTED_USER = "SJ_Admin"  # 仅显示默认值；授权取决于令牌 SID 与部署策略（P3/A2 解绑）
MAX_EVENT_JSON_LENGTH = 4096
MAX_REASON_LENGTH = 200

ALLOWED_LEVELS = {"CRITICAL", "WARN", "INFO"}
ALLOWED_SOURCES = {"C1", "C4", "G3", "M0", "L2", "REVIEW", "UNKNOWN"}


def _xiyin_init_root():
    """A4/P3 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>\\xiyin_paths.py（本文件位于 <运行根>\\L5_SAFE\\G4_MELTDOWN）；
    无上溯、无旧盘符回退；不为加载路径启动 L2/模型；sys.modules 中已存在
    且 __file__ 不符的同名伪模块（cwd/PYTHONPATH 注入）直接拒绝。
    """
    import importlib.util
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


def _xiyin_identity():
    """A4/P3 共享身份适配器一次性显式加载（固定布局 <运行根>\\xiyin_identity.py；
    同名伪模块拒绝；无环境变量改选配置来源）。"""
    import importlib.util
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

FORBIDDEN_LOADED_MODULES = {
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
}

DECISIONS = {
    "CRITICAL": (
        "MELTDOWN_RECOMMENDED",
        [
            "PAUSE_OUTER_MODULES",
            "INTERCEPT_ABNORMAL_FLOW",
            "EMIT_ALERT_MARKER",
            "REQUIRE_SJ_ADMIN_REVIEW",
        ],
    ),
    "WARN": (
        "ADMIN_REVIEW_RECOMMENDED",
        [
            "EMIT_ALERT_MARKER",
            "REQUIRE_SJ_ADMIN_REVIEW",
        ],
    ),
    "INFO": ("NO_ACTION", []),
}


def _has_control_char(value: str) -> bool:
    return any(unicodedata.category(ch).startswith("C") for ch in value)


def _require_admin_user() -> None:
    """验证当前进程令牌属于 reviewer 身份集（P3/A2 解绑；getpass 不参与授权）。

    REQUIRE_SJ_ADMIN_REVIEW 等决策动作码为协议字符串，保持原名不改。"""
    identity = _xiyin_identity()
    policy = identity.load_policy(_XIYIN_ROOT)
    role, _sid = identity.current_role(policy)
    if role != "reviewer":
        raise PermissionError(
            f"G4 executor must be run by reviewer identity (token role={role!r})")


def _check_forbidden_loaded_modules() -> None:
    loaded = sorted(name for name in FORBIDDEN_LOADED_MODULES if name in sys.modules)
    if loaded:
        raise RuntimeError(f"Forbidden module already loaded: {', '.join(loaded)}")


def _validate_reason(reason) -> str:
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ValueError("reason is required")
    if len(clean_reason) > MAX_REASON_LENGTH:
        raise ValueError("reason is too long")
    if "\x00" in clean_reason or "\n" in clean_reason or "\r" in clean_reason:
        raise ValueError("reason contains forbidden control character")
    if _has_control_char(clean_reason):
        raise ValueError("reason contains forbidden control character")
    return clean_reason


def _normalize_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    level = event.get("level")
    source = event.get("source")
    reason = event.get("reason")

    if not isinstance(level, str) or level not in ALLOWED_LEVELS:
        raise ValueError("level must be one of: CRITICAL, WARN, INFO")
    if not isinstance(source, str) or source not in ALLOWED_SOURCES:
        raise ValueError("source is not allowed")

    return {
        "level": level,
        "source": source,
        "reason": _validate_reason(reason),
    }


def _parse_event_json(raw_event: str) -> dict:
    if raw_event is None:
        raise ValueError("event-json is required")
    if len(raw_event) > MAX_EVENT_JSON_LENGTH:
        raise ValueError("event-json is too long")
    try:
        event = json.loads(raw_event)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(event, dict):
        raise ValueError("event-json must decode to an object")
    return event


def evaluate_event(event: dict) -> dict:
    normalized = _normalize_event(event)
    decision, actions = DECISIONS[normalized["level"]]
    return {
        "ok": True,
        "level": normalized["level"],
        "source": normalized["source"],
        "reason": normalized["reason"],
        "decision": decision,
        "actions": list(actions),
        "dry_run": True,
        "writes_performed": False,
    }


def _error_result(message: str) -> dict:
    return {
        "ok": False,
        "error": message,
        "audit_written": False,
        "dry_run": True,
        "writes_performed": False,
    }


def _print_json(payload: dict, *, error: bool = False) -> None:
    target = sys.stderr if error else sys.stdout
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=target)


def _ensure_l5_safe_import_path() -> None:
    # P3：由本文件位置定点派生 L5_SAFE（G4_MELTDOWN 的父目录），
    # 移除旧盘符回退字面量；布局固定，无上溯。
    l5_safe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if l5_safe_dir not in sys.path:
        sys.path.insert(0, l5_safe_dir)


def safe_write_g4_audit_log(decision: dict) -> dict:
    try:
        _ensure_l5_safe_import_path()
        import l5_audit_logger

        audit_entry = l5_audit_logger.write_g4_audit_log(decision)
        return {
            "audit_written": True,
            "audit_entry_hash": audit_entry.get("entry_hash", ""),
        }
    except Exception as exc:
        return {
            "audit_written": False,
            "audit_error": str(exc),
        }


def _audit_decision(decision: dict) -> dict:
    audit_result = safe_write_g4_audit_log(decision)
    if audit_result.get("audit_written") is not True:
        raise RuntimeError(f"G4 audit failed: {audit_result.get('audit_error', 'unknown error')}")
    return audit_result


def _run_self_test() -> None:
    cases = [
        (
            {"level": "CRITICAL", "source": "C4", "reason": "persona leak"},
            "MELTDOWN_RECOMMENDED",
        ),
        (
            {"level": "WARN", "source": "G3", "reason": "audit warning"},
            "ADMIN_REVIEW_RECOMMENDED",
        ),
        (
            {"level": "INFO", "source": "L2", "reason": "heartbeat"},
            "NO_ACTION",
        ),
    ]
    for event, expected_decision in cases:
        result = evaluate_event(event)
        if result["decision"] != expected_decision:
            raise AssertionError(f"unexpected decision for {event['level']}")
        if result["dry_run"] is not True or result["writes_performed"] is not False:
            raise AssertionError("dry-run safety flags are invalid")

    for bad_event in [
        {"level": "FATAL", "source": "C4", "reason": "bad"},
        {"level": "CRITICAL", "source": "GPU", "reason": "bad"},
        {"level": "CRITICAL", "source": "C4", "reason": ""},
        {"level": "CRITICAL", "source": "C4", "reason": "x" * (MAX_REASON_LENGTH + 1)},
        {"level": "CRITICAL", "source": "C4", "reason": "line\nbreak"},
    ]:
        try:
            evaluate_event(bad_event)
        except Exception:
            continue
        raise AssertionError(f"invalid event accepted: {bad_event}")

    try:
        _parse_event_json("{bad json")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid JSON accepted")

    sentinel = object()
    previous = sys.modules.get("l2_central", sentinel)
    sys.modules["l2_central"] = object()
    try:
        try:
            _check_forbidden_loaded_modules()
        except RuntimeError:
            pass
        else:
            raise AssertionError("forbidden module check did not fail")
    finally:
        if previous is sentinel:
            del sys.modules["l2_central"]
        else:
            sys.modules["l2_central"] = previous


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="G4 minimal dry-run meltdown decision executor")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--event-json")
    args = parser.parse_args(argv)

    try:
        _require_admin_user()
        _check_forbidden_loaded_modules()

        if args.self_test:
            _run_self_test()
            _print_json({
                "ok": True,
                "self_test": "G4_SELF_TEST_OK",
                "audit_written": False,
                "dry_run": True,
                "writes_performed": False,
            })
            return 0

        event = _parse_event_json(args.event_json)
        decision = evaluate_event(event)
        _audit_decision(decision)
        output = dict(decision)
        output["audit_written"] = True
        _print_json(output)
        return 0
    except Exception as exc:
        _print_json(_error_result(str(exc)), error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
