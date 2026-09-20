import os
import re
import sys
import time
import subprocess
import requests

# =============================================================
# [架构修复 1] 路径定位（XIYIN-PATH-IDENTITY-FULL-01 P2 重接线）
# __file__ 定点派生运行根；一次性显式加载便携解析器（固定布局：
# <运行根>\xiyin_paths.py，无上溯、无旧盘符回退）；sys.modules 中
# 已存在且 __file__ 不符的同名伪模块直接拒绝；BASE_PATH/MODULE_DIRS/
# G3 日志/manifest 同根派生。公开常量名与导入顺序保持不变
# （sys.path 插入仍先于 utils_guard 导入）。
# =============================================================
import importlib.util as _ilu

_L2_MAIN_DIR = os.path.dirname(os.path.abspath(__file__))
_EXPECTED_RESOLVER = os.path.join(
    os.path.dirname(os.path.dirname(_L2_MAIN_DIR)), "xiyin_paths.py")

_preloaded = sys.modules.get("xiyin_paths")
if _preloaded is not None and os.path.abspath(
        getattr(_preloaded, "__file__", "")) != os.path.abspath(_EXPECTED_RESOLVER):
    raise RuntimeError(
        "xiyin_paths pseudo-module rejected: "
        + repr(getattr(_preloaded, "__file__", None)))
if _preloaded is None:
    _spec = _ilu.spec_from_file_location("xiyin_paths", _EXPECTED_RESOLVER)
    xiyin_paths = _ilu.module_from_spec(_spec)
    sys.modules["xiyin_paths"] = xiyin_paths
    _spec.loader.exec_module(xiyin_paths)
else:
    xiyin_paths = _preloaded

_RUNTIME_ROOT = xiyin_paths.project_root()

BASE_PATH = os.path.join(str(_RUNTIME_ROOT), "L2_CENTRAL")
MODULE_DIRS = [
    BASE_PATH,
    os.path.join(BASE_PATH, "C1_Auth"),
    os.path.join(BASE_PATH, "C2_MEMORY"),
    os.path.join(BASE_PATH, "C3_INPUT_GUARD"),
    os.path.join(BASE_PATH, "C4_OUTPUT_CHECK"),
    os.path.join(BASE_PATH, "C5_LLM_CALL", "script"),
    os.path.join(BASE_PATH, "C6_WRITEBACK"),
    os.path.join(str(_RUNTIME_ROOT), "L5_SAFE"),
]

# 核心时序：必须在导入 utils_guard 之前执行插入
for _dir in MODULE_DIRS:
    if os.path.exists(_dir) and _dir not in sys.path:
        sys.path.insert(0, _dir)

import utils_guard

# 常量路径（模块级，边车 import 时可见）
G3_AUDIT_LOG  = os.path.join(str(_RUNTIME_ROOT), "L5_SAFE", "G3_AUDIT",
                             "l2_central_runtime.log")
MANIFEST_PATH = os.path.join(BASE_PATH, "C7_PLUGINS", "manifest.json")

# =============================================================
# 全局状态（默认安全值）— _boot() 负责填充真实状态
# 保持在模块顶层，使 submit_to_chain() 无需 _boot() 完成即可导入
# =============================================================
MODULE_STATUS  = {}
GPU_ACTIVE     = False
FALLBACK_MODE  = False
FALLBACK_REPLY = ""  # No character speech when generation/admission fails.
SIDECAR_PROCS  = {}
SIDECAR_LOG_FHS = {}

# [H1修复] 短期记忆海马体 + 双层上限保护
SHORT_TERM_MEMORY  = []
MAX_CONTEXT_ROUNDS = 1    # 滑动窗口：保留最近 N 轮送入 prompt 的条目数
MAX_STM_HARD_CAP   = 50   # 硬上限：防止无边界增长；超限触发 G3 WARN + 强制淘汰
DIALOGUE_STATE     = "responding"

# 函数引用占位符（_boot 填充；使模块可被安全 import 而不触发副作用）
qinai_permission_verify = None
c3_input_filter         = None
c2_get_memory           = None
c4_persona_check        = None
qinai_llm_call          = None
generate_qinai_prompt   = None
detect_expected_language = None
c6_submit_memory        = None
write_audit_log         = None
check_audit_permission  = None

# 启动幂等标志
_BOOTED = False
_BOOT_IN_PROGRESS = False  # XIYIN repair-03: concurrent-boot guard


# =============================================================
# 内部工具：G3 直写审计（L5 离线兜底）
# =============================================================
def _write_g3(step: str, status: str, detail: str):
    """
    Function : G3 runtime 日志追加写入，L5 离线时的审计兜底
    Input    : step(str) 操作标签, status(str) OK/FAIL/WARN,
               detail(str) 描述（截断至120字符）
    Output   : None — 静默失败，不阻断主链
    Depends  : G3_AUDIT_LOG 路径；SJ_Run 需有追加写权限
    Security : 不向终端输出任何内部路径或模块信息
    """
    try:
        ts    = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] | {step.ljust(14)} | {status.ljust(10)} | {detail[:120]}\n"
        with open(G3_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # 审计失败静默，不阻断主链


def _extract_relevance_terms(text: str) -> set:
    """
    Function : 提取用于 L2 二次相关性门控的最小关键词集合
    Input    : text(str) 原始用户输入或 C2 返回记忆
    Output   : set[str] — 归一化后的中英文关键词集合
    Depends  : utils_guard.qinai_normalize / re
    Security : 纯只读字符串处理，不修改主链状态
    """
    normalized = utils_guard.qinai_normalize(text).casefold()
    return {
        token for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", normalized)
        if token
    }


def _memory_relevance_score(user_input: str, memory_text: str) -> int:
    """
    Function : L2 二次相关性门控评分，避免 C2 返回的低相关记忆直接注入 C5
    Input    : user_input(str) 用户本轮输入；memory_text(str) C2 返回的候选记忆文本
    Output   : int — 命中的归一化关键词重叠数；0 表示拒绝注入
    Depends  : _extract_relevance_terms / utils_guard.qinai_normalize
    Security : 不改变 C2 检索结果本身，仅控制是否送入 C5 prompt
    """
    if not user_input or not memory_text:
        return 0

    safe_user = utils_guard.qinai_normalize(user_input)
    safe_memory = utils_guard.qinai_normalize(memory_text)
    if not safe_user or not safe_memory:
        return 0

    user_terms = _extract_relevance_terms(safe_user)
    memory_terms = _extract_relevance_terms(safe_memory)
    overlap = user_terms & memory_terms

    if overlap:
        return len(overlap)

    if len(safe_user) >= 4 and safe_user.casefold() in safe_memory.casefold():
        return 1

    return 0


# =============================================================
# _boot(): 模块加载与侧车启动 — 幂等，仅首次调用时执行
# 调用方：__main__ 入口（直接运行）/ submit_to_chain()（边车懒启动）
# =============================================================
def _boot():
    """
    Function : 完成 C1-C6、L5、C7 全模块加载与 GPU 探针；幂等执行
    Input    : None（读取模块级常量）
    Output   : None（填充全局 MODULE_STATUS / GPU_ACTIVE / 函数引用）
    Depends  : sys.path 已由模块顶层完成插入；所有 Cx 文件存在于部署路径
    Security : C1/C3 加载失败立即 sys.exit(1)；其余模块降级不阻断主链
    """
    global _BOOTED, _BOOT_IN_PROGRESS, MODULE_STATUS, GPU_ACTIVE, FALLBACK_MODE
    global qinai_permission_verify, c3_input_filter, c2_get_memory
    global c4_persona_check, qinai_llm_call, generate_qinai_prompt, detect_expected_language
    global c6_submit_memory, write_audit_log, check_audit_permission

    if _BOOTED:
        return
    if _BOOT_IN_PROGRESS:
        # XIYIN repair-03: another caller owns the boot sequence; do not run a
        # second boot. The chain's required-guard gate stays fail-closed here.
        return
    _BOOT_IN_PROGRESS = True

    print("=" * 70)
    print("祈奈AI L2中枢系统 | 全模块启动校验")
    print("=" * 70)
    print(f"当前运行用户：{os.getenv('USERNAME', '未知用户')}")
    print("-" * 70)

    # --- C1：零信任身份门禁（加载失败立即熔断）---
    print("[1/8] 正在加载 C1 身份权限与环境校验模块...")
    try:
        from c1_gatekeeper import qinai_permission_verify as _c1
        qinai_permission_verify = _c1
        c1_pass, c1_msg = qinai_permission_verify()
        if c1_pass is not True:
            raise SystemExit("C1 startup authorization failed")
    except Exception:
        print("\n[!!! MELTDOWN_PROTOCOL_ENGAGED !!!]")
        print("FATAL: 核心安全门禁(C1/C3)加载失败或文件损坏。")
        print("ACTION: TERMINATING PROCESS IMMEDIATELY.")
        sys.exit(1)
    MODULE_STATUS["C1"] = True
    print("C1 加载完成 (物理基线校验通过)")

    # --- C2：长期记忆检索（降级不阻断）---
    print("[2/8] 正在加载 C2 记忆检索模块...")
    try:
        from c2_retrieve import c2_get_memory as _c2
        c2_get_memory = _c2
        MODULE_STATUS["C2"] = True
        print("C2 加载完成")
    except Exception as e:
        MODULE_STATUS["C2"] = False
        _write_g3("C2_LOAD", "FAIL", str(e))
        print(f"C2 失败：{str(e)}")

    # --- C3：输入安全过滤（加载失败立即熔断）---
    print("[3/8] 正在加载 C3 安全过滤模块...")
    try:
        from c3_filter import c3_input_filter as _c3
        c3_input_filter = _c3
    except Exception:
        print("\n[!!! MELTDOWN_PROTOCOL_ENGAGED !!!]")
        print("FATAL: 核心安全门禁(C1/C3)加载失败或文件损坏。")
        print("ACTION: TERMINATING PROCESS IMMEDIATELY.")
        sys.exit(1)
    MODULE_STATUS["C3"] = True
    print("C3 加载完成")

    # --- C4：输出人设校验（降级不阻断）---
    print("[4/8] 正在加载 C4 输出人设校验模块...")
    try:
        from c4_verify import c4_persona_check as _c4
        c4_persona_check = _c4
        MODULE_STATUS["C4"] = True
        print("C4 加载完成")
    except Exception as e:
        MODULE_STATUS["C4"] = False
        _write_g3("C4_LOAD", "FAIL", str(e))
        print(f"C4 失败：{str(e)}")

    # --- C5：LLM 网关 + GPU 探针（连接失败降级为 FALLBACK）---
    print("[5/8] 正在加载 C5 LLM网关与Prompt引擎模块...")
    try:
        from c5_llm_gatekeeper import qinai_llm_call as _c5_llm
        from c5_persona_prompt import generate_qinai_prompt as _c5_prompt
        from c5_persona_prompt import detect_expected_language as _c5_detect_language
        qinai_llm_call        = _c5_llm
        generate_qinai_prompt = _c5_prompt
        detect_expected_language = _c5_detect_language
        MODULE_STATUS["C5"]   = True
        print("C5 模块导入成功")
        # A7: 探针与 C5 调用共同消费同一 runtime.toml 端点来源
        import tomllib as _toml
        with open(os.path.join(str(_RUNTIME_ROOT), "config", "runtime.toml"), "rb") as _fh:
            _inference = _toml.load(_fh)["inference"]["endpoint"]
        test_response = requests.post(
            _inference,
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

    # --- C6：记忆写回（降级不阻断）---
    print("[6/8] 正在加载 C6 记忆写回模块...")
    try:
        from c6_submit import c6_submit_memory as _c6
        c6_submit_memory    = _c6
        MODULE_STATUS["C6"] = True
        print("C6 加载完成")
    except Exception as e:
        MODULE_STATUS["C6"] = False
        _write_g3("C6_LOAD", "FAIL", str(e))
        print(f"C6 失败：{str(e)}")

    # --- L5：审计黑匣子（离线降级为 G3 直写）---
    print("[7/8] 正在加载 L5 审计黑匣子模块...")
    try:
        from l5_audit_logger import write_audit_log as _l5w, check_audit_permission as _l5c
        write_audit_log        = _l5w
        check_audit_permission = _l5c
        MODULE_STATUS["L5"]    = check_audit_permission()
        print("L5 加载完成")
    except Exception:
        MODULE_STATUS["L5"] = False
        print("L5 审计模块离线，降级为直写G3 (非阻断)")

    # --- C7：边车加载（任何异常不阻断主链）---
    print("[8/8] 正在加载 C7 边车模块...")
    try:
        if os.path.exists(MANIFEST_PATH):
            import c7_manifest_guard
            try:
                manifest         = c7_manifest_guard.load_manifest(MANIFEST_PATH)
                enabled_sidecars = c7_manifest_guard.select_enabled_sidecars(manifest)
            except Exception as e:
                _write_g3("SIDECAR_LOAD", "DENY", f"manifest invalid: {str(e)}")
                print(f"  C7 manifest 校验失败，跳过边车加载: {str(e)}")
                enabled_sidecars = []

            for mod in enabled_sidecars:
                if mod.get("enabled") is not True:
                    continue
                mod_id = mod.get("id", "unknown")
                entry  = mod.get("entry", "")
                if not os.path.exists(entry):
                    print(f"  边车 [{mod_id}] 入口文件不存在，跳过")
                    _write_g3("SIDECAR_LOAD", "SKIP", f"{mod_id} entry不存在: {entry}")
                    continue
                _sidecar_log_fh = None
                _handle_transferred = False
                try:
                    import time as _time
                    _sidecar_log_path = os.path.join(
                        os.path.dirname(G3_AUDIT_LOG), f"sidecar_{mod_id}.log"
                    )
                    _sidecar_log_fh = open(_sidecar_log_path, "a", encoding="utf-8")
                    proc = subprocess.Popen(
                        [sys.executable, entry],
                        stdout=_sidecar_log_fh,
                        stderr=_sidecar_log_fh
                    )
                    _time.sleep(1)
                    if proc.poll() is not None:
                        _write_g3("SIDECAR_LOAD", "FAIL",
                                  f"{mod_id} exited immediately rc={proc.returncode}")
                        print(f"  边车 [{mod_id}] 启动后立即退出 rc={proc.returncode}（非阻断）")
                        continue
                    SIDECAR_PROCS[mod_id] = proc
                    SIDECAR_LOG_FHS[mod_id] = _sidecar_log_fh
                    _handle_transferred = True
                    _write_g3("SIDECAR_LOAD", "OK",
                              f"{mod_id} pid={proc.pid} log={_sidecar_log_path}")
                    print(f"  边车 [{mod['name']}] 已启动 pid={proc.pid}")
                except Exception as e:
                    _write_g3("SIDECAR_LOAD", "FAIL", f"{mod_id}: {str(e)}")
                    print(f"  边车 [{mod_id}] 启动失败（非阻断）: {str(e)}")
                finally:
                    if _sidecar_log_fh is not None and not _handle_transferred:
                        try:
                            _sidecar_log_fh.close()
                        except Exception:
                            pass
        else:
            print("  manifest.json 不存在，跳过边车加载（正常）")
    except Exception as e:
        _write_g3("SIDECAR_LOAD", "FAIL", str(e))
        print(f"  边车加载异常（非阻断）: {str(e)}")

    print("=" * 70)
    success_count = sum(1 for v in MODULE_STATUS.values() if v)
    total_count   = len(MODULE_STATUS)
    print(f"L2中枢启动完成！{success_count}/{total_count} 模块加载正常")
    print(f"当前GPU状态：{'已激活' if GPU_ACTIVE else '未连接'}")
    print("-" * 70)

    _BOOTED = True
    _BOOT_IN_PROGRESS = False


# =============================================================
# submit_to_chain()：L3/B0/M0 等边车的唯一合规接入口
# 禁止任何边车绕过此函数直接调用 C5 或读写 L0/L1
# =============================================================
def submit_to_chain(text: str, source: str = "sidecar") -> str:
    """
    Function : 边车统一接入接口，走完整 C1→C3→C2→C5→C4→C6→L5 链路
    Input    : text(str) 原始文本；source(str) 来源标识（仅写 G3 审计，不对外）
    Output   : str — 最终回复；失败时为空，调用方不得播出或写入角色记忆
    Depends  : _boot()（懒启动）；_run_chain()
    Security : 边车唯一合规入口；禁止 C5 直连、禁止 L1 直写
    """
    reply = FALLBACK_REPLY
    try:
        _boot()  # 懒启动；失败不得返回角色兜底话术
        _write_g3("CHAIN_ENTER", source, text[:60])
        reply = _run_chain(text, source=source)
    except Exception as e:
        _write_g3("CHAIN_ERROR", source, str(e))
    return reply


def _run_chain(user_input: str, source: str = "interactive") -> str:
    """
    Function : 全链路执行核心（C1→C3→C2→C5→C4→C6→L5）
    Input    : user_input(str) 净化前原始输入；source(str) 审计来源标识
    Output   : str — 通过 C4 校验的最终回复文本
    Depends  : utils_guard；C1-C6 函数引用（需 _boot() 已执行）
    Security : C1 实时闸门；C3 输入过滤；C4 输出校验；C6 仅写 wait_check；
               STM 硬上限 MAX_STM_HARD_CAP，写入操作全量 G3 审计
    """
    user_input  = utils_guard.qinai_sanitize(user_input)
    final_reply = FALLBACK_REPLY

    if not all(MODULE_STATUS.get(key) for key in ("C1", "C3", "C4")):
        _write_g3("CHAIN_BLOCK", "FAIL", "REQUIRED_GUARD_UNAVAILABLE")
        return ""

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
        return security_msg

    expected_language = "zh"
    if detect_expected_language is not None:
        try:
            expected_language = detect_expected_language(user_input)
        except Exception:
            expected_language = "zh"

    # 2. C2 长期记忆检索
    long_term_memory = ""
    if MODULE_STATUS.get("C2"):
        long_term_memory = c2_get_memory(user_input=user_input, max_memory_num=3)
        if long_term_memory:
            relevance_score = _memory_relevance_score(user_input, long_term_memory)
            if relevance_score > 0:
                _write_g3("C2_RELEVANCE", "OK", f"score={relevance_score}")
            else:
                _write_g3("C2_RELEVANCE", "SKIP", "score=0")
                long_term_memory = ""

    # 组装短期上下文（海马体滑动窗口）
    recent_context = ""
    if SHORT_TERM_MEMORY:
        ctx_lines = [
            f"主理人: {m['user']}\n祈奈: {m['reply']}"
            for m in SHORT_TERM_MEMORY
        ]
        recent_context = "\n".join(ctx_lines)

    # 3. C5：Prompt 构建 + GPU 推理
    if not MODULE_STATUS.get("C5") or not GPU_ACTIVE:
        _write_g3("C5_CALL", "FAIL", "LOCAL_PROVIDER_UNAVAILABLE")
        return ""
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
        try:
            llm_raw_reply = qinai_llm_call(final_prompt)
        except Exception as exc:
            _write_g3("C5_CALL", "FAIL", type(exc).__name__)
            return ""
        if not isinstance(llm_raw_reply, str) or not llm_raw_reply.strip():
            _write_g3("C5_CALL", "FAIL", "EMPTY_OR_INVALID_RESPONSE")
            return ""

    # 4. C4 输出人设校验
    last_reply_text = SHORT_TERM_MEMORY[-1]["reply"] if SHORT_TERM_MEMORY else ""
    c4_pass = False
    if MODULE_STATUS.get("C4"):
        try:
            c4_pass, c4_result = c4_persona_check(
                llm_raw_reply,
                last_reply=last_reply_text,
                expected_language=expected_language,
                user_input=user_input
            )
        except Exception as exc:
            _write_g3("C4_CHECK", "FAIL", type(exc).__name__)
            return ""
        if c4_pass is not True or not isinstance(c4_result, str) or not c4_result.strip():
            _write_g3("C4_CHECK", "BLOCK", "OUTPUT_NOT_ADMITTED")
            return ""
        final_reply = c4_result
    else:
        return ""

    # 5. [H1修复] 更新海马体（双层保护）& C6 写回
    #    层1: MAX_STM_HARD_CAP 硬上限 — 超限触发 G3 WARN + 淘汰最旧条目
    #    层2: MAX_CONTEXT_ROUNDS 滑动窗口 — 控制送入 prompt 的上下文长度
    #    所有写入操作通过 G3 审计留痕，符合"所有写操作须可追溯"规则
    if c4_pass and source == "interactive":
        if len(SHORT_TERM_MEMORY) >= MAX_STM_HARD_CAP:
            _write_g3("STM_CAP", "WARN",
                      f"短期记忆达硬上限 {MAX_STM_HARD_CAP}，淘汰最旧条目")
            SHORT_TERM_MEMORY.pop(0)
        SHORT_TERM_MEMORY.append({"user": user_input, "reply": final_reply})
        _write_g3("STM_WRITE", "OK",
                  f"stm_len={len(SHORT_TERM_MEMORY)}/{MAX_STM_HARD_CAP}")
        if len(SHORT_TERM_MEMORY) > MAX_CONTEXT_ROUNDS:
            SHORT_TERM_MEMORY.pop(0)
        if MODULE_STATUS.get("C6") and security_pass:
            if utils_guard.check_c4_rules_for_c6(final_reply):
                try:
                    memory_ok, memory_status = c6_submit_memory(user_input, final_reply)
                    _write_g3("C6_WRITE", "OK" if memory_ok is True else "FAIL", str(memory_status))
                except Exception as exc:
                    _write_g3("C6_WRITE", "FAIL", type(exc).__name__)

    # 6. L5 审计记录
    if MODULE_STATUS.get("L5"):
        write_audit_log(user_input, final_reply, MODULE_STATUS)
    else:
        _write_g3("CHAIN_REPLY", source, final_reply[:60])

    return final_reply


# =============================================================
# 主入口保护 — 仅直接运行时执行启动与交互循环
# 边车通过 submit_to_chain() 导入，不触发此块，不产生任何副作用
# =============================================================
if __name__ == "__main__":
    _boot()
    utils_guard.bridge_audit_chain()

    while True:
        user_input = input("主理人: ").strip()
        if user_input.lower() in ["exit", "quit"]:
            for sid, proc in SIDECAR_PROCS.items():
                try:
                    proc.terminate()
                except Exception:
                    pass
            for sid, fh in SIDECAR_LOG_FHS.items():
                try:
                    fh.close()
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
        except SystemExit:
            print("检测到运行环境异常，祈奈需要暂时休息一下。")
            break
        except Exception as e:
            _write_g3("CHAIN_ERROR", "interactive", str(e))
            final_reply = FALLBACK_REPLY

        if not final_reply:
            print("系统：本轮未产生可播报回复，请检查本地推理与输出校验状态。")
            continue
        print(f"\n祈奈: ", end="", flush=True)
        for char in final_reply:
            print(char, end="", flush=True)
            time.sleep(0.04)
        print("\n" + "-" * 70)
