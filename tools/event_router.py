"""Ask whether a clip's own behaviour, not its human label, says which pipeline fits it.

The DINO round left one blocker standing: a hybrid architecture needs something to decide,
per clip, which branch to take — and the only thing that has ever said "this is an event" was
a person watching the footage. This asks whether cheap signals already sitting in the
database can stand in for that person, using no new model call and no manual timing.

Two families of candidate feature, both read off measurements this project already has:

  DINO SHAPE     how concentrated the clip's own change-point curve is — a single dominant
                 peak against a flat background, or many similar-sized changes throughout
  MOTION SHAPE   the same question asked of the motion feature already stored per window:
                 a calm clip with one loud burst, or a clip that moves throughout

Class labels (ACTION_EVENT, CONTINUOUS_ACTION, TRANSITIONAL, STABLE_COMPOSITION) are read only
to grade the result at the end — never to build a feature, and never to fit a threshold. Every
threshold used below is the continuous-action group's own median, which is a property of the
material being measured, not a number chosen after seeing the answer.

No classifier is trained. No weight is fit. The one combination rule tried is a fixed AND of
two features against their own frozen thresholds, reported for what it is: a diagnostic, not a
production decision.

Read-only. Reuses DINOv2 output already computed this round and motion already in the database.
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
BURST_MULTIPLE = 1.5  # a window counts toward "high motion" above this multiple of the clip's own median — fixed, not tuned per clip


def motion_features(windows) -> dict:
    even = [w for i, w in enumerate(windows)
            if i and w.asset_frame - windows[i - 1].asset_frame == EVEN_STEP]
    values = [w.motion for w in even if w.motion != 0.0]
    if not values:
        return {}
    median = st.median(values)
    return {
        "median_motion": median,
        "motion_variance": st.pvariance(values) if len(values) > 1 else 0.0,
        "motion_burst_ratio": (max(values) / median) if median else None,
        "motion_high_fraction": (
            sum(1 for v in values if v > BURST_MULTIPLE * median) / len(values)
            if median else None),
    }


def dino_shape_features(entry: dict) -> dict:
    top = sorted(entry["top_points"], key=lambda p: -p["distance"])
    baseline = entry["baseline_median"] or 1e-9
    top1 = top[0]["distance"] if top else 0.0
    top2 = top[1]["distance"] if len(top) > 1 else top1
    top3 = top[:3]
    return {
        "top1_ratio": top1 / baseline,
        "top3_mean_ratio": (st.mean(p["distance"] for p in top3) / baseline) if top3 else 0.0,
        "peak_isolation": (top1 / top2) if top2 else None,
        "spike_density_2.0": entry["spike_count_by_multiple"]["2.0"] / entry["curve_len"],
    }


def auc(a_values: list[float], b_values: list[float]) -> float:
    wins = ties = total = 0
    for a in a_values:
        for b in b_values:
            total += 1
            if a > b:
                wins += 1
            elif a == b:
                ties += 1
    return (wins + ties / 2) / total if total else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dino", type=Path, required=True, help="dino_candidates.py output")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    database = Database(database_path())
    assets = {a.name: a for a in project_assets(database, PROJECT_ID)}
    by_asset = asset_windows(database, PROJECT_ID)
    dino = json.loads(args.dino.read_text())

    rows: dict[str, dict] = {}
    for clip, entry in dino.items():
        asset = assets.get(clip)
        if asset is None:
            continue
        features = {
            **dino_shape_features(entry),
            **motion_features(sorted(by_asset.get(asset.id, ()), key=lambda w: w.asset_frame)),
        }
        rows[clip] = {"class": entry["class"], "total_frames": entry["total_frames"], **features}

    # Single-feature discrimination: ACTION_EVENT against CONTINUOUS_ACTION, clip-level.
    events = {k: v for k, v in rows.items() if v["class"] == "ACTION_EVENT"}
    continuous = {k: v for k, v in rows.items() if v["class"] == "CONTINUOUS_ACTION"}
    print(f"B) dataset: {len(events)} ACTION_EVENT, {len(continuous)} CONTINUOUS_ACTION, "
          f"{sum(1 for v in rows.values() if v['class'] == 'TRANSITIONAL')} TRANSITIONAL, "
          f"{sum(1 for v in rows.values() if v['class'] == 'STABLE_COMPOSITION')} STABLE\n")

    print("K) SINGLE-FEATURE DISCRIMINATION — event vs continuous, clip AUC")
    feature_names = ["top1_ratio", "top3_mean_ratio", "peak_isolation", "spike_density_2.0",
                     "motion_burst_ratio", "motion_high_fraction", "motion_variance",
                     "median_motion"]
    for name in feature_names:
        ev = [v[name] for v in events.values() if v.get(name) is not None]
        co = [v[name] for v in continuous.values() if v.get(name) is not None]
        if not ev or not co:
            continue
        print(f"  {name:22} AUC {auc(ev, co):.3f}   event median {st.median(ev):7.3f}   "
              f"continuous median {st.median(co):7.3f}")

    print("\nO-R) EACH EVENT CLIP, PERCENTILE WITHIN THE CONTINUOUS DISTRIBUTION")
    for name in ("motion_burst_ratio", "motion_high_fraction", "motion_variance",
                "median_motion"):
        co_sorted = sorted(v[name] for v in continuous.values() if v.get(name) is not None)
        print(f"  {name}:")
        for clip, v in events.items():
            value = v.get(name)
            if value is None:
                continue
            pct = sum(1 for x in co_sorted if x < value) / len(co_sorted)
            print(f"    {clip:12} {value:8.3f}   percentile {pct * 100:5.1f}%")

    # A fixed, pre-declared rule: both motion features above the continuous group's own median.
    co_burst = st.median(v["motion_burst_ratio"] for v in continuous.values()
                         if v.get("motion_burst_ratio") is not None)
    co_high = st.median(v["motion_high_fraction"] for v in continuous.values()
                        if v.get("motion_high_fraction") is not None)
    print(f"\nSIMPLE FIXED RULE: burst_ratio > {co_burst:.3f} AND high_fraction > {co_high:.3f}")
    by_class: dict[str, list[int]] = {}
    for clip, v in rows.items():
        b, h = v.get("motion_burst_ratio"), v.get("motion_high_fraction")
        flagged = b is not None and h is not None and b > co_burst and h > co_high
        by_class.setdefault(v["class"], [0, 0])
        by_class[v["class"]][1] += 1
        by_class[v["class"]][0] += int(flagged)
    for cls, (hit, total) in by_class.items():
        print(f"  {cls:20} flagged DISCRETE_VISUAL_EVENT {hit}/{total}")

    args.out.write_text(json.dumps(rows, indent=1))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
