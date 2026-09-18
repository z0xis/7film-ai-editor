"""P6.17 -- source-moment / event-sequence grammar diagnosis guards (read-only).

A bounded fix was attempted and rejected by the hard gates (no planner code shipped). These lock the
diagnosis and assert the planner was NOT changed.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "tools/fixtures/p6_17_sequence_diagnosis.json"
PLANNER = ROOT / "apps/api/sevenfilm/services/planner.py"


def _d():
    return json.loads(DIAG.read_text())


def test_no_planner_code_was_shipped():
    d = _d()
    assert d["attempted_fix"]["shipped"] is False
    assert d["safety"]["planner_changed"] is False
    # The rejected relief constant must not be present in the planner.
    assert "MOMENT_ASSET_REUSE_RELIEF" not in PLANNER.read_text()


def test_first_dance_members_split_camera_timecoded_vs_drone_timecodeless():
    m = _d()["first_dance_members"]
    assert m["C7388.MP4"]["timecode"] is True
    assert m["DJI_0528.MOV"]["timecode"] is False
    assert m["DJI_0528.MOV"]["day_position"] is None


def test_isolated_drone_loses_via_asset_reuse_not_content():
    e = _d()["score_component_evidence"]["isolated_first_dance_drone_DJI_0528_df3a49bf"]
    assert e["story_relevance"] >= 0.9          # content is strong
    assert e["reuse_penalty"] > 0.2             # but suppressed by asset reuse


def test_full_waiver_rejected_for_reception_regression():
    f = _d()["attempted_fix"]["full_waiver"]
    assert "COLLAPSED" in f["reception"]
    assert "REJECTED" in f["verdict"]


def test_half_waiver_rejected_for_chronology_misplacement():
    h = _d()["attempted_fix"]["half_waiver"]
    assert "misplaced" in h["problem"]
    assert "REJECTED" in h["verdict"]


def test_chronology_is_identified_as_primary_blocker():
    d = _d()
    assert "CHRONOLOGY" in d["primary_failure_class"]
    assert d["grammar_gap_after_p6_17"]["chronology"].startswith("OPEN")
    assert d["grammar_gap_after_p6_17"]["false_early_stop"].startswith("SOLVED")


def test_p6_16_reception_baseline_recorded():
    b = _d()["p6_16_baseline"]
    assert b["song2_items"] >= 30
    assert b["duration_s"] > 140
