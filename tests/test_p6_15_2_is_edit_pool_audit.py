"""P6.15.2 -- is-edit candidate-pool audit guards (read-only). No Resolve/DB/timeline writes."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures/p6_15_2_is_edit_pool_audit.json"


def _a():
    return json.loads(FIX.read_text())


def test_is_edit_is_a_curated_selects_pool():
    ie = _a()["is_edit"]
    assert ie["items"] == 187
    assert ie["unique_sources"] == 140
    assert ie["already_curated"] is True


def test_v7_draws_entirely_from_is_edit_and_refines_moments():
    m = _a()["v7_mapping"]
    assert m["v7_source_not_in_is_edit"] == 0          # V7 uses only is-edit material
    assert m["same_source_different_moment"] >= 30     # moment refinement on tightening
    assert m["late_reception_selects_left_out"] >= 20  # rich unused reception pool


def test_source_moment_grammar_prefers_action_over_setup():
    g = _a()["source_moment_grammar"]["cake_C7309"]
    assert "setup" in g["is_edit_early_src110"]
    assert "action" in g["v7_src3332"] or "CUT" in g["v7_src3332"]
    assert "action" in g["rule"]


def test_first_dance_built_from_forward_reuse_not_dji0529():
    fd = _a()["first_dance"]
    assert fd["DJI_0529_in_v7"] is False
    assert "forward" in fd["selection_logic"]


def test_same_source_reuse_is_event_phase_selection():
    r = _a()["same_source_reuse"]
    assert "FORWARD_SEQUENCE" in r["classification"] or "EVENT_PHASE" in r["classification"]


def test_false_early_stop_strongly_supported():
    fs = _a()["false_early_stop"]
    assert fs["good_unused_late_story_candidates"] == "YES"
    assert len(fs["examples"]) >= 4


def test_quality_is_filter_not_ranker():
    v = _a()["visual_filter_vs_ranking"]
    assert "FILTER" in v["conclusion"]
    assert "action phase" in v["ranking"]


def test_updated_p6_16_requirements_recorded():
    reqs = _a()["updated_p6_16_requirements"]
    assert len(reqs) >= 6
    assert any("high-value" in r.lower() or "HIGH-VALUE" in r for r in reqs)


def test_no_writes_and_no_frames_committed():
    s = _a()["safety"]
    assert s["resolve_writes"] == 0 and s["db_writes"] == 0
    assert s["timeline_changes"] == 0 and s["frames_committed"] is False
