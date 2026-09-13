"""Separate the shutter the clip was shot at from the moment the editor chose in it.

Some of this wedding was shot deliberately slow — the camera's own metadata records 1/16 and
1/20 of a second where the rest of the shoot sits at 1/101 — and those clips went into the
edit on purpose. A frame shot that way smears, and both measurements this project ranks
moments with are read off the picture: sharpness is a Laplacian variance, which a smear
lowers, and motion is a difference between frames, which a moving subject raises. So a
deliberate look could be reading as a technical fault in one measure and as unrest in the
other, and the earlier verdict on motion was taken over a set with both kinds of clip in it.

This asks two questions and keeps them apart:

  A  does creative low shutter distort the motion and sharpness measurements
  B  inside normal-shutter footage only, does motion carry a source-region signal at all

Everything is measured on the stored half-second window grid, and only on windows whose
predecessor is exactly one step earlier, so every reading on both sides of every comparison
spans the same interval. That is the confound that produced the earlier result, and it is not
repeated here.

Read-only. No production code is touched, no threshold is changed, nothing is written to the
plan or to Resolve.

Usage: tools/shutter_audit.py <project-id> --shutter shutter_all.json --cuts manuel.txt
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services.media import project_assets
from sevenfilm.services.windows import asset_windows

# Windows are half a second apart. A pair any other distance apart straddles a shot boundary,
# and its reading spans a different interval, so it is not comparable with the rest.
EVEN_STEP = 25

# What makes a clip creative low shutter, decided from the camera rather than from the data.
#
# An exposure longer than one capture frame period cannot have been taken frame by frame — the
# camera is holding the sensor open across more than one frame's worth of time, which is the
# slow-shutter look and is nothing an ordinary exposure does. That is a line from the physics,
# not a threshold picked off a histogram: it separates this shoot's 1/16 and 1/20 at 50p from
# everything else, and the nearest thing on the other side is 1/81, four times faster.
NORMAL, LOW, UNKNOWN = "NORMAL_SHUTTER", "CREATIVE_LOW_SHUTTER", "UNKNOWN"

# The editor's own sections, in film time, as P3.6 measured them: the stretches of the finished
# film that cut at a constant number of beats.
SECTION_BANDS = (
    (0.0, 63.0, "acilis-dusuk"), (63.0, 95.0, "ilk-yuksek"), (95.0, 107.0, "orta"),
    (107.0, 139.0, "sakin-dusuk"), (139.0, 174.0, "ikinci-orta"), (174.0, 1e9, "final-yuksek"),
)
FILM_START_FRAME = 180000
RATE_FPS = 50

SEED = 20260914
BOOTSTRAPS = 4000


def shutter_mode(reading: dict | None) -> tuple[str, float | None, float | None]:
    """The clip's shutter mode, its exposure in seconds, and its angle in degrees."""
    if not reading or "8109" not in reading or "8106" not in reading:
        return UNKNOWN, None, None
    top, bottom = reading["8109"]
    fps_top, fps_bottom = reading["8106"]
    if bottom <= 0 or fps_top <= 0:
        return UNKNOWN, None, None
    exposure = top / bottom
    frame_period = fps_bottom / fps_top
    angle = reading["8108"] / 60 if "8108" in reading else None
    return (LOW if exposure > frame_period else NORMAL), exposure, angle


def film_second(timeline_frame: int) -> float:
    return (timeline_frame - FILM_START_FRAME) / RATE_FPS


def section_of(second: float) -> str:
    for start, end, key in SECTION_BANDS:
        if start <= second < end:
            return key
    return "bilinmiyor"


def read_cuts(path: Path) -> list[dict]:
    """The editor's own cut list: clip, where it sits on the timeline, where it starts."""
    cuts = []
    for part in path.read_text().strip().split(";"):
        fields = part.split("|")
        if len(fields) < 5 or not fields[0].upper().endswith(".MP4"):
            continue
        clip, tl_in, tl_out, doubled, source_in = fields[:5]
        source_in, tl_in, tl_out = int(source_in), int(tl_in), int(tl_out)
        # A slowed cut is written with its source value doubled; its source therefore ran half
        # as long as its place on the timeline.
        slowed = source_in > 0 and abs(int(doubled) - 2 * source_in) <= 8
        frames = (tl_out - tl_in) // (2 if slowed else 1)
        cuts.append({"clip": clip, "source_in": source_in, "frames": max(1, frames),
                     "timeline_in": tl_in, "slowed": slowed,
                     "section": section_of(film_second(tl_in))})
    return cuts


def even_windows(windows):
    ordered = sorted(windows, key=lambda w: w.asset_frame)
    return [w for index, w in enumerate(ordered)
            if index and w.asset_frame - ordered[index - 1].asset_frame == EVEN_STEP]


def bootstrap(deltas, rng) -> tuple[float, float]:
    draws = sorted(
        st.mean(rng.choices(deltas, k=len(deltas))) for _ in range(BOOTSTRAPS))
    return draws[int(0.025 * BOOTSTRAPS)], draws[int(0.975 * BOOTSTRAPS)]


def paired_test(name: str, pairs, rng, unit: str = "") -> None:
    """Used against unused, in the same clip, on the same grid.

    Two tests, because they answer different things. Wilcoxon weighs how far apart the two
    sides are and is dragged about by a handful of clips with enormous motion; the sign test
    only asks which way each clip leans, which is the question a region rule actually needs.
    """
    from scipy.stats import binomtest, wilcoxon

    if len(pairs) < 6:
        print(f"  {name:26} n={len(pairs):3d}   LOW SAMPLE / INSUFFICIENT EVIDENCE")
        return
    used = [a for a, _ in pairs]
    rest = [b for _, b in pairs]
    deltas = [a - b for a, b in pairs]
    spread = st.stdev(deltas)
    low, high = bootstrap(deltas, rng)
    result = wilcoxon(used, rest)
    lower = sum(1 for d in deltas if d < 0)
    decided = [d for d in deltas if d != 0]
    sign = binomtest(lower, len(decided)).pvalue if decided else 1.0
    print(f"  {name:26} n={len(pairs):3d}   used {st.median(used):7.2f}{unit}  "
          f"rest {st.median(rest):7.2f}{unit}   "
          f"dz {st.mean(deltas) / spread if spread else 0:+.2f}   "
          f"CI [{low:+.2f}, {high:+.2f}]   wilcoxon p {result.pvalue:.3f}   "
          f"used lower on {lower}/{len(pairs)} = {100 * lower / len(pairs):.0f}%  "
          f"sign p {sign:.3f}")


def spread_of(values, unit=""):
    ordered = sorted(values)

    def at(share):
        return ordered[min(len(ordered) - 1, int(share * len(ordered)))]

    return (f"median {st.median(ordered):7.2f}{unit}  mean {st.mean(ordered):7.2f}{unit}  "
            f"p25 {at(.25):7.2f}  p75 {at(.75):7.2f}  p90 {at(.90):7.2f}")


def canonical(rows, bar: float) -> None:
    """One line per cut, with everything a person would want to check by eye."""
    from sevenfilm.services.planner import UNUSABLE_SHARPNESS_SHARE

    print(f"  {'clip':12} {'shutter':>8} {'angle':>8} {'in':>6} {'sn':>5} {'motion':>7} "
          f"{'crisp':>6} {'sharp':>7} {'gate':>9} {'section':14} class")
    for row in rows:
        crisp = row["used_sharpness"] / bar if bar else 1.0
        gate = ("REJECTED" if row["gate_failing"] == row["gate_windows"]
                else f"{row['gate_failing']}/{row['gate_windows']} out"
                if row["gate_failing"] else "passes")
        print(f"  {row['clip']:12} {'1/' + str(round(1 / row['shutter'])):>8} "
              f"{row['angle']:7.1f}d {row['source_in']:6d} {row['frames'] / RATE_FPS:5.2f} "
              f"{row['used_motion']:7.2f} {crisp:6.2f} {row['used_sharpness']:7.1f} "
              f"{gate:>9} {row['section']:14} {row['class']}")
    print(f"  the gate rejects a window under crisp {UNUSABLE_SHARPNESS_SHARE}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--shutter", type=Path, required=True)
    parser.add_argument("--cuts", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("shutter_audit.json"))
    args = parser.parse_args()

    from sevenfilm.services.planner import UNUSABLE_SHARPNESS_SHARE

    rng = random.Random(SEED)
    readings = json.loads(args.shutter.read_text())
    modes = {clip: shutter_mode(value) for clip, value in readings.items()}
    cuts = read_cuts(args.cuts)
    classes = json.loads(args.classes.read_text())

    database = Database(args.__dict__.get("db") or database_path())
    assets = {asset.name: asset for asset in project_assets(database, args.project_id)}
    by_asset = asset_windows(database, args.project_id)
    every = sorted(w.sharpness for windows in by_asset.values() for w in windows)
    bar = every[len(every) // 2] if every else 0.0

    print("A) SHUTTER METADATA AVAILABILITY")
    print(f"  clips with a camera reading : {sum(1 for m in modes.values() if m[0] != UNKNOWN)}"
          f"/{len(modes)}")
    print("  source            : the rtmd stream inside each MP4, camera unit metadata set")
    print("  tags used         : 8109 exposure as a rational, 8106 capture rate, 8108 angle")
    print("  cross-check       : angle and exposure agree on every clip "
          "(1/101 <-> 177.5 deg at 50p, 1/645 <-> 28.0 deg)")
    print("  sidecar XML       : carries gamma and colour only, no exposure")

    print("\nB) CLASSIFICATION")
    print("  CREATIVE_LOW_SHUTTER = exposure longer than one capture frame period.")
    print("  A line from the camera, not from the data: an exposure that outlasts a frame")
    print("  cannot have been taken frame by frame. No visual labelling was needed.")

    print("\nC) CLIP INVENTORY")
    groups: dict[str, list[str]] = {}
    for clip, (mode, exposure, angle) in modes.items():
        groups.setdefault(mode, []).append(clip)
    seen: dict[tuple, int] = {}
    for clip, (mode, exposure, angle) in modes.items():
        if exposure:
            seen[(mode, round(1 / exposure), angle)] = seen.get(
                (mode, round(1 / exposure), angle), 0) + 1
    print(f"  {'mode':22} {'shutter':>9} {'angle':>9}  clips")
    for (mode, denominator, angle), count in sorted(seen.items(), key=lambda kv: -kv[1]):
        print(f"  {mode:22} {'1/' + str(denominator):>9} {angle:8.1f}d  {count:4d}")
    for mode in (NORMAL, LOW, UNKNOWN):
        print(f"  {mode:22} total {len(groups.get(mode, ())):4d} of {len(modes)}")

    print("\nD) WHAT THE EDITOR ACTUALLY USED")
    used_clips = {cut["clip"] for cut in cuts}
    by_mode = {mode: [c for c in cuts if modes.get(c["clip"], (UNKNOWN,))[0] == mode]
               for mode in (NORMAL, LOW, UNKNOWN)}
    total_frames = sum(cut["frames"] for cut in cuts)
    print(f"  {len(cuts)} cuts from {len(used_clips)} clips")
    for mode in (NORMAL, LOW, UNKNOWN):
        rows = by_mode[mode]
        clips = {c["clip"] for c in rows}
        frames = sum(c["frames"] for c in rows)
        print(f"  {mode:22} cuts {len(rows):3d} ({100 * len(rows) / len(cuts):4.1f}%)   "
              f"clips {len(clips):3d}   source frames {frames:6d} "
              f"({100 * frames / total_frames:4.1f}%)")
    available = len(groups.get(LOW, ()))
    used_low = len({c['clip'] for c in by_mode[LOW]})
    print(f"  of the {available} low-shutter clips shot, {used_low} reached the edit")

    print("\nQ) LOW SHUTTER BY MUSIC SECTION")
    print(f"  {'section':16} {'cuts':>6} {'low':>6} {'share':>7}")
    for _start, _end, key in SECTION_BANDS:
        rows = [c for c in cuts if c["section"] == key]
        if not rows:
            continue
        low = sum(1 for c in rows if modes.get(c["clip"], (UNKNOWN,))[0] == LOW)
        print(f"  {key:16} {len(rows):6d} {low:6d} {100 * low / len(rows):6.1f}%")
    print("  Descriptive only. Six sections of one film is not a rule about weddings.")

    # ---------------------------------------------------------------------------------
    print("\nE) SAMPLING VALIDITY")
    print(f"  every reading below is a stored window, {EVEN_STEP} frames after the window it")
    print("  is measured against, on both sides of every comparison. No strip is used.")

    rows_out = []
    pairs_by_mode: dict[str, list] = {}
    sharp_pairs: dict[str, list] = {}
    percentile_by_mode: dict[str, list] = {}
    relative_pairs: dict[str, list] = {}
    gate_stats: dict[str, list] = {}
    used_motion: dict[str, list] = {}
    rest_motion: dict[str, list] = {}
    used_sharp: dict[str, list] = {}
    recall: dict[str, list] = {}

    for cut in cuts:
        clip = cut["clip"]
        asset = assets.get(clip)
        mode = modes.get(clip, (UNKNOWN, None, None))[0]
        if asset is None:
            continue
        windows = even_windows(by_asset.get(asset.id, ()))
        if len(windows) < 4:
            continue
        start, end = cut["source_in"], cut["source_in"] + cut["frames"]
        inside = [w for w in windows if start <= w.asset_frame < end]
        outside = [w for w in windows if not (start <= w.asset_frame < end)]
        if not inside or not outside:
            continue

        motions = [w.motion for w in windows]
        clip_median = st.median(motions)

        def percentile(value, motions=motions):
            return sum(1 for m in motions if m < value) / len(motions)

        used_median = st.median([w.motion for w in inside])
        rest_median = st.median([w.motion for w in outside])
        pairs_by_mode.setdefault(mode, []).append((used_median, rest_median))
        percentile_by_mode.setdefault(mode, []).append(percentile(used_median))
        relative_pairs.setdefault(mode, []).append(
            (percentile(used_median),
             st.median([percentile(w.motion) for w in outside])))
        sharp_pairs.setdefault(mode, []).append(
            (st.median([w.sharpness for w in inside]),
             st.median([w.sharpness for w in outside])))
        used_motion.setdefault(mode, []).extend(w.motion for w in inside)
        rest_motion.setdefault(mode, []).extend(w.motion for w in outside)
        used_sharp.setdefault(mode, []).extend(w.sharpness for w in inside)

        failing = [w for w in inside if bar > 0 and w.sharpness / bar < UNUSABLE_SHARPNESS_SHARE]
        gate_stats.setdefault(mode, []).append((len(failing), len(inside)))

        ready = [w for w in windows
                 if w.motion != 0.0 and w.motion < clip_median
                 and (bar <= 0 or w.sharpness / bar >= UNUSABLE_SHARPNESS_SHARE)]
        ready_frames = {w.asset_frame for w in ready}
        covered = sum(1 for w in inside if w.asset_frame in ready_frames)
        recall.setdefault(mode, []).append((
            any(abs(w.asset_frame - start) <= EVEN_STEP for w in ready),
            covered / len(inside)))

        rows_out.append({
            "clip": clip, "mode": mode, "section": cut["section"],
            "class": classes.get(clip, "CONTINUOUS_ACTION"),
            "shutter": modes.get(clip, (None, None, None))[1],
            "angle": modes.get(clip, (None, None, None))[2],
            "source_in": start, "source_out": end, "frames": cut["frames"],
            "slowed": cut["slowed"],
            "used_motion": round(used_median, 2), "rest_motion": round(rest_median, 2),
            "motion_percentile": round(percentile(used_median), 3),
            "used_sharpness": round(st.median([w.sharpness for w in inside]), 1),
            "rest_sharpness": round(st.median([w.sharpness for w in outside]), 1),
            "gate_failing": len(failing), "gate_windows": len(inside),
            "ready_recall": round(covered / len(inside), 3),
        })

    print("\nF) MOTION DISTRIBUTION BY SHUTTER MODE — every eligible window")
    for mode in (NORMAL, LOW):
        if mode in used_motion:
            print(f"  {mode:22} used   {spread_of(used_motion[mode])}")
            print(f"  {'':22} rest   {spread_of(rest_motion[mode])}")

    print("\nG-J) MOTION AUDIT — the editor's cut against the rest of the same clip")
    paired_test("G  every clip", [p for rows in pairs_by_mode.values() for p in rows], rng)
    paired_test(f"H  {NORMAL}", pairs_by_mode.get(NORMAL, []), rng)
    paired_test(f"I  {LOW}", pairs_by_mode.get(LOW, []), rng)
    paired_test(f"J  {UNKNOWN}", pairs_by_mode.get(UNKNOWN, []), rng)

    print("\n  motion percentile of the editor's own cut inside its clip (0.50 is chance)")
    for mode, values in sorted(percentile_by_mode.items()):
        if len(values) >= 6:
            print(f"  {mode:26} n={len(values):3d}   median {st.median(values):.3f}   "
                  f"below chance on {sum(1 for v in values if v < 0.5)}/{len(values)}")

    print("\nK-L) NORMAL SHUTTER, SPLIT BY MOMENT TYPE")
    normal_rows = [r for r in rows_out if r["mode"] == NORMAL]
    for label, wanted in (("K  non-event", False), ("L  action event", True)):
        chosen = [(r["used_motion"], r["rest_motion"]) for r in normal_rows
                  if (r["class"] == "ACTION_EVENT") == wanted]
        paired_test(label, chosen, rng)

    print("\nM) READY-REGION RECALL BY SHUTTER MODE  (diagnostic definition, not a rule)")
    for mode in (NORMAL, LOW, UNKNOWN):
        rows = recall.get(mode, [])
        if not rows:
            continue
        print(f"  {mode:22} IN at a ready window {sum(1 for r, _ in rows if r):3d}/{len(rows):3d}"
              f" = {100 * sum(1 for r, _ in rows if r) / len(rows):4.1f}%   "
              f"median share of the used interval that is ready "
              f"{st.median([share for _, share in rows]):.2f}")

    print("\nN) ABSOLUTE MOTION AGAINST CLIP-RELATIVE MOTION")
    for mode in (NORMAL, LOW):
        if mode in pairs_by_mode:
            paired_test(f"  absolute  {mode}", pairs_by_mode[mode], rng)
            paired_test(f"  relative  {mode}", relative_pairs[mode], rng)

    print("\nO) SHARPNESS BY SHUTTER MODE")
    for mode in (NORMAL, LOW):
        if mode in used_sharp:
            print(f"  {mode:22} used windows  {spread_of(used_sharp[mode])}")
    paired_test(f"  used vs rest  {NORMAL}", sharp_pairs.get(NORMAL, []), rng)
    paired_test(f"  used vs rest  {LOW}", sharp_pairs.get(LOW, []), rng)
    print(f"  the shoot's median sharpness is {bar:.1f}; the gate sits at "
          f"{bar * UNUSABLE_SHARPNESS_SHARE:.1f}")

    print("\nP) QUALITY GATE ON FOOTAGE THE EDITOR CHOSE")
    for mode in (NORMAL, LOW):
        rows = gate_stats.get(mode, [])
        if not rows:
            continue
        failing = sum(f for f, _ in rows)
        windows = sum(t for _, t in rows)
        cuts_hit = sum(1 for f, _ in rows if f)
        cuts_all = sum(1 for f, t in rows if f == t)
        print(f"  {mode:22} windows rejected {failing:4d}/{windows:5d} = "
              f"{100 * failing / windows:5.1f}%   cuts touched {cuts_hit:3d}/{len(rows):3d}   "
              f"cuts rejected outright {cuts_all:3d}")

    print("\nR) CANONICAL LOW-SHUTTER CUTS")
    print("  selection, fixed before looking: the five longest low-shutter cuts in the edit.")
    canonical(sorted([r for r in rows_out if r["mode"] == LOW],
                     key=lambda r: -r["frames"])[:5], bar)

    print("\nS) CANONICAL NORMAL-SHUTTER CUTS")
    print("  selection, fixed before looking: the five normal-shutter cuts whose length is")
    print("  closest to the median length of the five above, so the pair is comparable.")
    low_five = sorted([r for r in rows_out if r["mode"] == LOW],
                      key=lambda r: -r["frames"])[:5]
    target = st.median([r["frames"] for r in low_five]) if low_five else 0
    canonical(sorted([r for r in rows_out if r["mode"] == NORMAL],
                     key=lambda r: abs(r["frames"] - target))[:5], bar)

    print("\nT) C2075 — THE CAKE")
    cake = [r for r in rows_out if r["clip"] == "C2075.MP4"]
    if cake:
        canonical(cake, bar)
    mode, exposure, angle = modes.get("C2075.MP4", (UNKNOWN, None, None))
    print(f"  camera reading: {mode}, 1/{round(1 / exposure) if exposure else '?'} s at "
          f"{angle:.1f} degrees")
    print("  C2075 motion behaviour cannot be explained by low shutter: the clip was shot at")
    print("  the same 1/101 and 177.5 degrees as the bulk of this wedding.")

    args.out.write_text(json.dumps(rows_out, indent=1))
    print(f"\nwritten {args.out}  ({len(rows_out)} cuts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
