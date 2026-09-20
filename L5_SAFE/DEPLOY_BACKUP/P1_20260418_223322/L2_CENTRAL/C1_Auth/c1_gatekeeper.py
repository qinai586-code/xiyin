# =============================================================================
# L2-C1 身份权限与环境校验模块 (V2.4 终极整合版)
# 位置: C:\L0_RUNTIME\L2_CENTRAL\C1_Auth\c1_gatekeeper.py
# =============================================================================

import os
import shutil
import getpass
import sys

# === 安全基线配置 (强制硬编码) ===
EXPECTED_USER = "sj_run"  # 核心：锁定运行账户
ALLOWED_EXEC_PATH = r"C:\L0_RUNTIME\L2_CENTRAL"
MIN_C_DRIVE_SPACE_MB = 1024 

def _trigger_meltdown(reason: str):
    """触发绝对熔断，不留任何异常捕获空间"""
    print(f"\n[!!! C1_MELTDOWN_PROTOCOL_ENGAGED !!!]")
    print(f"FATAL: {reason}")
    print("ACTION: TERMINATING PROCESS IMMEDIATELY.")
    sys.exit(1)

def qinai_permission_verify():
    """
    C1 核心闸门：执行身份、路径、资源的零信任校验
    """
    try:
        # 1. 账户身份校验 (强制自毁)
        current_user = getpass.getuser().lower()
        if current_user != EXPECTED_USER:
            _trigger_meltdown(f"检测到非授权账户越权。当前账户: [{current_user}]")

        # 2. 物理运行路径校验 (修复目录逃逸漏洞)
        cwd_norm = os.path.normpath(os.getcwd()).lower()
        safe_base = os.path.normpath(ALLOWED_EXEC_PATH).lower()
        if not safe_base.endswith(os.sep):
            safe_base += os.sep
            
        if cwd_norm != safe_base.rstrip(os.sep) and not cwd_norm.startswith(safe_base):
            _trigger_meltdown(f"工作目录异常，拦截非法目录逃逸/越权注入: {os.getcwd()}")

        # 3. 磁盘资源防熔断校验 (强制自毁)
        _, _, free = shutil.disk_usage("C:\\")
        free_mb = free / (1024 * 1024)
        if free_mb < MIN_C_DRIVE_SPACE_MB:
            _trigger_meltdown(f"C盘空间不足 ({free_mb:.2f} MB)，为防系统损坏强制熔断。")

        return True, "[OK] C1 物理基线校验通过"
    except SystemExit:
        raise
    except Exception as e:
        _trigger_meltdown(f"C1 门禁系统运行异常: {str(e)}")

if __name__ == "__main__":
    qinai_permission_verify()
    print("[C1_SUCCESS] 身份、路径、资源硬核校验通过。通道已安全放行。")
