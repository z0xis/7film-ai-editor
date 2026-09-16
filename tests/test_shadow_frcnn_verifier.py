import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shadow_frcnn_policy import run_d4_frcnn, score
from shadow_frcnn_verifier import CONFIDENCE_THRESHOLDS, DOMINANT_RATIOS, summarize


def test_thresholds_and_ratios_match_p5_8_frozen_grid():
    """P5.9 must reuse the exact P5.8 pre-registered grid -- no new T43 etc."""
    assert CONFIDENCE_THRESHOLDS == [0.20, 0.35, 0.50, 0.70]
    assert DOMINANT_RATIOS == [0.25, 0.40, 0.60]


def test_summarize_takes_only_raw_detection_no_ground_truth():
    sig = inspect.signature(summarize)
    assert list(sig.parameters) == ["detection"]


def _summary(total, dominant25, dominant40=None, dominant60=None):
    return {"total_person_count": total, "cake_count": 0,
            "largest_person_area_ratio_to_frame": 0.1, "second_largest_person_area_ratio_to_frame": 0.05,
            "largest_to_second_box_ratio": 2.0,
            "dominant_ratio_0.25": dominant25,
            "dominant_ratio_0.4": dominant40 if dominant40 is not None else dominant25,
            "dominant_ratio_0.6": dominant60 if dominant60 is not None else dominant25}


def test_d4_frcnn_requires_p55_case_to_exist():
    """A case never evaluated by P5.5's atomic verifier cannot trigger D4-FRCNN abstention,
    no matter what FRCNN says -- agreement requires both signals."""
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "unseen_by_p55",
                "threshold_summary": {"0.35": _summary(1, 1)}}]
    rows = run_d4_frcnn(results, "0.35", "dominant_ratio_0.25")
    assert rows[0][1] == "ACCEPT"


def test_d4_frcnn_abstains_only_on_dual_agreement():
    results = [{"event": "first_dance", "human_verdict": "FP", "case_id": "HARMFUL_solo_performer_C7349",
                "threshold_summary": {"0.7": _summary(3, 1)}}]  # dominant=1 -> CONTRADICTED
    rows = run_d4_frcnn(results, "0.7", "dominant_ratio_0.6")
    assert rows[0][1] == "ABSTAIN"


def test_d4_frcnn_deterministic():
    results = [{"event": "first_dance", "human_verdict": "TP", "case_id": "genuine_first_dance_C7261",
                "threshold_summary": {"0.35": _summary(7, 1)}}]
    r1 = run_d4_frcnn(results, "0.35", "dominant_ratio_0.25")
    r2 = run_d4_frcnn(results, "0.35", "dominant_ratio_0.25")
    assert r1 == r2


def test_unsupported_events_excluded_from_d4_frcnn():
    results = [{"event": "ceremony_action", "human_verdict": "FP", "case_id": "x",
                "threshold_summary": {"0.35": _summary(4, 2)}}]
    rows = run_d4_frcnn(results, "0.35", "dominant_ratio_0.25")
    assert rows == []


def test_zero_detections_never_produces_frcnn_hard_veto_alone():
    """FRCNN detecting 0 persons (e.g. tiny/distant subjects) must not itself force ABSTAIN --
    D4 requires P5.5 agreement too, and UNKNOWN from FRCNN is not CONTRADICTED."""
    from shadow_frcnn_policy import evidence_status
    assert evidence_status(_summary(0, 0), "dominant_ratio_0.25") == "UNKNOWN"


def test_score_computes_precision_and_coverage():
    rows = [("a", "ACCEPT", "TP"), ("b", "ACCEPT", "FP"), ("c", "ABSTAIN", "TP")]
    s = score(rows)
    assert s["precision"] == 0.5
    assert s["coverage"] == 0.5
