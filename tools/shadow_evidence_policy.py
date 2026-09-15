"""P5.5 shadow-only Accept Policy V2: gates a supported-event Qwen classification behind an
atomic evidence check (E1, same-model, correlated) and an optional lightweight contradiction
signal (E3, existing YuNet face detector). Never wired into production.

Independence classes (see docs/p5_5_evidence_consistency.md):
  LOW           -- same Qwen call family, same prompt family (not used as a source here)
  LOW-MEDIUM    -- same Qwen model, but an atomic non-event prompt (E1)
  MEDIUM        -- different, already-shipped lightweight detector (E3, YuNet)
  HIGHER        -- a genuinely independent visual model/task (E4 -- UNAVAILABLE this package,
                   no additional model was downloaded; see report)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerificationStatus = Literal["SUPPORTED", "CONTRADICTED", "UNKNOWN", "FAILED"]
FinalDecision = Literal["DEEP_ACCEPT_VERIFIED", "DEEP_ABSTAIN_CONTRADICTION", "DEEP_ABSTAIN_UNKNOWN", "DEEP_ABSTAIN_FAILED", "FAST_ONLY"]

QWEN_SUPPORTED_EVENTS = {"cake_cutting", "first_dance"}


@dataclass(frozen=True)
class FirstDanceEvidence:
    primary_person_count: int | None  # None = UNKNOWN, not False
    two_person_support: bool | None
    couple_interaction_support: bool | None
    dance_action_support: bool | None
    solo_performer_contradiction: bool | None
    crowd_only_contradiction: bool | None
    evidence_source: str  # "e1_same_qwen_atomic" | "e3_yunet_facecount" | "e1+e3"
    evidence_quality: Literal["low", "low_medium", "medium", "higher"]
    parse_status: Literal["ok", "parse_failed", "exception"]


@dataclass(frozen=True)
class CakeCuttingEvidence:
    cake_visible: bool | None
    hand_cake_interaction: bool | None
    cutting_action_support: bool | None
    posing_only_contradiction: bool | None
    cake_detail_only_contradiction: bool | None
    evidence_source: str
    evidence_quality: Literal["low", "low_medium", "medium", "higher"]
    parse_status: Literal["ok", "parse_failed", "exception"]


def first_dance_evidence_from_atomic(atomic: dict | None, parse_failed: bool, exception: str | None,
                                      yunet_face_count: int | None) -> FirstDanceEvidence:
    if exception:
        return FirstDanceEvidence(None, None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "exception")
    if parse_failed or atomic is None:
        return FirstDanceEvidence(None, None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "parse_failed")

    two_person = atomic.get("two_people_interacting")
    solo = atomic.get("solo_performer_pattern")
    dance = atomic.get("dance_like_movement_visible")
    count = atomic.get("primary_person_count")

    crowd_only = None
    if isinstance(count, int):
        crowd_only = count > 2 and not two_person

    source = "e1_same_qwen_atomic"
    quality: Literal["low", "low_medium", "medium", "higher"] = "low_medium"
    if yunet_face_count is not None:
        source = "e1+e3"
        # E3 is a CONTRADICTION-only signal: 0 faces never overrides a two-person claim (profile,
        # back-turned, or drone-altitude framing routinely reads as 0 faces for genuine couples).
        # It can only ADD a contradiction signal when it independently also suggests <2 subjects
        # AND the atomic call already suggested ambiguity (not used to hard-veto by itself).

    return FirstDanceEvidence(
        primary_person_count=count if isinstance(count, int) else None,
        two_person_support=two_person if isinstance(two_person, bool) else None,
        couple_interaction_support=two_person if isinstance(two_person, bool) else None,
        dance_action_support=dance if isinstance(dance, bool) else None,
        solo_performer_contradiction=solo if isinstance(solo, bool) else None,
        crowd_only_contradiction=crowd_only,
        evidence_source=source,
        evidence_quality=quality,
        parse_status="ok",
    )


def cake_evidence_from_atomic(atomic: dict | None, parse_failed: bool, exception: str | None) -> CakeCuttingEvidence:
    if exception:
        return CakeCuttingEvidence(None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "exception")
    if parse_failed or atomic is None:
        return CakeCuttingEvidence(None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "parse_failed")

    cake_visible = atomic.get("cake_visible")
    cutting = atomic.get("cake_cutting_action_visible")
    posing_only = (cake_visible is True) and (cutting is False)

    return CakeCuttingEvidence(
        cake_visible=cake_visible if isinstance(cake_visible, bool) else None,
        hand_cake_interaction=cutting if isinstance(cutting, bool) else None,
        cutting_action_support=cutting if isinstance(cutting, bool) else None,
        posing_only_contradiction=posing_only if isinstance(cake_visible, bool) and isinstance(cutting, bool) else None,
        cake_detail_only_contradiction=None,
        evidence_source="e1_same_qwen_atomic",
        evidence_quality="low_medium",
        parse_status="ok",
    )


def verify_first_dance(evidence: FirstDanceEvidence) -> VerificationStatus:
    if evidence.parse_status != "ok":
        return "FAILED"
    if evidence.solo_performer_contradiction is True:
        return "CONTRADICTED"
    if evidence.crowd_only_contradiction is True:
        return "CONTRADICTED"
    if evidence.two_person_support is True and evidence.dance_action_support is True:
        return "SUPPORTED"
    if evidence.two_person_support is None or evidence.dance_action_support is None:
        return "UNKNOWN"
    return "UNKNOWN"


def verify_cake_cutting(evidence: CakeCuttingEvidence) -> VerificationStatus:
    if evidence.parse_status != "ok":
        return "FAILED"
    if evidence.posing_only_contradiction is True:
        return "CONTRADICTED"
    if evidence.cutting_action_support is True and evidence.cake_visible is True:
        return "SUPPORTED"
    if evidence.cutting_action_support is None or evidence.cake_visible is None:
        return "UNKNOWN"
    return "UNKNOWN"


def decide_v2(qwen_event: str, verification_status: VerificationStatus) -> FinalDecision:
    if qwen_event not in QWEN_SUPPORTED_EVENTS:
        return "DEEP_ABSTAIN_UNKNOWN"  # unsupported events are already handled by P5.3's allowlist
    if verification_status == "SUPPORTED":
        return "DEEP_ACCEPT_VERIFIED"
    if verification_status == "CONTRADICTED":
        return "DEEP_ABSTAIN_CONTRADICTION"
    if verification_status == "FAILED":
        return "DEEP_ABSTAIN_FAILED"
    return "DEEP_ABSTAIN_UNKNOWN"
