"""Pure helpers for P6.31 reference-membership and diagnostic classification."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class SelectMembership(StrEnum):
    EXACT_OR_OVERLAP = "EXACT_OR_OVERLAP"
    SAME_SOURCE_DIFFERENT_MOMENT = "SAME_SOURCE_DIFFERENT_MOMENT"
    OUTSIDE_SELECTS = "OUTSIDE_SELECTS"
    UNKNOWN = "UNKNOWN"


class RootCause(StrEnum):
    ELIGIBILITY_FALSE_NEGATIVE = "ELIGIBILITY_FALSE_NEGATIVE"
    QUALITY_GATE_TOO_WEAK = "QUALITY_GATE_TOO_WEAK"
    QUALITY_GATE_TOO_STRICT = "QUALITY_GATE_TOO_STRICT"
    SEMANTIC_ROLE_MISMATCH = "SEMANTIC_ROLE_MISMATCH"
    LOCAL_RANKING_FAILURE = "LOCAL_RANKING_FAILURE"
    SEQUENCE_CONTEXT_FAILURE = "SEQUENCE_CONTEXT_FAILURE"
    REUSE_NOVELTY_FAILURE = "REUSE_NOVELTY_FAILURE"
    CHRONOLOGY_FAILURE = "CHRONOLOGY_FAILURE"
    DURATION_CONSTRAINT = "DURATION_CONSTRAINT"
    HIGH_LEVEL_STORY_INTENT_FAILURE = "HIGH_LEVEL_STORY_INTENT_FAILURE"
    HUMAN_ALTERNATIVE_NOT_MEANINGFULLY_BETTER = "HUMAN_ALTERNATIVE_NOT_MEANINGFULLY_BETTER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceRange:
    source_name: str
    start: int
    end: int

    @property
    def ordered(self) -> tuple[int, int]:
        return min(self.start, self.end), max(self.start, self.end)


def classify_select_membership(
    candidate: SourceRange, selects: Iterable[SourceRange],
) -> SelectMembership:
    if not candidate.source_name or candidate.start == candidate.end:
        return SelectMembership.UNKNOWN
    same_source = [row for row in selects if row.source_name == candidate.source_name]
    if not same_source:
        return SelectMembership.OUTSIDE_SELECTS
    start, end = candidate.ordered
    if any(max(start, row.ordered[0]) < min(end, row.ordered[1]) for row in same_source):
        return SelectMembership.EXACT_OR_OVERLAP
    return SelectMembership.SAME_SOURCE_DIFFERENT_MOMENT


def eligibility_stage(
    *, in_pool: bool, technical: bool | None, duration: bool | None,
    semantic: bool | None, chronology: bool | None, reuse: bool | None,
    scored: bool,
) -> str:
    """Return the first evidenced funnel stage that removed an alternative."""
    if not in_pool:
        return "NOT_IN_POOL"
    for label, state in (("QUALITY", technical), ("DURATION", duration),
                         ("SEMANTIC", semantic), ("CHRONOLOGY", chronology),
                         ("REUSE_SEQUENCE", reuse)):
        if state is False:
            return label
        if state is None:
            return "UNKNOWN"
    return "SCORED" if scored else "UNKNOWN"


def cross_project_status(primary: bool | None, control: bool | None) -> str:
    if primary is None or control is None:
        return "UNKNOWN"
    if primary and control:
        return "CROSS_PROJECT_CONFIRMED"
    if primary and not control:
        return "CONTRADICTED_BY_ELENORA"
    if not primary and control:
        return "ELENORA_ONLY"
    return "NOT_MATERIAL"
