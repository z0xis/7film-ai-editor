"""P6.3: read-only shadow trace of moment_day / _due_now() / moment_bonus eligibility using
the EXACT unchanged production _moment_shots_of_the_day() and the same due_now() logic as
build_timeline() (planner.py), reproduced here rather than calling build_timeline() itself so
no timeline/Resolve/DB-persistence code path is ever touched. Frozen P6.1 Moments + shadow
day_by_asset (tools/shadow_day_by_asset.py) are the only inputs. No human labels are read by
any of this -- they are applied only afterwards, in the report, for interpretation.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "apps/api")

from sevenfilm.services.moments import Moment
from sevenfilm.services.planner import MOMENT_DAY_SPREAD, _moment_shots_of_the_day

PROJECT_ID = "29cd1e06-0af1-40c4-95bf-77f2add1159f"


def load_moments() -> tuple[Moment, ...]:
    data = json.loads(Path("tools/fixtures/p6_1_stage_b_moments_result.json").read_text())
    return tuple(
        Moment(name=m["name"], shot_ids=tuple(m["shot_ids"]), best=m["best"])
        for m in data["moments"]
    )


def load_shot_asset_map(shot_ids: set[str]) -> dict[str, str]:
    con = sqlite3.connect("file:data/sevenfilm.sqlite3?mode=ro", uri=True)
    placeholders = ",".join("?" for _ in shot_ids)
    rows = con.execute(
        f"SELECT s.id, s.asset_id FROM shots s WHERE s.id IN ({placeholders})",
        list(shot_ids),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def load_day_by_asset() -> dict[str, float]:
    data = json.loads(Path("tools/fixtures/p6_3_shadow_day_by_asset.json").read_text())
    return {
        asset_id: info["day_position"]
        for asset_id, info in data["day_by_asset"].items()
        if info["day_position"] is not None
    }


def _due_now(names: set[str], unshown: set[str], moment_day: dict[str, float]) -> bool:
    owed = names & unshown
    if not owed:
        return False
    earliest = min((moment_day[name] for name in unshown if name in moment_day), default=None)
    if earliest is None:
        return True
    return any(moment_day.get(name, earliest) <= earliest + MOMENT_DAY_SPREAD for name in owed)


def main() -> int:
    moments = load_moments()
    all_shot_ids = {sid for m in moments for sid in m.shot_ids}
    shot_asset = load_shot_asset_map(all_shot_ids)
    day_by_asset = load_day_by_asset()

    class _ShotStub:
        def __init__(self, id_: str, asset_id: str):
            self.id = id_
            self.asset_id = asset_id

    shot_by_id = {sid: _ShotStub(sid, aid) for sid, aid in shot_asset.items()}

    moment_of_shot: dict[str, set[str]] = {}
    kept_by_moment: dict[str, tuple[str, ...]] = {}
    for moment in moments:
        kept = _moment_shots_of_the_day(moment, shot_by_id, day_by_asset)
        kept_by_moment[moment.name] = kept
        for shot_id in kept:
            moment_of_shot.setdefault(shot_id, set()).add(moment.name)

    moment_day: dict[str, float] = {}
    for moment in moments:
        where = [
            day_by_asset[shot.asset_id]
            for shot_id in moment.shot_ids
            if (shot := shot_by_id.get(shot_id)) and shot.asset_id in day_by_asset
        ]
        if where:
            moment_day[moment.name] = sorted(where)[len(where) // 2]
        contributors = [
            (shot_id, shot_by_id[shot_id].asset_id, day_by_asset.get(shot_by_id[shot_id].asset_id))
            for shot_id in moment.shot_ids
            if shot_id in shot_by_id
        ]
        timed_contributors = [c for c in contributors if c[2] is not None]
        print(f"\n=== {moment.name} ===")
        print(f"  members: {len(moment.shot_ids)}, with day_position: {len(timed_contributors)}")
        for sid, aid, pos in contributors:
            print(f"    {sid[:8]}  asset={aid[:8]}  day_position={pos}")
        print(f"  moment_day (median of timed members): {moment_day.get(moment.name)}")
        kept_here = kept_by_moment[moment.name]
        dropped = [sid for sid in moment.shot_ids if sid not in kept_here]
        print(f"  kept by _moment_shots_of_the_day (spread={MOMENT_DAY_SPREAD}): {len(kept_here)} of {len(moment.shot_ids)}")
        print(f"  dropped as day-position outliers: {dropped}")

    unshown = {m.name for m in moments}
    print("\n=== due_now at story start (all 6 moments unshown) ===")
    for moment in moments:
        due = _due_now({moment.name}, unshown, moment_day)
        print(f"  {moment.name}: moment_day={moment_day.get(moment.name)} due_now={due}")

    out = {
        "moment_day": moment_day,
        "kept_counts": {k: len(v) for k, v in kept_by_moment.items()},
        "due_now_at_start": {
            m.name: _due_now({m.name}, unshown, moment_day) for m in moments
        },
        "contributors": {
            m.name: [
                {
                    "shot_id": sid,
                    "asset_id": shot_by_id[sid].asset_id if sid in shot_by_id else None,
                    "day_position": day_by_asset.get(shot_by_id[sid].asset_id) if sid in shot_by_id else None,
                }
                for sid in m.shot_ids
            ]
            for m in moments
        },
    }
    Path("tools/fixtures/p6_3_planner_trace.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nwrote tools/fixtures/p6_3_planner_trace.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
