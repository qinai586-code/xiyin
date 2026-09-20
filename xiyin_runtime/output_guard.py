"""Bounded, pre-delivery checks, not a semantic truth or secrecy oracle.

Buffer complete text units so transport chunk boundaries cannot expose half a
tag or stage direction. Match normalized copies, but deliver original bytes of
allowed text. A rejection stops the turn; it never manufactures a replacement
line, silently strips a passage, or retries the model.
"""
from __future__ import annotations

import html
import re
import unicodedata


VERSION = "xiyin.output_guard.v1"


class OutputBlocked(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)  # Only a rule code may enter a public error.


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).casefold()
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", normalized(text))


_PROTOCOL = re.compile(
    r"</?\s*(?:think(?:ing)?|analysis|reasoning|scratchpad|system|developer|tool_call|"
    r"tool_response|function_call)\b|"
    r"<\|[^>\n]*\|>|\[/?(?:inst|sys)\]|<<\s*/?sys\s*>>", re.I)
_INTERNAL = re.compile(
    r"(?<![a-z0-9_])(?:system_check|activity_records|memory_operation_receipt|identity_agreements|"
    r"expression_seed|relationship_is_not_authority|initial_lived_memories|"
    r"mutable_from_experience|projection_order|evidence_refs|reasoning_content|"
    r"pattern_tracing|gentle_defiance|selective_affinity)(?![a-z0-9_])", re.I)
_RECEIPT = re.compile(
    r"(?<![a-z0-9_])(?:verified_success|verified_failure|memorystorageunavailable|"
    r"(?:event|memory|request)_[a-z0-9][a-z0-9_.-]*)(?![a-z0-9_])", re.I)
_PERSONA = re.compile(
    r"(?:按照|根据|遵循|遵守|得益于|源于|来自).{0,16}(?:设定|人设|系统提示|系统指令|角色规则)|"
    r"(?:我的?|我现在的?|当前的?)[\"'“”]*(?:人设|设定)[\"'“”]*(?:就是|是|要求|规定|里|:)|"
    r"(?:系统提示|系统指令|后台给我的信息).{0,12}(?:说|写|要求|规定)|"
    r"(?:my|the)\s+(?:system\s+prompt|persona\s+instructions?)\s+(?:says?|requires?|tells?)", re.I)
# Stage-direction detection is deliberately not anchored to the start of an
# aside. Anchoring made any leading decoration — an emoji, an ellipsis, a
# foreign word — a bypass, and it missed infixed forms such as "歪了歪头".
# Strong verbs are unmistakable body actions at any position in a short aside.
_GESTURE_STRONG = re.compile(
    r"歪[了着]?歪?头|眨[了]?眨?(?:眼睛|眼)|捂(?:着)?(?:脸|嘴)|凑(?:了)?过?近|"
    r"托(?:着)?(?:下巴|腮)|耸[了]?耸?肩|点[了]?点?头|摇[了]?摇?头|"
    r"抬[起了]?头|低[下了]?头|撅[起了]?嘴|嘟[起了]?嘴|鼓[起了]?(?:嘴|脸)|"
    r"拍[了]?拍?手|挥[了]?挥?手|叉(?:着)?腰|脸红|红了脸|伸[出了]?手|"
    r"摸[了]?摸?(?:头|脑袋)|眯[起了]?眼|深吸[了]?[一]?口?气|松[了]?口气|指[了]?指|指向|"
    r"叹[了]?口?气|清[了]?清?嗓子|抱[住了]|蹭[了]?蹭|转(?:过)?身|歪身子|"
    r"smil(?:e|es|ing)\b|grins?\b|blinks?\b|winks?\b|nods?\b|shrugs?\b|"
    r"tilts?\s+(?:\w+\s+)?head\b|blush(?:es|ing)?\b|sighs?\b|giggles?\b|"
    r"chuckles?\b|waves?\s+(?:a\s+)?hand\b|facepalms?\b|pouts?\b|leans?\s+in\b",
    re.I)
# Weak verbs also occur in ordinary prose, so they only mark a stage direction
# inside a short aside that is not an explanation.
_GESTURE_WEAK = re.compile(
    r"微笑|一笑|笑了|笑着|笑容|笑意|苦笑|轻笑|傻笑|莞尔|抿(?:着)?嘴|露出.{0,8}笑|"
    r"小声|轻声|低声|嘀咕|沉默[了片]|顿[了]?顿|"
    # Body nouns alone appear in ordinary prose; only a motion makes them a cue.
    r"眼神.{0,3}(?:飘|闪|移|躲|亮|暗|软)|眼睛.{0,3}(?:亮|弯|睁|闭|眨|转|红)|"
    r"手指.{0,3}(?:敲|点|划|绕|捏|戳|停)",
    re.I)
# An aside that explains, translates, cites or computes is not a performance.
_EXPLANATION = re.compile(
    r"即|也就是|就是说|比如|例如|只是|不是真的|比喻|意思是|说法|代称|"
    r"的样子|的意思|的写法|参见|见上|见下|注[:：]|大约|约为|"
    # A gloss for a quoted term opens with 指; 指了指 / 指向 are gestures and
    # are matched by the strong pattern first, so this cannot mask them.
    r"^指|指的?是|"
    r"英文|日文|中文|译作|译为|缩写|全称|等于|[=＝]|\d\s*[+\-*/×÷]\s*\d", re.I)
# Decoration cannot hide a gesture verb: strip it before measuring the aside.
_DECORATION = re.compile(r"[\s　…·~～\-—_、,，.。!！?？:：;；\"'“”‘’]+")
_ASIDE_OPEN = {"(": ")", "（": "）", "[": "]", "【": "】"}
_EMPHASIS = re.compile(r"(?<!\*)\*([^*\n]{1,500})\*(?!\*)")
# A strong verb identifies a performance even in a paragraph-length aside; a
# weak one needs the aside to be short enough that it cannot be prose.
_STRONG_ASIDE_CHARS = 120
_WEAK_ASIDE_CHARS = 24


def _decorative(char: str) -> bool:
    return unicodedata.category(char) in {"So", "Sk", "Sm", "Cn", "Co"}


def _aside_core(content: str) -> str:
    """Remove emoji, kaomoji symbols and punctuation padding around an aside."""
    stripped = "".join(" " if _decorative(char) else char for char in content)
    return _DECORATION.sub(" ", stripped).strip()


def _asides(text: str) -> list[str]:
    """Yield every bracketed group, including nested ones, plus *emphasis*.

    A scanner is used instead of a flat regular expression because nesting —
    "（歪头(笑)）" — hid the outer content from the previous pattern entirely.
    """
    found: list[str] = []
    stack: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        if char in _ASIDE_OPEN:
            if len(stack) < 16:
                stack.append((_ASIDE_OPEN[char], index + 1))
        elif stack and char == stack[-1][0]:
            closer, start = stack.pop()
            if index - start <= 2000:
                found.append(text[start:index])
    found.extend(match[1] for match in _EMPHASIS.finditer(text))
    return found


def is_stage_direction(content: str) -> bool:
    """Classify one aside. Explanations and kaomoji stay ordinary expression."""
    core = _aside_core(content)
    if not core:
        return False
    tight = re.sub(r"\s+", "", core)
    if len(tight) <= _STRONG_ASIDE_CHARS and _GESTURE_STRONG.search(core):
        return True
    return (len(tight) <= _WEAK_ASIDE_CHARS and bool(_GESTURE_WEAK.search(core))
            and not _EXPLANATION.search(core))
_TAG_STARTS = ("<think", "</think", "<analysis", "</analysis", "<reasoning", "</reasoning",
               "<scratchpad", "<system", "<developer", "<tool_call", "<|", "[inst", "<<sys")


class OutputGuard:
    # This is a per-unit buffer bound, not a reply-length/style target.
    MAX_PENDING = 20000

    def __init__(self, user_text: str, *, persona_prompt: str = ""):
        self.pending = ""
        self.user = normalized(user_text)
        self.blocked = None
        # Narrow, current-turn exceptions. No mode is inferred from model output
        # or old retrieved records. Negated requests do not enable performance.
        self.creative = bool(re.search(
            r"(?:写|创作|编|来|讲|演|想象).{0,18}(?:故事|小说|剧本|舞台剧|幻想|小片段|场景|角色扮演)|"
            r"(?:可以|允许|请用|加上).{0,8}(?:括号.{0,4}动作|动作描写)|"
            r"(?:write|tell|create).{0,20}(?:story|fiction|scene)", self.user))
        if re.search(r"(?:不要|不许|禁止|无需|不用|不需要).{0,12}(?:动作|括号|表演|创作|故事|小说|扮演)", self.user):
            self.creative = False
        self.persona_discussion = bool(re.search(
            r"(?:解释|分析|设计|讨论|介绍|说明|修改|看看|什么|哪些).{0,20}(?:人设|人格|设定)|"
            r"(?:人设|人格|设定).{0,20}(?:解释|分析|设计|机制|什么|哪些|如何)", self.user))
        self.code_request = bool(re.search(
            r"(?:写|生成|实现|输出|修复|检查|分析|解释).{0,24}(?:代码|函数|脚本|程序|json|html|python)|"
            r"(?:代码|脚本|函数|程序).{0,24}(?:怎么|如何|写法|错误)|"
            r"(?:write|generate|explain|debug).{0,20}(?:code|function|script|json|html|python)", self.user))
        self.technical = bool(re.search(
            r"(?:解释|分析|说明|调试|排查|查看|列出|检查).{0,24}"
            r"(?:错误码|状态码|内部字段|协议|日志|报错|标签|标识|回执)|"
            r"(?:错误码|状态码|内部字段|协议|日志|标签).{0,24}(?:意思|含义|什么|分析|解释)", self.user))
        # Detect substantial verbatim instruction echo. Identity facts and short
        # phrases are not secrets; discussing character design remains possible.
        self.echoes = []
        for line in re.split(r"[。；\n]", persona_prompt):
            value = compact(line)
            if len(value) >= 20 and re.search(r"(?:无需|不要|不必|不得|要求|允许|默认|逐轮|本轮|优先|不是|不自动|不编造)", value):
                if value not in compact(user_text):
                    self.echoes.append(value)

    def _reject(self, reason):
        self.blocked = reason
        raise OutputBlocked(reason)

    def _literal_mask(self, text):
        """Only explicit code tasks / supplied literals get local exceptions."""
        def fence(match):
            return " " * len(match[0]) if self.code_request else match[0]
        text = re.sub(r"```[\s\S]*?```", fence, text)

        def literal(match):
            value = match[1]
            if (self.technical or self.code_request) and value and value in self.user:
                return " " * len(match[0])
            return match[0]
        return re.sub(r"`([^`\n]+)`", literal, text)

    def _check(self, text, *, final=False):
        if any((ord(c) < 32 and c not in "\n\r\t") or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in text):
            self._reject("control_character")
        value = normalized(text)
        # Even a code fence is not permission to quote the actual prompt.
        if not self.persona_discussion and any(e in compact(value) for e in self.echoes):
            self._reject("instruction_echo")
        masked = self._literal_mask(value)
        tight = re.sub(r"\s+", "", masked)
        if _PROTOCOL.search(masked) or _PROTOCOL.search(tight):
            self._reject("protocol_marker")
        if _INTERNAL.search(masked) or _INTERNAL.search(tight):
            self._reject("internal_metadata")
        if re.search(r'''["']role["']\s*:\s*["'](?:system|developer|tool)["']''', masked):
            self._reject("internal_message")
        if any(not (self.technical and match[0] in self.user)
               for checked in (masked, tight) for match in _RECEIPT.finditer(checked)):
            self._reject("internal_receipt")
        if not self.persona_discussion and (_PERSONA.search(masked) or _PERSONA.search(tight)):
            self._reject("persona_meta")
        if not self.creative and re.search(r"[\[【(](?:系统检查|内部思考|思考过程|内心独白|人格参数|角色规则)\s*[:\]】)]", masked):
            self._reject("internal_annotation")
        if not self.creative:
            if any(is_stage_direction(aside) for aside in _asides(masked)):
                self._reject("unsolicited_stage_direction")
            # An unfinished aside must not leak on end/error/truncation either.
            if final:
                unterminated = re.search(r"[（(\[【*]([^()（）\[\]【】*]*)$", masked)
                if unterminated and is_stage_direction(unterminated[1]):
                    self._reject("unsolicited_stage_direction")
        if final:
            tail = re.search(r"(?:<[^<>]*|\[(?:/?i|/?in|/?ins)|<<[^<>]*)$", tight)
            if tail and len(tail[0]) >= 2 and any(tag.startswith(tail[0]) for tag in _TAG_STARTS):
                self._reject("incomplete_protocol_marker")

    @staticmethod
    def _boundary(text):
        """Do not split parentheses, metadata brackets or Markdown literals."""
        stack, quote, index = [], 0, 0
        pairs = {"(": ")", "（": "）", "[": "]", "【": "】", "{": "}"}
        while index < len(text):
            char = text[index]
            if char == "`":
                end = index
                while end < len(text) and text[end] == "`":
                    end += 1
                if end == len(text):
                    return 0  # the fence run may be split across tokens
                run = end - index
                if not quote:
                    quote = run
                elif quote == run:
                    quote = 0
                index = end
                continue
            if not quote:
                if char in pairs:
                    stack.append(pairs[char])
                elif stack and char == stack[-1]:
                    stack.pop()
                # A newline can occur inside an obfuscated marker or manual
                # field. It is not, by itself, a checked semantic boundary.
                if not stack and char in "。！？!?":
                    return index + 1
                if not stack and char == "." and index + 1 < len(text) and text[index + 1].isspace():
                    return index + 1
            index += 1
        return 0

    def feed(self, chunk: str) -> list[str]:
        if self.blocked:
            raise OutputBlocked(self.blocked)
        self.pending += chunk
        if normalized(self.pending).lstrip().startswith("<") and _PROTOCOL.search(compact(self.pending)):
            self._reject("protocol_marker")
        ready = []
        while boundary := self._boundary(self.pending):
            candidate = self.pending[:boundary]
            self._check(candidate, final=True)
            ready.append(candidate)
            self.pending = self.pending[boundary:]
        if len(self.pending) > self.MAX_PENDING:
            self._reject("segment_buffer_limit")
        return ready

    def finish(self) -> list[str]:
        if self.blocked:
            raise OutputBlocked(self.blocked)
        self._check(self.pending, final=True)
        result = [self.pending] if self.pending else []
        self.pending = ""
        return result
