"""P6.20 -- generate the current-planner candidate manifest for a Resolve timeline build.

Runs the EXACT production planner (build_timeline) over the real production state, read-only and
write-hardened (reusing the P6.14 harness invocation), and emits a full placement manifest: per item
the source file path, source in/out frames, timeline in/out frames, implied speed, plus the music
segments. No chronology overlay is injected -- this is the plain production path. No DB/Resolve write.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
OUT = ROOT / "tools" / "fixtures" / "p6_20_candidate_manifest.json"


def _harness():
    spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    return h


def build(seed=1) -> dict:
    h = _harness()
    from sevenfilm import api
    from sevenfilm.services import planner
    h._harden(api.DATABASE)
    plan1, _f, segments = h._run_once(api, planner, seed=seed)
    plan2, _f2, _s2 = h._run_once(api, planner, seed=seed)
    ids1 = [it.shot.id for it in plan1.items]
    ids2 = [it.shot.id for it in plan2.items]
    deterministic = ids1 == ids2

    items = []
    for it in plan1.items:
        sr, tr = it.source_range, it.timeline_range
        src_dur = int(sr.duration_frames)
        tl_dur = int(tr.duration_frames)
        items.append({
            "shot_id": it.shot.id,
            "asset_id": it.shot.asset_id,
            "source_name": it.asset.name,
            "source_path": str(it.asset.path),
            "category": it.shot.category,
            "src_start_frame": int(sr.start_frame),
            "src_dur_frames": src_dur,
            "tl_start_frame": int(tr.start_frame),
            "tl_dur_frames": tl_dur,
            "speed": round(src_dur / tl_dur, 4) if tl_dur else 1.0,
            "rate": float(tr.rate.value),
            "score": round(it.score, 4),
        })

    music = [{
        "path": str(s.path), "name": Path(s.path).name,
        "tl_start_s": float(s.timeline_start), "dur_s": float(s.duration),
        "src_start_s": float(s.source_start),
        "tl_end_s": float(s.timeline_end),
    } for s in segments]

    plan_sig = "|".join(f"{x['shot_id']}:{x['src_start_frame']}:{x['tl_start_frame']}:{x['tl_dur_frames']}"
                        for x in items)
    plan_hash = hashlib.sha256(plan_sig.encode()).hexdigest()[:16]

    total_tl_frames = sum(x["tl_dur_frames"] for x in items)
    rate = items[0]["rate"] if items else 50.0
    result = {
        "plan_hash": plan_hash,
        "deterministic": deterministic,
        "seed": seed,
        "item_count": len(items),
        "duration_s": round(total_tl_frames / rate, 2),
        "rate": rate,
        "retimed_items": [x for x in items if abs(x["speed"] - 1.0) > 1e-6],
        "chronology_overlay": "none (plain production path)",
        "music": music,
        "items": items,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    r = build()
    print(json.dumps({k: v for k, v in r.items() if k != "items"}, indent=2, default=str))
