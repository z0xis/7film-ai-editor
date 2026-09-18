"""P6.16 -- false-early-stop / high-value reception continuation fix.

The bounded control-flow fix: when the cut-run window gate finds no shot able to carry a cut of the
CURRENT (long) requested length, the planner no longer ends the whole film once past the minimum
deliverable share -- it first checks whether any shot can carry the SHORTEST allowed cut and, if so,
shortens this cut and continues (a local slot failure, not global exhaustion). Only when nothing can
hold even a minimum cut does the enough-to-deliver early stop still apply.

Reproduction is the before/after shadow contrast on the SAME real production inputs:
  * old baseline (tools/fixtures/p6_14_shadow_plan.json): 59 items / ~96 s / 0 second-song items;
  * fixed (tools/fixtures/p6_16_fixed_shadow.json): continues into the reception.
Both fixtures come from the write-hardened, no-persistence shadow harness.
"""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "tools/fixtures/p6_14_shadow_plan.json"
NEW = ROOT / "tools/fixtures/p6_16_fixed_shadow.json"
PLANNER = ROOT / "apps/api/sevenfilm/services/planner.py"


def _old():
    return json.loads(OLD.read_text())


def _new():
    return json.loads(NEW.read_text())


def test_fix_is_a_local_min_cut_escape_before_global_break():
    src = PLANNER.read_text()
    # The min-cut escape must precede the deliverable-share break (not an unconditional break).
    assert "usable_at_min" in src
    assert "desired = MIN_CUT_SECONDS" in src
    i_escape = src.index("usable_at_min")
    i_break = src.index("target_duration * MINIMUM_DELIVERABLE_SHARE", i_escape)
    assert i_escape < i_break  # escape checked before the early-stop break


def test_old_baseline_stopped_before_the_second_song():
    old = _old()["plan"]
    assert old["items"] == 59
    assert old["duration_s"] < 100
    assert all(x["tl_start_s"] < 108 for x in _old()["all_items"])  # 0 second-song items


def test_fixed_plan_reaches_the_reception_second_song():
    new = _new()
    p = new["plan"]
    assert p["duration_s"] > 140  # was ~96s; now well past the false stop
    song2 = [x for x in new["all_items"] if x["tl_start_s"] >= 108]
    assert len(song2) >= 30  # real second-song reception coverage (was 0)


def test_fixed_plan_is_deterministic():
    assert _new()["plan"]["deterministic"] is True


def test_fix_does_not_overfill_strong_shots_remain_unused():
    new = _new()
    used = len({x["shot_id"] for x in new["all_items"]})
    # 2638 shots exist; a good edit uses a small fraction and leaves strong material unused.
    assert used < 400


def test_reception_is_real_content_not_day_filler():
    new = _new()
    song2 = [x for x in new["all_items"] if x["tl_start_s"] >= 108]
    cats = Counter(x["category"] for x in song2)
    # reception is party/couple/family/groom/bride, not a repeat of prep/detail filler
    assert cats["party"] + cats["couple"] >= 10


def test_same_source_reuse_is_bounded_not_runaway():
    new = _new()
    per_shot = Counter(x["shot_id"] for x in new["all_items"])
    # no single shot is spammed unboundedly by the min-cut escape
    assert max(per_shot.values()) <= 5


def test_first_dance_and_kiss_now_reach_selection_or_scoring():
    # The reception moments the old plan never reached now enter the funnel (carry-forward:
    # source-moment/sequence quality of first dance is a separate blocker, not the early stop).
    mc = _new()["moment_coverage"]
    assert mc["first_dance"]["selected"] >= 1
    assert mc["kiss"]["scored"] >= 1


def test_shadow_made_no_writes():
    s = _new()["safety"]
    assert s["checksum_before"] == s["checksum_after"]
    assert s["mtime_before"] == s["mtime_after"]
    assert s["post_manifest"] == s["pre_manifest"]
    assert s["pre_manifest"]["timeline_items"] == 129
