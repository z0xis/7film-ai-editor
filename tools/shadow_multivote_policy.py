"""P5.6: pre-registered normalization schema and M1-M4 decision rules. Frozen BEFORE any V2-V4
result was inspected in this package -- thresholds are not adjusted after seeing outcomes.

Normalized claim schema per prompt output:
  person_count: 0 | 1 | 2 | "3+" | "UNKNOWN"
  paired_interaction: True | False | "UNKNOWN"
  dance_action: True | False | "UNKNOWN"
  solo_dominant: True | False | "UNKNOWN"
  cake_visible: True | False | "UNKNOWN"
  cutting_action: True | False | "UNKNOWN"
  strong_contradiction: True | False  (see CONTRADICTION_PAIRS)
  internally_inconsistent: True | False

An internally-inconsistent output's vote is INVALID (counted as UNKNOWN for every field, and
excluded from support/contradiction tallies) -- pre-registered per package section 9, not
decided after seeing the data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Trinary = bool | Literal["UNKNOWN"]


@dataclass(frozen=True)
class NormalizedClaim:
    person_count: int | str  # int, or "3+", or "UNKNOWN"
    paired_interaction: Trinary
    dance_action: Trinary
    solo_dominant: Trinary
    cake_visible: Trinary
    cutting_action: Trinary
    internally_inconsistent: bool
    prompt_version: str


def _b(v) -> Trinary:
    return v if isinstance(v, bool) else "UNKNOWN"


def normalize_v1(parsed: dict | None) -> NormalizedClaim:
    if not parsed:
        return NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", False, "v1_atomic_checklist")
    pc = parsed.get("primary_person_count")
    person_count = pc if isinstance(pc, int) else "UNKNOWN"
    return _check_consistency(NormalizedClaim(
        person_count=person_count,
        paired_interaction=_b(parsed.get("two_people_interacting")),
        dance_action=_b(parsed.get("dance_like_movement_visible")),
        solo_dominant=_b(parsed.get("solo_performer_pattern")),
        cake_visible=_b(parsed.get("cake_visible")),
        cutting_action=_b(parsed.get("cake_cutting_action_visible")),
        internally_inconsistent=False,
        prompt_version="v1_atomic_checklist",
    ))


def normalize_v2(parsed: dict | None) -> NormalizedClaim:
    if not parsed:
        return NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", False, "v2_describe_then_structure")
    pc = parsed.get("number_of_people_clearly_in_focus")
    person_count = pc if isinstance(pc, int) else "UNKNOWN"
    return _check_consistency(NormalizedClaim(
        person_count=person_count,
        paired_interaction=_b(parsed.get("are_two_of_them_moving_or_interacting_as_a_pair")),
        dance_action=_b(parsed.get("does_the_scene_show_dance_like_motion")),
        solo_dominant="UNKNOWN",  # V2 does not ask this directly
        cake_visible=_b(parsed.get("is_a_cake_present")),
        cutting_action=_b(parsed.get("is_someone_actively_cutting_the_cake")),
        internally_inconsistent=False,
        prompt_version="v2_describe_then_structure",
    ))


def normalize_v3(parsed: dict | None) -> NormalizedClaim:
    if not parsed:
        return NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", False, "v3_contradiction_first")
    pc = parsed.get("primary_subject_count_estimate")
    person_count = pc if isinstance(pc, int) else "UNKNOWN"
    only_one = parsed.get("is_only_one_person_clearly_the_dominant_focus")
    no_second = parsed.get("is_there_clearly_no_second_person_interacting_with_the_main_subject")
    # V3 asks contradiction-shaped questions; paired_interaction is the logical negation of "no second person"
    paired = (not no_second) if isinstance(no_second, bool) else "UNKNOWN"
    solo = only_one if isinstance(only_one, bool) else "UNKNOWN"
    cake_only_visible = parsed.get("is_the_cake_merely_visible_in_frame_without_anyone_cutting_it")
    cutting = (not cake_only_visible) if isinstance(cake_only_visible, bool) else "UNKNOWN"
    return _check_consistency(NormalizedClaim(
        person_count=person_count,
        paired_interaction=paired,
        dance_action=_b(parsed.get("is_movement_or_posture_dance_like")),
        solo_dominant=solo,
        cake_visible="UNKNOWN",  # V3 only asks about cutting-vs-visible-only, not presence alone
        cutting_action=cutting,
        internally_inconsistent=False,
        prompt_version="v3_contradiction_first",
    ))


def normalize_v4(parsed: dict | None) -> NormalizedClaim:
    if not parsed:
        return NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", False, "v4_relationship_geometry")
    pc = parsed.get("how_many_dominant_people_are_in_the_frame")
    person_count = pc if isinstance(pc, int) else "UNKNOWN"
    cake_field = parsed.get("is_there_a_cake_and_is_a_cutting_motion_visible_toward_it")
    cake_visible: Trinary = "UNKNOWN"
    cutting: Trinary = "UNKNOWN"
    if cake_field == "no_cake":
        cake_visible, cutting = False, False
    elif cake_field == "cake_visible_no_cutting":
        cake_visible, cutting = True, False
    elif cake_field == "cutting_visible":
        cake_visible, cutting = True, True
    return _check_consistency(NormalizedClaim(
        person_count=person_count,
        paired_interaction=_b(parsed.get("are_two_dominant_people_spatially_close_and_facing_or_holding_each_other")),
        dance_action=_b(parsed.get("does_their_movement_appear_coordinated_with_each_other")),
        solo_dominant="UNKNOWN",  # V4 does not ask this directly
        cake_visible=cake_visible,
        cutting_action=cutting,
        internally_inconsistent=False,
        prompt_version="v4_relationship_geometry",
    ))


# Pre-registered internal-consistency rules (package section 9) -- checked, not tuned, after the fact.
def _check_consistency(claim: NormalizedClaim) -> NormalizedClaim:
    inconsistent = False
    if isinstance(claim.person_count, int) and claim.person_count <= 1 and claim.paired_interaction is True:
        inconsistent = True
    if claim.solo_dominant is True and claim.paired_interaction is True:
        inconsistent = True
    if claim.cake_visible is False and claim.cutting_action is True:
        inconsistent = True
    if inconsistent:
        return NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", True, claim.prompt_version)
    return claim


NORMALIZERS = {
    "v1_atomic_checklist": normalize_v1,
    "v2_describe_then_structure": normalize_v2,
    "v3_contradiction_first": normalize_v3,
    "v4_relationship_geometry": normalize_v4,
}


# ---- Pre-registered decision rules M1-M4 (event-agnostic: "does the claim set support the
# required evidence for the candidate event"). Applied only when the classifier's own event is
# already in the supported allowlist (first_dance, cake_cutting) -- unsupported events remain
# ABSTAIN regardless, unchanged from P5.3/P5.5.

def _valid_votes(claims: list[NormalizedClaim]) -> list[NormalizedClaim]:
    return [c for c in claims if not c.internally_inconsistent]


def _first_dance_support(c: NormalizedClaim) -> bool:
    return c.paired_interaction is True and c.dance_action is True


def _first_dance_contradiction(c: NormalizedClaim) -> bool:
    return c.solo_dominant is True or (isinstance(c.person_count, int) and c.person_count <= 1)


def _cake_support(c: NormalizedClaim) -> bool:
    return c.cake_visible is True and c.cutting_action is True


def _cake_contradiction(c: NormalizedClaim) -> bool:
    return c.cake_visible is True and c.cutting_action is False


def _vote_tallies(claims: list[NormalizedClaim], event: str) -> dict:
    valid = _valid_votes(claims)
    if event == "first_dance":
        support_fn, contra_fn = _first_dance_support, _first_dance_contradiction
    elif event == "cake_cutting":
        support_fn, contra_fn = _cake_support, _cake_contradiction
    else:
        return {"valid": 0, "support": 0, "contradiction": 0, "unknown": len(claims)}
    support = sum(1 for c in valid if support_fn(c))
    contradiction = sum(1 for c in valid if contra_fn(c))
    return {"valid": len(valid), "support": support, "contradiction": contradiction,
            "unknown": len(valid) - support - contradiction, "total_votes": len(claims)}


def decide_m1_unanimous(claims: list[NormalizedClaim], event: str) -> str:
    t = _vote_tallies(claims, event)
    if t["valid"] == 0:
        return "ABSTAIN_UNKNOWN"
    if t["contradiction"] > 0:
        return "ABSTAIN_CONTRADICTION"
    if t["support"] == t["valid"]:
        return "ACCEPT"
    return "ABSTAIN_UNKNOWN"


def decide_m2_simple_majority(claims: list[NormalizedClaim], event: str) -> str:
    t = _vote_tallies(claims, event)
    if t["valid"] == 0:
        return "ABSTAIN_UNKNOWN"
    if t["contradiction"] > t["valid"] / 2:
        return "ABSTAIN_CONTRADICTION"
    if t["support"] > t["valid"] / 2:
        return "ACCEPT"
    return "ABSTAIN_UNKNOWN"


def decide_m3_supermajority(claims: list[NormalizedClaim], event: str) -> str:
    t = _vote_tallies(claims, event)
    if t["valid"] == 0:
        return "ABSTAIN_UNKNOWN"
    if t["contradiction"] / t["valid"] > 0.25:
        return "ABSTAIN_CONTRADICTION"
    if t["support"] / t["valid"] >= 0.75:
        return "ACCEPT"
    return "ABSTAIN_UNKNOWN"


def decide_m4_contradiction_veto(claims: list[NormalizedClaim], event: str) -> str:
    t = _vote_tallies(claims, event)
    if t["contradiction"] > 0:
        return "ABSTAIN_CONTRADICTION"
    if t["valid"] == 0:
        return "ABSTAIN_UNKNOWN"
    if t["support"] > 0:
        return "ACCEPT"
    return "ABSTAIN_UNKNOWN"


POLICIES = {
    "M1_unanimous": decide_m1_unanimous,
    "M2_simple_majority": decide_m2_simple_majority,
    "M3_supermajority": decide_m3_supermajority,
    "M4_contradiction_veto": decide_m4_contradiction_veto,
}
