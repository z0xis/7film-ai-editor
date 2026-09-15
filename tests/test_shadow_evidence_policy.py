import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_evidence_policy import (
    CakeCuttingEvidence,
    FirstDanceEvidence,
    cake_evidence_from_atomic,
    decide_v2,
    first_dance_evidence_from_atomic,
    verify_cake_cutting,
    verify_first_dance,
)


def test_solo_performer_contradiction_blocks_accept():
    """Regression for the known P5.4 harmful accept: a solo performer must be CONTRADICTED,
    not SUPPORTED, even if the raw Qwen event label was 'first_dance'."""
    atomic = {"primary_person_count": 1, "two_people_interacting": False,
              "dance_like_movement_visible": True, "solo_performer_pattern": True,
              "cake_visible": False, "cake_cutting_action_visible": False}
    evidence = first_dance_evidence_from_atomic(atomic, parse_failed=False, exception=None, yunet_face_count=None)
    status = verify_first_dance(evidence)
    assert status == "CONTRADICTED"
    assert decide_v2("first_dance", status) == "DEEP_ABSTAIN_CONTRADICTION"


def test_genuine_two_person_dance_is_supported():
    atomic = {"primary_person_count": 2, "two_people_interacting": True,
              "dance_like_movement_visible": True, "solo_performer_pattern": False,
              "cake_visible": False, "cake_cutting_action_visible": False}
    evidence = first_dance_evidence_from_atomic(atomic, parse_failed=False, exception=None, yunet_face_count=None)
    status = verify_first_dance(evidence)
    assert status == "SUPPORTED"
    assert decide_v2("first_dance", status) == "DEEP_ACCEPT_VERIFIED"


def test_unknown_evidence_never_treated_as_supported():
    atomic = {"primary_person_count": None, "two_people_interacting": None,
              "dance_like_movement_visible": None, "solo_performer_pattern": None}
    evidence = first_dance_evidence_from_atomic(atomic, parse_failed=False, exception=None, yunet_face_count=None)
    status = verify_first_dance(evidence)
    assert status == "UNKNOWN"
    assert decide_v2("first_dance", status) != "DEEP_ACCEPT_VERIFIED"


def test_parse_failure_is_failed_not_supported():
    evidence = first_dance_evidence_from_atomic(None, parse_failed=True, exception=None, yunet_face_count=None)
    assert verify_first_dance(evidence) == "FAILED"
    assert decide_v2("first_dance", "FAILED") == "DEEP_ABSTAIN_FAILED"


def test_exception_is_failed():
    evidence = first_dance_evidence_from_atomic(None, parse_failed=False, exception="TimeoutError: x", yunet_face_count=None)
    assert verify_first_dance(evidence) == "FAILED"


def test_face_count_alone_never_hard_vetoes_a_two_person_claim():
    """Drone/back-turned couples routinely read as 0 faces -- E3 must never override a positive
    two-person claim by itself."""
    atomic = {"primary_person_count": 2, "two_people_interacting": True,
              "dance_like_movement_visible": True, "solo_performer_pattern": False}
    evidence = first_dance_evidence_from_atomic(atomic, parse_failed=False, exception=None, yunet_face_count=0)
    status = verify_first_dance(evidence)
    assert status == "SUPPORTED", "yunet face_count=0 must not veto a genuine two-person dance claim"


def test_cake_posing_only_is_contradicted():
    atomic = {"cake_visible": True, "cake_cutting_action_visible": False}
    evidence = cake_evidence_from_atomic(atomic, parse_failed=False, exception=None)
    status = verify_cake_cutting(evidence)
    assert status == "CONTRADICTED"


def test_cake_genuine_cutting_supported():
    atomic = {"cake_visible": True, "cake_cutting_action_visible": True}
    evidence = cake_evidence_from_atomic(atomic, parse_failed=False, exception=None)
    assert verify_cake_cutting(evidence) == "SUPPORTED"


def test_unsupported_event_never_reaches_verification():
    """ceremony_action stays abstain regardless of verification result -- P5.5 does not add it
    to the allowlist."""
    assert decide_v2("ceremony_action", "SUPPORTED") == "DEEP_ABSTAIN_UNKNOWN"
    assert decide_v2("entrance", "SUPPORTED") == "DEEP_ABSTAIN_UNKNOWN"


def test_evidence_dataclasses_allow_unknown_not_forced_boolean():
    ev = FirstDanceEvidence(None, None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "parse_failed")
    assert ev.two_person_support is None
    ev2 = CakeCuttingEvidence(None, None, None, None, None, "e1_same_qwen_atomic", "low_medium", "parse_failed")
    assert ev2.cake_visible is None


def test_verification_is_deterministic():
    atomic = {"primary_person_count": 2, "two_people_interacting": True,
              "dance_like_movement_visible": True, "solo_performer_pattern": False}
    e1 = first_dance_evidence_from_atomic(atomic, False, None, None)
    e2 = first_dance_evidence_from_atomic(atomic, False, None, None)
    assert verify_first_dance(e1) == verify_first_dance(e2)
