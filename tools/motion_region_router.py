"""Bring the clip-level "calm baseline, one loud burst" signature down to a region.

The router round found that motion's *shape* — not its level — separates the four ACTION_EVENT
clips from the rest: a burst standing out of a calmer surround, not sustained high motion. That
was a clip-wide summary. This asks the question a candidate generator actually needs answered:
where inside the clip is that burst, and how much of the clip does keeping it retain?

Nothing new is measured. Motion is already stored per half-second window from the production
analyser; this reads it back and asks, at each point, how it compares to its own local
neighbourhood rather than to the whole clip — because a wide clip can have more than one motion
regime, and a single clip-wide median would blur them together the way DINO's single scene
label blurred cutting from feeding from a toast two rounds ago.

Three neighbourhood widths are carried through everywhere as a fixed set, never narrowed to
"the one that works": two, four and eight seconds either side of the point being scored. None is
picked as primary in the code; the report below picks four seconds to lead with because it sits
in the middle, not because it scores best.

Manual timing is read only by the small evaluation script alongside this one, never here.

Read-only. No frame is decoded and no model is called — every number below is arithmetic over
motion already sitting in the database.
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
from sevenfilm.services.media import project_assets
from sevenfilm.services.windows import asset_windows

PROJECT_ID = "df2a4a62-e821-40f7-86fc-b6a9259e9ee9"
EVEN_STEP = 25       # half a second, the grid the stored motion already sits on
FPS = 50
CONTEXTS_SECONDS = (2, 4, 8)          # the fixed set, carried through everywhere
PRIMARY_CONTEXT = 4                    # the middle one, reported first — not the best-scoring one
BURST_MULTIPLE = 1.5                   # frozen from the clip-level round, not re-picked here
MIN_PEAK_SEPARATION_SECONDS = 2        # half the primary context, so top-K aren't one burst
TOP_K = (1, 3, 5)
NEIGHBOURHOOD_EXPANSIONS = (0.5, 1.0, 2.0)
MERGE_GAPS = (0.25, 0.5, 1.0)
OPENING_GUARD_SECONDS = 2              # known camera-settling artefact, excluded as a diagnostic
EPSILON = 1e-6


def even_series(windows) -> list[tuple[int, float]]:
    ordered = sorted(windows, key=lambda w: w.asset_frame)
    return [(w.asset_frame, w.motion) for i, w in enumerate(ordered)
            if i and w.asset_frame - ordered[i - 1].asset_frame == EVEN_STEP
            and w.motion != 0.0]


def local_baseline(series: list[tuple[int, float]], index: int, context_frames: int) -> float | None:
    """The median motion around a point, excluding the point's own reading."""
    frame = series[index][0]
    around = [v for f, v in series
              if 0 < abs(f - frame) <= context_frames]
    return st.median(around) if around else None


def burst_curve(series: list[tuple[int, float]], context_seconds: int) -> list[dict]:
    context_frames = context_seconds * FPS
    out = []
    for index, (frame, value) in enumerate(series):
        baseline = local_baseline(series, index, context_frames)
        contrast = value / (baseline + EPSILON) if baseline is not None else None
        out.append({"frame": frame, "motion": value, "baseline": baseline, "contrast": contrast})
    return out


def top_candidates(curve: list[dict], k: int, min_gap_frames: int) -> list[dict]:
    ranked = sorted((p for p in curve if p["contrast"] is not None),
                    key=lambda p: -p["contrast"])
    chosen: list[dict] = []
    for point in ranked:
        if all(abs(point["frame"] - c["frame"]) >= min_gap_frames for c in chosen):
            chosen.append(point)
        if len(chosen) >= k:
            break
    return chosen


def burst_width(series: list[tuple[int, float]], centre_frame: int, baseline: float) -> tuple[int, int]:
    """How far the burst extends either side of its peak before falling under the multiple."""
    threshold = BURST_MULTIPLE * baseline
    by_frame = dict(series)
    frames = sorted(by_frame)
    if centre_frame not in by_frame:
        return centre_frame, centre_frame
    index = frames.index(centre_frame)
    left = index
    while left > 0 and by_frame[frames[left - 1]] > threshold:
        left -= 1
    right = index
    while right < len(frames) - 1 and by_frame[frames[right + 1]] > threshold:
        right += 1
    return frames[left], frames[right]


def merge(intervals: list[tuple[int, int]], gap_frames: int) -> list[tuple[int, int]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        if start - merged[-1][1] <= gap_frames:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def analyse_clip(series: list[tuple[int, float]], total_frames: int) -> dict:
    if len(series) < 8:
        return {"abstain": True, "reason": "too few measured windows"}

    by_context: dict[str, dict] = {}
    for context in CONTEXTS_SECONDS:
        curve = burst_curve(series, context)
        candidates = {}
        for k in TOP_K:
            picks = top_candidates(curve, k, MIN_PEAK_SEPARATION_SECONDS * FPS)
            regions = []
            for pick in picks:
                left, right = burst_width(series, pick["frame"], pick["baseline"])
                regions.append({
                    "peak_frame": pick["frame"], "contrast": pick["contrast"],
                    "baseline": pick["baseline"], "width_start": left, "width_end": right,
                })
            by_expansion = {}
            for expansion in NEIGHBOURHOOD_EXPANSIONS:
                pad = int(expansion * FPS)
                windows = merge([(r["width_start"] - pad, r["width_end"] + pad)
                                 for r in regions], gap_frames=0)
                retained = sum(b - a for a, b in windows)
                by_expansion[str(expansion)] = {
                    "windows": windows,
                    "retained_share": round(retained / total_frames, 4),
                }
            candidates[str(k)] = {"regions": regions, "by_expansion": by_expansion}
        by_context[str(context)] = candidates

    # Opening-excluded diagnostic at the primary context only, reusing the same top-3 pick.
    guard_frames = OPENING_GUARD_SECONDS * FPS
    guarded_series = [(f, v) for f, v in series if f >= guard_frames]
    guarded_curve = burst_curve(guarded_series, PRIMARY_CONTEXT) if guarded_series else []
    guarded_top3 = top_candidates(guarded_curve, 3, MIN_PEAK_SEPARATION_SECONDS * FPS)

    # Merge-gap sensitivity, primary context, top-5, ±1s expansion.
    primary_top5 = by_context[str(PRIMARY_CONTEXT)]["5"]["regions"]
    merge_sensitivity = {}
    for gap in MERGE_GAPS:
        windows = merge([(r["width_start"] - FPS, r["width_end"] + FPS) for r in primary_top5],
                        gap_frames=int(gap * FPS))
        merge_sensitivity[str(gap)] = {
            "region_count": len(windows),
            "retained_share": round(sum(b - a for a, b in windows) / total_frames, 4),
        }

    # Cross-scale stability: does the top-1 peak at each context land near the others?
    top1_frames = {ctx: by_context[str(ctx)]["1"]["regions"][0]["peak_frame"]
                  for ctx in CONTEXTS_SECONDS if by_context[str(ctx)]["1"]["regions"]}
    spread = (max(top1_frames.values()) - min(top1_frames.values())) if len(top1_frames) > 1 else 0

    return {
        "abstain": False,
        "total_frames": total_frames,
        "by_context": by_context,
        "guarded_top3_frames": [p["frame"] for p in guarded_top3],
        "merge_sensitivity": merge_sensitivity,
        "top1_frames_by_context": top1_frames,
        "top1_cross_scale_spread_seconds": round(spread / FPS, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", type=Path, required=True,
                        help="a JSON list of rows with a 'clip' key naming every clip to run")
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    database = Database(database_path())
    assets = {a.name: a for a in project_assets(database, PROJECT_ID)}
    by_asset = asset_windows(database, PROJECT_ID)
    classes = json.loads(args.classes.read_text())
    names = sorted({row["clip"] for row in json.loads(args.compare.read_text())})

    results = {}
    for clip in names:
        asset = assets.get(clip)
        if asset is None:
            continue
        total_frames = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
        series = even_series(by_asset.get(asset.id, ()))
        result = analyse_clip(series, total_frames)
        result["class"] = classes.get(clip, "CONTINUOUS_ACTION")
        results[clip] = result

    args.out.write_text(json.dumps(results, indent=1))
    print(f"written {args.out}  {len(results)} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
