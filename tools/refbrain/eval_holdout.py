"""P6.22 -- leave-one-project-out holdout + retrieval ablation (shadow only, read-only).

Builds the 15A target context from 15A's OWN footage (no human-edit leakage), generates the Stage-1
plan with V7 + is edit EXCLUDED from retrieval, and compares the abstract plan to V7's structure ONLY
AFTER generation. Also runs the retrieval ablation (retrieval / off / aggregate). Writes a small
summary fixture. No DB / Resolve / timeline write.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
DB = ROOT / "data" / "sevenfilm.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
PROFILE = ROOT / "data" / "references" / "7film-style-profile.json"
CORPUS = ROOT / "data" / "reference_editor" / "corpus" / "corpus.json"
OUT = ROOT / "tools" / "fixtures" / "p6_22_holdout.json"

from tools.refbrain.retrieval import Retriever
from tools.refbrain.schema import CATEGORY_EVENT
from tools.refbrain.stage1 import Stage1Planner, TargetContext

HELDOUT_15A = ["IS EDIT - AI CUT V7", "is edit"]  # 15A human edits -- never in 15A retrieval


def _target_context_15a() -> TargetContext:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cats = [r[0] for r in con.execute(
        """SELECT DISTINCT s.category FROM shots s JOIN media_assets m ON m.id=s.asset_id
           WHERE m.project_id=?""", (P15,)).fetchall()]
    names = [r[0] for r in con.execute(
        """SELECT DISTINCT m.file_name FROM shots s JOIN media_assets m ON m.id=s.asset_id
           WHERE m.project_id=?""", (P15,)).fetchall()]
    con.close()
    events = {CATEGORY_EVENT.get(c, "OTHER") for c in cats}
    if any(n.startswith("C7309") for n in names):
        events.add("CAKE")
    if any(n.startswith("DJI_0528") for n in names):
        events.add("FIRST_DANCE")
    events.add("OUTRO")
    # music: two songs used by the current 15A pipeline (0-108, 108-180); energy low->high
    music = [{"energy": "low", "start_s": 0.0, "end_s": 108.0},
             {"energy": "high", "start_s": 108.0, "end_s": 180.0}]
    return TargetContext(project="15 Agustos", target_duration_s=180.0,
                         available_events=sorted(events), music_sections=music,
                         chronology_span=(0.0, 1.0))


def _v7_structure() -> dict:
    """Algorithmically extract V7's event order (post-hoc ground truth). Not hardcoded facts."""
    corpus = json.loads(CORPUS.read_text())
    v7 = [s for s in corpus["shots"] if s["reference_id"] == "IS EDIT - AI CUT V7"]
    v7.sort(key=lambda s: s["shot_index"])
    n = len(v7)
    seq = []
    for i, s in enumerate(v7):
        pos = i / n
        name = s["source_asset"] or ""
        cat = s["category"] or ""
        if pos >= 0.92:
            ev = "OUTRO"
        elif name.startswith("C7309"):
            ev = "CAKE"
        elif name.startswith("DJI_0528") and pos > 0.45:
            ev = "FIRST_DANCE"
        elif cat == "party":
            ev = "PARTY_KINA"
        elif cat == "ceremony":
            ev = "CEREMONY"
        elif cat in ("bride_prep", "groom_prep", "bride", "groom", "detail"):
            ev = "PREPARATION"
        else:
            ev = "OTHER"
        seq.append(ev)
    dedup = [e for i, e in enumerate(seq) if i == 0 or e != seq[i - 1]]
    ordered = [e for e in dedup if e != "OTHER"]
    return {"n_shots": n, "song_count": 1, "event_order_raw": dedup, "event_order": ordered}


def _lcs(a, b):
    m = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            m[i][j] = m[i + 1][j + 1] + 1 if a[i] == b[j] else max(m[i + 1][j], m[i][j + 1])
    return m[0][0]


def _compare(plan_events, v7_events):
    pe = [e for i, e in enumerate(plan_events) if e != "OTHER" and (i == 0 or e != plan_events[i - 1])]
    lcs = _lcs(pe, v7_events)
    covered = [e for e in v7_events if e in pe]
    return {"plan_event_order": pe, "v7_event_order": v7_events,
            "event_coverage": round(len(set(covered)) / max(1, len(set(v7_events))), 3),
            "order_lcs": lcs, "order_agreement": round(lcs / max(1, len(v7_events)), 3)}


def run() -> dict:
    ctx = _target_context_15a()
    profile = json.loads(PROFILE.read_text())
    medians = profile.get("section_median_shot_duration_seconds", {})

    # HOLDOUT retriever: 15A human edits excluded
    r_holdout = Retriever(exclude_references=HELDOUT_15A)
    plan_holdout = Stage1Planner(r_holdout, mode="retrieval").plan(ctx)

    # ablation
    plan_off = Stage1Planner(None, mode="off").plan(ctx)
    plan_agg = Stage1Planner(None, mode="aggregate", section_medians=medians).plan(ctx)

    v7 = _v7_structure()
    cmp_holdout = _compare(plan_holdout["event_order"], v7["event_order"])
    cmp_off = _compare(plan_off["event_order"], v7["event_order"])
    cmp_agg = _compare(plan_agg["event_order"], v7["event_order"])

    # leakage guard: no held-out reference appears in the holdout retrieval
    active = set(plan_holdout["active_references"])
    leak = [r for r in HELDOUT_15A if r in active]

    result = {
        "target_context": {"available_events": ctx.available_events,
                           "target_duration_s": ctx.target_duration_s},
        "heldout_references": HELDOUT_15A,
        "leakage_check": {"held_out_present_in_retrieval": leak, "clean": leak == []},
        "active_reference_count_holdout": len(active),
        "v7_structure": v7,
        "plan_holdout": plan_holdout,
        "comparison": {"holdout_vs_v7": cmp_holdout, "off_vs_v7": cmp_off, "aggregate_vs_v7": cmp_agg},
        "ablation": {
            "retrieval_role_order": plan_holdout["role_order"],
            "off_role_order": plan_off["role_order"],
            "aggregate_role_order": plan_agg["role_order"],
            "retrieval_durations": [s["duration_target_s"] for s in plan_holdout["sequences"]],
            "off_durations": [s["duration_target_s"] for s in plan_off["sequences"]],
            "aggregate_durations": [s["duration_target_s"] for s in plan_agg["sequences"]],
            "retrieval_equals_off": [s["duration_target_s"] for s in plan_holdout["sequences"]]
                                    == [s["duration_target_s"] for s in plan_off["sequences"]],
        },
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    r = run()
    print(json.dumps({
        "available_events": r["target_context"]["available_events"],
        "leakage_clean": r["leakage_check"]["clean"],
        "active_refs_holdout": r["active_reference_count_holdout"],
        "holdout_vs_v7": r["comparison"]["holdout_vs_v7"],
        "retrieval_equals_off": r["ablation"]["retrieval_equals_off"],
        "role_order": r["plan_holdout"]["role_order"],
    }, indent=2))
