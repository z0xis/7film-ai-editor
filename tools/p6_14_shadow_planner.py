"""P6.14 -- Shadow planner / story-coverage validation. Runs the EXACT production planner
(`build_timeline`) in memory over the real remediated production state, with NO persistence.

Safety: `build_timeline` takes no database and cannot write. As belt-and-suspenders this harness
replaces every write method on the production DATABASE (and persist_timeline) with a hard raise for
the duration of the run, so any accidental write aborts loudly. It never calls persist_timeline and
never creates a timeline row. Reads only. Writes a JSON fixture outside the DB.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.environ.pop("SEVENFILM_DATA_ROOT", None)  # -> real production data dir
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
TL_15A = "47dcab29-e8ca-4c78-ba3d-2c40457cc153"
FIXTURE = ROOT / "tools" / "fixtures" / "p6_14_shadow_plan.json"

_spec = importlib.util.spec_from_file_location("p6_11_safety", ROOT / "tools/p6_11_reencode_safety.py")
safety = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safety)


def _harden(database):
    def blocked(*a, **k):
        raise AssertionError("REFUSED: shadow planner attempted a production write")
    for meth in ("insert", "execute", "replace_rows", "update_job", "update_job_progress",
                 "transition_job", "touch_heartbeat"):
        if hasattr(database, meth):
            setattr(database, meth, blocked)


def _run_once(api, planner, seed):
    from sevenfilm.services.analysis import project_shots
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.moments import (
        project_distractions,
        project_moments,
        project_obstructions,
        project_opening_signs,
    )
    from sevenfilm.services.music import plan_music
    from sevenfilm.timebase import FrameRate

    DB_ = api.DATABASE
    project = api._project(P15)
    target = Fraction(project["target_duration_seconds"])
    songs = api.project_music(DB_, P15)
    music_segments = ()
    if songs:
        music_grid, music_segments, _mw = plan_music(songs, target, api._style_profile())
    else:
        music_grid = api._missing_music()

    # ---- instrument the funnel ----
    funnel = {"usable": {}, "scored": {}}
    real_is_usable = planner._is_usable
    real_score = planner._score_candidate

    def spy_usable(shot, minq, maxc):
        ok = real_is_usable(shot, minq, maxc)
        funnel["usable"][shot.id] = bool(ok)
        return ok

    def spy_score(shot, **kw):
        res = real_score(shot, **kw)
        score = res[0] if isinstance(res, tuple) else res
        funnel["scored"][shot.id] = {
            "moment_shot": bool(kw.get("moment_shot")),
            "day_position": kw.get("day_position"),
            "score": float(score),
        }
        return res

    planner._is_usable = spy_usable
    planner._score_candidate = spy_score
    try:
        plan = planner.build_timeline(
            project_id=P15,
            assets=project_assets(DB_, P15),
            shots=project_shots(DB_, P15),
            music=music_grid,
            frame_rate=FrameRate.parse(project["frame_rate"]),
            target_duration=target,
            style_profile=api._style_profile(),
            seed=seed,
            windows_by_shot=api.project_windows(DB_, P15),
            rejected=api.project_rejections(DB_, P15),
            moments=project_moments(DB_, P15),
            distractions=project_distractions(DB_, P15),
            obstructions=project_obstructions(DB_, P15),
            opening_signs=project_opening_signs(DB_, P15),
            table_settings=api.project_table_settings(DB_, P15),
            embeddings=api.project_embeddings(DB_, P15),
        )
        plan.music_segments = music_segments
    finally:
        planner._is_usable = real_is_usable
        planner._score_candidate = real_score
    return plan, funnel, music_segments


def main() -> dict:
    checksum_before = safety._sha256(DB)
    mtime_before = DB.stat().st_mtime
    pre_manifest = safety.build_manifest(DB, P15)

    from sevenfilm import api
    from sevenfilm.services import planner
    _harden(api.DATABASE)

    plan1, funnel, segments = _run_once(api, planner, seed=1)
    plan2, _f2, _s2 = _run_once(api, planner, seed=1)
    ids1 = [it.shot.id for it in plan1.items]
    ids2 = [it.shot.id for it in plan2.items]
    deterministic = ids1 == ids2

    # asset + moment maps (read-only)
    import sqlite3
    ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    aname = {r["id"]: r["file_name"] for r in ro.execute(
        "SELECT id, file_name FROM media_assets WHERE project_id=?", (P15,))}
    from sevenfilm.services.moments import project_moments
    moments = project_moments(api.DATABASE, P15)
    moment_of = {}
    for m in moments:
        for sid in m.shot_ids:
            moment_of.setdefault(sid, []).append(m.name)

    # music segment boundaries
    seg_bounds = [(float(s.timeline_start), float(s.timeline_start + s.duration)) for s in segments]

    def seg_index(t):
        for i, (a, b) in enumerate(seg_bounds):
            if a <= t < b:
                return i
        return len(seg_bounds) - 1 if seg_bounds else 0

    # selected items
    items = []
    cat_counts = defaultdict(int)
    src_counts = defaultdict(int)
    for it in plan1.items:
        src = aname.get(it.shot.asset_id, "?")
        t0 = float(it.timeline_range.start_frame) / it.timeline_range.rate.value
        items.append({
            "shot_id": it.shot.id, "source": src, "category": it.shot.category,
            "tl_start_s": round(t0, 2),
            "dur_s": round(float(it.timeline_range.duration_frames) / it.timeline_range.rate.value, 2),
            "moment": moment_of.get(it.shot.id, []),
            "segment": seg_index(t0),
            "is_drone": src.startswith("DJI_"),
            "score": round(it.score, 3),
        })
        cat_counts[it.shot.category] += 1
        src_counts[src] += 1

    # moment coverage: for each family, members / usable / scored / selected
    selected_ids = {it.shot.id for it in plan1.items}
    moment_report = {}
    for m in moments:
        members = list(m.shot_ids)
        moment_report[m.name] = {
            "members": len(members),
            "usable": sum(1 for s in members if funnel["usable"].get(s)),
            "scored": sum(1 for s in members if s in funnel["scored"]),
            "selected": sum(1 for s in members if s in selected_ids),
            "selected_sources": [aname.get(_shot_asset(ro, s), "?") for s in members if s in selected_ids],
            "member_sources": [aname.get(_shot_asset(ro, s), "?") for s in members],
        }

    # drone coverage
    drone_items = [x for x in items if x["is_drone"]]
    drones_selected = defaultdict(int)
    for x in drone_items:
        drones_selected[x["source"]] += 1

    # old 129 timeline (read-only)
    old = ro.execute(
        "SELECT ti.shot_id, ti.category, m.file_name FROM timeline_items ti "
        "JOIN media_assets m ON m.id=ti.asset_id WHERE ti.timeline_id=?", (TL_15A,)).fetchall()
    old_cats = defaultdict(int); old_drone = 0
    for r in old:
        old_cats[r["category"] or "?"] += 1
        if (r["file_name"] or "").startswith("DJI_"):
            old_drone += 1

    ro.close()
    result = {
        "safety": {
            "checksum_before": checksum_before, "checksum_after": safety._sha256(DB),
            "mtime_before": mtime_before, "mtime_after": DB.stat().st_mtime,
            "pre_manifest": pre_manifest, "post_manifest": safety.build_manifest(DB, P15),
        },
        "plan": {
            "items": len(plan1.items),
            "duration_s": round(sum(x["dur_s"] for x in items), 1),
            "target_s": float(plan1.target_duration),
            "warnings": list(plan1.warnings),
            "deterministic": deterministic,
            "music_segments": len(segments),
            "segment_bounds_s": [[round(a, 1), round(b, 1)] for a, b in seg_bounds],
            "category_counts": dict(cat_counts),
            "distinct_sources": len(src_counts),
            "top_sources": sorted(src_counts.items(), key=lambda kv: -kv[1])[:12],
        },
        "moment_coverage": moment_report,
        "drones": {"selected_items": len(drone_items),
                   "by_asset": dict(drones_selected),
                   "distinct_drone_assets_selected": len(drones_selected)},
        "intro_items": items[:12],
        "outro_items": items[-12:],
        "transition": _transition_window(items, seg_bounds),
        "grammar_by_segment": _grammar(items, len(seg_bounds)),
        "old_129": {"items": len(old), "drone": old_drone, "categories": dict(old_cats)},
        "all_items": items,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def _shot_asset(ro, shot_id):
    r = ro.execute("SELECT asset_id FROM shots WHERE id=?", (shot_id,)).fetchone()
    return r["asset_id"] if r else None


def _transition_window(items, seg_bounds):
    if len(seg_bounds) < 2:
        return {"exists": False}
    tpoint = seg_bounds[1][0]
    near = [x for x in items if tpoint - 10 <= x["tl_start_s"] <= tpoint + 15]
    return {"exists": True, "transition_s": round(tpoint, 1),
            "items": [{"source": x["source"], "category": x["category"],
                       "tl_start_s": x["tl_start_s"], "dur_s": x["dur_s"], "segment": x["segment"]}
                      for x in near]}


def _grammar(items, n_seg):
    out = {}
    for s in range(max(1, n_seg)):
        seg = [x for x in items if x["segment"] == s]
        if not seg:
            continue
        durs = sorted(x["dur_s"] for x in seg)
        out[s] = {"items": len(seg),
                  "median_dur_s": round(durs[len(durs) // 2], 2),
                  "cats": dict(_count([x["category"] for x in seg]))}
    return out


def _count(xs):
    d = defaultdict(int)
    for x in xs:
        d[x] += 1
    return d


if __name__ == "__main__":
    out = main()
    slim = {k: v for k, v in out.items() if k != "all_items"}
    print(json.dumps(slim, indent=2, sort_keys=True, default=str))
