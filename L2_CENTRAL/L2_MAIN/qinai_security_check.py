# -*- coding: utf-8 -*-

import os
import sys


def _xiyin_init_root():
    """A4/P3 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>\\xiyin_paths.py（本文件位于 <运行根>\\L2_CENTRAL\\L2_MAIN）；
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


# P3：BASE_RUNTIME 由运行根派生（原 C:\L0_RUNTIME 字面量解绑）。
BASE_RUNTIME = str(_XIYIN_ROOT)
L0_PROJECTION = os.path.join(BASE_RUNTIME, "L0_PROJECTION")
_MEMORY_ROOT = str(sys.modules["xiyin_paths"].resolve_path("data"))
L1_PASSED = os.path.join(_MEMORY_ROOT, "passed")
L1_WAIT = os.path.join(_MEMORY_ROOT, "wait_check")
L5_AUDIT = os.path.join(BASE_RUNTIME, "L5_SAFE", "G3_AUDIT")
# XIYIN has no configured external admin zone. Keep the report field, but
# do not probe historical directories belonging to another deployment.
D_ADMIN_ZONE = []

PATH_POLICIES = [
    ("L0_PROJECTION", L0_PROJECTION, "runtime persona projection; no Python write probe"),
    ("L1_PASSED", L1_PASSED, "approved memory store; no Python write probe"),
    ("L1_WAIT", L1_WAIT, "candidate memory queue; no Python write probe"),
    ("L5_AUDIT", L5_AUDIT, "audit target; no Python append/delete probe"),
]


def _account_role(token_role) -> str:
    """令牌角色 -> 报告角色名（输出协议名不变：admin_maintenance /
    runtime_account / unauthorized）。用户名不再参与判定（P3/A2）。"""
    if token_role == "reviewer":
        return "admin_maintenance"
    if token_role == "runtime":
        return "runtime_account"
    return "unauthorized"


def _path_observation(label: str, path: str, policy: str) -> dict:
    return {
        "label": label,
        "path": path,
        "exists": os.path.isdir(path),
        "policy": policy,
        "write_probe_performed": False,
        "delete_probe_performed": False,
    }


def collect_security_status() -> dict:
    identity = _xiyin_identity()
    policy = identity.load_policy(_XIYIN_ROOT)  # 缺失/损坏/非法 -> 异常（fail closed）
    token_role, sid = identity.current_role(policy)
    role = _account_role(token_role)

    path_checks = [_path_observation(label, path, policy) for label, path, policy in PATH_POLICIES]
    admin_zone_checks = [
        {
            "label": "D_ADMIN_ZONE",
            "path": path,
            "exists": os.path.isdir(path),
            "policy": "admin-only reference; no directory listing probe",
            "write_probe_performed": False,
            "delete_probe_performed": False,
        }
        for path in D_ADMIN_ZONE
    ]

    status = "SECURITY_CHECK_OK"
    ok = True
    messages = []

    if role == "unauthorized":
        status = "SECURITY_CHECK_FAIL"
        ok = False
        messages.append("unauthorized account")
    elif role == "admin_maintenance":
        status = "SECURITY_CHECK_WARN"
        messages.append("reviewer identity is for deployment and maintenance; runtime ACL is not verified by this script")
    else:
        messages.append("runtime identity recognized; zero-side-effect path observations completed")

    return {
        "ok": ok,
        "status": status,
        "current_user": sid,  # 进程令牌 SID（权威主体；用户名仅显示、不参与授权）
        "account_role": role,
        "base_runtime": BASE_RUNTIME,
        "runtime_truth_claimed": False,
        "writes_performed": False,
        "deletes_performed": False,
        "interactive_prompt": False,
        "path_checks": path_checks,
        "admin_zone_checks": admin_zone_checks,
        "messages": messages,
    }


def run_security_check() -> int:
    try:
        status = collect_security_status()
    except Exception as exc:
        print(f"SECURITY_CHECK_FAIL | exception | {exc.__class__.__name__}: {exc}")
        return 2

    print(status["status"])
    print(f"account_role={status['account_role']}")
    print(f"current_user={status['current_user']}")
    print(f"runtime_truth_claimed={status['runtime_truth_claimed']}")
    print(f"writes_performed={status['writes_performed']}")
    print(f"deletes_performed={status['deletes_performed']}")
    print(f"interactive_prompt={status['interactive_prompt']}")

    for item in status["path_checks"]:
        print(f"path_check={item['label']} exists={item['exists']} policy={item['policy']}")
    for item in status["admin_zone_checks"]:
        print(f"admin_zone={item['path']} exists={item['exists']} policy={item['policy']}")
    for message in status["messages"]:
        print(f"message={message}")

    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run_security_check())
