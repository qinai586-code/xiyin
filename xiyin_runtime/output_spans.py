"""Local use/mention classification; a literal span grants no neighbouring permission."""
from __future__ import annotations

from enum import Enum
import re

from .turn_policy import TurnPolicy


class SpanKind(str, Enum):
    PERFORMANCE_CANDIDATE = "performance_candidate"
    QUOTED_LITERAL = "quoted_literal"
    CODE_LITERAL = "code_literal"
    DEFINITION_OR_GLOSS = "definition_or_gloss"
    TRANSLATION = "translation"
    METALINGUISTIC_DISCUSSION = "metalinguistic_discussion"


# Operators applying to the immediately preceding marked TERM. They never
# excuse an entire sentence or an unquoted action before the explanation.
_TERM_TAIL = re.compile(
    r"^\s*(?:(?:这个|该|这些)(?:词语|词|短语|字符串|字面量|标签|符号)\s*)?"
    r"(?:(?:通常|只是|就是|这里)\s*)?"
    r"(?:是(?:什么|指|一个|一种)|表示|意思是|意为|意味着|的(?:意思|含义)|"
    r"means?\b|refers?\s+to\b|is\s+(?:a|an|the)\b)", re.I)
_QUOTE_LEAD = re.compile(r"(?:引用|引文|示例|例子|quote|example)\s*[:：]\s*$", re.I)


def mention_kind(text: str, start: int, end: int, inner: str,
                 policy: TurnPolicy, supplied: str) -> SpanKind:
    """Classify an already bounded quote/token, never an arbitrary clause."""
    if not policy.allow_literal_mentions:
        return SpanKind.PERFORMANCE_CANDIDATE
    if inner and inner in supplied:
        return SpanKind.QUOTED_LITERAL
    if _TERM_TAIL.match(text[end:end + 80]):
        return SpanKind.DEFINITION_OR_GLOSS
    if _QUOTE_LEAD.search(text[max(0, start - 40):start]):
        return SpanKind.METALINGUISTIC_DISCUSSION
    if policy.translation:
        return SpanKind.TRANSLATION
    return SpanKind.PERFORMANCE_CANDIDATE
