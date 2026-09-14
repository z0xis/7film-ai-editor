"""Ask whether a region candidate can be told apart from noise before anyone opens the manual cut.

The region round produced candidates and, without meaning to, a second number: how far a
clip's own top candidate moves when the same rule is read at 2, 4 and 8 second contexts. That
number lined up with three rounds of frozen method-utility evidence — clean where the event
branch is known to work, unstable exactly where it is known not to — but it was read off after
the fact. This asks whether it and a small set of equally cheap candidate-level features can be
turned into a confidence read *before* any manual timing is opened, on a candidate-by-candidate
basis rather than only the one that happens to rank first.

Every feature below is arithmetic over `motion_region_router.py`'s own output — no new frame is
decoded, no model is called, nothing here is fit to the four canonical clips' known outcomes.
The four canonical clips are read only to check whether the resulting ordering already matches
the method-utility evidence three rounds established (C1987 and C2075 worked, C1999 partly,
C2052 did not) — never to choose which feature or threshold to report.

Read-only.
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
EVEN_STEP = 25
FPS = 50
PRIMARY_CONTEXT = "4"
OPENING_GUARD_FRAMES = 2 * FPS

# Reported as a fixed set of sensitivity bands, never narrowed to "the one that works".
DRIFT_BANDS_SECONDS = (1, 2, 4, 8)
CANONICAL_UTILITY = {
    "C1987.MP4": "high", "C2075.MP4": "high", "C1999.MP4": "medium", "C2052.MP4": "low",
}


def even_series(windows) -> list[tuple[int, float]]:
    ordered = sorted(windows, key=lambda w: w.asset_frame)
    return [(w.asset_frame, w.motion) for i, w in enumerate(ordered)
            if i and w.asset_frame - ordered[i - 1].asset_frame == EVEN_STEP
            and w.motion != 0.0]


def pre_post_asymmetry(series: list[tuple[int, float]], centre: int, radius_frames: int) -> dict:
    pre = [v for f, v in series if centre - radius_frames <= f < centre]
    post = [v for f, v in series if centre < f <= centre + radius_frames]
    pre_med = st.median(pre) if pre else None
    post_med = st.median(post) if post else None
    ratio = (post_med / pre_med) if pre_med and post_med else None
    return {"pre_median": pre_med, "post_median": post_med, "post_over_pre": ratio}


def candidate_features(entry: dict, series: list[tuple[int, float]]) -> list[dict]:
    """One row per top-5 candidate at the primary context, with everything cheap attached."""
    ctx = entry["by_context"][PRIMARY_CONTEXT]
    regions = ctx["5"]["regions"]
    total_frames = entry["total_frames"]
    density_per_minute = len(regions) / (total_frames / FPS / 60) if total_frames else None

    # Cross-scale peaks for rank/overlap comparisons.
    peaks_by_context = {c: [r["peak_frame"] for r in entry["by_context"][c]["5"]["regions"]]
                        for c in entry["by_context"]}

    rows = []
    for rank, region in enumerate(regions):
        contrast = region["contrast"]
        next_contrast = regions[rank + 1]["contrast"] if rank + 1 < len(regions) else None
        competition = (contrast / next_contrast) if next_contrast else None
        width_frames = region["width_end"] - region["width_start"]
        retained_share = round(
            (width_frames + 2 * FPS) / total_frames, 4) if total_frames else None

        # Does this exact candidate (by nearest match) survive into the top-5 at 2s and 8s?
        survives = {}
        for c, peaks in peaks_by_context.items():
            nearest = min((abs(region["peak_frame"] - p) for p in peaks), default=None)
            survives[c] = nearest is not None and nearest <= FPS  # within one second

        asymmetry = pre_post_asymmetry(series, region["peak_frame"], 4 * FPS)

        rows.append({
            "rank": rank,
            "peak_frame": region["peak_frame"],
            "contrast": contrast,
            "competition_vs_next": competition,
            "width_seconds": round(width_frames / FPS, 2),
            "retained_share": retained_share,
            "density_per_minute": round(density_per_minute, 2) if density_per_minute else None,
            "near_opening": region["peak_frame"] < OPENING_GUARD_FRAMES,
            "survives_cross_scale": survives,
            "scale_drift_seconds": (
                entry["top1_cross_scale_spread_seconds"] if rank == 0 else None),
            **asymmetry,
        })
    return rows


def veto_sensitivity(rows_by_clip: dict[str, list[dict]], classes: dict[str, str]) -> None:
    print("Q) HIGH-DRIFT VETO SENSITIVITY — rank-0 candidates only")
    rank0 = {clip: rows[0] for clip, rows in rows_by_clip.items()
            if rows and rows[0]["scale_drift_seconds"] is not None}
    for band in DRIFT_BANDS_SECONDS:
        vetoed_events = [c for c in CANONICAL_UTILITY
                         if c in rank0 and rank0[c]["scale_drift_seconds"] > band]
        vetoed_continuous = sum(
            1 for clip, row in rank0.items()
            if classes.get(clip) == "CONTINUOUS_ACTION" and row["scale_drift_seconds"] > band)
        total_continuous = sum(1 for clip in rank0 if classes.get(clip) == "CONTINUOUS_ACTION")
        print(f"  drift > {band}s: vetoes {vetoed_events} of the four canonical clips   "
              f"vetoes {vetoed_continuous}/{total_continuous} continuous rank-0 candidates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    regions = json.loads(args.regions.read_text())
    database = Database(database_path())
    assets = {a.name: a for a in project_assets(database, PROJECT_ID)}
    by_asset = asset_windows(database, PROJECT_ID)

    all_rows: dict[str, list[dict]] = {}
    for clip, entry in regions.items():
        if entry.get("abstain"):
            continue
        asset = assets.get(clip)
        if asset is None:
            continue
        series = even_series(by_asset.get(asset.id, ()))
        all_rows[clip] = candidate_features(entry, series)

    classes = {clip: e["class"] for clip, e in regions.items()}

    print("D) SCALE-DRIFT DISTRIBUTION, rank-0 candidates")
    for cls in ("ACTION_EVENT", "CONTINUOUS_ACTION", "TRANSITIONAL", "STABLE_COMPOSITION"):
        vals = [rows[0]["scale_drift_seconds"] for clip, rows in all_rows.items()
                if classes.get(clip) == cls and rows and rows[0]["scale_drift_seconds"] is not None]
        if vals:
            print(f"  {cls:20} n={len(vals):3d}  median {st.median(vals):6.2f}s  "
                  f"max {max(vals):6.2f}s   >2s: {sum(1 for v in vals if v > 2)}/{len(vals)}")

    veto_sensitivity(all_rows, classes)

    print("\nR) LOW DRIFT ALONE AS A POSITIVE SIGNAL")
    zero_drift_continuous = sum(
        1 for clip, rows in all_rows.items()
        if classes.get(clip) == "CONTINUOUS_ACTION" and rows
        and rows[0]["scale_drift_seconds"] == 0.0)
    total_continuous = sum(1 for clip in all_rows if classes.get(clip) == "CONTINUOUS_ACTION")
    print(f"  continuous clips with zero rank-0 drift: {zero_drift_continuous}/{total_continuous} "
          f"— zero drift is common, not event-specific; it is necessary, not sufficient")

    print("\nG) RETAINED-FRACTION DISTRIBUTION, rank-0 candidate, ±1s")
    for cls in ("ACTION_EVENT", "CONTINUOUS_ACTION"):
        vals = [rows[0]["retained_share"] for clip, rows in all_rows.items()
                if classes.get(clip) == cls and rows]
        print(f"  {cls:20} median {st.median(vals) * 100:.1f}%")

    print("\nO) C1999 — DOES ONE CANDIDATE STAND ABOVE THE OTHERS?")
    for row in all_rows.get("C1999.MP4", []):
        print(f"  rank{row['rank']} frame {row['peak_frame']:5d}  contrast {row['contrast']:.2f}  "
              f"competition_vs_next {row['competition_vs_next']}  "
              f"post/pre {row['post_over_pre']}")

    print("\nCANDIDATE-LEVEL FEATURES, four canonical clips, primary context, top5")
    for clip, utility in CANONICAL_UTILITY.items():
        print(f"\n  {clip}  (frozen method utility: {utility})")
        for row in all_rows.get(clip, []):
            print(f"    rank{row['rank']} frame {row['peak_frame']:5d}  "
                  f"contrast {row['contrast']:5.2f}  width {row['width_seconds']:.2f}s  "
                  f"retained {row['retained_share'] * 100:5.1f}%  "
                  f"post/pre {row['post_over_pre']}  "
                  f"near_opening {row['near_opening']}  "
                  f"drift {row['scale_drift_seconds']}")

    Path(args.out).write_text(json.dumps(all_rows, indent=1))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
