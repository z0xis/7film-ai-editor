"""Run the moment search twice — as the planner runs it, and over the whole clip — and report.

Reads the project, builds the plan the way the API does, then for every cut works out what a
search over the whole clip would have been allowed to reach. Writes nothing to the project, to
Resolve, or to the plan: the production range is whatever the planner returned.

Two questions it answers:

  * does the production plan come out unchanged (it must; nothing here is wired in)
  * how much of the editor's own moment comes into reach once the shot boundary stops being
    the search boundary

Usage: tools/shadow_recall.py <project-id> [--reference reference.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services import shadow
from sevenfilm.services.analysis import project_shots
from sevenfilm.services.media import project_assets
from sevenfilm.services.planner import _window_score
from sevenfilm.services.windows import asset_windows, project_windows


def sharpness_bar(windows_by_shot) -> float:
    values = sorted(w.sharpness for rows in windows_by_shot.values() for w in rows)
    return values[len(values) // 2] if values else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--reference", type=Path, default=None,
                        help="JSON of {clip: [manual_in, manual_out]} to measure recall against")
    parser.add_argument("--plan", type=Path, default=None,
                        help="JSON of [{clip, src_in, frames}] standing in for a built plan")
    args = parser.parse_args()

    database = Database(database_path())
    assets = {asset.id: asset for asset in project_assets(database, args.project_id)}
    shots = project_shots(database, args.project_id)
    by_asset_name = {}
    for asset in assets.values():
        by_asset_name.setdefault(asset.name, asset)

    windows_by_shot = project_windows(database, args.project_id)
    windows_by_asset = asset_windows(database, args.project_id)
    bar = sharpness_bar(windows_by_shot)

    coverage = {}
    for asset in assets.values():
        measured = len(windows_by_asset.get(asset.id, ()))
        total = max(1, int(asset.duration * 2))
        coverage[asset.name] = min(1.0, measured / total)

    covered = sorted(coverage.values())
    print(f"assets: {len(assets)}   shots: {len(shots)}")
    print(f"windows: {sum(len(v) for v in windows_by_asset.values())}")
    print(f"coverage of clip length: median {covered[len(covered)//2]:.2f}, "
          f"under half on {sum(1 for c in covered if c < 0.5)}/{len(covered)} clips")
    print(f"sharpness bar: {bar:.2f}")

    if not args.reference or not args.plan:
        return 0

    reference = json.loads(args.reference.read_text())
    plan = json.loads(args.plan.read_text())
    shots_by_asset = {}
    for shot in shots:
        shots_by_asset.setdefault(shot.asset_id, []).append(shot)
    for rows in shots_by_asset.values():
        rows.sort(key=lambda s: s.source_range.start_frame)

    legacy_hits = shadow_hits = 0
    fallbacks = 0
    rows_out = []
    for item in plan:
        clip = item["clip"]
        manual = reference.get(clip)
        asset = by_asset_name.get(clip)
        if manual is None or asset is None:
            continue
        host = next(
            (s for s in shots_by_asset.get(asset.id, ())
             if s.source_range.start_frame <= item["src_in"] < s.source_range.end_frame),
            None)
        if host is None:
            continue
        frames = int(item["frames"])
        total_frames = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
        result = shadow.evaluate(
            host, frames,
            asset_duration_frames=total_frames,
            windows=windows_by_asset.get(asset.id, ()),
            sharpness_bar=bar,
            window_score=_window_score,
            legacy_start=int(item["src_in"]),
        )
        legacy_ok = shadow.reachable(result.legacy_range, manual[0])
        shadow_ok = shadow.reachable(result.shadow_range, manual[0])
        legacy_hits += legacy_ok
        shadow_hits += shadow_ok
        fallbacks += result.fallback
        rows_out.append({
            "clip": clip, "manual_in": manual[0], "legacy_in": item["src_in"],
            "shadow_in": result.shadow_start, "frames": frames,
            "legacy_range": [result.legacy_range.first_frame, result.legacy_range.last_frame],
            "shadow_range": ([result.shadow_range.first_frame, result.shadow_range.last_frame]
                             if result.shadow_range else None),
            "legacy_reachable": legacy_ok, "shadow_reachable": shadow_ok,
            "fallback": result.fallback, "reason": result.reason,
            "host_shot": host.id, "winner_shot": result.host_shot_id,
        })

    total = len(rows_out)
    print(f"\npairs measured: {total}")
    print(f"  editor's moment reachable, shot search : {legacy_hits}/{total}")
    print(f"  editor's moment reachable, clip search : {shadow_hits}/{total}")
    print(f"  fallbacks: {fallbacks}/{total}")
    Path("shadow_recall.json").write_text(json.dumps(rows_out, indent=1))
    print("written shadow_recall.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
