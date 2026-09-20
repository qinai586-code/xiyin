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
_GESTURE = re.compile(
    r"^(?:(?:我|栖音|轻轻|悄悄|偷偷|慢慢|微微|小声|轻声|期待地|好奇地|"
    r"无奈地|开心地|害羞地|笑着|温柔地|认真地|稍微)\s*)*"
    r"(?:歪(?:着)?头|眨(?:了眨|眨)?眼|捂脸|凑近|托着?下巴|耸(?:耸)?肩|"
    r"点(?:点|了点)?头|摇(?:摇|了摇)?头|抬(?:起)?头|低(?:下)?头|撅嘴|鼓(?:起)?嘴|"
    r"拍手|挥手|叉腰|脸红|嘟嘴|伸(?:出)?手|摸(?:摸)?头|眯(?:起)?眼|"
    r"眼神|眼睛|手指|微笑|笑了.{0,4}|露出.{0,8}笑|深吸.{0,4}气|松了?口气|"
    r"smiles?\b|blinks?\b|tilts?\b|nods?\b|blush(?:es)?\b|sighs?\b)", re.I)
_BRACKET = re.compile(r"[（(\[【]([^()（）\[\]【】]{1,2000})[）)\]】]|"
                      r"(?<!\*)\*([^*\n]{1,500})\*(?!\*)")
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
            if any(_GESTURE.search((m[1] or m[2]).strip()) for m in _BRACKET.finditer(masked)):
                self._reject("unsolicited_stage_direction")
            # An unfinished aside must not leak on end/error/truncation either.
            if final and re.search(r"[（(\[【*]([^()（）\[\]【】*]*)$", masked):
                tail = re.search(r"[（(\[【*]([^()（）\[\]【】*]*)$", masked)[1]
                if _GESTURE.search(tail.strip()):
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
