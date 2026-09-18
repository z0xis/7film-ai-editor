"""P6.18 -- shadow drone chronology inference guards (read-only). No DB/timeline/Resolve write."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"
PLANNER = ROOT / "apps/api/sevenfilm/services/planner.py"
TOOL = ROOT / "tools/p6_18_drone_chronology.py"


def _j(name):
    return json.loads((FIX / name).read_text())


def test_camera_holdout_validates_the_estimator():
    h = _j("p6_18_holdout.json")
    # inferring a hidden camera's day_position from other cameras is accurate to a few percent
    assert h["median_err"] < 0.06
    assert h["event_region_accuracy"] >= 0.6


def test_drone_chronology_is_fail_closed_and_tiered():
    d = _j("p6_18_drone_chronology.json")
    tc = d["tier_counts"]
    assert set(tc) <= {"HIGH", "MEDIUM", "LOW", "UNRESOLVED"}
    assert tc.get("HIGH", 0) >= 1          # some high-confidence estimates exist
    # not everything is forced to HIGH -- low-support drone shots stay low/unresolved
    assert tc.get("LOW", 0) + tc.get("UNRESOLVED", 0) >= 1


def test_asset_order_is_monotonic_with_drone_creation_time():
    d = _j("p6_18_drone_chronology.json")
    # inferred asset-median day_position broadly follows the drones' own creation-time order
    assert d["asset_monotonic_fraction"] >= 0.7
    assert d["asset_creation_order"][0].startswith("DJI_0522")


def test_injection_does_not_regress_reception():
    s = _j("p6_18_shadow_summary.json")
    for cond in ("HIGH", "HIGH+MEDIUM"):
        assert s[cond]["song2_items"] >= 40          # reception preserved (baseline 60)
        assert s[cond]["duration_s"] > 140
        assert s[cond]["deterministic"] is True


def test_chronology_alone_does_not_fix_first_dance():
    """Decisive: with chronology injected, the camera crowd-dance still wins first_dance -- the
    reuse/redundancy penalty (P6.17) is the remaining blocker, not chronology."""
    s = _j("p6_18_shadow_summary.json")
    assert s["baseline"]["first_dance_selected"] == s["HIGH"]["first_dance_selected"]
    assert "C7388.MP4" in s["HIGH"]["first_dance_selected"]


def test_injection_is_shadow_only_no_writes():
    s = _j("p6_18_shadow_summary.json")
    for cond in s:
        assert s[cond]["safety_no_write"] is True
    # the tool must not write the DB and must not read V7 / is-edit timelines as inference labels
    src = TOOL.read_text()
    assert "INSERT" not in src and "UPDATE " not in src and "replace_rows" not in src
    assert "GetTimeline" not in src and "timeline_items" not in src


def test_planner_unchanged():
    # P6.18 ships no scoring change; the P6.17 reuse relief must stay reverted.
    assert "MOMENT_ASSET_REUSE_RELIEF" not in PLANNER.read_text()
