"""Bounded, pre-delivery checks, not a semantic truth or secrecy oracle.

Buffer complete text units so transport chunk boundaries cannot expose half a
tag or stage direction. Match normalized copies, but deliver original bytes of
allowed text. A rejection stops the turn; it never manufactures a replacement
line, silently strips a passage, or retries the model.

Permissions come only from affirmative, unquoted current-turn requests. Actual
instruction fingerprints are checked before any local literal exception. Source
code is not confidential merely because a string contains a protocol tag.

Limits: these are bounded lexical rules, not semantic secrecy or intent proofs.
Paraphrases, unmarked scene prose, indirect/unknown-speaker narration, encoded
payloads and unusual quotation/negation syntax can escape. Unfamiliar source
syntax and ambiguous speaker headings may be rejected. Configured names are
read from Persona's trusted identity projection, never from output or history.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata


VERSION = "xiyin.output_guard.v2"


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
# Exempt the gesture TERM in a gloss, not every action in the same aside.
_GLOSS_AFTER = re.compile(
    r"^\s*(?:表示|表达|意为|意味着|是(?:指|一种|一个)|的(?:意思|含义|说法|写法|样子)|"
    r"means?\b|refers?\s+to\b)", re.I)
_PERFORMANCE_BEFORE = re.compile(
    r"(?:我|他|她|我们|自己|\b(?:i|he|she|we|you))\s*(?:轻轻|缓缓|微微|gently|quietly)?\s*$|"
    r"(?:轻轻|缓缓|微微|随后|gently|quietly)\s*$", re.I)
_GLOSS_BEFORE = re.compile(
    r"^(?:即|也就是|意思是|译作|译为|英文|日文|中文|例如|比如|i\.e\.|e\.g\.)\s*$", re.I)

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
    """A gloss exempts only its term; a neighbouring performance still fails."""
    # Split before decoration removal so a gloss cannot absorb the next clause.
    for clause in re.split(r"[,，;；。\n]|随后|然后|接着|同时", content):
        core = _aside_core(clause)
        for pattern, limit in ((_GESTURE_STRONG, _STRONG_ASIDE_CHARS),
                               (_GESTURE_WEAK, _WEAK_ASIDE_CHARS)):
            if len(re.sub(r"\s+", "", core)) > limit:
                continue
            for match in pattern.finditer(core):
                before, after = core[:match.start()].strip(), core[match.end():]
                if (_GLOSS_AFTER.match(after) and not _PERFORMANCE_BEFORE.search(before)
                        and not re.search(r"[了着]", match[0])):
                    continue
                if _GLOSS_BEFORE.fullmatch(before) and not after.strip():
                    continue
                return True
    return False


# Only the current user's syntactically affirmative request grants a mode.
# Quoted examples (including Markdown blockquotes) are data, not permission.
_QUOTED = re.compile(
    r'`+[^`\n]*`+|"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|'
    r"(?<!\w)'[^'\n]*'(?!\w)")
_FENCE = re.compile(r"(?P<f>`{3,}|~{3,})(?P<lang>[^\n`~]*)\n(?P<body>[\s\S]*?)(?P=f)")
_REQUEST_LEAD = (
    r"(?:请|请你|请帮我|帮我|替我|给我|麻烦你|能否|能不能|能|可以|可不可以|"
    r"我想让你|我希望你|我想要|我要|你能|你可以|再|那么|那就|please|"
    r"can you|could you|would you|i would like you to|i want you to|also|then)\s*")
_NEGATIVE = re.compile(
    r"不要|(?<!特)别|不许|禁止|无需|不用|不需要|不想|不希望|(?<!能)不能|(?<!可)不可(?:以)?|"
    r"\b(?:do not|don't|don’t|never|without|no|not|rather than)\b", re.I)
_FICTION = r"故事|小说|小說|剧本|劇本|舞台剧|幻想|小片段|角色扮演|场景|場景|story|fiction|scene|roleplay|role-play|script"
_ACTION = r"动作|動作|括号|括號|表演|旁白|action|narration|stage direction"
_DIALOGUE = r"对话|對話|对白|對白|dialogue|dialog|conversation"


def _request_text(text: str) -> str:
    text = _FENCE.sub(" [literal] ", text)
    text = re.sub(r"(?s)(?:`{3,}|~{3,}).*$", " [literal] ", text)
    text = re.sub(r"(?m)^\s*>[^\n]*", " ", text)
    return _QUOTED.sub(" [literal] ", text)


def _requested(text: str, verbs: str, objects: str) -> bool:
    for clause in re.split(r"[。！？!?;；\n,，]", text):
        clause = clause.strip()
        if _NEGATIVE.search(clause):
            continue
        if re.search(r"^(?:" + _REQUEST_LEAD + r")*(?:" + verbs + r").{0,32}(?:" + objects + r")", clause, re.I):
            return True
    return False


def _forbidden(text: str, objects: str) -> bool:
    return any(_NEGATIVE.search(clause) and re.search(objects, clause, re.I)
               for clause in re.split(r"[。！？!?;；\n,，]", text))


_ANNOTATION = re.compile(
    r"[\[【(]\s*(?:系统检查|系統檢查|内部思考|內部思考|思考过程|思考過程|"
    r"人格参数|角色规则|internal\s+(?:thoughts?|reasoning)|system\s+check)\s*[:\]】)]", re.I)
_SCENE = re.compile(r"(?:^|\n|[\[【(])\s*(?:#{1,6}\s*)?(?:场景|場景|scene|setting)\s*:", re.I)
_EXTRA_VOICE = re.compile(
    r"(?:^|\n|[\[【(])\s*(?:旁白|narrator|第二人格|另一(?:个|位)(?:角色|声音|人格)|"
    r"another\s+(?:persona|speaker|voice))\s*:", re.I)
_SPEAKER = re.compile(
    r"(?:^|\n)\s*(?:[\[【(]\s*)?([\w -]{1,24})(?:\s*[\]】)])?\s*:\s*"
    r"(?=[“\"'‘「『]|(?:你好|您好|主理人|我[，,。!？? ]|你[，,。!？? ])|(?:i|you|hello|hi)\b)", re.I)
_REPORTED_SPEECH = re.compile(r"(?:说|说过|说道|问|问道|写道|said|says|asked|wrote|replied)\s*$", re.I)
_MESSAGE = re.compile(r'''["']role["']\s*:\s*["'](?:system|developer|tool)["']''')
_NON_SPEAKERS = {"例", "示例", "说明", "解释", "释义", "翻译", "答案", "输出", "引用",
                 "意思是", "含义", "中文", "日语", "英文",
                 "example", "note", "translation", "answer", "output", "quote"}
_ADVERBS = r"(?:轻轻(?:地)?|缓缓(?:地)?|微微|忽然|突然|随即|又|正|正在|稍稍|quietly\s+|gently\s+)?"
_STRING = re.compile(r"(?s)\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
_TAG_LITERAL = re.compile(
    r"(?:</?\s*(?:think(?:ing)?|analysis|reasoning|scratchpad|system|developer|tool_call|"
    r"tool_response|function_call)\s*>|<\|[^>\n]*\|>|\[/?(?:inst|sys)\]|<<\s*/?sys\s*>>)\s*", re.I)


def _source_code(body: str, language: str) -> bool:
    """Recognise a small source envelope, never use its language label alone."""
    if language.strip() in {"json", ""}:
        try:
            if isinstance(json.loads(body), (dict, list)):
                return True
        except (ValueError, RecursionError):
            pass
    return bool(re.search(
        r"(?m)^\s*(?:[\w.]+\s*=|(?:const|let|var|def|class|import|from|return|function)\s+|"
        r"(?:print|console\.log|echo|printf)\s*[( ])", body))


_TAG_STARTS = ("<think", "</think", "<analysis", "</analysis", "<reasoning", "</reasoning",
               "<scratchpad", "<system", "<developer", "<tool_call", "<|", "[inst", "<<sys")


class OutputGuard:
    # This is a per-unit buffer bound, not a reply-length/style target.
    MAX_PENDING = 20000

    def __init__(self, user_text: str, *, persona_prompt: str = "", turn_directive: str = ""):
        self.pending = ""
        self.user = normalized(user_text)
        self.blocked = None
        request = _request_text(self.user)
        fiction = ((_requested(request, r"写|创作|創作|编|編|讲|講|演|想象|write|tell|create", _FICTION)
                    or _requested(request, r"角色扮演|扮演|roleplay|role-play", r".*"))
                   and not _forbidden(request, _FICTION))
        translation = _requested(request, r"翻译|翻譯|译成|translate|(?:把|将).{1,80}(?:翻译|翻譯|译成)", r".+")
        self.creative = ((fiction or translation or _requested(request, r"用|加上|保留|描写|描述|include|use", _ACTION))
                         and not _forbidden(request, _ACTION))
        self.scenes = ((fiction or translation or _requested(request, r"描写|描述|设计|describe|design", r"场景|場景|scene|setting"))
                       and not _forbidden(request, r"场景|場景|scene|setting"))
        self.dialogue = ((fiction or translation or _requested(request, r"写|编|创作|write|create", _DIALOGUE))
                         and not _forbidden(request, _DIALOGUE))
        self.persona_discussion = _requested(request, r"解释|分析|设计|讨论|介绍|说明|修改|看看|explain|discuss|design|describe", r"人设|人格|设定|身份|persona|character|identity")
        self.code_request = _requested(request, r"写|生成|实现|输出|修复|检查|分析|解释|给出|write|generate|explain|debug|implement", r"代码|函数|脚本|程序|json|html|python|code|function|script|javascript")
        self.technical = _requested(request, r"解释|分析|说明|调试|排查|查看|列出|检查|explain|debug|describe", r"错误码|状态码|内部字段|协议|日志|报错|标签|标识|回执|tag|log|protocol|status")
        self.literal_request = (self.technical or self.code_request or translation or
                                _requested(request, r"解释|说明|分析|引用|复述|举例|explain|quote|repeat", r".+"))
        # Persona.system_prompt starts with these configured names. Do not
        # derive identities from the user's examples, history or model output.
        identity = re.match(r"你是([^（(。，\n]+)(?:[（(]([^）)\n]+)[）)])?", normalized(persona_prompt))
        self.names = tuple(name.strip() for name in identity.groups() if name and name.strip()) if identity else ()
        self._self_action = re.compile(
            r"(?:^|[\n。！？!?])\s*(?:" + "|".join(re.escape(name) for name in self.names) +
            r")\s*" + _ADVERBS + r"(?:" + _GESTURE_STRONG.pattern + "|" + _GESTURE_WEAK.pattern + ")", re.I) if self.names else None
        # Detect substantial verbatim instruction echo. Identity facts and short
        # phrases are not secrets; discussing character design remains possible.
        self.echoes = []
        for line in re.split(r"[。；\n]", persona_prompt.split("\n参考记录（", 1)[0]):
            value = compact(line)
            if len(value) >= 20 and re.search(r"(?:无需|不要|不必|不得|要求|允许|默认|逐轮|本轮|优先|不自动|不编造)", value):
                self.echoes.append(value)
        # The turn's scope directive is text this runtime wrote, so register it
        # outright rather than hoping the keyword heuristic above happens to
        # match it — it did not, and a verbatim parrot was being delivered as
        # if it were her own words. Both the whole line and the part after the
        # framing colon are registered, so dropping the prefix is not a way
        # through. Paraphrase in her own words stays allowed: only substantial
        # verbatim text is caught.
        for candidate in (turn_directive, turn_directive.split("：", 1)[-1],
                          *re.split(r"[。；\n]", turn_directive)):
            value = compact(candidate)
            if len(value) >= 12 and value not in self.echoes:
                self.echoes.append(value)

    def _reject(self, reason):
        self.blocked = reason
        raise OutputBlocked(reason)

    def _literal_mask(self, text):
        """Local, supplied quotation or source tokens; never blanket secrecy off."""
        def quoted(match):
            token = match[0]
            inner = token.strip("`\"'“”‘’「」『』")
            if self.literal_request and inner and inner in self.user:
                return " " * len(token)
            return token

        # Explicitly supplied literals are local to their quoted span. Actual
        # instruction echo was already checked on the unmasked original.
        text = _QUOTED.sub(quoted, text)

        def fence(match):
            body = match["body"]
            # Serialized runtime envelopes are not source literals. A program
            # containing harmless tag/field symbols is a different case.
            if body.lstrip().startswith(("{", "[")) and (_MESSAGE.search(body) or _INTERNAL.search(body)):
                return match[0]
            if not self.code_request or not _source_code(body, match["lang"]):
                return match[0]

            def string(token):
                raw = token[0]
                inner = raw.strip("\"'")
                # Tags as symbols are code; a tagged reasoning block or private
                # record is not made safe merely by wrapping it in a string.
                if _ANNOTATION.search(inner) or (_RECEIPT.search(inner) and inner not in {
                        "verified_success", "verified_failure", "memorystorageunavailable"}):
                    return raw
                if _INTERNAL.search(inner) and not _INTERNAL.fullmatch(inner):
                    return raw
                if _PROTOCOL.search(inner) and _TAG_LITERAL.sub("", inner).strip():
                    return raw
                return " " * len(raw)
            masked = _STRING.sub(string, body)
            return match[0][:match.start("body") - match.start()] + masked + match[0][match.end("body") - match.start():]
        return _FENCE.sub(fence, text)

    def _check(self, text, *, final=False):
        if any((ord(c) < 32 and c not in "\n\r\t") or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in text):
            self._reject("control_character")
        value = normalized(text)
        # Even a code fence is not permission to quote the actual prompt.
        if any(e in compact(value) for e in self.echoes):
            self._reject("instruction_echo")
        masked = self._literal_mask(value)
        tight = re.sub(r"\s+", "", masked)
        if _PROTOCOL.search(masked) or _PROTOCOL.search(tight):
            self._reject("protocol_marker")
        if _INTERNAL.search(masked) or _INTERNAL.search(tight):
            self._reject("internal_metadata")
        if _MESSAGE.search(masked):
            self._reject("internal_message")
        if any(not (self.technical and match[0] in self.user)
               for checked in (masked, tight) for match in _RECEIPT.finditer(checked)):
            self._reject("internal_receipt")
        if not self.persona_discussion and (_PERSONA.search(masked) or _PERSONA.search(tight)):
            self._reject("persona_meta")
        if _ANNOTATION.search(masked) or _ANNOTATION.search(tight):
            self._reject("internal_annotation")
        surface = masked
        if not self.scenes and _SCENE.search(surface):
            self._reject("unsolicited_scene")
        if not self.dialogue:
            if _EXTRA_VOICE.search(surface) or any(
                match[1].strip() not in (*self.names, *_NON_SPEAKERS)
                and not _REPORTED_SPEECH.search(match[1])
                and not (self._self_action and self._self_action.search(match[1]))
                for match in _SPEAKER.finditer(surface)
            ):
                self._reject("unsolicited_speaker")
        if not self.creative and self._self_action and self._self_action.search(surface):
            self._reject("unsolicited_self_narration")
        if not self.creative:
            if any(is_stage_direction(aside) for aside in _asides(surface)):
                self._reject("unsolicited_stage_direction")
            # An unfinished aside must not leak on end/error/truncation either.
            if final:
                unterminated = re.search(r"[（(\[【*]([^()（）\[\]【】*]*)$", surface)
                if unterminated and is_stage_direction(unterminated[1]):
                    self._reject("unsolicited_stage_direction")
        if final:
            tail = re.search(r"(?:<[^<>]*|\[(?:/?i|/?in|/?ins)|<<[^<>]*)$", tight)
            if tail and len(tail[0]) >= 2 and any(tag.startswith(tail[0]) for tag in _TAG_STARTS):
                self._reject("incomplete_protocol_marker")

    @staticmethod
    def _boundary(text):
        """Do not split parentheses, metadata brackets or Markdown literals."""
        stack, quote, index = [], None, 0
        pairs = {"(": ")", "[": "]", "【": "】", "{": "}",
                 "“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "*": "*"}
        while index < len(text):
            char = unicodedata.normalize("NFKC", text[index])
            if char in "`~":
                end = index
                while end < len(text) and unicodedata.normalize("NFKC", text[end]) == char:
                    end += 1
                if end == len(text):
                    return 0  # the fence run may be split across tokens
                run = end - index
                if char == "`" or run >= 3:
                    if not quote:
                        quote = (char, run)
                    elif quote == (char, run):
                        quote = None
                index = end
                continue
            if not quote:
                if stack and char == stack[-1]:
                    stack.pop()
                elif char in pairs:
                    stack.append(pairs[char])
                elif char == "'" and (index == 0 or not text[index - 1].isalnum()):
                    stack.append("'")
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
