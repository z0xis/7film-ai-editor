"""P5.8: D0-D4 policy simulation over the SSDLite bake-off results. Pre-registered policies,
evaluated (not threshold-fished) against the frozen 17-case set. SSDLite is used only as a
presence/contradiction signal -- it never grants ACCEPT by itself (person or cake detection is
not event verification, see docs/p5_8 report section 23).
"""

from __future__ import annotations

import json

QWEN_SUPPORTED_EVENTS = {"first_dance", "cake_cutting"}
# P5.5's atomic-verifier (V1) result for the same 10 cases it evaluated -- frozen from that
# package, reused here unmodified for D3/D4 comparison. Cases outside that 10 default to
# "not_evaluated" (D3/D4 only apply where a P5.5 atomic result actually exists).
P5_5_ATOMIC_STATUS = {
    "genuine_first_dance_C7450": "SUPPORTED",
    "genuine_first_dance_drone_A": "SUPPORTED",
    "genuine_first_dance_drone_B": "SUPPORTED",
    "genuine_first_dance_C7261": "CONTRADICTED",  # P5.5's known false contradiction
    "genuine_cake_cutting_C7309": "SUPPORTED",
    "HARMFUL_solo_performer_C7349": "CONTRADICTED",  # P5.5's known correct catch
}


def evidence_status(summary_at_t: dict, dominant_key: str) -> str:
    total = summary_at_t["total_person_count"]
    dominant = summary_at_t[dominant_key]
    if total == 0:
        return "UNKNOWN"
    if dominant <= 1:
        return "CONTRADICTED"
    return "SUPPORTED"


def run_policies(results: list[dict], t: str, dominant_key: str) -> dict:
    outcomes = {p: [] for p in ("D0", "D1", "D2", "D4")}
    for case in results:
        if case["event"] not in QWEN_SUPPORTED_EVENTS:
            continue  # unsupported events stay ABSTAIN regardless, unchanged since P5.3
        human = case["human_verdict"]
        ssd_status = evidence_status(case["threshold_summary"][t], dominant_key)
        ssd_total = case["threshold_summary"][t]["total_person_count"]

        # D0: P5.4 allowlist baseline -- always accept a supported-event Qwen call.
        outcomes["D0"].append((case["case_id"], "ACCEPT", human))

        # D1: naive hard veto if raw total person count < 2.
        d1 = "ABSTAIN" if ssd_total < 2 else "ACCEPT"
        outcomes["D1"].append((case["case_id"], d1, human))

        # D2: reliability-aware -- only veto on a genuine CONTRADICTED status (not on UNKNOWN).
        d2 = "ABSTAIN" if ssd_status == "CONTRADICTED" else "ACCEPT"
        outcomes["D2"].append((case["case_id"], d2, human))

        # D4: P5.5 atomic verifier + SSDLite agreement-required -- abstain only when BOTH
        # independently say CONTRADICTED. If P5.5 has no result for this case, SSDLite alone
        # cannot trigger D4 (no agreement possible without both signals).
        p55 = P5_5_ATOMIC_STATUS.get(case["case_id"])
        if p55 == "CONTRADICTED" and ssd_status == "CONTRADICTED":
            d4 = "ABSTAIN"
        else:
            d4 = "ACCEPT"
        outcomes["D4"].append((case["case_id"], d4, human))

    return outcomes


def score(outcomes: list[tuple]) -> dict:
    tp = fp = abstained_tp = abstained_fp = 0
    for _cid, decision, human in outcomes:
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
    with open("tools/fixtures/p5_8_ssdlite_results.json") as f:
        results = json.load(f)
    for t in ["0.2", "0.35", "0.5", "0.7"]:
        for dk in ["dominant_ratio_0.25", "dominant_ratio_0.4", "dominant_ratio_0.6"]:
            outcomes = run_policies(results, t, dk)
            print(f"\n--- T={t} {dk} ---")
            for policy, rows in outcomes.items():
                s = score(rows)
                harmful = next((d for cid, d, h in rows if cid == "HARMFUL_solo_performer_C7349"), None)
                print(f"  {policy}: {s}  harmful_C7349={harmful}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
