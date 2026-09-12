"""Compare three moment searches against the editor's own choice, on the clips both used.

  A  what the planner does      — shot search, production score
  B  P1                         — clip search, production score
  C  P1 + P2                    — clip search, sharpness as a gate rather than a ranker

Reads the project and the media measurements. Writes a JSON report. Changes nothing: the
planner's answer is read from the plan it produced, and neither shadow path is wired into it.

Usage: tools/shadow_compare.py <project-id> --reference ref.json --plan plan.json
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services import shadow
from sevenfilm.services.analysis import project_shots
from sevenfilm.services.media import project_assets
from sevenfilm.services.planner import UNUSABLE_SHARPNESS_SHARE, _window_score
from sevenfilm.services.windows import asset_windows, project_windows

RATE = 50


def sharpness_bar(windows_by_shot) -> float:
    values = sorted(w.sharpness for rows in windows_by_shot.values() for w in rows)
    return values[len(values) // 2] if values else 0.0


def spread(values):
    ordered = sorted(values)
    def pick(share):
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]
    return {
        "median": st.median(ordered), "mean": st.mean(ordered),
        "p25": pick(0.25), "p75": pick(0.75), "p90": pick(0.90),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("shadow_compare.json"))
    args = parser.parse_args()

    database = Database(database_path())
    assets = {}
    for asset in project_assets(database, args.project_id):
        assets.setdefault(asset.name, asset)
    shots_by_asset: dict[str, list] = {}
    for shot in project_shots(database, args.project_id):
        shots_by_asset.setdefault(shot.asset_id, []).append(shot)
    for rows in shots_by_asset.values():
        rows.sort(key=lambda s: s.source_range.start_frame)

    windows_by_asset = asset_windows(database, args.project_id)
    bar = sharpness_bar(project_windows(database, args.project_id))

    reference = json.loads(args.reference.read_text())
    plan = json.loads(args.plan.read_text())

    rows = []
    for item in plan:
        clip = item["clip"]
        manual = reference.get(clip)
        asset = assets.get(clip)
        if manual is None or asset is None:
            continue
        host = next((s for s in shots_by_asset.get(asset.id, ())
                     if s.source_range.start_frame <= item["src_in"] < s.source_range.end_frame),
                    None)
        if host is None:
            continue
        frames = int(item["frames"])
        total = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
        windows = windows_by_asset.get(asset.id, ())

        legacy = shadow.legacy_search_range(host, frames)
        p1 = shadow.evaluate(host, frames, asset_duration_frames=total, windows=windows,
                             sharpness_bar=bar, window_score=_window_score,
                             legacy_start=int(item["src_in"]))
        p2 = shadow.evaluate(host, frames, asset_duration_frames=total, windows=windows,
                             sharpness_bar=bar, window_score=shadow.gated_window_score,
                             legacy_start=int(item["src_in"]))

        # how many candidate starts share the winning score, under each scorer
        def ties(scorer, span, windows=windows, frames=frames):
            if not span:
                return 0
            starts = [span.first_frame] + [
                w.asset_frame for w in windows
                if span.first_frame < w.asset_frame <= span.last_frame]
            values = []
            for start in starts:
                covered = [w for w in windows if start <= w.asset_frame < start + frames]
                if not covered:
                    earlier = [w for w in windows if w.asset_frame <= start]
                    covered = earlier[-1:] if earlier else []
                if covered:
                    values.append(round(min(
                        scorer(w.as_shot_window(), bar, w.category) for w in covered), 9))
            if not values:
                return 0
            return sum(1 for v in values if v == max(values))

        def crisp_floor_breach(start, windows=windows, frames=frames):
            covered = [w for w in windows if start <= w.asset_frame < start + frames]
            return any(w.sharpness / bar < UNUSABLE_SHARPNESS_SHARE for w in covered)

        rows.append({
            "clip": clip, "manual_in": manual[0], "frames": frames,
            "a_in": int(item["src_in"]),
            "b_in": p1.shadow_start, "b_score": p1.shadow_score,
            "c_in": p2.shadow_start, "c_score": p2.shadow_score,
            "a_reachable": shadow.reachable(legacy, manual[0]),
            "b_reachable": shadow.reachable(p1.shadow_range, manual[0]),
            "c_reachable": shadow.reachable(p2.shadow_range, manual[0]),
            "b_ties": ties(_window_score, p1.shadow_range),
            "c_ties": ties(shadow.gated_window_score, p2.shadow_range),
            "candidates": len([w for w in windows
                               if p2.shadow_range and p2.shadow_range.holds(w.asset_frame)]),
            "a_floor_breach": crisp_floor_breach(int(item["src_in"])),
            "c_floor_breach": (crisp_floor_breach(p2.shadow_start)
                               if p2.shadow_start is not None else False),
            "b_fallback": p1.fallback, "c_fallback": p2.fallback,
            "host_shot": host.id,
        })

    args.out.write_text(json.dumps(rows, indent=1))

    def distance(key):
        return [abs(r[key] - r["manual_in"]) / RATE for r in rows if r[key] is not None]

    print(f"pairs: {len(rows)}\n")
    print("F) SEARCH RECALL")
    for label, key in (("A planner   ", "a_reachable"), ("B P1        ", "b_reachable"),
                       ("C P1+P2     ", "c_reachable")):
        print(f"  {label}: {sum(r[key] for r in rows)}/{len(rows)}")

    print("\nG) DISTANCE TO THE EDITOR'S IN POINT, seconds")
    print(f"  {'path':12} {'median':>7} {'mean':>7} {'p25':>6} {'p75':>6} {'p90':>6}")
    for label, key in (("A planner", "a_in"), ("B P1", "b_in"), ("C P1+P2", "c_in")):
        s = spread(distance(key))
        print(f"  {label:12} {s['median']:7.2f} {s['mean']:7.2f} {s['p25']:6.2f} "
              f"{s['p75']:6.2f} {s['p90']:6.2f}")

    print("\nH) HIT RATE")
    for window in (0.5, 1.0):
        line = "  ".join(
            f"{label} {sum(1 for d in distance(key) if d <= window)}/{len(rows)}"
            for label, key in (("A", "a_in"), ("B", "b_in"), ("C", "c_in")))
        print(f"  within {window:.1f}s : {line}")

    print("\nI) C AGAINST B, paired")
    deltas = [(abs(r["c_in"] - r["manual_in"]) - abs(r["b_in"] - r["manual_in"])) / RATE
              for r in rows if r["b_in"] is not None and r["c_in"] is not None]
    better = sum(1 for d in deltas if d < 0)
    worse = sum(1 for d in deltas if d > 0)
    same = sum(1 for d in deltas if d == 0)
    print(f"  closer {better}   further {worse}   unchanged {same}")
    print(f"  median paired delta: {st.median(deltas):+.2f}s "
          f"(negative means C is closer)")
    moved = sum(1 for r in rows if r["b_in"] != r["c_in"])
    print(f"  cuts where the chosen moment moved at all: {moved}/{len(rows)}")

    print("\nK) QUALITY")
    print(f"  cuts holding a window under the floor — A "
          f"{sum(r['a_floor_breach'] for r in rows)}/{len(rows)}, C "
          f"{sum(r['c_floor_breach'] for r in rows)}/{len(rows)}")
    print(f"  fallbacks — B {sum(r['b_fallback'] for r in rows)}, "
          f"C {sum(r['c_fallback'] for r in rows)}")

    print("\nL) TIES AT THE WINNING SCORE")
    for label, key in (("B production score", "b_ties"), ("C gated score     ", "c_ties")):
        values = [r[key] for r in rows]
        print(f"  {label}: median {st.median(values):.0f} of "
              f"{st.median([r['candidates'] for r in rows]):.0f} candidates, "
              f"max {max(values)}, all-tied on {sum(1 for r in rows if r[key] == r['candidates'])}")
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
