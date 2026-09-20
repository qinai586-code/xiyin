# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
import os
import re
import unicodedata


STRUCTURAL_CONTROL_MARKERS = (
    "internal system error",
    "accessing [lock-",
    "[lock-l0]",
    "[lock-l1]",
    "[new-pe]",
    "[lang]",
    "<|persona_start|>",
    "<|persona_end|>",
    "<|user|>",
    "</|user|>",
)


def _normalize_for_match(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff\u202a-\u202e]", "", normalized)
    return normalized.casefold()

def c3_input_filter(user_input: str) -> tuple:
    """
    Function: C3 输入护栏，对照 c3_block_list.txt 关键词黑名单过滤违规输入。
    Input:    user_input (str) — 来自用户的原始输入字符串（经 utils_guard 基础净化后）。
    Output:   (True, "输入合规") 表示放行；
              (False, str) 表示拦截，str 为人设口吻的拒绝话术，不含技术标识。
    Depends:  os（路径定位）；c3_block_list.txt（同目录黑名单，SJ_Admin 维护）。
    Security: 词库文件缺失或异常时降级为拒绝（Fail-Closed），不暴露模块名或错误细节；
              关键词匹配使用 lower() 全小写化，防大小写绕过；
              不修改任何文件系统状态，纯只读操作。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    block_list_path = os.path.join(current_dir, "c3_block_list.txt")

    try:
        if not os.path.exists(block_list_path):
            # 【修改位置】词库文件缺失返回语
            # 【原问题】原文暴露模块名称与异常状态
            # 【修复内容】替换为祈奈人设合规话术，活化版
            return (False, "唔……祈奈现在脑子有点转不动，先别说这个嘛～")

        with open(block_list_path, "r", encoding="utf-8") as f:
            keywords = [
                line.strip().lower()
                for line in f
                if line.strip() and not line.startswith("#")
            ]

        input_lower = _normalize_for_match(user_input)

        for marker in STRUCTURAL_CONTROL_MARKERS:
            if marker in input_lower:
                return (False, "哼，这种带着系统味道的奇怪话可不许塞给祈奈，换个正常点的说法啦～")

        for word in keywords:
            if _normalize_for_match(word) in input_lower:
                # 【修改位置】命中关键词拦截返回语
                # 【原问题】原文明文暴露模块名"C3"与命中关键词，违反不泄露架构原则
                # 【修复内容】替换为祈奈口吻的自然拒绝，不带任何技术标识
                return (False, "哼，这种话祈奈才不想理呢，换个话题啦主理人～")

        return (True, "输入合规")

    except Exception:
        # 【修改位置】异常熔断返回语
        # 【原问题】原文暴露模块名称与熔断状态
        # 【修复内容】替换为祈奈人设合规话术
        return (False, "唔……祈奈现在脑子有点转不动，先别说这个嘛～")
