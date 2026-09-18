"""P6.19 -- shadow validation of the distinct-source-phase asset-reuse fix.

The planner now counts DISTINCT source phases (shot ids) drawn from an asset for the asset-reuse
penalty, instead of raw uses -- so over-playing one phase no longer suppresses a genuinely distinct
angle of the same asset (that repeat stays charged per-shot). This runs the real production planner
shadow two ways and writes P6.19 fixtures WITHOUT touching the accepted P6.16 baseline fixture:

  A (reuse-fix only)         -> tools/fixtures/p6_19_reuse_fix_shadow.json
  B (reuse-fix + P6.18 HIGH) -> tools/fixtures/p6_19_reuse_fix_high_shadow.json

Read-only, write-hardened, no persistence (same harness as P6.14/P6.16). No DB/timeline/Resolve write,
no chronology persisted (the HIGH overlay is injected in-memory via a scoring wrapper, exactly as P6.18).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
FIX = ROOT / "tools" / "fixtures"


def _harness(out_fixture: Path):
    spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    h.FIXTURE = out_fixture  # AFTER exec_module (which resets the module's own FIXTURE)
    return h


def run_a() -> dict:
    """Reuse-fix only, no chronology overlay."""
    h = _harness(FIX / "p6_19_reuse_fix_shadow.json")
    return h.main()


def run_b() -> dict:
    """Reuse-fix + P6.18 HIGH drone-chronology overlay (in-memory, no persistence)."""
    data = json.loads((FIX / "p6_18_drone_chronology.json").read_text())["estimates"]
    inferred = {sid: v["est"] for sid, v in data.items()
                if v["est"] is not None and v["tier"] == "HIGH"}
    from sevenfilm.services import planner
    real = planner._score_candidate

    def wrapped(shot, **kw):
        if shot.id in inferred:
            kw = dict(kw)
            kw["day_position"] = inferred[shot.id]
        return real(shot, **kw)

    planner._score_candidate = wrapped
    h = _harness(FIX / "p6_19_reuse_fix_high_shadow.json")
    try:
        return h.main()
    finally:
        planner._score_candidate = real


def _summ(out: dict) -> dict:
    p = out["plan"]
    gbs = out["grammar_by_segment"]
    seg1 = gbs.get("1", gbs.get(1, {}))
    return {"items": p["items"], "duration_s": p["duration_s"],
            "song2_items": seg1.get("items"),
            "deterministic": p["deterministic"], "distinct_sources": p["distinct_sources"],
            "top_sources": p["top_sources"][:6],
            "checksum_after": out["safety"]["checksum_after"][:12]}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode in ("a", "both"):
        print("A", json.dumps(_summ(run_a()), indent=2, default=str))
    if mode in ("b", "both"):
        print("B", json.dumps(_summ(run_b()), indent=2, default=str))
