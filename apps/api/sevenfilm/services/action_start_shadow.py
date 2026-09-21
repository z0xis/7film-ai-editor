"""P6.29 conservative source-in proposals, deliberately outside the planner.

The caller supplies interpretable temporal evidence for a small set of duration-safe starts inside
one already-selected shot.  This module never selects another shot and never mutates a timeline.
Thresholds are fixed against synthetic behavioural cases; human timeline starts are evaluation-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CutInVerdict(StrEnum):
    KEEP_ORIGINAL = "KEEP_ORIGINAL"
    TRIM_PROPOSAL = "TRIM_PROPOSAL"
    REVIEW = "REVIEW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TemporalEvidence:
    start_frame: int
    subject_readiness: float
    action_onset: float
    camera_settle: float
    technical_usability: float
    obstruction_clearance: float
    semantic_continuity: float
    beat_proximity: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class CutInResult:
    verdict: CutInVerdict
    original_start: int
    proposed_start: int | None
    delta_frames: int
    confidence: float
    components: dict[str, float]
    reason: str


def candidate_starts(
    *, original_start: int, shot_end: int, required_source_frames: int, fps: float,
    maximum_shift_seconds: float = 1.0,
) -> tuple[int, ...]:
    """A bounded deterministic proposal grid that always preserves source-out capacity."""
    if fps <= 0 or required_source_frames <= 0 or original_start + required_source_frames > shot_end:
        return ()
    latest = min(shot_end - required_source_frames,
                 original_start + round(maximum_shift_seconds * fps))
    step = max(1, round(0.2 * fps))
    starts = [original_start]
    starts.extend(range(original_start + step, latest + 1, step))
    if latest > original_start and starts[-1] != latest:
        starts.append(latest)
    return tuple(dict.fromkeys(starts))


def rank_cut_in(
    *, original_start: int, evidence: tuple[TemporalEvidence, ...],
    intentional_still: bool = False,
) -> CutInResult:
    """Recommend a trim only when at least two independent visual gates agree.

    Beat proximity is reported but intentionally excluded from the gate: changing source-in does
    not change the cut's timeline position, and music cannot make a dead source moment usable.
    """
    base = next((item for item in evidence if item.start_frame == original_start), None)
    if base is None or len(evidence) < 2 or base.confidence < 0.45:
        return CutInResult(CutInVerdict.UNKNOWN, original_start, None, 0, 0.0, {},
                           "insufficient_temporal_evidence")
    if intentional_still and base.technical_usability >= 0.45 and base.camera_settle >= 0.35:
        return CutInResult(CutInVerdict.KEEP_ORIGINAL, original_start, None, 0, base.confidence,
                           _components(base), "intentional_still_preserved")

    later = [item for item in evidence if item.start_frame > original_start and item.confidence >= 0.6]
    if not later:
        return CutInResult(CutInVerdict.UNKNOWN, original_start, None, 0, base.confidence,
                           _components(base), "no_reliable_duration_safe_proposal")

    def priority(item: TemporalEvidence) -> tuple[float, int]:
        # Factorized terms remain visible; this ordering only chooses among candidates that pass
        # the explicit gates below. Earlier wins a tie to avoid over-trimming.
        value = (
            0.27 * item.subject_readiness + 0.25 * item.action_onset
            + 0.22 * item.camera_settle + 0.16 * item.technical_usability
            + 0.10 * item.obstruction_clearance
        )
        return value, -item.start_frame

    best = max(later, key=priority)
    subject_gain = best.subject_readiness - base.subject_readiness
    action_gain = best.action_onset - base.action_onset
    settle_gain = best.camera_settle - base.camera_settle
    technical_gain = best.technical_usability - base.technical_usability
    obstruction_gain = best.obstruction_clearance - base.obstruction_clearance
    continuity_ok = best.semantic_continuity >= 0.72
    visual_regression = technical_gain < -0.12 or best.technical_usability < 0.42

    camera_case = settle_gain >= 0.38 and (technical_gain >= 0.10 or obstruction_gain >= 0.18)
    action_case = action_gain >= 0.32 and subject_gain >= 0.18 and settle_gain >= -0.08
    independent_gains = sum((subject_gain >= 0.18, action_gain >= 0.32,
                             settle_gain >= 0.38, technical_gain >= 0.10,
                             obstruction_gain >= 0.18))
    if continuity_ok and not visual_regression and independent_gains >= 2 and (camera_case or action_case):
        confidence = min(1.0, best.confidence * (0.72 + 0.07 * independent_gains))
        reason = "camera_settles" if camera_case and not action_case else (
            "subject_ready_and_action_begins" if action_case and not camera_case
            else "camera_settles_and_action_begins")
        return CutInResult(CutInVerdict.TRIM_PROPOSAL, original_start, best.start_frame,
                           best.start_frame - original_start, round(confidence, 3),
                           _components(best), reason)

    ambiguous_gain = max(subject_gain, action_gain, settle_gain, technical_gain, obstruction_gain)
    if ambiguous_gain >= 0.2 or not continuity_ok:
        return CutInResult(CutInVerdict.REVIEW, original_start, None, 0, best.confidence,
                           _components(best), "signals_ambiguous_or_discontinuous")
    return CutInResult(CutInVerdict.KEEP_ORIGINAL, original_start, None, 0, base.confidence,
                       _components(base), "no_clear_later_visual_advantage")


def _components(item: TemporalEvidence) -> dict[str, float]:
    return {
        "subject_readiness": round(item.subject_readiness, 3),
        "action_onset": round(item.action_onset, 3),
        "camera_settle": round(item.camera_settle, 3),
        "technical_usability": round(item.technical_usability, 3),
        "obstruction_clearance": round(item.obstruction_clearance, 3),
        "semantic_continuity": round(item.semantic_continuity, 3),
        "beat_proximity": round(item.beat_proximity, 3),
    }
