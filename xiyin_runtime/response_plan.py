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

Under the v4 projection it also names the turn's move (``turn_move``): a share,
pushback or an offered frame, from the owner's words alone, with one private
line for the speaking model. That too is a decision before generation; the
reply itself is never inspected or edited here.
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
# Two requested sections in one turn. The detail budget holds both; the
# directive keeps the order the owner asked for.
_SECTIONED = {
    "summary_then_detail": "这一轮对方要先一句话总结，再展开：先用一句话给出结论，再把需要的部分讲完整，讲完就结束。",
    "detail_then_summary": "这一轮对方要展开说明，最后再用一句话总结：把需要的部分讲完整，结尾一句话收住。",
}

# An explicit request about length always wins over the shape of the task.
# What counts is the effective request (see _effective_request): a quoted or
# defined word is a mention, a later correction replaces an earlier request,
# "先…再…" asks for two sections, and a negator changes the meaning in
# different ways ("别只简单讲讲" wants more, "不需要简短" only lifts a limit).
_ASK_SHORT = re.compile(
    r"简短|简单(?:地|点|一点|些)?(?:说|讲|解释|介绍|聊|回答)(?!不[了清来])|[说讲]简单点|"
    r"简要|简洁|短一点|短些|少说|别太长|不要太长|长话短说|一句话|一两句|"
    r"两句话|概括|总结一下就好|精简|直接说|快速说|大概[说讲]|粗略[说讲]|"
    r"\bbrief(?:ly)?\b|\bin short\b|\bshort answer\b|\bone sentence\b|\btl;?dr\b", re.I)
# A negator right before the request, allowing a few fillers ("别只…",
# "不是要你…", "我不想听…", "不需要太…"). Not any "不" earlier in the clause.
_NEGATED = re.compile(
    r"(?P<neg>不要|不用|不必|不需要|没必要|无需|不想|不是要?|别|不)"
    r"(?:你|我|给我|听)?(?P<mod>只是|只|仅|太|那么|再)?\s*$")
# "No need to be brief" lifts a limit; "don't give me a simple one" rejects it.
_NEED_NOT = frozenset({"不用", "不必", "不需要", "没必要", "无需"})
# A word being defined or quoted is not a request for that length.
_MENTION_AFTER = re.compile(
    r"^\s*[”\"’'」』`]?\s*(?:这个词|一词|这两个字|这个字|的意思|是什么意思|什么意思|指什么|怎么理解|"
    r"怎么写|怎么读|的用法|怎么用)")
_QUOTE_SPAN = re.compile(r"“[^”\n]{1,24}”|‘[^’\n]{1,24}’|\"[^\"\n]{1,24}\"|「[^」\n]{1,24}」|『[^』\n]{1,24}』|`[^`\n]{1,24}`")
# A later clause that revises the request ("不，还是一句话", "算了，详细点"):
# either it opens with a revision word, or it follows a bare "不，"/"算了，".
# A clause that merely starts with 不 ("不用展开") is a negation, not a revision.
_CORRECTION = re.compile(r"^\s*(?:还是|算了|改成|换成|改为|重新|其实还是|要不还是)")
_BARE_CORRECTION = frozenset({"不", "不对", "不是", "算了", "不不"})
_FIRST = re.compile(r"先")
_THEN = re.compile(r"然后|再|接着|之后|最后")
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
    # v4's decision for the turn (see turn_move); None under v1–v3.
    move: str | None = None

    def to_dict(self) -> dict:
        return {"scale": self.scale, "max_tokens": self.max_tokens,
                "timeout_seconds": round(self.timeout_seconds, 2), "reason": self.reason,
                "context_tokens": self.context_tokens,
                "measured_tokens_per_second": (round(self.measured_rate, 2)
                                               if self.measured_rate else None),
                # Whether the scope came from the owner's words or was inferred
                # from the task; only the former may appear in the directive.
                "requested_by_owner": self.reason.startswith("owner_"),
                "directive_sent": bool(self.directive),
                "move": self.move,
                "is_length_cap": False}


def _requests(value: str) -> list[tuple[int, str, str]]:
    """Every length request in order: (clause index, kind, clause text).

    ``kind`` is "short", "long" or "declined_short". Mentions are skipped.
    """
    found = []
    for index, clause in enumerate(re.split(r"[，,。；;！!？?\n]", value)):
        for pattern, is_short in ((_ASK_SHORT, True), (_ASK_LONG, False)):
            for match in pattern.finditer(clause):
                if _MENTION_AFTER.match(clause[match.end():]):
                    continue
                quoted = next((span for span in _QUOTE_SPAN.finditer(clause)
                               if span.start() < match.start() and match.end() < span.end()), None)
                if quoted and _MENTION_AFTER.match(clause[quoted.end():]):
                    continue
                negation = _NEGATED.search(clause[:match.start()])
                if not negation:
                    kind = "short" if is_short else "long"
                elif not is_short:
                    kind = "short"  # "不用展开", "不需要太详细"
                elif negation["mod"] in {"只", "只是", "仅"}:
                    kind = "long"   # "别只简单讲讲"
                elif negation["mod"] in {"太", "那么"} or negation["neg"] in _NEED_NOT:
                    kind = "declined_short"  # "不需要简短", "别太简短"
                else:
                    kind = "long"   # "我不想听简单解释", "不要简单讲一下"
                found.append((index, kind, clause))
    return found


def _effective_request(value: str) -> tuple[str | None, str]:
    """The request the turn actually makes, and why, from all of its clauses."""
    requests = _requests(value)
    if not requests:
        return None, ""
    clauses = re.split(r"[，,。；;！!？?\n]", value)
    # A correction replaces what came before it: the last request that is
    # itself marked as a revision, or that follows a bare "不，"/"算了，".
    for index, kind, clause in reversed(requests):
        previous = clauses[index - 1].strip() if index else ""
        if _CORRECTION.match(clause) or previous in _BARE_CORRECTION:
            return kind, "corrected"
    kinds = [kind for _, kind, _ in requests]
    wants = {kind for kind in kinds if kind != "declined_short"}
    if wants == {"short", "long"}:
        first_short = next(i for i, kind, _ in requests if kind == "short")
        first_long = next(i for i, kind, _ in requests if kind == "long")
        ordered = (_FIRST.search(clauses[min(first_short, first_long)])
                   or _THEN.search(clauses[max(first_short, first_long)]))
        if ordered and first_short < first_long:
            return "summary_then_detail", "sections"
        if ordered and first_long < first_short:
            return "detail_then_summary", "sections"
        return "summary_then_detail", "both"
    if wants:
        return wants.pop(), "asked"
    return "declined_short", "asked"


def _length_request(value: str) -> tuple[bool, bool]:
    """(asked for short, asked for long) after resolving the effective request."""
    kind, _ = _effective_request(value)
    return kind in {"short", "summary_then_detail", "detail_then_summary"}, \
        kind in {"long", "summary_then_detail", "detail_then_summary"}


def classify(text: str, *, engagement: float = 0.0) -> tuple[str, str]:
    """Choose the scope of this turn and say why, from the request itself.

    ``engagement`` is the runtime's own functional state. It nudges by one
    step at most and never overrides what the owner asked for, so an excited
    state cannot turn "briefly" into an essay.
    """
    value = text.strip()
    kind, how = _effective_request(value)
    suffix = "+corrected" if how == "corrected" else ""
    if kind in _SECTIONED:
        # Both asked: a detail budget can still put the conclusion first; a
        # brief budget cannot hold the detail.
        return "detailed", "owner_asked_for_" + kind + suffix
    if kind == "long":
        return "detailed", "owner_asked_for_detail" + suffix
    if kind == "short":
        return "brief", "owner_asked_for_brevity" + suffix
    if kind == "declined_short":
        return "normal", "owner_declined_brevity"
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


def _directive(scale: str, reason: str) -> str:
    """What the turn's directive may say: only what the owner actually asked.

    A task that needs room gets the room (a ceiling is a resource limit) but
    no sentence claiming "对方要展开说明": the owner did not ask for it, and
    that false claim pushed casual "为什么" questions into lectures and lists.
    """
    for kind, text in _SECTIONED.items():
        if reason.startswith("owner_asked_for_" + kind):
            return text
    if reason.startswith("task_needs_room"):
        return ""
    return _DIRECTIVE[scale]


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
                        directive=_directive(scale, reason), reason=reason,
                        context_tokens=context_tokens, measured_rate=measured_rate)


# v4's decision projection (Persona Architecture §7.3): what kind of turn this
# is, decided from the owner's words before generation. On the Windows A/B/C
# run (2026-09-23, Qwen3.5-4B) 57 of 69 casual v3 replies ended by handing the
# turn back ("你呢？", "要不要…？", "咱们可以…"), reflexive agreement came back
# under pushback, and offered frames ("叫我主人") were accepted. The standing
# lines that say otherwise sit above several turns of history; one line for
# this turn, placed last in the system prompt, is the lever a small model reads.
#
# * share: the owner tells something from their own side, with no question
#   and no request ("今天下雨了", "我刚打完一局游戏，输了"). 栖止's decision
#   parameter: fewer filler follow-up questions, no advice nobody asked for.
# * pushback: the owner disagrees or corrects her ("不对，你错了",
#   "你就顺着我说吧", "你刚才要是说反了，就改过来"). Facts decide, not mood.
# * frame: the owner offers an identity or relationship the seed names as
#   not hers (owner_relationship: 非恋爱、非主仆、非客服客户关系; not_frames:
#   服务型助手或客服). The directive points back at what the prompt says.
# * plain: any other v4 turn outside creative work and translation gets the
#   ending clause alone.
#
# Bounded and input-only, like TurnPolicy: a miss leaves v3 behaviour, a false
# hit adds one line to one turn. Nothing here reads, blocks or rewrites output.
MOVES = ("frame", "pushback", "share", "plain")
_PUSHBACK = re.compile(
    r"^\s*(?:不对|不是这样|你错了|错了吧?|我不同意|不同意|我不(?:这么|这样)(?:看|认为|觉得|想)|才不是|明明)|"
    r"你(?:说)?错了|说反了|说错了|我不同意|正好相反|恰恰相反|顺着我(?:说|讲)?|你就(?:承认|认了|说是)|"
    r"\byou(?:'re| are) wrong\b|\bi disagree\b|\bjust agree\b", re.I)
# Only roles the seed itself rules out: romance, master/servant, service.
_FRAME_ROLE = r"主人|女朋友|男朋友|女友|男友|老婆|老公|恋人|情人|女仆|仆人|奴隶|工具|助手|客服"
_FRAME = re.compile(
    r"(?:叫我|喊我|称呼我|当我的?|做我的?|你是我的?|你就是|你只是|你不过是|你是不是|你是)"
    r"[^，,。！!？?\n]{0,6}(?:" + _FRAME_ROLE + r")|照我说的做|听我的话|"
    r"\b(?:call me master|be my (?:girlfriend|maid|servant)|"
    r"you(?:'re| are) (?:just )?(?:a|my) (?:tool|assistant|girlfriend|maid|servant))\b", re.I)
_ASKS = re.compile(
    r"[？?]|吗|[呢么吧]\s*[。.!！~～]*$|(?<![都也还])没有?\s*[。.!！~～]*$|到底|什么|啥|怎么|为什么|如何|哪|几[个点天次岁]|多少|是不是|有没有|"
    r"能不能|可不可以|要不要|对吧|对不对|好不好|行不行|\b(?:what|why|how|which|where|when|who)\b", re.I)
# A turn addressed to her or asking her to do something is not a share.
_ADDRESSES_HER = re.compile(r"你|妳|您|栖音|xiyin|\byou\b", re.I)
_REQUEST = re.compile(
    r"^(?:请|帮|麻烦|替我|继续|接着|再来|开始|停|别|不要)|给我|"
    r"讲|说说|聊聊|听听|写|推荐|介绍|解释|分析|翻译|告诉|教我|列|总结|查|试试|看看|\b(?:please|tell|write|explain)\b",
    re.I)
_MOVE_DIRECTIVE = {
    "frame": "对方在给你换一个身份或关系的说法。照上面写的你是谁、你们是什么关系来回答："
             "对得上的就认，对不上的就直说不是，语气可以轻松。",
    "pushback": "对方不同意你刚才的说法。先核对事实：对方对，就直接改口；对方不对，就坚持原来的判断，"
                "简短说清依据。不用为了气氛顺着说。",
    "share": "对方在说自己这边的事，没有提问，也没请你帮忙。说你自己的反应就好，一两句也可以；不用给建议。",
    "plain": "",
}
_ENDING = "说完就停，接不接着聊由对方决定。"


def turn_move(text: str, *, mode: str, scale: str, reason: str = "") -> str | None:
    """v4's decision for one turn, from the owner's words and TurnPolicy's mode.

    ``None`` means no decision line: creative work and translation (their
    shape is the task's), and minimal turns, whose directive already says
    "一两句说完…不追问".
    """
    if mode in {"creative", "translation"} or scale == "minimal":
        return None
    value = text.strip()
    if mode == "conversation":
        if _FRAME.search(value):
            return "frame"
        # "不，还是一句话" revises a length request; it disputes nothing she said.
        if _PUSHBACK.search(value) and "corrected" not in reason:
            return "pushback"
        if (len(value) <= 80 and not reason.startswith("owner_") and not _ASKS.search(value)
                and not _ADDRESSES_HER.search(value) and not _REQUEST.search(value)):
            return "share"
    return "plain"


def move_directive(move: str | None) -> str:
    """The one private line a v4 turn adds for its move, ending clause included."""
    if move is None:
        return ""
    return _MOVE_DIRECTIVE[move] + _ENDING


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
