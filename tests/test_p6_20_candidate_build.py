"""P6.20 -- controlled candidate rough cut V2 build guards (read-only).

The current production planner (HEAD after P6.19) was exported through the production exporter and
imported into Resolve as ONE new isolated timeline "AI CUT V2 - P6.20 CANDIDATE". These lock the plan
identity, the Resolve build faithfulness, and the protected-timeline / DB safety recorded at build.
No DB/Resolve write happens in the test; it reads the recorded build fixtures.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _j(name):
    return json.loads((FIX / name).read_text())


def test_plan_matches_the_accepted_p6_19_baseline():
    m = _j("p6_20_candidate_manifest.json")
    assert m["item_count"] == 132
    assert m["deterministic"] is True
    assert abs(m["duration_s"] - 162.94) < 0.1
    assert m["chronology_overlay"].startswith("none")   # plain production path, no hidden overlay


def test_resolve_build_matches_the_manifest_structurally():
    b = _j("p6_20_build_verification.json")
    assert b["planned_items"] == b["actual_video_items"] == 132
    mm = b["manifest_match"]
    assert mm["source_name_mismatches"] == 0
    assert mm["tl_start_mismatches"] == 0
    assert mm["tl_dur_mismatches"] == 0
    assert b["actual_audio_items"] == 2                  # both songs placed
    assert b["song2_transition_s"] == 108.0


def test_new_timeline_is_isolated_and_named():
    b = _j("p6_20_build_verification.json")
    assert b["timeline_name"] == "AI CUT V2 - P6.20 CANDIDATE"
    assert b["timeline_count_after"] == b["timeline_count_before"] + 1
    assert b["fps"] == 50.0
    assert b["resolution"] == "3840x2160"


def test_protected_timelines_unchanged():
    b = _j("p6_20_build_verification.json")
    p = b["protected_unchanged"]
    # hashes recorded before creation equal hashes recorded after (see the P6.20 report)
    assert p["AI Rough Cut"] == "056645bd0f954826"
    assert p["is edit"] == "efe59c58e9236478"
    assert p["IS EDIT - AI CUT V7"] == "689d0c574319a091"


def test_production_db_unchanged():
    b = _j("p6_20_build_verification.json")
    assert b["db_checksum"] == "e8798470c518"
    assert b["db_unchanged"] is True


def test_matches_prior_shadow_plan_shot_for_shot():
    """The candidate is the accepted P6.16/P6.19 plan -- same shot order as the P6.19 shadow."""
    b = _j("p6_20_build_verification.json")
    assert b["matches_p6_19_baseline_shotforshot"] is True
    m = [it["shot_id"] for it in _j("p6_20_candidate_manifest.json")["items"]]
    a = [it["shot_id"] for it in _j("p6_19_reuse_fix_shadow.json")["all_items"]]
    assert m == a
