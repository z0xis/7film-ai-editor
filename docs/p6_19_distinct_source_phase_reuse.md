# PACKAGE 06.19 — REDUNDANCY / DISTINCT-SOURCE-PHASE REUSE FIX

START HEAD: `110844d`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

The asset-reuse penalty now counts **distinct source phases** (distinct shot ids) drawn from an asset,
instead of raw uses — so over-playing one phase no longer inflates the asset counter against a
genuinely distinct angle of the same asset. The per-shot repeat charge (`REUSE_PENALTY`) is untouched,
so repeating one phase is still penalised. Bounded (7-line change to `planner.py`), no full asset-reuse
waiver (the P6.17 failure), no chronology change (the P6.18 estimator is frozen). Validated in shadow
against the real production state, two ways, with the P6.18 HIGH chronology overlay applied in one.
Tool: `tools/p6_19_shadow.py`; fixtures: `tools/fixtures/p6_19_{reuse_fix_shadow,reuse_fix_high_shadow,
shadow_summary}.json`; tests: `tests/test_p6_19_distinct_source_phase_reuse.py`.

--------------------------------
## THE MISATTRIBUTION (confirmed)
--------------------------------

In the P6.16 baseline, asset **DJI_0528** is used 6× but is only **4 distinct source phases** — shot
`b2563ae4` (a kiss angle) repeats **3×**. The old accounting fed `asset_usage[asset]` (raw uses = 6)
into `asset_reuse_count`, so every *distinct* sibling of DJI_0528 — including the isolated first-dance
drone `df3a49bf` (story_relevance 0.928, own use count 0) — inherited the over-used shot's debt
(≈ `ASSET_REUSE_PENALTY 0.06 × ~4`). That is the P6.17 finding: the sibling was suppressed by a
different, over-used shot of the same asset, not by its own repetition.

--------------------------------
## THE FIX
--------------------------------

file: `apps/api/sevenfilm/services/planner.py`. Shots are non-overlapping source segments, so a
distinct shot id **is** a distinct, non-overlapping source phase. Track the set of distinct phases
drawn per asset (`asset_phases[asset_id] = {selected shot ids}`) and feed
`len(asset_phases[asset_id])` — not `asset_usage[asset_id]` — into `asset_reuse_count` (the free
trailing-run subtraction is unchanged). A repeat of one phase no longer grows the count; it stays
charged per-shot by `REUSE_PENALTY × reuse_count`. General (no ids, no moment special-case), bounded
(7 lines), and it distinguishes same-shot / distinct-phase reuse exactly as the package asked, using
existing shot-segment identity rather than moment labels (the rejected P6.17 route).

--------------------------------
## SHADOW A / B
--------------------------------

| condition | items | dur | song2 | deterministic | plan vs baseline | DB checksum |
|---|---|---|---|---|---|---|
| baseline (P6.16) | 132 | 162.9 s | 60 | yes | — | e8798470… |
| A reuse-fix only | 132 | 162.9 s | 60 | yes | **identical shot-for-shot** | e8798470… (unchanged) |
| B reuse-fix + P6.18 HIGH | 132 | 162.9 s | 60 | yes | **identical shot-for-shot** | e8798470… (unchanged) |

Both conditions reproduce the accepted plan exactly, byte-for-byte on the 132-item shot sequence.

--------------------------------
## RECEPTION REGRESSION
--------------------------------

**None.** song2 stays 60, duration 162.9 s, 132 items, deterministic, in both A and B. The P6.16
coverage the user required to protect is fully preserved — the fix removes the misattribution without
collapsing reception (unlike the P6.17 full waiver) or front-loading.

--------------------------------
## FIRST DANCE — RESULT
--------------------------------

classification: **GENERIC_DANCE_ONLY (unchanged).** The isolated first-dance drone `df3a49bf` still
does not win the first-dance slot, even with the reuse relief and the HIGH chronology overlay applied
together. The distinct-phase relief is ≈ 0.12 of score; the residual gap to the timecoded crowd-dance
camera (C7388/C7389, `day_position` 0.786, correctly anchored to the reception) is larger, and the
inferred drone `day_position` (≈ 0.41, P6.18) anchors it *before* the reception. As instructed, first
dance was **not forced** — no gate was bent to move it.

--------------------------------
## WHY SHIP AN OTHERWISE-NEUTRAL CHANGE
--------------------------------

The change is behaviourally neutral on *this* shoot but is a strict **correctness** fix to the reuse
accounting: it removes a real cross-shot penalty misattribution (proved present: DJI_0528 6 uses / 4
phases / one shot ×3) that would suppress distinct angles on any input where one phase is over-used.
It is bounded, general, deterministic, passes every hard gate (no reception regression, plan
unchanged, DB untouched), and keeps same-phase repetition charged. This is materially different from
P6.17, where every variant tripped a gate and nothing shipped. Here the fix is safe, so it ships.

--------------------------------
## SAFETY
--------------------------------

planner diff: **7 lines** (accounting only; no waiver, no chronology, no moment special-case). DB
writes 0 · Resolve writes 0 · timeline writes 0 · chronology persisted: none (HIGH overlay in-memory
only). DB checksum `e8798470…` and mtime `2026-09-18 21:07:36` unchanged; shots/features/embeddings
2638; 129-cut / V7 / is edit unchanged; jobs 0 · Elenora 1405 · contamination 0. Accepted P6.14 /
P6.16 / P6.18 baseline fixtures untouched. `shadow_source_moment` WIP preserved. Full suite 1138
passed, ruff clean.

--------------------------------
## CANDIDATE-CUT DECISION
--------------------------------

The bounded distinct-source-phase reuse fix is **safe and shipped**. Chronology (P6.18) is validated
and injectable; the reuse misattribution (P6.17/P6.19) is now corrected. The production plan is the
accepted, coherent 132-item / 162.9 s / 60-song2 edit, deterministic and unchanged. First-dance
representation stays the timecoded crowd-dance — a known, documented limitation of missing drone
timecode, deliberately not forced.

**DECISION: PROCEED TO CONTROLLED CANDIDATE ROUGH CUT.** The planner research/fix track closes here —
no new broad planner-research package. The remaining first-dance-drone gap is a chronology-authoring
question for production design (P6.18 option B/C), not a scoring defect to keep chasing.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **YES** (with the documented first-dance limitation).
READY FOR GENERAL PRODUCTION: **NO** (first-dance drone chronology remains an authoring task).

--------------------------------
## FINAL VERDICT
--------------------------------

**B — proceed.** The redundancy misattribution is fixed correctly and safely (distinct-phase
accounting; no reception regression; plan unchanged shot-for-shot; DB untouched; suite green). First
dance is not perfect and was not forced. The candidate cut can proceed on the accepted plan with the
corrected reuse accounting in place. No further broad planner-research package is opened.
