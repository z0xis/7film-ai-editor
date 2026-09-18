"""P6.14 -- Shadow planner / story-coverage validation guards (read-only).

Lock the observed conclusions of tools/p6_14_shadow_planner.py, which ran the real production
`build_timeline` in memory over the remediated state with NO persistence. These are diagnostic
guards (the shadow plan is not a product), plus a no-write guard on the harness.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures/p6_14_shadow_plan.json"
TOOL = ROOT / "tools/p6_14_shadow_planner.py"


def _r():
    return json.loads(FIX.read_text())


def test_harness_is_write_guarded_and_never_persists():
    src = TOOL.read_text()
    ast.parse(src)
    assert "_harden" in src
    assert "REFUSED: shadow planner attempted a production write" in src
    # It must never call the persistence function.
    assert "persist_timeline(" not in src


def test_production_unchanged_by_shadow_run():
    s = _r()["safety"]
    assert s["checksum_before"] == s["checksum_after"]
    assert s["mtime_before"] == s["mtime_after"]
    assert s["pre_manifest"]["timeline_items"] == 129
    assert s["post_manifest"] == s["pre_manifest"]


def test_plan_is_deterministic():
    assert _r()["plan"]["deterministic"] is True


def test_cake_and_ring_reach_scoring_and_are_selected():
    m = _r()["moment_coverage"]
    # Positive controls: cake (C7309) and ring flow through to selection.
    assert m["cake"]["scored"] == m["cake"]["members"]
    assert m["cake"]["selected"] >= 1
    assert "C7309.MP4" in m["cake"]["selected_sources"]
    assert m["ring"]["selected"] >= 1


def test_first_dance_scored_but_not_selected():
    """Hard case: first_dance members reach scoring but none are selected -- other cuts win and
    the plan never reaches the reception/night story."""
    fd = _r()["moment_coverage"]["first_dance"]
    assert fd["scored"] >= 1
    assert fd["selected"] == 0


def test_kiss_never_reaches_scoring():
    """Kiss members are usable but never scored -- the plan truncates before their story."""
    k = _r()["moment_coverage"]["kiss"]
    assert k["usable"] >= 1
    assert k["scored"] == 0


def test_plan_undershoots_target_and_leaves_second_song_empty():
    p = _r()["plan"]
    assert p["target_s"] == 180.0
    assert p["duration_s"] < 130  # observed ~96s
    # No items land in the second music segment (>=108s).
    assert all(x["tl_start_s"] < 108 for x in _r()["all_items"])


def test_drone_coverage_now_present_vs_old_zero():
    r = _r()
    assert r["drones"]["distinct_drone_assets_selected"] >= 5
    assert r["old_129"]["drone"] == 0  # the degraded 129-item cut had no drone coverage


def test_new_plan_has_richer_categories_than_old_129():
    r = _r()
    assert len(r["plan"]["category_counts"]) >= 8
    assert len(r["old_129"]["categories"]) <= 5
