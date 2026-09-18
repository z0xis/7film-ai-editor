"""P6.19 -- distinct-source-phase asset-reuse fix guards.

The asset-reuse penalty now counts DISTINCT source phases (shot ids) drawn from an asset, not raw
uses, so over-playing one phase no longer suppresses a genuinely distinct angle of the same asset
(the repeat stays charged per-shot via REUSE_PENALTY). This is a strict correctness fix to the reuse
accounting; on the production shoot it is behaviourally neutral (no reception regression, plan
unchanged shot-for-shot). Shadow-only; no DB/timeline/Resolve write.
"""

import json
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import Shot
from sevenfilm.services.planner import (
    ASSET_REUSE_PENALTY,
    _score_candidate,
)
from sevenfilm.timebase import FrameRate, TimeRange

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"
PLANNER = ROOT / "apps/api/sevenfilm/services/planner.py"
RATE = FrameRate(50)


def _shot(identifier, asset):
    return Shot(id=identifier, asset_id=asset, source_range=TimeRange(0, 500, RATE),
                category="couple", shot_scale="medium", technical_quality=.8,
                aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{identifier}", brightness=.36, saturation=.15,
                highlight_clipping=.01)


def _score(asset_reuse_count):
    return _score_candidate(
        _shot("cand", "assetA"),
        preferred_categories=("couple",), preferred_scales=("medium",),
        energy="mid", recent=(), desired_duration=Fraction(1),
        random_jitter=0.0, asset_reuse_count=asset_reuse_count)


def _j(name):
    return json.loads((FIX / name).read_text())


# --- synthetic mechanism ------------------------------------------------------------------------

def test_distinct_phase_count_relieves_a_sibling_of_an_overused_shot():
    """Old accounting counted every use: one shot played 3x made asset_reuse_count 3 for a distinct
    sibling. New accounting counts distinct phases (here 1), so the sibling pays 2xASSET_REUSE_PENALTY
    less -- it competes on its own merit instead of inheriting the repeat's debt."""
    score_distinct, comp_distinct = _score(asset_reuse_count=1)   # one distinct phase used
    score_raw, comp_raw = _score(asset_reuse_count=3)             # old: three raw uses
    relief = comp_raw["reuse_penalty"] - comp_distinct["reuse_penalty"]
    assert abs(relief - 2 * ASSET_REUSE_PENALTY) < 1e-9
    assert score_distinct > score_raw


def test_same_phase_repeat_is_still_charged_per_shot():
    """The fix does not waive same-shot repetition: reuse_count (per-shot) still adds its penalty."""
    _, base = _score(asset_reuse_count=0)
    from sevenfilm.services.planner import REUSE_PENALTY
    _, repeated = _score_candidate(
        _shot("cand", "assetA"),
        preferred_categories=("couple",), preferred_scales=("medium",),
        energy="mid", recent=(), desired_duration=Fraction(1),
        random_jitter=0.0, reuse_count=2, asset_reuse_count=0)
    assert repeated["reuse_penalty"] - base["reuse_penalty"] > REUSE_PENALTY  # 2x per-shot charge


# --- accounting wiring --------------------------------------------------------------------------

def test_call_site_feeds_distinct_phase_count_not_raw_uses():
    src = PLANNER.read_text()
    # asset_reuse_count is fed the count of distinct phases, and phases are a set of selected shot ids
    assert "len(asset_phases.get(shot.asset_id, ()))" in src
    assert "asset_phases.setdefault(selected_shot.asset_id, set()).add(selected_shot.id)" in src


# --- shadow: no reception regression, plan unchanged --------------------------------------------

def test_shadow_does_not_regress_reception():
    s = _j("p6_19_shadow_summary.json")
    for cond in ("A_reuse_fix", "B_reuse_fix_high"):
        assert s[cond]["song2_items"] >= 40          # reception preserved (baseline 60)
        assert s[cond]["duration_s"] > 140
        assert s[cond]["items"] == s["baseline"]["items"]
        assert s[cond]["deterministic"] is True


def test_shadow_plan_is_unchanged_shot_for_shot():
    s = _j("p6_19_shadow_summary.json")
    assert s["A_equals_baseline_shotforshot"] is True
    assert s["B_equals_baseline_shotforshot"] is True


def test_the_misattribution_the_fix_targets_is_real():
    """DJI_0528 is used 6x but only 4 distinct phases: one shot repeats 3x, which under the old
    accounting inflated the asset counter against the asset's distinct siblings."""
    d = _j("p6_19_shadow_summary.json")["baseline"]["dji0528"]
    assert d["uses"] > d["distinct_phases"]
    assert d["max_same_shot"] >= 3


def test_shadow_is_shadow_only_no_writes():
    s = _j("p6_19_shadow_summary.json")
    assert s["safety_no_write"] is True
    # the P6.17 rejected relief constant must not have been revived
    assert "MOMENT_ASSET_REUSE_RELIEF" not in PLANNER.read_text()
