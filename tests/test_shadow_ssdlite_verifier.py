import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_ssdlite_analysis import evidence_status
from shadow_ssdlite_policy import run_policies, score
from shadow_ssdlite_verifier import CONFIDENCE_THRESHOLDS, DOMINANT_RATIOS, summarize


def _summary(total, dominant25, dominant40=None, dominant60=None):
    return {"total_person_count": total, "cake_count": 0,
            "largest_person_area_ratio_to_frame": 0.1, "second_largest_person_area_ratio_to_frame": 0.05,
            "largest_to_second_box_ratio": 2.0,
            "dominant_ratio_0.25": dominant25,
            "dominant_ratio_0.4": dominant40 if dominant40 is not None else dominant25,
            "dominant_ratio_0.6": dominant60 if dominant60 is not None else dominant25}


def test_zero_detections_is_unknown_not_contradiction():
    assert evidence_status(_summary(0, 0), "dominant_ratio_0.25") == "UNKNOWN"


def test_one_dominant_person_is_contradicted():
    assert evidence_status(_summary(3, 1), "dominant_ratio_0.25") == "CONTRADICTED"


def test_two_or_more_dominant_persons_is_supported_only():
    assert evidence_status(_summary(3, 2), "dominant_ratio_0.25") == "SUPPORTED"


def test_thresholds_and_ratios_are_frozen_pre_registered_values():
    assert CONFIDENCE_THRESHOLDS == [0.20, 0.35, 0.50, 0.70]
    assert DOMINANT_RATIOS == [0.25, 0.40, 0.60]


def test_summarize_never_reads_ground_truth():
    """summarize() takes only a raw detection dict (boxes/labels/scores/frame size) -- it
    structurally cannot see a human label or event field."""
    sig = inspect.signature(summarize)
    assert list(sig.parameters) == ["detection"]


def test_evidence_status_is_deterministic():
    s = _summary(2, 2)
    assert evidence_status(s, "dominant_ratio_0.25") == evidence_status(s, "dominant_ratio_0.25")


def test_drone_zero_detection_never_produces_hard_veto():
    """The package's hard rule: absence of detection != absence of person. A drone/tiny-scale
    frame with 0 boxes must never be treated as CONTRADICTED."""
    zero_detection_drone_like = _summary(0, 0)
    assert evidence_status(zero_detection_drone_like, "dominant_ratio_0.25") != "CONTRADICTED"


def test_d0_baseline_always_accepts():
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "x",
                "threshold_summary": {"0.35": _summary(2, 2)}}]
    outcomes = run_policies(results, "0.35", "dominant_ratio_0.25")
    assert outcomes["D0"][0][1] == "ACCEPT"


def test_d1_naive_veto_is_deterministic():
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "x",
                "threshold_summary": {"0.35": _summary(1, 1)}}]
    o1 = run_policies(results, "0.35", "dominant_ratio_0.25")
    o2 = run_policies(results, "0.35", "dominant_ratio_0.25")
    assert o1["D1"] == o2["D1"]


def test_d2_only_vetoes_on_genuine_contradiction_not_unknown():
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "unknown_case",
                "threshold_summary": {"0.35": _summary(0, 0)}}]
    outcomes = run_policies(results, "0.35", "dominant_ratio_0.25")
    assert outcomes["D2"][0][1] == "ACCEPT"  # UNKNOWN must not veto


def test_d4_requires_agreement_from_both_signals():
    """D4 (P5.5 atomic + SSDLite) must only abstain a case whose case_id has a known P5.5
    CONTRADICTED result -- SSDLite alone, on a case P5.5 never evaluated, cannot trigger D4."""
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "never_seen_by_p55",
                "threshold_summary": {"0.35": _summary(1, 1)}}]
    outcomes = run_policies(results, "0.35", "dominant_ratio_0.25")
    assert outcomes["D4"][0][1] == "ACCEPT"


def test_score_never_treats_unsupported_events():
    results = [{"event": "ceremony_action", "human_verdict": "FP", "case_id": "x",
                "threshold_summary": {"0.35": _summary(2, 2)}}]
    outcomes = run_policies(results, "0.35", "dominant_ratio_0.25")
    for policy in outcomes:
        assert outcomes[policy] == []  # unsupported events never reach any D-policy


def test_score_computes_precision_and_coverage():
    rows = [("a", "ACCEPT", "TP"), ("b", "ACCEPT", "FP"), ("c", "ABSTAIN", "TP")]
    s = score(rows)
    assert s["accepted_tp"] == 1
    assert s["accepted_fp"] == 1
    assert s["abstained_tp"] == 1
    assert s["precision"] == 0.5
    assert s["coverage"] == 0.5
