"""Freeze the two-signal rule from last round and see if it holds on the 50 clips it never saw.

Last round's rule — fall back when the top candidate's cross-scale drift exceeds four seconds,
or when it barely leads its runner-up — was built by looking at exactly four clips. This applies
it, unchanged, to all 54, and extends it to a third band using only the same two signals and the
continuous group's own distribution landmarks (its 25th percentile and its median), never a
number chosen after looking at a result.

    FALLBACK          drift > 4s   OR  competition_vs_next < continuous p25
    ABSTAIN           drift > 2s   OR  competition_vs_next < continuous median
    HIGH_CONFIDENCE   neither

Only four of the 54 clips carry independent method-utility evidence from earlier rounds
(C1987 and C2075 strong, C1999 partial, C2052 failed); the other 50 have no such evidence and
are reported descriptively — candidate load, length, shutter mode — never scored against a
label that does not exist.

Read-only. Reuses `motion_confidence.py`'s and `motion_regions.json`'s own output.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shutter_audit import shutter_mode

DRIFT_FALLBACK = 4.0
DRIFT_ABSTAIN = 2.0
CANONICAL_UTILITY = {
    "C1987.MP4": "STRONG", "C2075.MP4": "STRONG", "C1999.MP4": "PARTIAL", "C2052.MP4": "FAIL",
}


def continuous_landmarks(confidence: dict, classes: dict) -> tuple[float, float]:
    values = sorted(
        confidence[clip][0]["competition_vs_next"]
        for clip in confidence
        if classes.get(clip) == "CONTINUOUS_ACTION" and confidence[clip]
        and confidence[clip][0]["competition_vs_next"] is not None)
    return values[len(values) // 4], st.median(values)


def decide(row: dict, comp_p25: float, comp_median: float) -> str:
    drift = row.get("scale_drift_seconds")
    comp = row.get("competition_vs_next")
    if (drift is not None and drift > DRIFT_FALLBACK) or (comp is not None and comp < comp_p25):
        return "FALLBACK"
    if (drift is not None and drift > DRIFT_ABSTAIN) or (comp is not None and comp < comp_median):
        return "ABSTAIN"
    return "HIGH_CONFIDENCE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confidence", type=Path, required=True)
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--shutter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    confidence = json.loads(args.confidence.read_text())
    regions = json.loads(args.regions.read_text())
    shutter = json.loads(args.shutter.read_text())
    classes = {clip: entry["class"] for clip, entry in regions.items()}

    comp_p25, comp_median = continuous_landmarks(confidence, classes)
    print(f"continuous competition landmarks: p25={comp_p25:.4f}  median={comp_median:.4f}")

    decisions = {}
    for clip, rows in confidence.items():
        if not rows:
            continue
        mode, _exposure, _angle = shutter_mode(shutter.get(clip))
        decisions[clip] = {
            "decision": decide(rows[0], comp_p25, comp_median),
            "drift": rows[0].get("scale_drift_seconds"),
            "competition": rows[0].get("competition_vs_next"),
            "class": classes.get(clip),
            "total_frames": regions[clip]["total_frames"],
            "shutter_mode": mode,
            "method_utility": CANONICAL_UTILITY.get(clip, "UNKNOWN"),
        }

    print("\nCANONICALS")
    for clip, utility in CANONICAL_UTILITY.items():
        d = decisions[clip]
        print(f"  {clip:12} utility={utility:8} decision={d['decision']:16} "
              f"drift={d['drift']}  competition={d['competition']:.3f}")

    print("\nDECISIONS BY CLASS")
    by_class: dict[str, dict[str, int]] = {}
    for d in decisions.values():
        by_class.setdefault(d["class"], {}).setdefault(d["decision"], 0)
        by_class[d["class"]][d["decision"]] += 1
    for cls, counts in by_class.items():
        print(f"  {cls:20} {counts}")

    continuous = [d for d in decisions.values() if d["class"] == "CONTINUOUS_ACTION"]
    high_share = sum(1 for d in continuous if d["decision"] == "HIGH_CONFIDENCE") / len(continuous)
    print(f"\nCONTINUOUS_ACTION HIGH_CONFIDENCE share: {high_share * 100:.1f}% (n={len(continuous)})")

    print("\nLENGTH BY DECISION (seconds)")
    for dec in ("HIGH_CONFIDENCE", "ABSTAIN", "FALLBACK"):
        lens = [d["total_frames"] / 50 for d in decisions.values() if d["decision"] == dec]
        if lens:
            print(f"  {dec:16} n={len(lens):3d}  median {st.median(lens):.1f}s")

    print("\nSHUTTER MODE BY DECISION")
    by_shutter: dict[str, dict[str, int]] = {}
    for d in decisions.values():
        by_shutter.setdefault(d["shutter_mode"], {}).setdefault(d["decision"], 0)
        by_shutter[d["shutter_mode"]][d["decision"]] += 1
    for mode, counts in by_shutter.items():
        print(f"  {mode:22} {counts}")

    Path(args.out).write_text(json.dumps(decisions, indent=1))
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
