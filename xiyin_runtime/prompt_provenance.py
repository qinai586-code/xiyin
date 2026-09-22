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
    PRIVATE_BEHAVIOR_INSTRUCTION = "private_behavior_instruction"
    PRIVATE_RUNTIME_DIRECTIVE = "private_runtime_directive"


SAYABLE_SOURCES = frozenset({PromptSource.PUBLIC_IDENTITY, PromptSource.PUBLIC_EXPRESSION})


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


def runtime_projection(facts: str, directive: str = "") -> PromptProjection:
    """Classify only runtime-built text, before context appends retrieved data."""
    lines = (facts, directive.strip()) if directive.strip() else (facts,)
    return PromptProjection("\n".join(lines), tuple(
        PromptFragment(PromptSource.PRIVATE_RUNTIME_DIRECTIVE, line)
        for line in lines if line.strip()))
