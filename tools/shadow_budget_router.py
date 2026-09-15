"""P5.4: budget-capped router simulation + dedup/episode analysis on the frozen 156-shot 15A
shadow sample. Priority score built only from generic router signals (no ground truth). Also
measures asset-level temporal-proximity dedup potential without touching segmentation.
"""

from __future__ import annotations

import json
from pathlib import Path

STORY_CRITICAL = {"ceremony", "party", "couple", "bride_prep", "groom_prep"}


def priority_score(pred: dict) -> float:
    """Higher = more worth escalating. Built only from (category, margin) -- the same two
    generic signals R3/R4b use, combined into a continuous score for budget-capping instead of
    a hard threshold."""
    not_story_crit = 1.0 if pred["top1"] not in STORY_CRITICAL else 0.0
    ambiguity = max(0.0, 1.0 - pred["margin"] / 0.5)  # margin>=0.5 -> 0 ambiguity, margin=0 -> 1.0
    return 0.6 * not_story_crit + 0.4 * ambiguity


def main() -> int:
    data = json.loads(Path("tools/fixtures/p5_3_shadow_router_15agustos.json").read_text())
    for e in data:
        e["priority_score"] = round(priority_score(e["clip_pred"]), 4)

    ranked = sorted(data, key=lambda e: -e["priority_score"])
    n = len(ranked)

    known_positive_indices = {95, 111}  # genuine first_dance frames found in P5.3 (frame_index space of the 156 sample)
    hallucination_index = 61

    print("BUDGET ROUTER (priority-ranked, generic signals only)")
    for pct in [5, 10, 15, 20, 30]:
        k = max(1, round(n * pct / 100))
        top_k = ranked[:k]
        top_k_indices = {e["frame_index"] for e in top_k}
        captured_known = known_positive_indices & top_k_indices
        captured_halluc = hallucination_index in top_k_indices
        est_runtime_s = k * 6.0  # P5.3/P5.4 measured median
        print(f"  {pct}% budget: k={k} known_event_capture={len(captured_known)}/2 "
              f"hallucination_case_included={captured_halluc} est_runtime={est_runtime_s/60:.1f}min")

    # dedup analysis: same source asset + within N frames of another candidate + same CLIP category family
    print("\nDEDUP / EPISODE ANALYSIS (R3 candidates only)")
    r3 = [e for e in data if e["router"]["r3_not_story_critical"]]
    by_asset = {}
    for e in r3:
        by_asset.setdefault(e["path"], []).append(e)
    clusters = 0
    total_in_clusters = 0
    for items in by_asset.values():
        items.sort(key=lambda e: e["start_frame"])
        i = 0
        while i < len(items):
            j = i
            while j + 1 < len(items) and items[j + 1]["start_frame"] - items[j]["start_frame"] < 500 and \
                    items[j + 1]["clip_pred"]["top1"] == items[i]["clip_pred"]["top1"]:
                j += 1
            cluster_size = j - i + 1
            if cluster_size > 1:
                clusters += 1
                total_in_clusters += cluster_size
            i = j + 1
    print(f"  R3 candidates: {len(r3)}")
    print(f"  clusters found (same asset, <500 frames apart, same top1 category): {clusters}")
    print(f"  candidates inside a cluster: {total_in_clusters}")
    reduction = total_in_clusters - clusters  # if each cluster reduced to 1 representative
    print(f"  potential reduction if 1-representative-per-cluster: {reduction} candidates "
          f"({100*reduction/len(r3):.0f}% of R3 total)")
    known_positive_paths_frames = [(e["path"], e["start_frame"]) for e in r3 if e["frame_index"] in known_positive_indices]
    print(f"  known positives' (path, start_frame): {known_positive_paths_frames}")

    # drone breakdown
    print("\nDRONE BREAKDOWN")
    drone_total = sum(1 for e in data if "drone" in e["path"].lower())
    drone_r3 = sum(1 for e in r3 if "drone" in e["path"].lower())
    non_drone_total = len(data) - drone_total
    non_drone_r3 = len(r3) - drone_r3
    print(f"  drone candidates in 156-sample: {drone_total}, escalated by R3: {drone_r3} "
          f"({100*drone_r3/drone_total:.0f}% of drone)" if drone_total else "  no drone candidates in sample")
    print(f"  non-drone candidates: {non_drone_total}, escalated by R3: {non_drone_r3} "
          f"({100*non_drone_r3/non_drone_total:.0f}% of non-drone)" if non_drone_total else "")

    Path("tools/fixtures/p5_4_budget_router_results.json").write_text(
        json.dumps({"ranked_frame_indices": [e["frame_index"] for e in ranked]}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
