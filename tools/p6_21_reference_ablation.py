"""P6.21 -- reference-influence ablation (shadow only, read-only, no writes).

Runs the EXACT production planner three ways and compares the resulting plans shot-for-shot:

  A  normal            -- style_profile = data/references/7film-style-profile.json (the 18-ref stats)
  B  no-reference      -- style_profile = None (all reference-derived influence removed)
  C  neutral-arc       -- style_profile present but story_arc / scale_shares / held_shots stripped

If A == B shot-for-shot, the reference style profile does not materially change runtime decisions.
Uses the P6.14 harness invocation; monkeypatches api._style_profile only (no media/semantic change).
No DB / Resolve / timeline write.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
OUT = ROOT / "tools" / "fixtures" / "p6_21_reference_ablation.json"


def _harness():
    spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    return h


def _plan_ids(api, planner, h):
    plan, _f, _s = h._run_once(api, planner, seed=1)
    ids = [it.shot.id for it in plan.items]
    durs = [int(it.timeline_range.duration_frames) for it in plan.items]
    sig = "|".join(f"{i}:{d}" for i, d in zip(ids, durs))
    return {"n": len(ids), "hash": hashlib.sha256(sig.encode()).hexdigest()[:16],
            "ids": ids, "durs": durs}


def run() -> dict:
    h = _harness()
    from sevenfilm import api
    from sevenfilm.services import planner
    h._harden(api.DATABASE)
    real_profile = api._style_profile
    base = real_profile()

    # A: normal
    api._style_profile = lambda: real_profile()
    A = _plan_ids(api, planner, h)

    # B: no reference influence at all
    api._style_profile = lambda: None
    B = _plan_ids(api, planner, h)

    # C: profile present but sequence/story structure stripped (keep only scalar pacing stats)
    def neutral():
        p = copy.deepcopy(base)
        for k in ("story_arc", "scale_shares", "scale_shares_source", "held_shots"):
            p.pop(k, None)
        return p
    api._style_profile = neutral
    C = _plan_ids(api, planner, h)

    api._style_profile = real_profile

    def diff(x, y):
        same = x["ids"] == y["ids"]
        pos = sum(1 for a, b in zip(x["ids"], y["ids"]) if a != b) if len(x["ids"]) == len(y["ids"]) else None
        dur_changed = sum(1 for a, b in zip(x["durs"], y["durs"]) if a != b) if len(x["durs"]) == len(y["durs"]) else None
        return {"identical": same, "count_delta": len(y["ids"]) - len(x["ids"]),
                "shot_position_mismatches": pos, "duration_mismatches": dur_changed}

    result = {
        "A_normal": {"n": A["n"], "hash": A["hash"]},
        "B_no_reference": {"n": B["n"], "hash": B["hash"]},
        "C_neutral_arc": {"n": C["n"], "hash": C["hash"]},
        "A_vs_B": diff(A, B),
        "A_vs_C": diff(A, C),
        "reference_count_in_profile": base.get("reference_count") if base else None,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
