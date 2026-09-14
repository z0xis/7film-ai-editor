"""Open the manual cuts and see whether the blind motion-burst regions found them.

Reads `motion_region_router.py`'s output — computed with no knowledge of any manual cut — and
the editor's own cut list, and compares them. This is the only file in this round that reads
manual timing.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

PRIMARY_CONTEXT = "4"
FPS = 50


def cut_list(path: Path) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for part in path.read_text().strip().split(";"):
        fields = part.split("|")
        if len(fields) < 5 or not fields[0].upper().endswith(".MP4"):
            continue
        clip, start, end, doubled, source = fields[:5]
        source, start, end = int(source), int(start), int(end)
        slowed = source > 0 and abs(int(doubled) - 2 * source) <= 8
        frames = max(1, (end - start) // (2 if slowed else 1))
        out.setdefault(clip, []).append((source, source + frames))
    return out


def overlaps(interval, windows) -> bool:
    a, b = interval
    return any(a < w[1] and b > w[0] for w in windows)


def canonical_report(name, entry, cuts):
    print(f"\n{name} — {len(cuts)} manual interval(s), class {entry['class']}")
    if entry.get("abstain"):
        print(f"  ABSTAIN — {entry.get('reason')}")
        return
    ctx = entry["by_context"][PRIMARY_CONTEXT]
    for k in ("1", "3", "5"):
        regions = ctx[k]["regions"]
        peaks = [r["peak_frame"] for r in regions]
        for exp in ("0.5", "1.0", "2.0"):
            info = ctx[k]["by_expansion"][exp]
            hit = any(overlaps(c, info["windows"]) for c in cuts)
            print(f"  top{k} ±{exp}s: peaks={peaks}  hit={hit}  "
                  f"retained={info['retained_share'] * 100:.1f}%")
    print(f"  cross-scale top1 spread: {entry['top1_cross_scale_spread_seconds']}s   "
          f"top1 by context: {entry['top1_frames_by_context']}")
    print(f"  opening-guarded top3 frames: {entry['guarded_top3_frames']}")
    print(f"  manual intervals: {cuts}")
    top5 = ctx["5"]["regions"]
    for region in top5:
        near = any(a - 50 <= region["peak_frame"] <= b + 50 for a, b in cuts)
        print(f"    peak {region['peak_frame']:6d}  contrast {region['contrast']:.2f}  "
              f"width [{region['width_start']},{region['width_end']}]  near_manual={near}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--cuts", type=Path, required=True)
    args = parser.parse_args()

    regions = json.loads(args.regions.read_text())
    cuts = cut_list(args.cuts)

    for name in ("C1987.MP4", "C2075.MP4", "C1999.MP4", "C2052.MP4"):
        if name in regions and name in cuts:
            canonical_report(name, regions[name], cuts[name])

    print("\n\nP) 38 CONTINUOUS_ACTION — pooled recall / retained / regions-per-minute")
    hits = {"1": {"0.5": 0, "1.0": 0, "2.0": 0}, "3": {"0.5": 0, "1.0": 0, "2.0": 0},
            "5": {"0.5": 0, "1.0": 0, "2.0": 0}}
    retained = {"1": {"0.5": [], "1.0": [], "2.0": []}, "3": {"0.5": [], "1.0": [], "2.0": []},
               "5": {"0.5": [], "1.0": [], "2.0": []}}
    per_minute = []
    n = 0
    for clip, entry in regions.items():
        if entry["class"] != "CONTINUOUS_ACTION" or entry.get("abstain") or clip not in cuts:
            continue
        n += 1
        ctx = entry["by_context"][PRIMARY_CONTEXT]
        per_minute.append(len(ctx["5"]["regions"]) / (entry["total_frames"] / FPS / 60))
        for k in ("1", "3", "5"):
            for exp in ("0.5", "1.0", "2.0"):
                info = ctx[k]["by_expansion"][exp]
                retained[k][exp].append(info["retained_share"])
                if any(overlaps(c, info["windows"]) for c in cuts[clip]):
                    hits[k][exp] += 1
    print(f"  n={n} continuous clips with manual cuts")
    for k in ("1", "3", "5"):
        for exp in ("0.5", "1.0", "2.0"):
            print(f"  top{k} ±{exp}s: recall {hits[k][exp]}/{n} "
                  f"median retained {st.median(retained[k][exp]) * 100:.1f}%")
    print(f"  median candidate regions/minute (top5, primary context): "
          f"{st.median(per_minute):.1f}")

    print("\n\nB) EVENT vs CONTINUOUS — event-method-useful recall at the same settings")
    events = {c: e for c, e in regions.items() if e["class"] == "ACTION_EVENT"}
    for clip, entry in events.items():
        if entry.get("abstain") or clip not in cuts:
            continue
        ctx = entry["by_context"][PRIMARY_CONTEXT]
        row = []
        for k in ("1", "3", "5"):
            info = ctx[k]["by_expansion"]["1.0"]
            hit = any(overlaps(c, info["windows"]) for c in cuts[clip])
            row.append(f"top{k}={hit}({info['retained_share']*100:.0f}%)")
        print(f"  {clip:12} " + "  ".join(row))

    print("\n\nT) MERGE-GAP SENSITIVITY (primary context, top5, ±1s expansion)")
    for clip in ("C1987.MP4", "C2075.MP4", "C1999.MP4", "C2052.MP4"):
        if clip not in regions or regions[clip].get("abstain"):
            continue
        print(f"  {clip}: {regions[clip]['merge_sensitivity']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
