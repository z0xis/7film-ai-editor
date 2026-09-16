"""P5.8: analysis over the raw SSDLite bake-off results -- threshold sensitivity, false
contradiction rate, harmful-FP catch rate, and D0-D4 policy simulation. Pre-registered rules
(section 11 hard rule: 0 detections = UNKNOWN, never contradiction; dominant ratios frozen in
shadow_ssdlite_verifier.py before any result was inspected).
"""

from __future__ import annotations

import json

CONFIDENCE_THRESHOLDS = ["0.2", "0.35", "0.5", "0.7"]
DOMINANT_KEYS = ["dominant_ratio_0.25", "dominant_ratio_0.4", "dominant_ratio_0.6"]


def evidence_status(summary_at_t: dict, dominant_key: str) -> str:
    """H1/H2/H3 from the package spec. 0 detections -> UNKNOWN (never contradiction).
    Exactly 1 dominant person -> possible CONTRADICTED (for a paired-interaction claim).
    >=2 dominant persons -> SUPPORT only (never event verification)."""
    total = summary_at_t["total_person_count"]
    dominant = summary_at_t[dominant_key]
    if total == 0:
        return "UNKNOWN"
    if dominant <= 1:
        return "CONTRADICTED"
    return "SUPPORTED"


def main() -> int:
    with open("tools/fixtures/p5_8_ssdlite_results.json") as f:
        results = json.load(f)

    print("=== THRESHOLD SENSITIVITY TABLE (evidence status per case) ===")
    header = f"{'case_id':38s}" + "".join(f"T{t.replace('0.', '')}/d25  " for t in CONFIDENCE_THRESHOLDS)
    print(header)
    for case in results:
        row = f"{case['case_id']:38s}"
        for t in CONFIDENCE_THRESHOLDS:
            status = evidence_status(case["threshold_summary"][t], "dominant_ratio_0.25")
            row += f"{status[:8]:8s} "
        print(row)

    print("\n=== FALSE CONTRADICTION RATE (genuine first-dance frames only) ===")
    genuine = [c for c in results if c["event"] == "first_dance" and c["human_verdict"] == "TP"]
    for t in CONFIDENCE_THRESHOLDS:
        for dk in DOMINANT_KEYS:
            false_contra = sum(1 for c in genuine if evidence_status(c["threshold_summary"][t], dk) == "CONTRADICTED")
            print(f"  T={t} {dk}: {false_contra}/{len(genuine)} genuine frames wrongly CONTRADICTED")

    print("\n=== HARMFUL-FP CATCH (C7349) ===")
    harmful = next(c for c in results if c["case_id"] == "HARMFUL_solo_performer_C7349")
    for t in CONFIDENCE_THRESHOLDS:
        for dk in DOMINANT_KEYS:
            status = evidence_status(harmful["threshold_summary"][t], dk)
            print(f"  T={t} {dk}: {status}")

    print("\n=== DRONE (UNKNOWN vs false contradiction check) ===")
    for cid in ["genuine_first_dance_drone_A", "genuine_first_dance_drone_B"]:
        c = next(x for x in results if x["case_id"] == cid)
        for t in CONFIDENCE_THRESHOLDS:
            status = evidence_status(c["threshold_summary"][t], "dominant_ratio_0.25")
            print(f"  {cid} T={t}: {status} (total_persons={c['threshold_summary'][t]['total_person_count']})")

    print("\n=== ORDINARY/CROWD DANCE (does 2+ person support look identical to genuine?) ===")
    for cid in ["ordinary_dance_crowd_076", "ordinary_dance_couple_in_crowd_079"]:
        c = next(x for x in results if x["case_id"] == cid)
        for t in CONFIDENCE_THRESHOLDS:
            s = c["threshold_summary"][t]
            print(f"  {cid} T={t}: total={s['total_person_count']} dom25={s['dominant_ratio_0.25']}")

    print("\n=== CAKE ===")
    for cid in ["genuine_cake_cutting_C7309", "cake_visible_only_050"]:
        c = next(x for x in results if x["case_id"] == cid)
        for t in CONFIDENCE_THRESHOLDS:
            print(f"  {cid} T={t}: cake_count={c['threshold_summary'][t]['cake_count']}")

    print("\n=== CEREMONY/HENNA (characterization only) ===")
    for cid in ["ceremony_halluc_C7343", "ceremony_halluc_C7344", "ceremony_borderline_C7342"]:
        c = next(x for x in results if x["case_id"] == cid)
        print(f"  {cid}: persons@0.35={c['threshold_summary']['0.35']['total_person_count']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
