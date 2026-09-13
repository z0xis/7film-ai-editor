"""Check the motion finding the ready region was going to be built on.

P3.5 reported that the editor cuts into the calm part of a clip: 79.1% clip-grouped
discrimination, dz -1.05 against within-clip controls. This re-tests that on a grid where every
reading is measured the same way, because the strip it was measured on was not.

Motion is the mean absolute difference between a frame and the frame sampled before it, so it
scales with the gap between the two samples. In the P3.5 strip that gap was not constant: the
readings around the editor's cut sat 0.25 s apart in a dense run, and the random controls were
single isolated frames whose predecessor was wherever the previous strip ended. Controls were
therefore measured across a wider gap than the editor's own frames, and a wider gap reads as
more motion on the same material.

Two things are measured here. First, the size of that confound in the P3.5 strip file itself.
Second, the same question asked again on the stored window grid, where every reading is a
half-second step and the gap is the same for both sides.

Usage: tools/motion_audit.py <project-id> --compare shadow_compare7.json --strips strips.json
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

# The stored windows are half a second apart, and this is that gap in frames at this shoot's
# rate. A pair of windows any other distance apart is a shot boundary, not a step, and its
# motion reading is not comparable with the rest.
EVEN_STEP = 25
# The strip in P3.5 was sampled in quarter-second steps; anything wider is a reading that
# crossed from one strip to the next.
STRIP_STEP = 12


def sampling_confound(strips) -> None:
    """How much of the P3.5 result is the gap between samples rather than the picture."""
    editor, controls = [], []
    for row in strips:
        frames = sorted({
            reading["f"] for key in ("in_strip", "out_strip", "e1_strip", "controls")
            for reading in row[key] if reading
        })
        place = {frame: index for index, frame in enumerate(frames)}

        def gap_before(reading, frames=frames, place=place):
            index = place[reading["f"]]
            return frames[index] - frames[index - 1] if index else None

        middle = row["in_strip"][len(row["in_strip"]) // 2]
        if middle:
            editor.append((gap_before(middle), middle["motion"]))
        for control in row["controls"]:
            if control:
                controls.append((gap_before(control), control["motion"]))

    def median_gap(pairs):
        return st.median([gap for gap, _ in pairs if gap])

    print("A) THE P3.5 STRIP — was the comparison measured the same way on both sides?")
    print(f"  editor's own reading : gap before it {median_gap(editor):5.0f} frames   "
          f"motion {st.median([m for _, m in editor]):6.2f}")
    print(f"  random control      : gap before it {median_gap(controls):5.0f} frames   "
          f"motion {st.median([m for _, m in controls]):6.2f}")
    wide = [m for gap, m in controls if gap and gap > STRIP_STEP]
    tight = [m for gap, m in controls if gap and gap <= STRIP_STEP]
    print(f"  the same controls, split by their own gap: "
          f"wide n={len(wide)} motion {st.median(wide):.1f}   "
          f"tight n={len(tight)} motion {st.median(tight):.1f}")
    print("  Same material, same measure. The gap alone moves the reading by that much.")


def even_grid(database: Database, project_id: str, rows) -> None:
    """The same question on the stored windows, where every reading is one half-second step."""
    from scipy.stats import wilcoxon

    assets = {asset.name: asset for asset in project_assets(database, project_id)}
    by_asset = asset_windows(database, project_id)
    pairs, percentiles = [], []
    for row in rows:
        asset = assets.get(row["clip"])
        if asset is None:
            continue
        windows = sorted(by_asset.get(asset.id, ()), key=lambda w: w.asset_frame)
        even = [w for index, w in enumerate(windows)
                if index and w.asset_frame - windows[index - 1].asset_frame == EVEN_STEP]
        if len(even) < 4:
            continue
        nearest = min(even, key=lambda w: abs(w.asset_frame - row["manual_in"]))
        if abs(nearest.asset_frame - row["manual_in"]) > EVEN_STEP:
            continue
        others = [w.motion for w in even if w is not nearest]
        pairs.append((nearest.motion, st.median(others)))
        percentiles.append(sum(1 for m in others if m < nearest.motion) / len(others))

    editor = [a for a, _ in pairs]
    clip = [b for _, b in pairs]
    deltas = [a - b for a, b in pairs]
    result = wilcoxon(editor, clip)
    print("\nB) THE SAME QUESTION ON AN EVEN GRID")
    print(f"  n={len(pairs)} clips  ·  editor's window {st.median(editor):.1f}  "
          f"his clip {st.median(clip):.1f}")
    print(f"  Wilcoxon p={result.pvalue:.3f}  dz={st.mean(deltas) / st.stdev(deltas):+.2f}  "
          f"calmer than his clip on {sum(1 for d in deltas if d < 0)}/{len(pairs)}")
    print(f"  motion percentile of his own in-point: median "
          f"{st.median(percentiles):.2f}  (0.50 is chance)")

    out_pairs = []
    for row in rows:
        asset = assets.get(row["clip"])
        if asset is None:
            continue
        windows = sorted(by_asset.get(asset.id, ()), key=lambda w: w.asset_frame)
        even = [w for index, w in enumerate(windows)
                if index and w.asset_frame - windows[index - 1].asset_frame == EVEN_STEP]
        out = row["manual_in"] + row["frames"]
        before = [w.motion for w in even if out - 2 * EVEN_STEP <= w.asset_frame < out]
        after = [w.motion for w in even if out <= w.asset_frame < out + 2 * EVEN_STEP]
        if before and after:
            out_pairs.append((st.median(before), st.median(after)))
    before = [a for a, _ in out_pairs]
    after = [b for _, b in out_pairs]
    deltas = [b - a for a, b in out_pairs]
    result = wilcoxon(before, after)
    print(f"\nC) AND AT THE OUT POINT — n={len(out_pairs)}  before {st.median(before):.1f}  "
          f"after {st.median(after):.1f}")
    print(f"  Wilcoxon p={result.pvalue:.3f}  dz={st.mean(deltas) / st.stdev(deltas):+.2f}  "
          f"rises on {sum(1 for d in deltas if d > 0)}/{len(out_pairs)}")


def quality_only(database: Database, project_id: str, rows) -> None:
    """What the quality gate on its own can and cannot do as a region finder."""
    from sevenfilm.services.planner import UNUSABLE_SHARPNESS_SHARE

    assets = {asset.name: asset for asset in project_assets(database, project_id)}
    by_asset = asset_windows(database, project_id)
    every = sorted(w.sharpness for windows in by_asset.values() for w in windows)
    bar = every[len(every) // 2] if every else 0.0
    inside, total, shares = 0, 0, []
    for row in rows:
        asset = assets.get(row["clip"])
        if asset is None:
            continue
        windows = by_asset.get(asset.id, ())
        if not windows:
            continue
        total += 1
        passing = [w for w in windows if w.sharpness / bar >= UNUSABLE_SHARPNESS_SHARE]
        shares.append(len(passing) / len(windows))
        inside += any(w.asset_frame <= row["manual_in"] < w.asset_frame + EVEN_STEP
                      for w in passing)
    print(f"\nD) THE QUALITY GATE ALONE — his in-point passes on {inside}/{total}, "
          f"and {st.median(shares):.0%} of an average clip passes with it")
    print("  It keeps unusable picture out. It does not narrow a clip down to anywhere.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--compare", type=Path, required=True)
    parser.add_argument("--strips", type=Path, required=True)
    args = parser.parse_args()

    rows = json.loads(args.compare.read_text())
    sampling_confound(json.loads(args.strips.read_text()))
    database = Database(database_path())
    even_grid(database, args.project_id, rows)
    quality_only(database, args.project_id, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
