"""Per-request generation budgets, derived from the request and the machine.

Every turn previously used one fixed ``max_tokens`` and one fixed timeout, so
a request for detail hit the same 512-token wall as a greeting, and a detailed
answer on CPU ran out the same 60 seconds as a one-line reply. Length also had
no signal at all: "briefly" and a neutral question produced the same budget and
the same prompt, which is why the brief reply came out longer than the neutral
one.

This module decides scope, a token ceiling and a timeout for one turn. It does
not cap content, truncate text, choose words or select a reply template. The
ceiling is set high enough that a cooperative answer ends on its own; when it
does not, the turn still reports truncation rather than hiding it.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re


# Ordered from smallest to largest. The token figure is a ceiling with
# headroom, not a target length: the directive carries the intended scope.
SCALES = ("minimal", "brief", "normal", "detailed", "extended")
_CEILING = {"minimal": 160, "brief": 320, "normal": 640, "detailed": 1280, "extended": 1792}
_DIRECTIVE = {
    "minimal": "这一轮对方要的是确认或很短的回答：一两句说完，不补背景、不列举、不追问。",
    "brief": "这一轮对方明确要简短：先直接给结论，控制在两三句以内，不铺陈背景也不逐条展开。",
    "normal": "",
    "detailed": "这一轮对方要展开说明：把需要的部分讲完整，可以分点或举例，讲完就结束，不为凑长度重复。",
    "extended": "这一轮是长内容任务：按结构写完整，需要多少写多少；写完就结束，不复述已经写过的部分。",
}

# An explicit request about length always wins over the shape of the task.
_ASK_SHORT = re.compile(
    r"简短|简单说|简要|简洁|短一点|短些|少说|别太长|不要太长|长话短说|一句话|"
    r"两句话|概括|总结一下就好|精简|直接说|快速说|"
    r"\bbrief(?:ly)?\b|\bin short\b|\bshort answer\b|\bone sentence\b|\btl;?dr\b", re.I)
_ASK_LONG = re.compile(
    r"详细|详尽|具体说|展开说?|深入|完整地?|全面|逐条|逐步|分点|分条|多说(?:一?点|些)|"
    r"长一点|详解|细说|说透|讲透|一步一步|从头(?:讲|说)|"
    r"\bin detail\b|\bdetailed\b|\belaborate\b|\bstep[- ]by[- ]step\b|\bcomprehensive\b|"
    r"\bthorough(?:ly)?\b|\bwalk me through\b", re.I)
# Tasks whose content genuinely needs room, when no length was requested.
_EXPANSIVE = re.compile(
    r"为什么|怎么(?:做|办|实现|理解)|如何|原理|区别|对比|优缺点|步骤|教程|方案|设计|"
    r"写(?:一段|一篇|个)?(?:代码|函数|脚本|程序|故事|小说|剧本|文章|说明)|"
    r"解释|分析|评估|推荐.{0,6}(?:几|多)|列出|举例|"
    r"\bwhy\b|\bhow (?:do|does|to|can)\b|\bexplain\b|\bcompare\b|\bwrite (?:a|an|some)\b", re.I)
# Short closed questions and acknowledgements.
_CLOSED = re.compile(
    r"^(?:嗯+|哦+|好(?:的|呀|吧)?|行|可以|在吗|你好|早|晚安|谢谢|辛苦了|收到|ok|okay|hi|hello|thanks?)"
    r"[。.!！?？~～\s]*$", re.I)
_CONFIRMATION = re.compile(r"(?:是不是|对不对|对吗|好吗|可以吗|行吗|能吗|有没有|是吗)[？?。.!！\s]*$")

_SAFETY_TOKENS = 96  # Reserve for the chat template and a stop sequence.
_MIN_TIMEOUT = 20.0


def estimate_tokens(text: str) -> int:
    """Approximate a tokenizer without importing one.

    CJK runs at roughly one token per character for this model family; Latin
    text runs closer to one token per four characters. It only has to be good
    enough to keep a budget inside the server's context window.
    """
    if not text:
        return 0
    wide = sum(1 for char in text
               if "㐀" <= char <= "鿿" or "぀" <= char <= "ヿ"
               or "가" <= char <= "힯" or "＀" <= char <= "￯")
    return int(wide + math.ceil((len(text) - wide) / 3.2))


@dataclass(frozen=True)
class ResponsePlan:
    scale: str
    max_tokens: int
    timeout_seconds: float
    directive: str
    reason: str
    context_tokens: int
    measured_rate: float | None = None

    def to_dict(self) -> dict:
        return {"scale": self.scale, "max_tokens": self.max_tokens,
                "timeout_seconds": round(self.timeout_seconds, 2), "reason": self.reason,
                "context_tokens": self.context_tokens,
                "measured_tokens_per_second": (round(self.measured_rate, 2)
                                               if self.measured_rate else None),
                "is_length_cap": False}


def classify(text: str, *, engagement: float = 0.0) -> tuple[str, str]:
    """Choose the scope of this turn and say why, from the request itself.

    ``engagement`` is the runtime's own functional state. It nudges by one
    step at most and never overrides what the owner asked for, so an excited
    state cannot turn "briefly" into an essay.
    """
    value = text.strip()
    if _ASK_SHORT.search(value):
        return "brief", "owner_asked_for_brevity"
    if _ASK_LONG.search(value):
        return "detailed", "owner_asked_for_detail"
    if _CLOSED.match(value):
        return "minimal", "greeting_or_acknowledgement"
    if _CONFIRMATION.search(value) and len(value) <= 40:
        return "minimal", "closed_confirmation_question"
    if _EXPANSIVE.search(value) or len(value) > 160:
        scale = "detailed" if len(value) > 60 or _EXPANSIVE.search(value) else "normal"
        return scale, "task_needs_room"
    # An engaged conversation earns a little more room; a flat one does not.
    if engagement >= 0.6:
        return "normal", "ordinary_turn_engaged"
    return "normal", "ordinary_turn"


def plan_response(text: str, *, prompt_tokens: int, context_tokens: int, ceiling: int,
                  default_rate: float, max_timeout: float, measured_rate: float | None = None,
                  engagement: float = 0.0) -> ResponsePlan:
    scale, reason = classify(text, engagement=engagement)
    budget = min(_CEILING[scale], ceiling)
    headroom = context_tokens - prompt_tokens - _SAFETY_TOKENS
    if headroom < budget:
        budget = max(64, headroom)
        reason = reason + "+context_limited"
    rate = measured_rate if measured_rate and measured_rate > 0 else default_rate
    timeout = min(max_timeout, max(_MIN_TIMEOUT, _MIN_TIMEOUT + budget / rate * 1.5))
    return ResponsePlan(scale=scale, max_tokens=int(budget), timeout_seconds=float(timeout),
                        directive=_DIRECTIVE[scale], reason=reason,
                        context_tokens=context_tokens, measured_rate=measured_rate)


def updated_rate(previous: float | None, tokens: int, seconds: float) -> float | None:
    """Blend one observed generation rate into the running estimate.

    Only substantial, completed generations are worth learning from; a two
    token reply measures startup latency, not throughput.
    """
    if tokens < 24 or seconds <= 0.05:
        return previous
    observed = tokens / seconds
    if not math.isfinite(observed) or not 0.05 <= observed <= 5000:
        return previous
    if previous is None or not math.isfinite(previous) or previous <= 0:
        return observed
    return previous * 0.7 + observed * 0.3
