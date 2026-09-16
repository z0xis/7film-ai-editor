"""P5.9: D4-FRCNN policy simulation (P5.5 atomic verifier AND Faster R-CNN independent
contradiction agreement) over the frozen 17-case set, for head-to-head comparison against
P5.8's D4-SSDLite result. Same P5.5 atomic reference values, same agreement-required logic.
"""

from __future__ import annotations

import json

QWEN_SUPPORTED_EVENTS = {"first_dance", "cake_cutting"}
P5_5_ATOMIC_STATUS = {
    "genuine_first_dance_C7450": "SUPPORTED",
    "genuine_first_dance_drone_A": "SUPPORTED",
    "genuine_first_dance_drone_B": "SUPPORTED",
    "genuine_first_dance_C7261": "CONTRADICTED",
    "genuine_cake_cutting_C7309": "SUPPORTED",
    "HARMFUL_solo_performer_C7349": "CONTRADICTED",
}


def evidence_status(summary_at_t: dict, dominant_key: str) -> str:
    total = summary_at_t["total_person_count"]
    dominant = summary_at_t[dominant_key]
    if total == 0:
        return "UNKNOWN"
    if dominant <= 1:
        return "CONTRADICTED"
    return "SUPPORTED"


def run_d4_frcnn(results: list[dict], t: str, dominant_key: str) -> list[tuple]:
    rows = []
    for case in results:
        if case["event"] not in QWEN_SUPPORTED_EVENTS:
            continue
        human = case["human_verdict"]
        frcnn_status = evidence_status(case["threshold_summary"][t], dominant_key)
        p55 = P5_5_ATOMIC_STATUS.get(case["case_id"])
        decision = "ABSTAIN" if (p55 == "CONTRADICTED" and frcnn_status == "CONTRADICTED") else "ACCEPT"
        rows.append((case["case_id"], decision, human))
    return rows


def score(rows: list[tuple]) -> dict:
    tp = fp = abstained_tp = abstained_fp = 0
    for _cid, decision, human in rows:
        if decision == "ACCEPT" and human == "TP":
            tp += 1
        elif decision == "ACCEPT" and human == "FP":
            fp += 1
        elif decision == "ABSTAIN" and human == "TP":
            abstained_tp += 1
        elif decision == "ABSTAIN" and human == "FP":
            abstained_fp += 1
    total = tp + fp
    precision = tp / total if total else None
    coverage_total = tp + abstained_tp
    coverage = tp / coverage_total if coverage_total else None
    return {"accepted_tp": tp, "accepted_fp": fp, "abstained_tp": abstained_tp,
            "abstained_fp": abstained_fp, "precision": precision, "coverage": coverage}


def main() -> int:
    with open("tools/fixtures/p5_9_frcnn_results.json") as f:
        results = json.load(f)
    for t in ["0.2", "0.35", "0.5", "0.7"]:
        for dk in ["dominant_ratio_0.25", "dominant_ratio_0.4", "dominant_ratio_0.6"]:
            rows = run_d4_frcnn(results, t, dk)
            s = score(rows)
            harmful = next((d for cid, d, h in rows if cid == "HARMFUL_solo_performer_C7349"), None)
            c7261 = next((d for cid, d, h in rows if cid == "genuine_first_dance_C7261"), None)
            print(f"T={t} {dk}: {s} harmful={harmful} c7261={c7261}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
