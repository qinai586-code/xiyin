# =============================================================================
# 祈奈 AI L2 中枢 C5 LLM 调用网关组件
# 存放路径: C:\L0_RUNTIME\L2_CENTRAL\C5_LLM_CALL\script\c5_llm_gatekeeper.py
# =============================================================================

import requests

# 对齐 GPU 侧车端口/路由（架构锁定，禁止修改）
GPU_API_URL = "http://127.0.0.1:11434/generate"

# 【修改位置】FALLBACK_REPLY 兜底话术
# 【原问题】原话术合规但语感偏平，缺少祈奈口吻的情绪层次
# 【修复内容】保持无AI身份词汇（不触发C4死锁），活化为带情绪的祈奈口吻
FALLBACK_REPLY = "唔……祈奈的思路好像卡住了，但是对主理人的心意可是一点都没变哦，哼。"


def qinai_llm_call(prompt):
    if not prompt:
        return FALLBACK_REPLY
    try:
        # 【修改位置】移除原三处 DEBUG/ERROR print
        # 【原问题】[C5_DEBUG]/[C5_ERROR] 明文暴露模块标识、GPU侧车存在性、端口、模型输出片段
        # 【修复内容】全部静默，不对外输出任何架构信息
        response = requests.post(
            GPU_API_URL,
            json={"prompt": prompt},
            headers={"Content-Type": "application/json"},
            timeout=120
        )
        if response.status_code == 200:
            reply = response.json().get("response", FALLBACK_REPLY).strip()
            return reply
    except Exception:
        # 静默捕获，不输出任何异常详情
        pass
    return FALLBACK_REPLY


# 原始降级导入函数，必须保留（架构要求）
def llm_create_completion(prompt):
    return qinai_llm_call(prompt)