"""Trusted prompt provenance kept beside, never inferred from, model text.

These labels describe runtime-authored projections. Retrieved records and user
messages are data and cannot grant themselves a label by printing its name.
Public identity metadata is deliberately separate from the engineering wording
that instructs the model how to present that identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PromptSource(str, Enum):
    PUBLIC_IDENTITY = "public_identity"
    # Example wording she may say as her own (a style exemplar). Not identity
    # and not an instruction; the line that frames it is still private.
    PUBLIC_EXPRESSION = "public_expression"
    # A true statement of her current situation (what is connected, her
    # current state) that the prompt tells her to answer from. Stating it is
    # an honest answer; only the instructions around it are private.
    PUBLIC_RUNTIME_FACT = "public_runtime_fact"
    PRIVATE_BEHAVIOR_INSTRUCTION = "private_behavior_instruction"
    PRIVATE_RUNTIME_DIRECTIVE = "private_runtime_directive"


SAYABLE_SOURCES = frozenset({PromptSource.PUBLIC_IDENTITY, PromptSource.PUBLIC_EXPRESSION,
                             PromptSource.PUBLIC_RUNTIME_FACT})


@dataclass(frozen=True)
class PromptFragment:
    source: PromptSource
    text: str


@dataclass(frozen=True)
class PromptProjection:
    text: str
    fragments: tuple[PromptFragment, ...]

    @property
    def protected_instructions(self) -> tuple[str, ...]:
        """No length/keyword test: classification belongs to the constructor."""
        return tuple(dict.fromkeys(fragment.text for fragment in self.fragments
                                   if fragment.source in {
                                       PromptSource.PRIVATE_BEHAVIOR_INSTRUCTION,
                                       PromptSource.PRIVATE_RUNTIME_DIRECTIVE,
                                   } and fragment.text.strip()))


def runtime_projection(facts: str | PromptProjection, directive: str = "") -> PromptProjection:
    """Classify only runtime-built text, before context appends retrieved data.

    Plain text is treated as a private directive, as before. A projection
    built by the runtime keeps the labels its constructor gave each part, so
    a situation fact is not protected merely for sharing a block with rules.
    """
    if isinstance(facts, PromptProjection):
        fragments = list(facts.fragments)
        text = facts.text
    else:
        fragments = [PromptFragment(PromptSource.PRIVATE_RUNTIME_DIRECTIVE, facts)] if facts.strip() else []
        text = facts
    if directive.strip():
        fragments.append(PromptFragment(PromptSource.PRIVATE_RUNTIME_DIRECTIVE, directive.strip()))
        text = "\n".join(filter(None, (text, directive.strip())))
    return PromptProjection(text, tuple(fragments))


def fact_projection(parts) -> PromptProjection:
    """Join runtime-authored ``(sayable, text)`` parts without changing the text."""
    parts = [(sayable, text) for sayable, text in parts if text]
    return PromptProjection("".join(text for _, text in parts), tuple(
        PromptFragment(PromptSource.PUBLIC_RUNTIME_FACT if sayable
                       else PromptSource.PRIVATE_RUNTIME_DIRECTIVE, text)
        for sayable, text in parts))
