"""Run the ready-region and music-grid arrangement beside the searches that came before it.

  A   planner        the shot search with the production score, as the plan made it
  B   P1             the clip search with the production score
  E1  P3             the clip search ranked by who is in the window
  V2  this round     ready regions in source time, the corrected beat grid in timeline time

Reads the project, the stored measurements, the editor's own cut list and the beat grid
measured from his music. Writes one JSON. Changes nothing: no plan is built here, no shadow
path is wired into one, and the planner's answer is read from the plan it already produced.

What is deliberately given away: the timeline position of each cut is the editor's own. This
round is not re-planning the film — the question is what happens at one cut when the source
moment is chosen this way, so everything upstream of the source moment is held fixed at what
he did. A V2 that also chose the clip and the timeline position would be a different question.

Usage: tools/moment_v2_eval.py <project-id> --compare shadow_compare7.json --beats mz_beats.npy
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.config import database_path
from sevenfilm.db import Database
from sevenfilm.services import moment_v2
from sevenfilm.services.media import project_assets
from sevenfilm.services.windows import asset_windows, project_windows

RATE_FPS = 50

# The editor's cut list carries the music time of every cut, already moved by the empirical
# offset P3.5 reported. That offset has to come back off before a phase is applied, or the same
# displacement is counted twice — which is what the first run of this tool did, and it made the
# corrected grid look five times worse than the raw one.

# The beat multiple each stretch of this film is cut on, measured on his 167 cuts in P3.6 and
# used here as the target to reconstruct. These are numbers about one wedding's two songs, not
# about weddings: they are a parameter of this evaluation, not a constant of the module.
SECTION_BANDS = (
    (0.0, 63.0, "opening-low", 2),
    (63.0, 95.0, "first-high", 2),
    (95.0, 107.0, "medium", 2),
    (107.0, 139.0, "quiet-low", 6),
    (139.0, 174.0, "second-medium", 1),
    (174.0, 1e9, "finale-high", 1),
)

CANONICAL = ("C1899.MP4", "C2146.MP4", "C1986.MP4", "C2075.MP4")


def section_of(second: float) -> tuple[str, int]:
    for start, end, key, beats in SECTION_BANDS:
        if start <= second < end:
            return key, beats
    return "unknown", moment_v2.DEFAULT_SECTION_BEATS


def sharpness_bar(database: Database, project_id: str) -> float:
    values = sorted(w.sharpness for rows in project_windows(database, project_id).values()
                    for w in rows)
    return values[len(values) // 2] if values else 0.0


def share(count: int, total: int) -> str:
    return f"{count:3d}/{total}  {100 * count / total:5.1f}%" if total else "   n/a"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--compare", type=Path, required=True)
    parser.add_argument("--beats", type=Path, required=True)
    parser.add_argument("--manual-beats", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("moment_v2_eval.json"))
    args = parser.parse_args()

    database = Database(database_path())
    assets = {}
    for asset in project_assets(database, args.project_id):
        assets.setdefault(asset.name, asset)
    windows_by_asset = asset_windows(database, args.project_id)
    bar = sharpness_bar(database, args.project_id)

    raw = [Fraction(float(value)).limit_denominator(10_000)
           for value in np.load(args.beats)]
    grid = moment_v2.edit_grid(raw)
    if grid is None:
        print("the beat grid is not reliable enough to correct; nothing to run")
        return 1
    interval = grid.interval
    print(f"beat {float(interval) * 1000:.1f} ms · phase {float(grid.phase) * 1000:.1f} ms "
          f"(= interval x {moment_v2.GRID_PHASE_SHARE}) · {len(raw)} raw beats\n")

    rows = json.loads(args.compare.read_text())
    classes = json.loads(args.classes.read_text())
    cut_list = json.loads(args.manual_beats.read_text())
    stored_shift = float(cut_list.get("shift", 0.0))
    manual: dict[str, list] = {}
    for cut in cut_list["rows"]:
        manual.setdefault(cut["clip"], []).append(cut)
    print(f"the cut list carries a {stored_shift:.2f} s offset; taking it back off so the "
          f"phase measured here is the only one applied\n")

    out_rows = []
    for row in rows:
        clip = row["clip"]
        asset = assets.get(clip)
        if asset is None:
            continue
        # A clip the editor used twice has two cuts; the one meant here is the one that starts
        # where this row says it does.
        cuts = manual.get(clip, ())
        cut = min(cuts, key=lambda c: abs(c["src_in"] - row["manual_in"])) if cuts else None
        windows = windows_by_asset.get(asset.id, ())
        total = asset.frame_rate.frames_from_seconds(asset.duration, rounding="floor")
        second = (Fraction(cut["song_t"] - stored_shift).limit_denominator(10_000)
                  if cut else None)
        key, beats = section_of(float(second)) if cut else ("unknown",
                                                            moment_v2.DEFAULT_SECTION_BEATS)

        regions = moment_v2.ready_regions(
            windows, sharpness_bar=bar, rate=asset.frame_rate, asset_duration_frames=total)
        decision = moment_v2.decide(
            windows, sharpness_bar=bar, rate=asset.frame_rate, asset_duration_frames=total,
            grid=grid, timeline_second=second, section_key=key,
            section_policy={key: beats}, fallback_frames=row["frames"])

        manual_in, manual_frames = row["manual_in"], row["frames"]
        if second is None:
            # No music time for this cut, so it carries region metrics only. Reported rather
            # than dropped: one of the four clips every round has followed is in this state.
            pass
        manual_out = manual_in + manual_frames
        holding = [r for r in regions if r.contains(manual_in)]
        chosen = decision.region
        raw_beat = min(raw, key=lambda beat: abs(beat - second)) if second else None
        corrected = grid.nearest(second) if second else None
        overlap = 0
        if chosen:
            overlap = max(0, min(manual_out, chosen.source_end)
                          - max(manual_in, chosen.source_start))

        out_rows.append({
            "clip": clip,
            "class": classes.get(clip, "CONTINUOUS_ACTION"),
            "category": row["category"],
            "section": key,
            "manual_in": manual_in, "manual_out": manual_out, "manual_frames": manual_frames,
            "a_in": row["a_in"], "b_in": row["b_in"], "e_in": row["e_in"],
            "v2_in": decision.source_start, "v2_frames": decision.frames,
            "v2_fallback": decision.fallback, "v2_reason": decision.reason,
            "v2_out_status": decision.out_status,
            "has_music_time": second is not None,
            "v2_beats": decision.beats, "v2_beats_requested": decision.beats_requested,
            "region_count": len(regions),
            "region_rank": decision.region_rank,
            "region_start": chosen.source_start if chosen else None,
            "region_end": chosen.source_end if chosen else None,
            "region_frames": chosen.duration_frames if chosen else None,
            "region_crosses_shot": chosen.crosses_shot_boundary if chosen else None,
            "region_median_motion": chosen.median_motion if chosen else None,
            "region_median_faces": chosen.median_face_count if chosen else None,
            "manual_in_in_any_region": bool(holding),
            "manual_out_in_any_region": any(r.contains(manual_out - 1) for r in regions),
            "manual_in_in_chosen": bool(chosen and chosen.contains(manual_in)),
            "manual_overlap_frames": overlap,
            "same_region": bool(holding and chosen and chosen in holding),
            "music_second": float(second) if second else None,
            "raw_beat_distance": float(abs(second - raw_beat)) if second else None,
            "corrected_beat_distance": (
                float(abs(second - corrected)) if second else None),
            "manual_beats": manual_frames / float(interval) / RATE_FPS,
            "v2_beat_error": (
                None if decision.fallback
                else decision.frames / float(interval) / RATE_FPS
                - manual_frames / float(interval) / RATE_FPS),
        })

    args.out.write_text(json.dumps(out_rows, indent=1))
    report(out_rows, interval)
    print(f"\nwritten {args.out}")
    return 0


def report(rows, interval) -> None:
    total = len(rows)
    normal = [r for r in rows if r["class"] != "ACTION_EVENT"]
    events = [r for r in rows if r["class"] == "ACTION_EVENT"]
    print(f"{total} clips both edits use · {len(normal)} in supported classes · "
          f"{len(events)} action events, held out\n")

    print("N) READY REGION RECALL")
    print(f"  editor's IN inside some ready region  {share(sum(r['manual_in_in_any_region'] for r in rows), total)}")
    print(f"  editor's OUT inside some ready region {share(sum(r['manual_out_in_any_region'] for r in rows), total)}")
    print(f"  editor's IN inside the chosen region  {share(sum(r['manual_in_in_chosen'] for r in rows), total)}")
    counts = [r["region_count"] for r in rows]
    frames = [r["region_frames"] for r in rows if r["region_frames"]]
    print(f"  regions per clip: median {st.median(counts):.0f}, max {max(counts)}")
    print(f"  chosen region length: median {st.median(frames) / 50:.2f}s, "
          f"min {min(frames) / 50:.2f}s, max {max(frames) / 50:.2f}s")
    ranks = [r["region_rank"] for r in rows if r["region_rank"] is not None]
    print(f"  chosen region was the first ranked on {sum(1 for r in ranks if r == 0)}/{len(ranks)}")
    crossing = sum(1 for r in rows if r["region_crosses_shot"])
    print(f"  chosen region crossed a detected shot boundary on {crossing}/{total}")

    print("\nO) MUSIC GRID, distance from the editor's cut to the beat")
    for label, key in (("raw grid", "raw_beat_distance"),
                       ("corrected grid", "corrected_beat_distance")):
        values = [r[key] for r in rows if r[key] is not None]
        print(f"  {label:15} median {st.median(values) * 1000:6.0f} ms   "
              f"p90 {sorted(values)[int(0.9 * len(values))] * 1000:6.0f} ms   "
              + "  ".join(f"+-{t}ms {share(sum(1 for v in values if v <= t / 1000), len(values))}"
                          for t in (40, 80, 120)))
    print(f"  a cut placed at random would sit {float(interval) / 4 * 1000:.0f} ms out")

    print("\nP) DURATION")
    errors = [abs(r["v2_beat_error"]) for r in rows if r["v2_beat_error"] is not None]
    manual_beats = [r["manual_beats"] for r in rows]
    off_grid = [abs(b - round(b)) for b in manual_beats]
    print(f"  the editor's own cuts, distance from a whole beat: median {st.median(off_grid):.2f} beats")
    print(f"  within 0.25 beats of a whole one: {share(sum(1 for e in off_grid if e <= 0.25), total)}")
    if errors:
        print(f"  V2 duration error against his: median {st.median(errors):.2f} beats, "
              f"within 1 beat {share(sum(1 for e in errors if e <= 1), len(errors))}")
    shortened = sum(1 for r in rows
                    if r["v2_beats"] and r["v2_beats"] < (r["v2_beats_requested"] or 0))
    print(f"  took a shorter beat multiple because the region was short: {shortened}/{total}")

    print("\nQ) SOURCE IN DISTANCE, seconds  (secondary)")
    print(f"  {'path':10} {'median':>7} " + "".join(f"{f'+-{w}s':>8}" for w in (0.5, 1, 2, 3)))
    for label, key in (("planner", "a_in"), ("P1", "b_in"), ("P3 E1", "e_in"), ("V2", "v2_in")):
        distances = [abs(r[key] - r["manual_in"]) / 50 for r in rows if r[key] is not None]
        if not distances:
            continue
        cells = "".join(f"{sum(1 for d in distances if d <= w):8d}" for w in (0.5, 1, 2, 3))
        print(f"  {label:10} {st.median(distances):7.2f} {cells}   of {len(distances)}")

    print("\nR) CONTINUOUS ACTION — diagnostic only, never counted as a hit")
    same = [r for r in rows if r["same_region"]]
    print(f"  editor's IN and V2's IN in the same ready region: {share(len(same), total)}")
    print("  POSSIBLY_EDITORIALLY_EQUIVALENT on " +
          f"{sum(1 for r in same if r['class'] == 'CONTINUOUS_ACTION')} continuous-action clips")

    print("\nH) OUT VALIDATION")
    for status in (moment_v2.OUT_SAFE, moment_v2.OUT_NEAR_BREAKDOWN,
                   moment_v2.OUT_OUTSIDE_READY_REGION):
        print(f"  {status:26} {share(sum(1 for r in rows if r['v2_out_status'] == status), total)}")

    print("\nI) FALLBACKS")
    fell = [r for r in rows if r["v2_fallback"]]
    print(f"  {share(len(fell), total)}")
    for reason in sorted({r["v2_reason"] for r in fell}):
        print(f"    {reason}: {sum(1 for r in fell if r['v2_reason'] == reason)}")

    print("\nM) BY CLASS")
    for name in ("CONTINUOUS_ACTION", "TRANSITIONAL", "STABLE_COMPOSITION", "ACTION_EVENT"):
        group = [r for r in rows if r["class"] == name]
        if not group:
            continue
        note = "   KNOWN UNSUPPORTED CLASS" if name == "ACTION_EVENT" else (
            "   LOW SAMPLE" if len(group) < 6 else "")
        inside = sum(r["manual_in_in_any_region"] for r in group)
        distances = [abs(r["v2_in"] - r["manual_in"]) / 50 for r in group if r["v2_in"]]
        print(f"  {name:20} n={len(group):2d}  IN in a ready region {inside:2d}  "
              f"V2 source distance median "
              f"{st.median(distances) if distances else float('nan'):5.2f}s{note}")

    print("\nS-V) THE FOUR CLIPS CARRIED THROUGH EVERY ROUND")
    for clip in CANONICAL:
        row = next((r for r in rows if r["clip"] == clip), None)
        if row is None:
            print(f"  {clip}: not in this set")
            continue
        print(f"  {clip}  {row['class']}  {row['category']}  section {row['section']}")
        print(f"    editor  in {row['manual_in']:6d}  out {row['manual_out']:6d}  "
              f"{row['manual_frames'] / 50:.2f}s = {row['manual_beats']:.2f} beats")
        print(f"    planner in {row['a_in']:6d}   P1 in {row['b_in']:6d}   "
              f"P3 in {row['e_in']:6d}")
        print(f"    V2      in {row['v2_in']!s:>6}  {row['v2_frames']!s:>4} frames  "
              f"{row['v2_beats']} beats  {row['v2_out_status']}")
        print(f"    region  {row['region_start']}-{row['region_end']} of "
              f"{row['region_count']} on the clip, rank {row['region_rank']}, "
              f"motion {row['region_median_motion']}")
        print(f"    editor's IN inside it: {row['manual_in_in_chosen']}   "
              f"inside any: {row['manual_in_in_any_region']}   "
              f"beat {row['corrected_beat_distance'] * 1000:.0f} ms out")
        if row["class"] == "ACTION_EVENT":
            print("    EXPECTED UNSUPPORTED EVENT FAILURE — this class has no measured rule")


if __name__ == "__main__":
    raise SystemExit(main())
