"""P6.4: run the REAL production build_timeline() in-memory against the real 15A candidate
pool, real music analysis, frozen P6.1 Moments and the shadow day_by_asset chronology from
P6.3 -- to observe actual representative-shot selection. build_timeline() is a pure function
(no DB write, no Resolve call, no file I/O); its result is inspected here and never persisted,
exported, or written back. All DB access is read-only (sqlite URI mode=ro). The only
instrumentation is a pass-through wrapper around planner._score_candidate that records every
candidate's score/components at every cut without altering its return value or any other
planner behaviour -- so build_timeline()'s actual selections are identical to what production
would compute, just observed.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, "apps/api")

from sevenfilm.domain import BeatGrid
from sevenfilm.services import planner as planner_mod
from sevenfilm.services.analysis import row_to_shot
from sevenfilm.services.media import row_to_asset
from sevenfilm.services.moments import Moment

PROJECT_ID = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
DB_PATH = "file:data/sevenfilm.sqlite3?mode=ro"


def load_shots():
    con = sqlite3.connect(DB_PATH, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT shots.* FROM shots JOIN media_assets ON media_assets.id = shots.asset_id "
        "WHERE media_assets.project_id = ? ORDER BY media_assets.path, shots.start_frame",
        (PROJECT_ID,),
    ).fetchall()
    return [row_to_shot(dict(r)) for r in rows]


def load_assets():
    con = sqlite3.connect(DB_PATH, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM media_assets WHERE project_id = ? ORDER BY path", (PROJECT_ID,)
    ).fetchall()
    return [row_to_asset(dict(r)) for r in rows]


def load_music() -> BeatGrid:
    con = sqlite3.connect(DB_PATH, uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM music_tracks WHERE project_id = ? ORDER BY position, created_at LIMIT 1",
        (PROJECT_ID,),
    ).fetchone()
    row = dict(row)
    return BeatGrid(
        bpm=float(row["bpm"]),
        beats=tuple(Fraction(item) for item in json.loads(row["beats_json"])),
        duration=Fraction(row["duration_seconds"]),
        sections=tuple(json.loads(row["sections_json"])),
    )


def load_moments() -> tuple[Moment, ...]:
    data = json.loads(Path("tools/fixtures/p6_1_stage_b_moments_result.json").read_text())
    return tuple(
        Moment(name=m["name"], shot_ids=tuple(m["shot_ids"]), best=m["best"])
        for m in data["moments"]
    )


CAPTURED: list[dict] = []


def instrument_score_candidate():
    """Wrap _score_candidate with a pure pass-through logger: calls the real function,
    returns its exact result unmodified, and records the call for later analysis."""
    original = planner_mod._score_candidate

    def wrapper(shot, **kwargs):
        score, components = original(shot, **kwargs)
        CAPTURED.append(
            {
                "shot_id": shot.id,
                "asset_id": shot.asset_id,
                "score": score,
                "components": dict(components),
                "missing_moment": kwargs.get("missing_moment"),
                "moment_shot": kwargs.get("moment_shot"),
                "day_position": kwargs.get("day_position"),
                "progress": kwargs.get("progress"),
            }
        )
        return score, components

    planner_mod._score_candidate = wrapper
    return original


def main() -> int:
    shots = load_shots()
    assets = load_assets()
    music = load_music()
    moments = load_moments()

    original_score_fn = instrument_score_candidate()
    try:
        plan = planner_mod.build_timeline(
            project_id=PROJECT_ID,
            assets=assets,
            shots=shots,
            music=music,
            frame_rate=shots[0].source_range.rate,
            target_duration=Fraction(180),
            seed=3,
            moments=moments,
        )
    finally:
        planner_mod._score_candidate = original_score_fn

    print(f"plan items: {len(plan.items)}")
    print(f"candidate-scoring calls captured: {len(CAPTURED)}")

    # Group captured calls into per-cut pools (consecutive calls share progress/context).
    moment_shot_ids = {sid for m in moments for sid in m.shot_ids}
    cuts = []
    current_pool: list[dict] = []
    current_progress = None
    for call in CAPTURED:
        if current_progress is not None and call["progress"] != current_progress:
            cuts.append(current_pool)
            current_pool = []
        current_progress = call["progress"]
        current_pool.append(call)
    if current_pool:
        cuts.append(current_pool)
    print(f"reconstructed cuts: {len(cuts)}")

    # For each cut, rank the pool and see if the winner (or any moment member) is present.
    cut_summaries = []
    for i, pool in enumerate(cuts):
        ranked = sorted(pool, key=lambda c: -c["score"])
        winner = ranked[0]
        moment_members_in_pool = [c for c in pool if c["shot_id"] in moment_shot_ids]
        cut_summaries.append(
            {
                "cut_index": i,
                "progress": winner["progress"],
                "pool_size": len(pool),
                "winner_shot_id": winner["shot_id"],
                "winner_score": winner["score"],
                "winner_is_moment_member": winner["shot_id"] in moment_shot_ids,
                "moment_members_in_pool": [
                    {"shot_id": c["shot_id"], "score": c["score"], "rank": ranked.index(c) + 1}
                    for c in moment_members_in_pool
                ],
            }
        )

    # Identify the actual selected item for each of plan.items whose shot is a moment member.
    moment_cuts = []
    for idx, item in enumerate(plan.items):
        if item.shot.id in moment_shot_ids:
            member_of = [m.name for m in moments if item.shot.id in m.shot_ids]
            moment_cuts.append(
                {
                    "plan_index": idx,
                    "shot_id": item.shot.id,
                    "asset_id": item.shot.asset_id,
                    "moment_names": member_of,
                    "score": item.score,
                    "timeline_start": str(item.timeline_range.start_frame),
                }
            )
    print(f"moment-member shots actually selected into the plan: {len(moment_cuts)}")
    for mc in moment_cuts:
        print(f"  cut {mc['plan_index']}: {mc['shot_id'][:8]} moments={mc['moment_names']} score={mc['score']:.4f}")

    out = {
        "plan_item_count": len(plan.items),
        "captured_calls": len(CAPTURED),
        "reconstructed_cuts": len(cuts),
        "moment_member_selected_cuts": moment_cuts,
        "cut_summaries": cut_summaries,
    }
    out_path = Path("tools/fixtures/p6_4_candidate_pool_trace.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {out_path}")

    # Also dump full per-cut candidate detail for the specific cuts where cake/first_dance/
    # kiss/ring members appear anywhere in the pool (not just when selected) -- this is the
    # "freeze complete candidate pool" requirement.
    detail = []
    for i, pool in enumerate(cuts):
        names_present = {
            m.name for m in moments for c in pool if c["shot_id"] in set(m.shot_ids)
        }
        if names_present:
            ranked = sorted(pool, key=lambda c: -c["score"])
            detail.append(
                {
                    "cut_index": i,
                    "progress": pool[0]["progress"],
                    "moment_names_present": sorted(names_present),
                    "pool_size": len(pool),
                    "top10": [
                        {
                            "rank": r + 1,
                            "shot_id": c["shot_id"],
                            "asset_id": c["asset_id"],
                            "score": c["score"],
                            "components": c["components"],
                            "missing_moment": c["missing_moment"],
                            "day_position": c["day_position"],
                        }
                        for r, c in enumerate(ranked[:10])
                    ],
                }
            )
    detail_path = Path("tools/fixtures/p6_4_moment_cut_detail.json")
    detail_path.write_text(json.dumps(detail, indent=2, ensure_ascii=False))
    print(f"wrote {detail_path} ({len(detail)} cuts with a moment member present in the pool)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
