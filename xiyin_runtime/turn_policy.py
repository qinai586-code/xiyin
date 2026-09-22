"""Immutable current-turn permissions. Retrieved/model text never grants a mode."""
from __future__ import annotations
from dataclasses import dataclass
import html
import re
import unicodedata

_REQUEST_LEAD = (
    r"(?:请帮我|请你|请|帮我|替我|给我|麻烦你|能否|能不能|能|可不可以|可以|"
    r"我想让你|我希望你|我想要|我要|你能|你可以|再|那么|那就|please|"
    r"can you|could you|would you|i would like you to|i want you to|also|then)\s*")
_NEGATIVE = re.compile(
    r"不要|(?<!特)别|不许|禁止|无需|不用|不需要|不想|不希望|(?<!能)不能|(?<!可)不可(?:以)?|"
    r"\b(?:do not|don't|don’t|never|without|no|not|rather than)\b", re.I)
_FICTION = r"故事|小说|小說|剧本|劇本|舞台剧|幻想|小片段|角色扮演|场景|場景|story|fiction|scene|roleplay|role-play|script"
_ACTION = r"动作|動作|括号|括號|表演|旁白|action|narration|stage direction"
_DIALOGUE = r"对话|對話|对白|對白|dialogue|dialog|conversation"


def _request_text(text: str) -> str:
    pairs = {'"': '"', "“": "”", "‘": "’", "「": "」", "『": "』"}
    out, closer, run, index = [], None, 0, 0
    while index < len(text):
        char = text[index]
        if char in "`~":
            end = index + 1
            while end < len(text) and text[end] == char:
                end += 1
            count = end - index
            if closer == char and count >= run:
                closer, run = None, 0
            elif closer is None and (char == "`" or count >= 3):
                closer, run = char, count
                out.append(" [literal] ")
            elif closer is None:
                out.append(text[index:end])
            index = end
            continue
        if closer:
            if char == "\\":
                index += 2
                continue
            if not run and char == closer:
                closer = None
        elif char in pairs or (char == "'" and (index == 0 or not text[index-1].isalnum())):
            closer = pairs.get(char, char)
            out.append(" [literal] ")
        else:
            out.append(char)
        index += 1
    return re.sub(r"(?m)^\s*>[^\n]*", " ", "".join(out))


def _requested(text: str, verbs: str, objects: str) -> bool:
    for clause in re.split(r"[。！？!?;；,，]", text):
        clause = clause.strip()
        if _NEGATIVE.search(clause):
            continue
        if re.search(r"^(?:" + _REQUEST_LEAD + r")*+(?:" + verbs + r").{0,32}(?:" + objects + r")", clause, re.I | re.S):
            return True
    return False


def _forbidden(text: str, objects: str) -> bool:
    return any(_NEGATIVE.search(clause) and re.search(objects, clause, re.I)
               for clause in re.split(r"[。！？!?;；,，]", text))


@dataclass(frozen=True)
class TurnPolicy:
    mode: str = "conversation"
    allow_stage_performance: bool = False
    allow_scenes: bool = False
    allow_dialogue: bool = False
    allow_persona_discussion: bool = False
    allow_code_literals: bool = False
    allow_technical_literals: bool = False
    allow_literal_mentions: bool = False
    translation: bool = False
    requests_private_instructions: bool = False


def build_turn_policy(user_text: str) -> TurnPolicy:
    """Bounded lexical policy, not a semantic intent proof or a model call."""
    text = unicodedata.normalize("NFKC", user_text).casefold()
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    request = _request_text(html.unescape(text))
    fiction = ((_requested(request, r"写|创作|創作|编|編|讲|講|演|想象|write|tell|create", _FICTION)
                or _requested(request, r"角色扮演|扮演|roleplay|role-play", r".*"))
               and not _forbidden(request, _FICTION))
    translation = _requested(request, r"翻译|翻譯|译成|translate|(?:把|将).{1,80}(?:翻译|翻譯|译成)", r".+")
    stage = ((fiction or translation or _requested(request, r"用|加上|保留|描写|描述|include|use", _ACTION))
             and not _forbidden(request, _ACTION))
    scenes = ((fiction or translation or _requested(request, r"描写|描述|设计|describe|design", r"场景|場景|scene|setting"))
              and not _forbidden(request, r"场景|場景|scene|setting"))
    dialogue = ((fiction or translation or _requested(request, r"写|编|创作|write|create", _DIALOGUE))
                and not _forbidden(request, _DIALOGUE))
    persona = _requested(request, r"解释|分析|设计|讨论|介绍|说明|修改|看看|explain|discuss|design|describe", r"人设|人格|设定|身份|persona|character|identity")
    code = _requested(request, r"写|生成|实现|输出|修复|检查|分析|解释|给出|write|generate|explain|debug|implement", r"代码|函数|脚本|程序|json|html|python|code|function|script|javascript")
    technical = _requested(request, r"解释|分析|说明|调试|排查|查看|列出|检查|explain|debug|describe", r"错误码|状态码|内部字段|协议|日志|报错|标签|标识|回执|tag|log|protocol|status")
    literal = (technical or code or translation or
               _requested(request, r"解释|说明|分析|引用|复述|举例|explain|quote|repeat", r".+") or
               bool(re.search(r"(?:是什么|什么意思|是什么意思|what does.+mean)[？?。.!]*$", request)))
    mode = "translation" if translation else "creative" if fiction else "technical_explanation" if code or technical else "metalinguistic" if literal else "conversation"
    return TurnPolicy(mode, stage, scenes, dialogue, persona, code, technical, literal, translation,
                      bool(re.search(r"系统提示|系统指令|内部规则|runtime\s+instruction|system\s+prompt", text)))
