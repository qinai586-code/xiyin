import os
import sys
import time
import json
import subprocess
import requests

# =============================================================
# [架构修复 1] 强制挂载 C1-C6 绝对物理路径（彻底消除路径计算误差）
# =============================================================
BASE_PATH = r"C:\L0_RUNTIME\L2_CENTRAL"
MODULE_DIRS = [
    BASE_PATH,  # <--- 救命稻草：必须把 L2_CENTRAL 本身也加进搜索路径！
    os.path.join(BASE_PATH, "C1_Auth"),
    os.path.join(BASE_PATH, "C2_MEMORY"),
    os.path.join(BASE_PATH, "C3_INPUT_GUARD"),
    os.path.join(BASE_PATH, "C4_OUTPUT_CHECK"),
    os.path.join(BASE_PATH, "C5_LLM_CALL", "script"),
    os.path.join(BASE_PATH, "C6_WRITEBACK"),
    r"C:\L0_RUNTIME\L5_SAFE",  
]

# 核心时序：必须在导入 utils_guard 之前执行插入
for dir_path in MODULE_DIRS:
    if os.path.exists(dir_path) and dir_path not in sys.path:
        sys.path.insert(0, dir_path)

# 路径挂载完毕，安全导入套管组件
import utils_guard

# G3 系统日志直写路径（与L5 JSON审计日志分离，避免格式冲突）
G3_AUDIT_LOG = r"C:\L0_RUNTIME\L5_SAFE\G3_AUDIT\l2_central_runtime.log"
MANIFEST_PATH = r"C:\L0_RUNTIME\L2_CENTRAL\C7_PLUGINS\manifest.json"

# 启动日志横幅
print("=" * 70)
print("祈奈AI L2中枢系统 | 全模块启动校验")
print("=" * 70)
current_user = os.getenv("USERNAME", "未知用户")
print(f"当前运行用户：{current_user}")
print("-" * 70)

# 全局状态标记
MODULE_STATUS = {}
GPU_ACTIVE    = False
FALLBACK_MODE = False
FALLBACK_REPLY = "祈奈的大脑还在启动中，不过祈奈对主理人的心意是不会变的哦～"

# 边车进程注册表（由 [8/N] 加载区填充）
SIDECAR_PROCS = {}

# =============================================================
# [生命体进化核心变量] 短期缓存海马体 & 对话状态机
# =============================================================
SHORT_TERM_MEMORY = []
MAX_CONTEXT_ROUNDS = 1
DIALOGUE_STATE = "responding"

# =============================================================
# 内部工具：G3 直写审计（L5离线兜底，不对外暴露任何技术信息）
# =============================================================
def _write_g3(step: str, status: str, detail: str):
    """最小化审计写入，SJ_Run追加权限，不对终端输出任何内部信息"""
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] | {step.ljust(14)} | {status.ljust(10)} | {detail[:120]}\n"
        with open(G3_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # 审计失败静默，不阻断主链

# =============================================================
# [架构修复 2] 模块导入 — 移除不存在的 c1_permission，严格对齐真实文件
# P0修复：原代码 from c1_permission import c1_verify_environment 导致
#         每次启动 ImportError，C1 失效，FALLBACK_MODE 永远为 True
# =============================================================
print("[1/8] 正在加载 C1 身份权限与环境校验模块...")
try:
    from c1_gatekeeper import qinai_permission_verify
except Exception:
    print("\n[!!! MELTDOWN_PROTOCOL_ENGAGED !!!]")
    print("FATAL: 核心安全门禁(C1/C3)加载失败或文件损坏。")
    print("ACTION: TERMINATING PROCESS IMMEDIATELY.")
    import sys
    sys.exit(1)
MODULE_STATUS["C1"] = True
print("C1 加载完成 (物理基线校验通过)")

print("[2/8] 正在加载 C2 记忆检索模块...")
try:
    from c2_retrieve import c2_get_memory
    MODULE_STATUS["C2"] = True
    print("C2 加载完成")
except Exception as e:
    MODULE_STATUS["C2"] = False
    _write_g3("C2_LOAD", "FAIL", str(e))
    print(f"C2 失败：{str(e)}")

print("[3/8] 正在加载 C3 安全过滤模块...")
try:
    from c3_filter import c3_input_filter
except Exception:
    print("\n[!!! MELTDOWN_PROTOCOL_ENGAGED !!!]")
    print("FATAL: 核心安全门禁(C1/C3)加载失败或文件损坏。")
    print("ACTION: TERMINATING PROCESS IMMEDIATELY.")
    import sys
    sys.exit(1)
MODULE_STATUS["C3"] = True
print("C3 加载完成")

print("[4/8] 正在加载 C4 输出人设校验模块...")
try:
    from c4_verify import c4_persona_check
    MODULE_STATUS["C4"] = True
    print("C4 加载完成")
except Exception as e:
    MODULE_STATUS["C4"] = False
    _write_g3("C4_LOAD", "FAIL", str(e))
    print(f"C4 失败：{str(e)}")

print("[5/8] 正在加载 C5 LLM网关与Prompt引擎模块...")
try:
    from c5_llm_gatekeeper import qinai_llm_call
    from c5_persona_prompt import generate_qinai_prompt
    MODULE_STATUS["C5"] = True
    print("C5 模块导入成功")
    test_response = requests.post(
        "http://127.0.0.1:11434/generate",
        json={"prompt": "test"},
        timeout=60
    )
    if test_response.status_code == 200:
        GPU_ACTIVE = True
        print("GPU侧车连接正常（127.0.0.1:11434）")
    else:
        FALLBACK_MODE = True
        _write_g3("C5_GPU", "WARN", f"GPU响应异常 status={test_response.status_code}")
except Exception as e:
    MODULE_STATUS["C5"] = False
    FALLBACK_MODE = True
    _write_g3("C5_LOAD", "FAIL", str(e))
    print(f"C5 连接失败：{str(e)}")

print("[6/8] 正在加载 C6 记忆写回模块...")
try:
    from c6_submit import c6_submit_memory
    MODULE_STATUS["C6"] = True
    print("C6 加载完成")
except Exception as e:
    MODULE_STATUS["C6"] = False
    _write_g3("C6_LOAD", "FAIL", str(e))
    print(f"C6 失败：{str(e)}")

print("[7/8] 正在加载 L5 审计黑匣子模块...")
try:
    from l5_audit_logger import write_audit_log, check_audit_permission
    MODULE_STATUS["L5"] = check_audit_permission()
    print("L5 加载完成")
except Exception as e:
    MODULE_STATUS["L5"] = False
    # L5离线不阻断主链，降级为 _write_g3 直写
    print("L5 审计模块离线，降级为直写G3 (非阻断)")

# =============================================================
# [8/8] C7 边车加载区
# 读取 manifest.json，按 enabled 标志启动各边车进程
# 任何边车异常不阻断主链；forbidden 目录越权的模块跳过不启动
# =============================================================
print("[8/8] 正在加载 C7 边车模块...")

def _check_sidecar_permissions(mod: dict) -> bool:
    """
    前置权限校验：manifest 中 forbidden 列表的目录不允许边车有写权限。
    当前为路径声明检查（运行时 NTFS ACL 是最终执行层）。
    """
    forbidden = mod.get("permissions", {}).get("forbidden", [])
    write_dirs = mod.get("permissions", {}).get("write", [])
    for wd in write_dirs:
        for fd in forbidden:
            if os.path.normpath(wd).lower().startswith(os.path.normpath(fd).lower()):
                _write_g3("SIDECAR_ACL", "DENY",
                          f"{mod['id']} 申请写入禁区 {wd}")
                return False
    return True

try:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        for mod in manifest.get("modules", []):
            if not mod.get("enabled", False):
                continue  # enabled:false → 跳过，不启动

            mod_id = mod.get("id", "unknown")
            entry  = mod.get("entry", "")

            if not os.path.exists(entry):
                print(f"  边车 [{mod_id}] 入口文件不存在，跳过")
                _write_g3("SIDECAR_LOAD", "SKIP", f"{mod_id} entry不存在: {entry}")
                continue

            if not _check_sidecar_permissions(mod):
                print(f"  边车 [{mod_id}] 权限校验失败，拒绝启动")
                continue

            try:
                proc = subprocess.Popen(
                    [sys.executable, entry],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                SIDECAR_PROCS[mod_id] = proc
                _write_g3("SIDECAR_LOAD", "OK", f"{mod_id} pid={proc.pid}")
                print(f"  边车 [{mod['name']}] 已启动 pid={proc.pid}")
            except Exception as e:
                _write_g3("SIDECAR_LOAD", "FAIL", f"{mod_id}: {str(e)}")
                print(f"  边车 [{mod_id}] 启动失败（非阻断）: {str(e)}")
    else:
        print("  manifest.json 不存在，跳过边车加载（正常）")

except Exception as e:
    # 边车加载整体异常不阻断主链
    _write_g3("SIDECAR_LOAD", "FAIL", str(e))
    print(f"  边车加载异常（非阻断）: {str(e)}")

print("=" * 70)
success_count = sum(1 for v in MODULE_STATUS.values() if v)
total_count   = len(MODULE_STATUS)
gpu_status    = "已激活" if GPU_ACTIVE else "未连接"
print(f"L2中枢启动完成！{success_count}/{total_count} 模块加载正常")
print(f"当前GPU状态：{gpu_status}")
print("-" * 70)


# =============================================================
# submit_to_chain()：L3/B0/M0 等边车的唯一合规接入口
# 走完整 C1→C3→C2→C5→C4→C6 链路，source 参数仅用于审计标签
# 禁止任何边车绕过此函数直接调用 C5 或读写 L0/L1
# =============================================================
def submit_to_chain(text: str, source: str = "sidecar") -> str:
    """
    边车统一接入接口。
    - text   : 送入链路的原始文本
    - source : 来源标识，写入 G3 审计日志（不对外暴露）
    返回祈奈的最终回复文本；异常时返回兜底话术。
    """
    _write_g3("CHAIN_ENTER", source, text[:60])
    reply = FALLBACK_REPLY
    try:
        reply = _run_chain(text, source=source)
    except Exception as e:
        _write_g3("CHAIN_ERROR", source, str(e))
    return reply


def _run_chain(user_input: str, source: str = "interactive") -> str:
    """
    全链路执行核心，由主对话循环和 submit_to_chain 共同调用。
    不直接对外暴露，所有调用必须经由上面两个入口。
    """
    user_input = utils_guard.qinai_sanitize(user_input)  # 架构师修复：根据Gemini报告修正C3穿透注入问题
    final_reply = FALLBACK_REPLY

    # 0. C1 实时物理闸门校验
    if MODULE_STATUS.get("C1"):
        c1_pass, c1_msg = qinai_permission_verify()
        if not c1_pass:
            _write_g3("C1_GATE", "MELTDOWN", c1_msg)
            raise SystemExit(f"C1 熔断: {c1_msg}")

    # 1. C3 安全过滤
    security_pass = True
    if MODULE_STATUS.get("C3"):
        security_pass, security_msg = c3_input_filter(user_input)
    if not security_pass:
        _write_g3("C3_FILTER", "BLOCK", source)
        return security_msg  # 直接返回祈奈话术，不进入后续链路

    # 2. C2 长期记忆检索
    long_term_memory = ""
    if MODULE_STATUS.get("C2"):
        long_term_memory = c2_get_memory(user_input=user_input, max_memory_num=3)

    # 组装短期上下文（海马体）
    recent_context = ""
    if SHORT_TERM_MEMORY:
        ctx_lines = [
            f"主理人: {m['user']}\n祈奈: {m['reply']}"
            for m in SHORT_TERM_MEMORY
        ]
        recent_context = "\n".join(ctx_lines)

    # [P0修复] 替换内联 final_prompt → 调用 generate_qinai_prompt()
    # 原代码在此处硬编码 prompt 字符串，完全绕过 C5 的：
    #   · P1 人设文件加载与哈希校验
    #   · 输入净化（全角转半角、Unicode 过滤、反注入标签清洗）
    #   · SHA-256 完整性验证
    # 修复：将长期记忆 + 短期上下文合并后传入 generate_qinai_prompt
    llm_raw_reply = FALLBACK_REPLY
    if MODULE_STATUS.get("C5"):
        memory_parts = []
        if long_term_memory:
            memory_parts.append(long_term_memory)
        if recent_context:
            memory_parts.append(f"【最近对话】\n{recent_context}")
        combined_memory = "\n\n".join(memory_parts)

        final_prompt = generate_qinai_prompt(
            memory_context=combined_memory,
            user_input=user_input
        )

        # 4. C5 调用 GPU 侧车
        if GPU_ACTIVE:
            llm_raw_reply = qinai_llm_call(final_prompt)
        else:
            llm_raw_reply = FALLBACK_REPLY

    # 5. C4 输出人设校验
    last_reply_text = SHORT_TERM_MEMORY[-1]["reply"] if SHORT_TERM_MEMORY else ""
    c4_pass = True
    if MODULE_STATUS.get("C4"):
        c4_pass, c4_result = c4_persona_check(llm_raw_reply, last_reply=last_reply_text)
        final_reply = c4_result
    else:
        final_reply = llm_raw_reply

    # 6. 更新海马体 & C6 写回（仅主链交互写入，边车来源不写记忆）
    if c4_pass and source == "interactive":
        SHORT_TERM_MEMORY.append({"user": user_input, "reply": final_reply})
        if len(SHORT_TERM_MEMORY) > MAX_CONTEXT_ROUNDS:
            SHORT_TERM_MEMORY.pop(0)
        if MODULE_STATUS.get("C6") and security_pass:
            if utils_guard.check_c4_rules_for_c6(final_reply):  # 架构师修复：根据Gemini报告修正C6与C4规则脱节问题
                c6_submit_memory(user_input, final_reply)

    # 7. L5 审计记录
    if MODULE_STATUS.get("L5"):
        write_audit_log(user_input, final_reply, MODULE_STATUS)
    else:
        _write_g3("CHAIN_OK", source, final_reply[:60])

    return final_reply


# =============================================================
# 全链路主对话循环
# =============================================================
utils_guard.bridge_audit_chain()  # 架构师修复：根据Gemini报告修正L5审计哈希链断链问题
while True:
    user_input = input("主理人: ").strip()
    if user_input.lower() in ["exit", "quit"]:
        # 关闭所有边车进程
        for sid, proc in SIDECAR_PROCS.items():
            try:
                proc.terminate()
            except Exception:
                pass
        print("祈奈已安全下线，主理人再见～")
        break
    if not user_input:
        continue

    print("祈奈(L2 中枢运转中)...")
    final_reply = FALLBACK_REPLY

    try:
        final_reply = _run_chain(user_input, source="interactive")
    except SystemExit as e:
        # [P1修复] C1 熔断不打印内部标识到终端，写审计后安全退出
        print("检测到运行环境异常，祈奈需要暂时休息一下。")
        break
    except Exception as e:
        # [P1修复] 全链路异常写 G3 审计，不向终端暴露模块名与堆栈
        _write_g3("CHAIN_ERROR", "interactive", str(e))
        final_reply = FALLBACK_REPLY

    # 逐字打字机输出
    print(f"\n祈奈: ", end="", flush=True)
    for char in final_reply:
        print(char, end="", flush=True)
        time.sleep(0.04)
    print("\n" + "-" * 70)
