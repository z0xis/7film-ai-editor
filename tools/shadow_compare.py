"""Compare moment searches against the editor's own choice, on the clips both used.

  A  what the planner does  — shot search, production score
  B  P1                     — clip search, production score
  C  P1 + P2                — clip search, sharpness gates rather than ranks
  D  P1 + P2.5              — C with the charge for other people's faces taken off
  E1 E2 E3                  — D with a positive content term in the base

Reads the project and the stored measurements. Writes a JSON report. Changes nothing: the
planner's answer is read from the plan it produced, and no shadow path is wired into it.

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
from sevenfilm.services.planner import (
    FRAME_EDGE_PENALTY,
    UNUSABLE_SHARPNESS_SHARE,
    _window_score,
)
from sevenfilm.services.windows import asset_windows, project_windows

RATE = 50


def build_paths(face_bar, ratio_bar):
    """The searches being compared, in the order they were added."""
    return (
        ("A planner", "a_in", _window_score),
        ("B P1", "b_in", _window_score),
        ("C P1+P2", "c_in", shadow.gated_window_score),
        ("D P1+P2.5", "d_in", shadow.unpenalised_window_score),
        ("E1 faces", "e_in", shadow.content_scorer(
            face_bar, ratio_bar, use_count=True, use_ratio=False)),
        ("E2 face size", "f_in", shadow.content_scorer(
            face_bar, ratio_bar, use_count=False, use_ratio=True)),
        ("E3 both", "g_in", shadow.content_scorer(
            face_bar, ratio_bar, use_count=True, use_ratio=True)),
    )


def sharpness_bar(windows_by_shot) -> float:
    values = sorted(w.sharpness for rows in windows_by_shot.values() for w in rows)
    return values[len(values) // 2] if values else 0.0


def spread(values):
    ordered = sorted(values)

    def pick(share):
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]

    return {"median": st.median(ordered), "mean": st.mean(ordered),
            "p25": pick(0.25), "p75": pick(0.75), "p90": pick(0.90)}


def covering(windows, start, frames):
    rows = [w for w in windows if start <= w.asset_frame < start + frames]
    if rows:
        return rows
    earlier = [w for w in windows if w.asset_frame <= start]
    return earlier[-1:] if earlier else []


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
    every_window = [w for rows in windows_by_asset.values() for w in rows]
    face_bar, ratio_bar = shadow.content_bars(every_window)
    paths = build_paths(face_bar, ratio_bar)
    print(f"bars - sharpness {bar:.2f}, face count {face_bar:.2f}, "
          f"largest face {ratio_bar:.5f}\n")
    reference = json.loads(args.reference.read_text())
    plan = json.loads(args.plan.read_text())

    rows = []
    for item in plan:
        clip, manual = item["clip"], reference.get(item["clip"])
        asset = assets.get(clip)
        if manual is None or asset is None:
            continue
        shots = shots_by_asset.get(asset.id, ())
        host = next((s for s in shots
                     if s.source_range.start_frame <= item["src_in"] < s.source_range.end_frame),
                    None)
        if host is None:
            continue
        frames = int(item["frames"])
        total = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
        windows = windows_by_asset.get(asset.id, ())

        found = {}
        for label, key, scorer in paths[1:]:
            found[key] = shadow.evaluate(
                host, frames, asset_duration_frames=total, windows=windows,
                sharpness_bar=bar, window_score=scorer,
                legacy_start=int(item["src_in"]))

        def shot_index(frame, shots=shots):
            for index, shot in enumerate(shots):
                if shot.source_range.start_frame <= frame < shot.source_range.end_frame:
                    return index
            return None

        def ties(scorer, span, windows=windows, frames=frames):
            if not span:
                return 0, 0
            starts = [span.first_frame] + [
                w.asset_frame for w in windows
                if span.first_frame < w.asset_frame <= span.last_frame]
            values = []
            for start in starts:
                rows_in = covering(windows, start, frames)
                if rows_in:
                    values.append(round(min(
                        scorer(w.as_shot_window(), bar, w.category) for w in rows_in), 9))
            if not values:
                return 0, 0
            return sum(1 for v in values if v == max(values)), len(values)

        def held(key, start, windows=windows, frames=frames):
            rows_in = covering(windows, start, frames)
            if not rows_in:
                return None
            return {
                "bystanders": st.median([w.bystanders for w in rows_in]),
                "faces": st.median([w.face_count for w in rows_in]),
                "edge": st.median([w.face_edge for w in rows_in]),
                "sharpness": st.median([w.sharpness for w in rows_in]),
                "under_floor": any(w.sharpness / bar < UNUSABLE_SHARPNESS_SHARE
                                   for w in rows_in),
            }

        row = {
            "clip": clip, "manual_in": manual[0], "frames": frames,
            "category": host.category,
            "a_in": int(item["src_in"]),
            "a_reachable": shadow.reachable(
                shadow.legacy_search_range(host, frames), manual[0]),
        }
        for label, key, _scorer in paths[1:]:
            result = found[key]
            row[key] = result.shadow_start
            row[f"{key[0]}_score"] = result.shadow_score
            row[f"{key[0]}_reachable"] = shadow.reachable(result.shadow_range, manual[0])
            row[f"{key[0]}_fallback"] = result.fallback
            row[f"{key[0]}_first"] = bool(
                result.shadow_range
                and result.shadow_start == result.shadow_range.first_frame)
        for label, key, scorer in paths[1:]:
            top, count = ties(scorer, found[key].shadow_range)
            row[f"{key[0]}_ties"], row[f"{key[0]}_candidates"] = top, count
        for _label, key, _scorer in paths:
            row[f"{key[0]}_held"] = held(key, row[key]) if row[key] is not None else None
            row[f"{key[0]}_shot"] = shot_index(row[key]) if row[key] is not None else None
        row["manual_held"] = held("manual_in", manual[0])
        row["manual_shot"] = shot_index(manual[0])
        rows.append(row)

    args.out.write_text(json.dumps(rows, indent=1))

    def distance(key):
        return [abs(r[key] - r["manual_in"]) / RATE for r in rows if r[key] is not None]

    print(f"pairs: {len(rows)}\n")
    print("F) SEARCH RECALL")
    for label, key, _ in paths:
        print(f"  {label:12}: {sum(r[f'{key[0]}_reachable'] for r in rows)}/{len(rows)}")

    print("\nG) DISTANCE TO THE EDITOR'S IN POINT, seconds")
    print(f"  {'path':12} {'median':>7} {'mean':>7} {'p25':>6} {'p75':>6} {'p90':>6}")
    for label, key, _ in paths:
        s = spread(distance(key))
        print(f"  {label:12} {s['median']:7.2f} {s['mean']:7.2f} {s['p25']:6.2f} "
              f"{s['p75']:6.2f} {s['p90']:6.2f}")

    print("\nH) HIT RATE")
    for window in (0.5, 1.0, 2.0):
        cells = "  ".join(
            f"{label.split()[0]} {sum(1 for d in distance(key) if d <= window):2d}"
            for label, key, _ in paths)
        print(f"  within {window:.1f}s : {cells}   of {len(rows)}")

    print("\nK) BACKGROUND FACES IN THE CHOSEN WINDOW")
    print(f"  {'path':12} {'median':>7} {'mean':>7}    0   1   2  3+")
    for label, key in (("editor", "manual"), *[(l, k[0]) for l, k, _ in paths]):
        values = [r[f"{key}_held"]["bystanders"] for r in rows
                  if r.get(f"{key}_held")]
        buckets = [sum(1 for v in values if v == 0), sum(1 for v in values if 0 < v <= 1),
                   sum(1 for v in values if 1 < v <= 2), sum(1 for v in values if v > 2)]
        print(f"  {label:12} {st.median(values):7.2f} {st.mean(values):7.2f} "
              + "".join(f"{b:4d}" for b in buckets))

    print("\nCOARSE REACH - within N seconds of the editor's in point")
    for window in (2.0, 3.0, 5.0):
        cells = "  ".join(
            f"{label.split()[0]:2} {sum(1 for d in distance(key) if d <= window):2d}"
            for label, key, _ in paths)
        print(f"  within {window:.0f}s : {cells}   of {len(rows)}")

    print("\nFIRST-CANDIDATE COLLAPSE")
    for label, key, _ in paths[1:]:
        first = sum(1 for r in rows if r.get(f"{key[0]}_first"))
        print(f"  {label:12} chose the earliest candidate on {first}/{len(rows)}")

    print("\nI) EACH PATH AGAINST D, paired")
    for label, key, _ in paths:
        if key == "d_in":
            continue
        deltas = [(abs(r[key] - r["manual_in"]) - abs(r["d_in"] - r["manual_in"])) / RATE
                  for r in rows if r[key] is not None and r["d_in"] is not None]
        print(f"  {label:12} closer {sum(1 for d in deltas if d < 0):2d}  "
              f"further {sum(1 for d in deltas if d > 0):2d}  "
              f"same {sum(1 for d in deltas if d == 0):2d}   "
              f"median {st.median(deltas):+.2f}s  mean {st.mean(deltas):+.2f}s")

    print("\nM) TIES AT THE WINNING SCORE")
    for label, key, _ in paths[1:]:
        top = [r[f"{key[0]}_ties"] for r in rows]
        cand = [r[f"{key[0]}_candidates"] for r in rows]
        print(f"  {label:12} median {st.median(top):.0f} of {st.median(cand):.0f} candidates, "
              f"max {max(top)}, everything tied on "
              f"{sum(1 for r in rows if r[f'{key[0]}_ties'] == r[f'{key[0]}_candidates'])}")

    print("\nN) WHAT DECIDES IN D — frame-edge charge on the chosen window")
    edges = [r["d_held"]["edge"] for r in rows if r.get("d_held")]
    print(f"  median edge {st.median(edges):.3f}, non-zero on "
          f"{sum(1 for e in edges if e > 0)}/{len(edges)}  "
          f"(charge weight {FRAME_EDGE_PENALTY})")

    print("\nQUALITY")
    for label, key, _ in paths:
        breaches = sum(1 for r in rows if r.get(f"{key[0]}_held")
                       and r[f"{key[0]}_held"]["under_floor"])
        print(f"  {label:12} cuts holding a window under the floor: {breaches}/{len(rows)}")

    print("\nL) CATEGORY BREAKDOWN, C to D, median distance in seconds")
    by_category: dict[str, list] = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)
    for category, group in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        c = st.median([abs(r["c_in"] - r["manual_in"]) / RATE for r in group])
        d = st.median([abs(r["d_in"] - r["manual_in"]) / RATE for r in group])
        note = "  LOW SAMPLE" if len(group) < 6 else ""
        print(f"  {category:12} n={len(group):2d}  C {c:6.2f}  D {d:6.2f}  "
              f"{d - c:+6.2f}{note}")

    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
