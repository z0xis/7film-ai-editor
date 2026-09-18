"""P6.15 -- V7-guided planner diagnosis guards (read-only).

Locks the V7 reference facts (extracted read-only from the live Resolve project) and the proven
early-stop diagnosis. No Resolve write, no timeline write, no DB write.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAG = ROOT / "tools/fixtures/p6_15_v7_diagnosis.json"
SHADOW = ROOT / "tools/fixtures/p6_14_shadow_plan.json"


def _d():
    return json.loads(DIAG.read_text())


def test_v7_is_the_reference_and_is_not_180s():
    v7 = _d()["v7"]
    assert v7["timeline_name"] == "IS EDIT - AI CUT V7"
    # The human-acceptable reference is ~123s, not the planner's nominal 180s target.
    assert 115 <= v7["duration_s"] <= 130
    assert len(v7["songs"]) == 2


def test_v7_transitions_to_second_song_for_reception():
    v7 = _d()["v7"]
    assert v7["songs"][1]["tl_start_s"] < 85  # song 2 enters ~78-80s
    assert v7["songs"][1]["tl_end_s"] > 120    # and carries to the end
    assert v7["cake"]["present"] is True
    assert v7["first_dance"]["present"] is True


def test_v7_uses_drones_and_reuses_sources_forward():
    v7 = _d()["v7"]
    assert len(v7["drone_assets_used"]) >= 5
    reuse = v7["same_source_reuse_forward"]
    # same source reused with forward-progressing source-in frames
    for _src, ins in reuse.items():
        assert ins == sorted(ins), f"{_src} not forward"
    assert "DJI_0528" in reuse  # first-dance drone reused forward


def test_shadow_stops_at_96s_not_from_exhaustion():
    diag = _d()
    sh = diag["shadow_p6_14"]
    assert sh["duration_s"] < diag["v7"]["duration_s"]  # shadow shorter than the human ref
    assert sh["second_song_items"] == 0                 # never reaches reception/song 2
    assert sh["source_range_none_exhaustions"] == 0     # NOT source exhaustion


def test_shadow_fixture_agrees():
    sh = json.loads(SHADOW.read_text())["plan"]
    assert sh["items"] == 59
    assert sh["duration_s"] < 130
    assert all(x["tl_start_s"] < 108 for x in json.loads(SHADOW.read_text())["all_items"])


def test_early_stop_diagnosis_is_cut_run_gate_not_semantics():
    diag = _d()["early_stop_diagnosis"]
    assert diag["is_96s_erroneous_vs_v7"] is True
    assert "MINIMUM_DELIVERABLE_SHARE" in diag["mechanism"]
    assert "SCORING_WEIGHT" in diag["primary_class"] or "CANDIDATE_ELIGIBILITY" in diag["primary_class"]


def test_no_fix_implemented_in_diagnosis_package():
    assert _d()["fix_implemented"] is False
    assert _d()["duration_conclusion"]["hard_180_requirement"] is False
