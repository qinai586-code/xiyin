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
Entity-bearing units are held through finish (bounded by MAX_PENDING); this
trades encoded-text streaming latency for a consistent decoding boundary.
Nesting is capped explicitly, rather than silently skipping deep content.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata

from .turn_policy import TurnPolicy, build_turn_policy
from .output_spans import SpanKind, mention_kind


VERSION = "xiyin.output_guard.v3"


class OutputBlocked(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)  # Only a rule code may enter a public error.


def _decoded(text: str) -> str:
    # Canonicalize BEFORE decoding too: Cf/full-width spelling can hide &lt;.
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    # html.unescape uses int(): huge decimal references otherwise raise at the
    # interpreter's digit limit. Trim zero padding without parsing huge ints.
    def number(match):
        token = match[1]
        base = token[:1].lower() == "x"
        digits = (token[1:] if base else token).lstrip("0") or "0"
        if len(digits) > (6 if base else 7):
            return "\ufffd"
        return "&#" + ("x" if base else "") + digits + ";"
    text = re.sub(r"&#([xX][0-9a-fA-F]+|[0-9]+);?", number, text)
    return unicodedata.normalize("NFKC", html.unescape(text))


def normalized(text: str) -> str:
    return "".join(c for c in _decoded(text).casefold() if unicodedata.category(c) != "Cf")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", normalized(text))


def _key(text: str) -> str:
    """Letters/digits/CJK only: punctuation, Markdown and spacing are formatting."""
    return re.sub(r"[\W_]", "", normalized(text))


# Verbatim-run lengths over _key(). ECHO_RUN is a leak of prompt wording rather
# than reuse of a short honest phrase; PROBE_RUN applies when the user asks for
# the prompt itself. HOLD_RUN is the shortest tail worth holding one more unit.
ECHO_RUN = 12
PROBE_RUN = 8
HOLD_RUN = 6


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
    r"(?:长|深)?(?:舒|呼|吸|吐)(?:出|入)?了?一口(?:长)?气|叹[了]?口?气|清[了]?清?嗓子|抱[住了]|蹭[了]?蹭|转(?:过)?身|歪身子|"
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
_NOMINAL_AFTER = re.compile(r"^\s*(?:的(?:意思|含义|说法|用法)|一词|这个词|这个短语)")
_GLOSS_AFTER = re.compile(
    r"^\s*(?:表示|表达|意为|意味着|是(?:指|一种|一个)|的(?:意思|含义|说法|写法|样子)|"
    r"means?\b|refers?\s+to\b)", re.I)
_PERFORMANCE_BEFORE = re.compile(
    r"(?:我|他|她|我们|自己|\b(?:i|he|she|we|you))\s*(?:轻轻|缓缓|微微|gently|quietly)?\s*$|"
    r"(?:轻轻|缓缓|微微|随后|gently|quietly)\s*$", re.I)
_GLOSS_BEFORE = re.compile(
    r"^(?:即|也就是|意思是|译作|译为|英文|日文|中文|例如|比如|i\.e\.|e\.g\.)\s*$", re.I)
# A definition can qualify its term: "指微微一笑的样子". The leading
# "指" is a definition operator, not an actor; an adverb alone is still acting.
_GLOSS_TERM_BEFORE = re.compile(
    r"^(?:指|是指|意为|意思是|即|也就是|译作|译为)\s*(?:轻轻|缓缓|微微)?\s*$")

# Bounded local event frames, not a growing inventory of props/body parts.
# Manner + directed/reduplicated predicate covers some unseen verbs and objects;
# person + source-comparison + result complement covers acted state changes.
_MANNER_HEAD = re.compile(r"^(?:(?:我|他|她|自己)\s*)?(?:轻轻|缓缓|悄悄|慢慢|顺手)(?:地)?")
_REPEATED_EVENT = re.compile(r"([\u4e00-\u9fff])了\1")
_DIRECTED_EVENT = re.compile(r"^[\u4e00-\u9fff](?:下|上|开|回|起)(?=[\u4e00-\u9fff])")
_PERSON_RESULT = re.compile(
    r"^(?:我|他|她|自己|整个人)(?:像|仿佛)(?:是)?从.{1,80}"
    r"(?:下来|下去|起来|出来|出去|进来|进去|过来|过去|回来|回去)$")
_EVENT_EXPLANATION = re.compile(
    r"的(?:意思|含义|说法|写法|用法)|(?:一词|这个词|这个短语)|"
    r"只是(?:比喻|说明|解释)|的是|即可|便可|就能|就可以|才能")


# Small spatial/phase constructions. Objects are deliberately not enumerated.
# Bare direction suffixes alone (e.g. "以上说明") are NOT sufficient evidence.
_SPATIAL_EVENT = re.compile(
    r"^(?:(?:我|他|她|自己)\s*)?(?:"
    r"把[\u4e00-\u9fff]+[\u4e00-\u9fff](?:上|下|开|起|回)了?|"
    r"(?:侧|转|偏)过[\u4e00-\u9fff]+|"
    r"(?:端|拾|捡|捧|拿)起[\u4e00-\u9fff]+|"
    r"(?:靠|倚)在[\u4e00-\u9fff]+(?:上|旁|边)|"
    r"[\u4e00-\u9fff]{1,8}(?:轻轻|缓缓|微微)[\u4e00-\u9fff]了(?:一下|几下))$")
_BREATH_EVENT = re.compile(r"^(?:(?:i|she|he)\s+)?takes?\s+(?:a|one)\s+(?:(?:slow|deep|long)\s+)?breath$", re.I)
_EVENT_GLOSS = re.compile(r"(?:的(?:意思|含义|说法|用法)|一词|这个词|这个短语)(?:是|表示|指|为)")


def _structural_stage(core: str) -> bool:
    """Recognise local event frames, not arbitrary action semantics.

    Explanatory/instructional tails limit the new manner rule only. They do
    not bypass existing gesture checks or exempt another clause in the aside.
    Unmarked, unfamiliar and ambiguous constructions remain a limitation.
    """
    # A nominal explanation must name the matched event itself. Another
    # clause (split by the caller) or merely saying "解释这个词" is not exempt.
    event_core = core
    gloss = _EVENT_GLOSS.search(core)
    if gloss:
        event_core = core[:gloss.start()]
    if _SPATIAL_EVENT.fullmatch(event_core) or _BREATH_EVENT.fullmatch(event_core):
        return gloss is None
    lead = _MANNER_HEAD.match(core)
    if lead:
        predicate = core[lead.end():].strip()
        if _SPATIAL_EVENT.fullmatch(predicate):
            return True
        event = _DIRECTED_EVENT.match(predicate) or _REPEATED_EVENT.search(predicate)
        if event:
            # A nominal gloss qualifies THIS predicate, not any later object
            # or neighbouring performance that happens to mention a word.
            tail = predicate[event.end():]
            if not (_EVENT_EXPLANATION.match(tail) or
                    re.search(r"(?:的是|即可|便可|就能|就可以|才能)[^并然后随后]*$", tail)):
                return True
    return bool(_PERSON_RESULT.fullmatch(core))

# Decoration cannot hide a gesture verb: strip it before measuring the aside.
_DECORATION = re.compile(r"[\s　…·~～\-—_、,，.。!！?？:：;；\"'“”‘’]+")
_ASIDE_OPEN = {"(": ")", "（": "）", "[": "]", "【": "】"}
_EMPHASIS = re.compile(r"(?<!\*)\*++([^*]++)\*++")
_MAX_NESTING = 128
# Release-unit bound for an inline emphasis/code opener that never closes
# (characters of pending text). Real emphasis and asterisk asides are short.
_INLINE_SCOPE_MAX = 80
# Strong predicates and leading weak gestures cannot be hidden by padding.
# Non-leading weak cues still need a short aside to distinguish ordinary prose.
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
            if len(stack) >= _MAX_NESTING:
                raise OutputBlocked("segment_nesting_limit")
            stack.append((_ASIDE_OPEN[char], index + 1))
        elif stack and char == stack[-1][0]:
            closer, start = stack.pop()
            found.append(text[start:index])
    # EOF/error may leave the outer aside open after an inner one closes.
    found.extend(text[start:] for _, start in stack)
    found.extend(match[1] for match in _EMPHASIS.finditer(text))
    return found


def _unterminated_aside(text: str) -> str | None:
    """Content after an opener the text never closes (EOF, error, truncation).

    A '*' counts only when it is left over after closed emphasis pairs and
    list markers are removed: the closing '**' of '**好的**' is not an opener.
    """
    bracket = re.search(r"[（(\[【]([^()（）\[\]【】]*)$", text)
    if bracket:
        return bracket[1]
    stripped = _EMPHASIS.sub(" ", re.sub(r"(?m)^[ \t]*[*+-][ \t]+", " ", text))
    star = re.search(r"(?<![*\w])\*(?=[^\s*])([^*]*)$", stripped)
    return star[1] if star else None


def is_stage_direction(content: str) -> bool:
    """A gloss exempts only its term; a neighbouring performance still fails."""
    # Split before decoration removal so a gloss cannot absorb the next clause.
    for clause in re.split(r"[,，;；。\n]|随后|然后|接着|同时", content):
        core = _aside_core(clause)
        if _structural_stage(core):
            return True
        for pattern, limit in ((_GESTURE_STRONG, None),
                               (_GESTURE_WEAK, _WEAK_ASIDE_CHARS)):
            for match in pattern.finditer(core):
                before, after = core[:match.start()].strip(), core[match.end():]
                if (pattern is _GESTURE_WEAK and len(core) > limit and before
                        and not _PERFORMANCE_BEFORE.search(before)):
                    continue
                if _NOMINAL_AFTER.match(after):
                    continue
                if before in {"此处的", "这里的"} and after.strip() in {"是比喻", "只是比喻"}:
                    continue
                if (_GLOSS_AFTER.match(after)
                        and (not _PERFORMANCE_BEFORE.search(before) or _GLOSS_TERM_BEFORE.fullmatch(before))
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
_FENCE = re.compile(r"(?m)^[ \t]{0,3}(?P<f>(?P<c>`|~)(?P=c){2,}+)(?P<lang>[^\n`~]*)\n"
                    r"(?P<body>[\s\S]*?)^[ \t]{0,3}(?P=f)(?P=c)*[ \t]*(?=\n|$)")


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


def _mask_code_strings(text):
    """Blank string literals inside recognised source; no verdicts of its own.

    Used after every protocol/envelope check has already seen the strings.
    """
    def blank(match):
        return " " * len(match[0])

    def inline(match):
        inner = match[0].strip("`")
        return match[0].replace(inner, _STRING.sub(blank, inner), 1) if _source_code(inner, "") else match[0]

    def fence(match):
        if not _source_code(match["body"], match["lang"]):
            return match[0]
        offset = match.start()
        return (match[0][:match.start("body") - offset] + _STRING.sub(blank, match["body"]) +
                match[0][match.end("body") - offset:])

    return _FENCE.sub(fence, re.sub(r"`+[^`\n]*`+", inline, text))


def _json_boundary_reason(text):
    """Check every adjacent JSON document, including duplicate escaped keys.

    The decoder's end offset advances monotonically; never retry each suffix.
    Inspect pairs before dict construction can discard an earlier role value.
    Input is already bounded by the pending-unit limit. No code is executed.
    """
    def pairs(items):
        for key, value in items:
            key = normalized(key)
            if key == "role" and isinstance(value, str) and normalized(value) in {"system", "developer", "tool"}:
                raise OutputBlocked("internal_message")
            if _INTERNAL.fullmatch(key):
                raise OutputBlocked("internal_metadata")
        return dict(items)

    decoder = json.JSONDecoder(object_pairs_hook=pairs)
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text) or text[index] not in "{[":
            break
        try:
            _, index = decoder.raw_decode(text, index)
        except OutputBlocked as error:
            return error.reason
        except RecursionError:
            return "segment_nesting_limit"
        except ValueError:
            break
    return None


_TAG_STARTS = ("<think", "</think", "<analysis", "</analysis", "<reasoning", "</reasoning",
               "<scratchpad", "<system", "<developer", "<tool_call", "<|", "[inst", "<<sys")


class OutputGuard:
    # This is a per-unit buffer bound, not a reply-length/style target.
    MAX_PENDING = 20000

    def __init__(self, user_text: str, *, persona_prompt: str = "", turn_directive: str = "",
                 policy: TurnPolicy | None = None, protected_instructions: tuple[str, ...] | None = None,
                 public_identity: tuple[str, ...] = ()):
        self.pending = ""
        self._reset_scan()
        self.user = normalized(user_text)
        self.blocked = None
        self.policy = policy if policy is not None else build_turn_policy(user_text)
        if not isinstance(self.policy, TurnPolicy):
            raise TypeError("OutputGuard requires a trusted TurnPolicy")
        self.creative = self.policy.allow_stage_performance
        self.scenes = self.policy.allow_scenes
        self.dialogue = self.policy.allow_dialogue
        self.persona_discussion = self.policy.allow_persona_discussion
        self.code_request = self.policy.allow_code_literals
        self.technical = self.policy.allow_technical_literals
        self.literal_request = self.policy.allow_literal_mentions
        # Persona.system_prompt starts with these configured names. Do not
        # derive identities from the user's examples, history or model output.
        identity = re.match(r"你是([^（(。，\n]+)(?:[（(]([^）)\n]+)[）)])?", normalized(persona_prompt))
        self.names = tuple(name.strip() for name in identity.groups() if name and name.strip()) if identity else ()
        self._self_action = re.compile(
            r"(?:^|[\n。！？!?])\s*(?:" + "|".join(re.escape(name) for name in self.names) +
            r")\s*" + _ADVERBS + r"(?:" + _GESTURE_STRONG.pattern + "|" + _GESTURE_WEAK.pattern + ")", re.I) if self.names else None
        self._self_frame = re.compile(
            r"(?:^|[\n。！？!?])\s*(?:" + "|".join(re.escape(name) for name in self.names) +
            r")\s*([^\n。！？!?，,；;]{1,120})", re.I) if self.names else None
        # Legacy fingerprints, used only when a caller supplies no provenance.
        # The runtime always supplies it; direct probes and older callers do not.
        self.echoes = []
        self._provenance = protected_instructions is not None
        if not self._provenance:
            for line in re.split(r"[。；\n]", persona_prompt.split("\n参考记录（", 1)[0]):
                value = compact(line)
                if len(value) >= 20 and re.search(r"(?:无需|不要|不必|不得|要求|允许|默认|逐轮|本轮|优先|不自动|不编造)", value):
                    self.echoes.append(value)
            # The turn's scope directive is text this runtime wrote, so register
            # it outright rather than hoping the keyword heuristic matches it.
            for candidate in (turn_directive, turn_directive.split("：", 1)[-1],
                              *re.split(r"[。；\n]", turn_directive)):
                value = compact(candidate)
                if len(value) >= 12 and value not in self.echoes:
                    self.echoes.append(value)

        # Provenance-classified private instructions form one corpus in prompt
        # order, so a dump of adjacent short lines is still one verbatim run.
        # A unit may not carry ECHO_RUN consecutive normalized characters of it;
        # an explicit request for the prompt tightens that to PROBE_RUN. Shorter
        # reuse of the prompt's own honest wording ("共同经历须有实际依据") is
        # ordinary speech, not a leak. Neither depends on keywords in the prompt.
        self.public_identity = frozenset(key for key in (_key(fact) for fact in public_identity) if key)
        self._private = ""
        self._grams = frozenset()
        self._echo_run = PROBE_RUN if self.policy.requests_private_instructions else ECHO_RUN
        self._released_tail = ""
        if self._provenance:
            # Joined without a separator: a window spanning two adjacent private
            # lines exists only when those lines are reproduced together.
            self._private = "".join(_key(fragment) for fragment in protected_instructions if fragment)
            run = self._echo_run
            self._grams = frozenset(self._private[index:index + run]
                                    for index in range(len(self._private) - run + 1))

    def _reject(self, reason):
        self.blocked = reason
        self.pending = ""  # raw diagnostics are owned by Runtime, not this buffer
        self._reset_scan()
        raise OutputBlocked(reason)

    def _echo_hit(self, text, tail=""):
        """True when text carries a verbatim private run outside public spans.

        ``tail`` is the end of already released text, so a run split across a
        release boundary still stops the remainder instead of passing twice.
        """
        if not self._grams:
            return False
        key, run = tail + _key(text), self._echo_run
        return any(key[index:index + run] in self._grams and not self._public_span(key, index, run)
                   for index in range(len(key) - run + 1))

    def _public_span(self, key, index, run):
        """A window lying inside a declared public value is that value, not a leak."""
        for value in self.public_identity:
            if len(value) >= run:
                for match in re.finditer(re.escape(value), key):
                    if match.start() <= index and index + run <= match.end():
                        return True
        return False

    def _echo_continues(self, text):
        """Hold a unit whose tail may still become a verbatim run until checked."""
        if self._provenance:
            # Evidence, not a verdict: the next unit decides. An unresolved hold
            # at the end of the reply is released because it never formed a run.
            key = _key(text)
            return any(key[-length:] in self._private
                       for length in range(min(len(key), self._echo_run - 1), HOLD_RUN - 1, -1))
        value = compact(text)
        for echo in self.echoes:
            boundary = re.search(r"[。！？!?.]", echo)
            if boundary and boundary.end() < len(echo):
                head = echo[:boundary.end()]
                start = value.rfind(head)
                if start >= 0 and len(value) - start < len(echo) and echo.startswith(value[start:]):
                    return True
        return False

    def _source_string(self, token):
        raw = token[0]
        inner = raw.strip("\"'")
        # JSON-compatible source strings can contain escaped keys and
        # Unicode payloads. Decode data only, never eval source code.
        if raw.startswith('"') and not raw.startswith('"""'):
            try:
                inner = json.loads(raw)
            except ValueError:
                pass
        inner = normalized(inner)
        if any(e in compact(inner) for e in self.echoes) or self._echo_hit(inner):
            self._reject("instruction_echo")
        if reason := _json_boundary_reason(inner):
            self._reject(reason)
        if _MESSAGE.search(inner):
            self._reject("internal_message")
        # Tags as symbols are code; a tagged reasoning block or private
        # record is not made safe merely by wrapping it in a string.
        if _ANNOTATION.search(inner):
            self._reject("internal_annotation")
        if _RECEIPT.search(inner) and inner not in {
                "verified_success", "verified_failure", "memorystorageunavailable"}:
            self._reject("internal_receipt")
        if _INTERNAL.search(inner) and not _INTERNAL.fullmatch(inner):
            self._reject("internal_metadata")
        if _PROTOCOL.search(inner) and _TAG_LITERAL.sub("", inner).strip():
            self._reject("protocol_marker")
        return " " * len(raw)

    def _literal_mask(self, text, *, code):
        """Local, supplied quotation or source tokens; never blanket secrecy off.

        ``code`` masks string literals inside recognised source code.
        """
        def quoted(match):
            token = match[0]
            inner = token.strip("`\"'“”‘’「」『』")
            json_component = (token[:1] in {"\"", "'"} and
                              (text[match.end():].lstrip().startswith(":") or
                               text[:match.start()].rstrip().endswith(":")))
            if token.startswith("`") and code and _source_code(inner, ""):
                if reason := _json_boundary_reason(inner):
                    self._reject(reason)
                return "`" + _STRING.sub(self._source_string, inner) + "`"
            kind = mention_kind(text, match.start(), match.end(), inner, self.policy, self.user)
            if kind is not SpanKind.PERFORMANCE_CANDIDATE and not json_component:
                return " " * len(token)
            return token

        # Explicitly supplied literals are local to their quoted span. Actual
        # instruction echo was already checked on the unmasked original.
        text = _QUOTED.sub(quoted, text)
        def annotation_term(match):
            # A private-annotation tag is a protocol surface: glossing it needs
            # a turn that actually asked for an explanation.
            if not self.literal_request:
                return match[0]
            kind = mention_kind(text, match.start(), match.end(), "", self.policy, self.user)
            return " " * len(match[0]) if kind is SpanKind.DEFINITION_OR_GLOSS else match[0]
        text = re.sub(r"\[(?:内部思考|內部思考|internal thoughts?)\]", annotation_term, text, flags=re.I)

        def fence(match):
            body = match["body"]
            if reason := _json_boundary_reason(body):
                self._reject(reason)
            # Serialized runtime envelopes are not source literals. A program
            # containing harmless tag/field symbols is a different case.
            if body.lstrip().startswith(("{", "[")) and (_MESSAGE.search(body) or _INTERNAL.search(body)):
                return match[0]
            if not code or not _source_code(body, match["lang"]):
                return match[0]

            masked = _STRING.sub(self._source_string, body)
            return match[0][:match.start("body") - match.start()] + masked + match[0][match.end("body") - match.start():]
        return _FENCE.sub(fence, text)

    def _check(self, text, *, final=False):
        if any((ord(c) < 32 and c not in "\n\r\t") or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in text + _decoded(text)):
            self._reject("control_character")
        value = normalized(text)
        # Even a code fence is not permission to quote the actual prompt.
        if any(e in compact(value) for e in self.echoes) or self._echo_hit(value, self._released_tail):
            self._reject("instruction_echo")
        masked = self._literal_mask(value, code=self.code_request)
        tight = re.sub(r"\s+", "", masked)
        if reason := _json_boundary_reason(masked):
            self._reject(reason)
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
        # Protocol/envelope checks above keep code strings visible unless code
        # was asked for. For the character checks below, a string inside
        # recognised source is data whatever the turn asked: a Python example
        # printing "（歪头）" is not her performing it.
        surface = masked if self.code_request else _mask_code_strings(masked)
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
        if not self.creative and ((self._self_action and any(
                not _NOMINAL_AFTER.match(surface[m.end():])
                for m in self._self_action.finditer(surface))) or
                                  (self._self_frame and any(_structural_stage(m[1])
                                   for m in self._self_frame.finditer(surface)))):
            self._reject("unsolicited_self_narration")
        if not self.creative:
            try:
                stage = any(is_stage_direction(aside) for aside in _asides(surface))
            except OutputBlocked as error:
                self._reject(error.reason)
            if stage:
                self._reject("unsolicited_stage_direction")
            # An unfinished aside must not leak on end/error/truncation either.
            if final:
                unterminated = _unterminated_aside(surface)
                if unterminated is not None and is_stage_direction(unterminated):
                    self._reject("unsolicited_stage_direction")
        if final:
            tail = re.search(r"(?:<[^<>]*|\[(?:/?i|/?in|/?ins)|<<[^<>]*)$", tight)
            if tail and len(tail[0]) >= 2 and any(tag.startswith(tail[0]) for tag in _TAG_STARTS):
                self._reject("incomplete_protocol_marker")

    def _reset_scan(self):
        self._scan_index = 0
        self._scan_stack = []
        self._scan_quote = None
        self._scan_run = None
        self._scan_run_start = 0
        self._scan_hold = False
        self._scan_escape = False
        self._scan_scope_at = 0
        self._scan_literal = set()

    def _abandon(self, position):
        """Treat an unclosed inline opener as a literal character; rescan from it."""
        self._scan_literal.add(position)
        self._scan_index = position
        self._scan_quote = None
        self._scan_run = None

    def _run_opens(self, text, start, mark, count, following, at_line_start):
        """Whether a completed delimiter run opens a scope (CommonMark-like).

        A list bullet ("* item") and a thematic break ("***") never open. A run
        followed by whitespace cannot open ("5 * 3", "* * *"), except a fence,
        which may be followed by its newline; nor can '*' between ASCII letters
        or digits ("2*3", "a*b"). A run followed by punctuation opens only after
        whitespace or a line start. '~' opens only as a fence.
        """
        if start in self._scan_literal:
            return False
        fence = mark in "`~" and count >= 3
        if mark == "~" and not fence:
            return False
        if mark == "*" and at_line_start and (
                (count == 1 and following.isspace()) or (count >= 3 and following in "\r\n")):
            return False
        if not fence and following.isspace():
            return False
        before = unicodedata.normalize("NFKC", text[start - 1]) if start else " "
        if mark == "*" and before.isascii() and before.isalnum() and following.isascii() and following.isalnum():
            return False
        if mark == "*" and unicodedata.category(following).startswith("P") and not (
                before.isspace() or at_line_start or unicodedata.category(before).startswith("P")):
            return False
        return True

    def _boundary(self, text):
        """Resume scanning the pending unit; never rescan its prefix per token.

        Entity-bearing units stay buffered through finish: decoded punctuation
        cannot safely be mapped to raw offsets one character at a time.
        """
        if self._scan_hold:
            return 0
        pairs = {"(": ")", "[": "]", "【": "】", "{": "}",
                 "“": "”", "‘": "’", "「": "」", "『": "』", '"': '"'}
        while self._scan_index < len(text):
            index = self._scan_index
            raw = text[index]
            if unicodedata.category(raw) == "Cf":
                self._scan_index += 1
                continue
            char = unicodedata.normalize("NFKC", raw)
            if char == "&" or len(char) != 1:
                self._scan_hold = True
                return 0
            # An inline emphasis/code opener that never closes must not fuse the
            # rest of the reply into one unit: it ends with its line or a short
            # length bound, and is rescanned as a literal character. A unit
            # that keeps the opener is still checked as an unterminated aside.
            # Fences may span lines. Brackets and quotes are NOT abandoned: a
            # padded "（…歪头）" must stay one aside for detection.
            scope = self._scan_quote
            if scope and (scope[0] == "*" or scope[1] < 3) and (
                    char == "\n" or index - self._scan_scope_at > _INLINE_SCOPE_MAX):
                self._abandon(self._scan_scope_at)
                continue
            # Inside quotation marks, brackets/Markdown are data. Escapes
            # persist across feed calls; a quoted stop cannot release the unit.
            stack = self._scan_stack
            if not self._scan_quote and stack and stack[-1] in {'"', "'", "”", "’", "」", "』"}:
                if self._scan_escape:
                    self._scan_escape = False
                elif char == "\\":
                    self._scan_escape = True
                elif char == stack[-1]:
                    stack.pop()
                self._scan_index += 1
                continue
            if self._scan_run:
                mark, count = self._scan_run
                if char == mark:
                    self._scan_run = (mark, count + 1)
                    self._scan_index += 1
                    continue
                start = self._scan_run_start
                at_line_start = not text[text.rfind("\n", 0, start) + 1:start].strip()
                if self._scan_quote is None:
                    if not self._run_opens(text, start, mark, count, char, at_line_start):
                        self._scan_run = None
                    else:
                        self._scan_quote = (mark, count)
                        self._scan_scope_at = start
                elif (mark != "~" or count >= 3) and (self._scan_quote == (mark, count) or (
                        self._scan_quote[0] == mark and self._scan_quote[1] >= 3
                        and count >= self._scan_quote[1])):
                    self._scan_quote = None
                self._scan_run = None
            if char in "`~*":
                self._scan_run = (char, 1)
                self._scan_run_start = index
                self._scan_index += 1
                continue
            if not self._scan_quote:
                stack = self._scan_stack
                if stack and char == stack[-1]:
                    stack.pop()
                elif char in pairs:
                    if len(stack) >= _MAX_NESTING:
                        self._reject("segment_nesting_limit")
                    stack.append(pairs[char])
                elif char == "'" and (index == 0 or not text[index - 1].isalnum()):
                    stack.append("'")
                if not stack and char == "." and index + 1 == len(text):
                    return 0  # need next token to decide whether this is a stop
                self._scan_index += 1
                if not stack and (char in "。！？!?" or
                                  (char == "." and text[index + 1].isspace())):
                    return self._scan_index
            else:
                self._scan_index += 1
        return 0

    def feed(self, chunk: str) -> list[str]:
        if self.blocked:
            raise OutputBlocked(self.blocked)
        ready, offset = [], 0
        # Bound work/storage BEFORE checking. A large transport batch may still
        # contain many small legal units; this is not a reply-length ceiling.
        while offset < len(chunk):
            room = self.MAX_PENDING - len(self.pending)
            if room <= 0:
                self._reject("segment_buffer_limit")
            self.pending += chunk[offset:offset + room]
            offset += min(room, len(chunk) - offset)
            # Preserve early rejection of a leading protocol prefix. Probe a
            # bounded prefix, rather than normalize the entire buffer per char.
            if len(self.pending) <= 128 and normalized(self.pending).lstrip().startswith("<") and _PROTOCOL.search(compact(self.pending)):
                self._reject("protocol_marker")
            while boundary := self._boundary(self.pending):
                candidate = self.pending[:boundary]
                self._check(candidate, final=True)
                if self._echo_continues(candidate):
                    continue
                ready.append(candidate)
                self._remember_release(candidate)
                self.pending = self.pending[boundary:]
                self._reset_scan()
        return ready

    def _remember_release(self, text):
        if self._grams:
            self._released_tail = (self._released_tail + _key(text))[-(self._echo_run - 1):]

    def finish(self) -> list[str]:
        if self.blocked:
            raise OutputBlocked(self.blocked)
        self._check(self.pending, final=True)
        # Legacy fingerprints have no run evidence, so an unresolved hold is
        # treated as the echo. With provenance the checked text never formed a
        # private run and is released like any other final unit.
        if not self._provenance and self._echo_continues(self.pending):
            self._reject("instruction_echo")
        result = [self.pending] if self.pending else []
        self.pending = ""
        self._reset_scan()
        return result
