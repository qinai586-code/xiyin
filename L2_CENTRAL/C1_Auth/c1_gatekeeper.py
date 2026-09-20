# =============================================================================
# L2-C1 身份权限与环境校验模块 (V2.4 终极整合版)
# 位置: <运行根>\L2_CENTRAL\C1_Auth\c1_gatekeeper.py
# P3 重接线（XIYIN-PATH-IDENTITY-FULL-01）：运行身份 / 受信工作目录 / 容量
# 三项分别校验；默认单账户模式仍读取真实令牌，另保留显式双账户部署。
# =============================================================================

import os
import shutil
import sys

# === 安全基线配置（强制硬编码）===
# 容量阈值保留（蓝图 §5.3：阈值先保留，C1 运行卷保护与 C6 写入卷保护
# 目的不同，不把 1024MB 与 50MB 草率统一）。运行身份与受信 cwd 来自
# <运行根>\config\deployment.toml（共享身份适配器严格读取），配置缺失/
# 损坏/非法一律熔断；生产角色值未配置时保持拒绝（部署输入另行交付）。
MIN_C_DRIVE_SPACE_MB = 1024


def _load_identity():
    """一次性显式加载共享身份适配器（固定布局 <运行根>\\xiyin_identity.py）。

    本文件位于 <运行根>\\L2_CENTRAL\\C1_Auth；无上溯、无旧盘符回退；
    sys.modules 中已存在且 __file__ 不符的同名伪模块直接拒绝。
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))  # C1_Auth -> L2_CENTRAL -> 运行根
    expected = os.path.join(root, "xiyin_identity.py")
    preloaded = sys.modules.get("xiyin_identity")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError(
            "xiyin_identity pseudo-module rejected: "
            + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_identity",
                                                      expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_identity"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_identity"], root


_XIYIN_IDENTITY, _RUNTIME_ROOT = _load_identity()


def _trigger_meltdown(reason: str):
    """
    Function: 触发不可逆进程熔断，打印致命原因后立即以 exit-code 1 退出。
    Input:    reason (str) — 触发熔断的人类可读原因字符串。
    Output:   无返回值；进程在本函数内终止，调用方永远不会收到控制权。
    Depends:  sys.stderr.buffer（绕过 cp1252 编码限制，直接写 UTF-8 字节）。
    Security: 不捕获任何异常，确保熔断不可被外部 try/except 压制；
              所有消息以 errors='replace' 编码，防止二次 UnicodeEncodeError。
    """
    msg = f"\n[!!! C1_MELTDOWN_PROTOCOL_ENGAGED !!!]\nFATAL: {reason}\nACTION: TERMINATING PROCESS IMMEDIATELY.\n"
    sys.stderr.buffer.write(msg.encode("utf-8", errors="replace"))
    sys.stderr.buffer.flush()
    sys.exit(1)

def qinai_permission_verify():
    """
    Function: C1 零信任闸门，依序执行运行身份、工作目录、磁盘资源三重校验。
    Input:    无参数；身份取当前进程令牌 SID（适配器 ctypes 读取，API 失败
              即拒绝，绝不回退用户名/环境变量）；受信 cwd 与运行身份集来自
              机器部署策略；容量按运行根实际所在卷核对。
    Output:   (True, str) 校验通过；校验失败时调用 _trigger_meltdown() 直接终止进程。
    Depends:  共享身份适配器 xiyin_identity（load_policy/current_role）；
              os、shutil；常量 MIN_C_DRIVE_SPACE_MB。
    Security: 非运行身份令牌、cwd 越界、策略缺失/损坏/非法、令牌读取失败、
              运行卷空间不足均触发不可逆熔断；异常均上抛至
              _trigger_meltdown，禁止静默吞没任何校验异常；改变
              USERNAME/LOGNAME/USER/LNAME 不改变同一令牌的校验结果。
    """
    try:
        # 0. 机器部署策略（缺失/损坏/非法 → 熔断，fail closed）
        policy = _XIYIN_IDENTITY.load_policy(_RUNTIME_ROOT)

        # 1. 真实进程令牌按显式部署模式校验；不读用户名或环境变量。
        role, sid = _XIYIN_IDENTITY.current_role(policy)
        if role != "runtime":
            _trigger_meltdown(f"检测到非授权账户越权。当前令牌 SID: [{sid}]")

        # 2. 物理运行路径校验（受信位置来自策略；修复目录逃逸漏洞）
        _XIYIN_IDENTITY.validate_runtime_cwd(policy, os.getcwd())

        # 3. 磁盘资源防熔断校验（运行根实际所在卷；阈值保留；强制自毁）
        _, _, free = shutil.disk_usage(str(_RUNTIME_ROOT))
        free_mb = free / (1024 * 1024)
        if free_mb < MIN_C_DRIVE_SPACE_MB:
            _trigger_meltdown(f"运行卷空间不足 ({free_mb:.2f} MB)，为防系统损坏强制熔断。")

        return True, "[OK] C1 物理基线校验通过"
    except SystemExit:
        raise
    except Exception as e:
        _trigger_meltdown(f"C1 门禁系统运行异常: {str(e)}")

if __name__ == "__main__":
    qinai_permission_verify()
    print("[C1_SUCCESS] 身份、路径、资源硬核校验通过。通道已安全放行。")
