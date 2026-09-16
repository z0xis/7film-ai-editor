import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_multivote_policy import (
    NormalizedClaim,
    decide_m1_unanimous,
    decide_m2_simple_majority,
    decide_m3_supermajority,
    decide_m4_contradiction_veto,
    normalize_v1,
    normalize_v2,
    normalize_v3,
    normalize_v4,
)
from shadow_prompt_family import PROMPTS, prompt_hash


def test_prompt_family_is_frozen_and_hashed():
    assert len(PROMPTS) == 4
    for version in PROMPTS:
        h = prompt_hash(version)
        assert len(h) == 12


def test_no_event_label_leakage_in_any_prompt():
    """Field names describing a physical action (e.g. 'cutting the cake') are legitimate atomic
    evidence, not event-label leakage -- the actual concern is asking the model to judge the
    EVENT itself ('is this a first dance / a cake-cutting event')."""
    forbidden = ["first dance", "first_dance", "is this a first dance", "is this a cake cutting",
                 "cake-cutting event", "cake_cutting event"]
    for text in PROMPTS.values():
        lowered = text.lower()
        for term in forbidden:
            assert term not in lowered, f"prompt leaks event judgment: {term!r}"


def test_no_role_identity_request_in_any_prompt():
    forbidden = ["who is the bride", "who is the groom", "identify the bride", "identify the groom"]
    for text in PROMPTS.values():
        lowered = text.lower()
        for term in forbidden:
            assert term not in lowered


def test_decision_functions_take_no_ground_truth_parameter():
    for fn in (decide_m1_unanimous, decide_m2_simple_majority, decide_m3_supermajority, decide_m4_contradiction_veto):
        sig = inspect.signature(fn)
        assert set(sig.parameters) == {"claims", "event"}


def test_normalizers_take_only_parsed_json():
    for fn in (normalize_v1, normalize_v2, normalize_v3, normalize_v4):
        sig = inspect.signature(fn)
        assert list(sig.parameters) == ["parsed"]


def test_unknown_is_not_false():
    c = normalize_v1(None)
    assert c.paired_interaction == "UNKNOWN"
    assert c.paired_interaction is not False


def test_internal_inconsistency_detected_solo_and_paired():
    parsed = {"primary_person_count": 2, "two_people_interacting": True,
              "dance_like_movement_visible": True, "solo_performer_pattern": True}
    c = normalize_v1(parsed)
    assert c.internally_inconsistent is True


def test_internal_inconsistency_detected_person_count_one_and_paired():
    parsed = {"primary_person_count": 1, "two_people_interacting": True,
              "dance_like_movement_visible": True, "solo_performer_pattern": False}
    c = normalize_v1(parsed)
    assert c.internally_inconsistent is True


def test_internal_inconsistency_detected_cake_absent_but_cutting():
    # V3 doesn't set cake_visible directly (UNKNOWN), so this check exercises v1's mapping instead
    c1 = normalize_v1({"primary_person_count": 2, "two_people_interacting": True,
                        "dance_like_movement_visible": False, "solo_performer_pattern": False,
                        "cake_visible": False, "cake_cutting_action_visible": True})
    assert c1.internally_inconsistent is True


def test_inconsistent_claim_excluded_from_valid_votes():
    inconsistent = NormalizedClaim(2, True, True, True, "UNKNOWN", "UNKNOWN", True, "v1_atomic_checklist")
    valid = NormalizedClaim(2, True, True, False, "UNKNOWN", "UNKNOWN", False, "v2_describe_then_structure")
    decision = decide_m2_simple_majority([inconsistent, valid], "first_dance")
    assert decision == "ACCEPT"  # only the valid vote counts, and it supports


def test_m1_unanimous_requires_all_valid_votes_to_support():
    support = NormalizedClaim(2, True, True, False, False, False, False, "v1")
    unknown = NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", False, "v2")
    assert decide_m1_unanimous([support, support], "first_dance") == "ACCEPT"
    assert decide_m1_unanimous([support, unknown], "first_dance") != "ACCEPT"


def test_m4_any_contradiction_vetoes():
    support = NormalizedClaim(2, True, True, False, False, False, False, "v1")
    contradiction = NormalizedClaim(1, False, True, True, False, False, False, "v2")
    decision = decide_m4_contradiction_veto([support, support, support, contradiction], "first_dance")
    assert decision == "ABSTAIN_CONTRADICTION"


def test_decisions_are_deterministic():
    support = NormalizedClaim(2, True, True, False, False, False, False, "v1")
    for fn in (decide_m1_unanimous, decide_m2_simple_majority, decide_m3_supermajority, decide_m4_contradiction_veto):
        r1 = fn([support, support, support, support], "first_dance")
        r2 = fn([support, support, support, support], "first_dance")
        assert r1 == r2


def test_cake_support_and_contradiction_are_distinguished():
    from shadow_multivote_policy import _cake_contradiction, _cake_support
    visible_cutting = NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", True, True, False, "v1")
    visible_only = NormalizedClaim("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", True, False, False, "v1")
    assert _cake_support(visible_cutting) is True
    assert _cake_contradiction(visible_only) is True
    assert _cake_support(visible_only) is False


def test_unsupported_event_never_votes_accept():
    support = NormalizedClaim(2, True, True, False, False, False, False, "v1")
    for fn in (decide_m1_unanimous, decide_m2_simple_majority, decide_m3_supermajority, decide_m4_contradiction_veto):
        assert fn([support, support, support, support], "ceremony_action") != "ACCEPT"
        assert fn([support, support, support, support], "entrance") != "ACCEPT"
