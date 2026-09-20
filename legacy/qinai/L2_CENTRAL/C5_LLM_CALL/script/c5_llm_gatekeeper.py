# =============================================================================
# Qinai AI L2 central C5 LLM gateway
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
# Path: C:\L0_RUNTIME\L2_CENTRAL\C5_LLM_CALL\script\c5_llm_gatekeeper.py
# =============================================================================

import os
import time


def _xiyin_init_root():
    """A4/P4 极薄入口加载接线（本文件位于 <运行根>\L2_CENTRAL\C5_LLM_CALL\script）。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))),
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
    return sys.modules["xiyin_paths"]


_XIYIN_ROOT = _xiyin_init_root().project_root()

import requests

# Fixed local GPU sidecar route. Do not change architecture binding.
# A7: 推理端点单一可配置来源（config/runtime.toml [inference].endpoint），
# 探针与调用共同消费同一来源；缺失/损坏即失败（不回退硬编码，不冒充可用）。
def _load_inference_config() -> str:
    import tomllib
    paths = _xiyin_init_root()
    path = paths._inside(_XIYIN_ROOT, _XIYIN_ROOT / "config" / "runtime.toml")
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    endpoint = cfg["inference"]["endpoint"]
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("runtime.toml [inference].endpoint must be a nonempty string")
    return endpoint.strip()

_INFERENCE_ENDPOINT = _load_inference_config()
GPU_API_URL = _INFERENCE_ENDPOINT
RUNTIME_LOG_PATH = os.path.join(str(_XIYIN_ROOT), "L5_SAFE", "G3_AUDIT", "l2_central_runtime.log")
REQUEST_TIMEOUT_SECONDS = 300  # raised from 120 — first inference after GPU load can be slow
MAX_ATTEMPTS = 2

# Retained compatibility constant; failures never become character speech.
FALLBACK_REPLY = ""


class LLMUnavailableError(RuntimeError):
    """The local provider did not produce usable model text."""


def _write_runtime_marker(step: str, status: str, detail: str):
    """
    Function: 将 C5 LLM 调用事件（重试/降级/恢复）追加写入运行时日志。
    Input:    step (str) — 步骤标识（如 "C5_CALL"）；
              status (str) — 状态（如 "RETRY" / "FALLBACK" / "RECOVER"）；
              detail (str) — 详情，自动截断至 100 字符并去换行。
    Output:   无返回值；写入失败静默忽略。
    Depends:  time；RUNTIME_LOG_PATH 常量（C:\L0_RUNTIME\L5_SAFE\G3_AUDIT\）。
    Security: 所有写入异常静默处理，防止日志失败阻塞 LLM 调用主路径；
              detail 截断防止超长响应体污染日志结构。
    """
    try:
        safe_detail = str(detail).replace("\n", " ")[:100]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"[{timestamp}] | 环节: {step.ljust(12)} | "
            f"状态: {status.ljust(16)} | 详情: {safe_detail}\n"
        )
        with open(RUNTIME_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception:
        pass


def _extract_reply(response):
    """
    Function: 从 GPU sidecar HTTP 响应中提取 reply 字符串并校验结构合法性。
    Input:    response — requests.Response 对象。
    Output:   (str, None) 提取成功，str 为非空 reply；
              (None, str) 失败，str 为错误码（HTTP_xxx / INVALID_JSON / MISSING_RESPONSE / EMPTY_RESPONSE）。
    Depends:  requests.Response.json()。
    Security: 对 HTTP 非 200、JSON 解析失败、字段缺失、空响应分别返回错误码，
              不抛出异常，确保调用方可对所有失败路径统一处理。
    """
    if response.status_code != 200:
        return None, f"HTTP_{response.status_code}"

    try:
        payload = response.json()
    except Exception:
        return None, "INVALID_JSON"

    if not isinstance(payload, dict):
        return None, "INVALID_PAYLOAD"
    reply = payload.get("response")
    if not isinstance(reply, str):
        return None, "MISSING_RESPONSE"

    reply = reply.strip()
    if not reply:
        return None, "EMPTY_RESPONSE"

    return reply, None


def qinai_llm_call(prompt):
    """
    Function: C5 LLM 调用主接口，向本地 GPU sidecar 发送 prompt 并返回生成文本。
    Input:    prompt (str) — generate_qinai_prompt() 生成的完整 prompt 字符串。
    Output:   str — 非空模型回复；失败抛出 LLMUnavailableError。
    Depends:  requests；GPU_API_URL（127.0.0.1:11434，仅本机可达）；
              REQUEST_TIMEOUT_SECONDS / MAX_ATTEMPTS 常量；_extract_reply、_write_runtime_marker。
    Security: 仅绑定 127.0.0.1，不可从外部网络访问；
              空 prompt 直接抛错，不发起网络请求；
              重试上限 MAX_ATTEMPTS=2，防止因 sidecar 宕机导致无限阻塞；
              网络异常按固定次数重试后转为明确失败，不生成角色话术。
    """
    if not isinstance(prompt, str) or not prompt.strip():
        _write_runtime_marker("C5_CALL", "FAIL", "EMPTY_PROMPT")
        raise LLMUnavailableError("EMPTY_PROMPT")

    last_reason = "UNKNOWN"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                GPU_API_URL,
                json={"prompt": prompt},
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            reply, error = _extract_reply(response)
            if reply is not None:
                if attempt > 1:
                    _write_runtime_marker("C5_CALL", "RECOVER", f"attempt={attempt}")
                return reply
            last_reason = error or "UNKNOWN_RESPONSE"
        except requests.Timeout:
            last_reason = "TIMEOUT"
        except requests.RequestException:
            last_reason = "REQUEST_ERR"
        except Exception:
            last_reason = "CALL_ERR"

        if attempt < MAX_ATTEMPTS:
            _write_runtime_marker("C5_CALL", "RETRY", f"attempt={attempt} reason={last_reason}")
        else:
            _write_runtime_marker("C5_CALL", "FAIL", f"reason={last_reason}")

    raise LLMUnavailableError(last_reason)


# Original compatibility wrapper required by architecture.
def llm_create_completion(prompt):
    """
    Function: 架构兼容性包装器，将旧版调用约定代理至 qinai_llm_call()。
    Input:    prompt (str) — 同 qinai_llm_call 的 prompt 参数。
    Output:   str — 同 qinai_llm_call 的返回值。
    Depends:  qinai_llm_call()（本模块）。
    Security: 纯转发，无额外风险面；保留以维持旧调用链兼容性，勿直接删除。
    """
    return qinai_llm_call(prompt)
