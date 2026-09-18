# PACKAGE 06.16 — FALSE-EARLY-STOP / HIGH-VALUE RECEPTION CONTINUATION

START HEAD: `85537d1`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

One bounded control-flow fix to `build_timeline` so the planner no longer ends the film at a local
cut-run failure once past the minimum deliverable share, validated in shadow only. No timeline/
Resolve/DB write; no weight/threshold/model/music/timecode change; no persisted timeline. Code:
`apps/api/sevenfilm/services/planner.py`; harness: `tools/p6_16_shadow.py`; fixtures:
`tools/fixtures/p6_16_fixed_shadow.json` (fixed) vs `p6_14_shadow_plan.json` (restored baseline);
tests: `tests/test_p6_16_early_stop_fix.py`.

--------------------------------
## BASELINE
--------------------------------

duration ~96.0 s · items 59 · song2 (>=108 s): 0 · deterministic · stop point ~96 s ·
warning "edit ended at 96s; target 180s; no usable place remained". Reproduced identically before
touching the planner.

--------------------------------
## FALSE STOP
--------------------------------

failed slot: the cut-run window gate (`_cut_run_score > UNUSABLE_RUN_SCORE`) evaluated at the
current requested cut length `desired`. candidate funnel: usable→0 **at that length** (0 source
exhaustions; the pool was not empty). local gate: cut-run window quality for `desired`. global
break: `elif current_frame >= target_duration * MINIMUM_DELIVERABLE_SHARE (0.5): break` — one local
slot failure ended the whole film, contradicting the code's own comment two lines above ("a shot
stays in the pool for the next cut, where a different length may reach a better stretch").

--------------------------------
## FUTURE STORY EVIDENCE
--------------------------------

planner-native: 2620/2638 usable shots, second music section (108–180 s) unused, later
chronology/moment windows unreached. is-edit reference (P6.15.2): 39 strong reception selects the
editor had beyond V7. V7 reference (P6.15.1): coherent first dance / cake / kına / bouquet / drone
outro all live after ~80 s. So the ~96 s stop was strongly false — high-value story remained.

--------------------------------
## FIX
--------------------------------

file: `apps/api/sevenfilm/services/planner.py` (the cut-run block, ~line 2329).
logic: when no shot passes the cut-run gate for the current `desired` length, before the global
break, test whether any shot passes the gate at the **minimum allowed cut** (`MIN_CUT_SECONDS`). If
one does → this is a **local slot failure**, not global exhaustion: set `desired = MIN_CUT_SECONDS`,
keep that shot pool, and continue (a shorter cut — exactly what the faster reception wants). Only
when nothing can hold even a minimum cut does the enough-to-deliver early stop still apply.
global-stop condition: `usable_at_min` empty AND past minimum deliverable share (unchanged guard).
why bounded: one extra cut-run pass at a fixed length; deterministic; no IDs; no fixed duration; no
new weights/thresholds; preserves both quality gates (`UNUSABLE_RUN_SCORE`, `MINIMUM_DELIVERABLE_
SHARE`). why general: keys entirely off existing planner concepts (`_cut_run_score`,
`MIN_CUT_SECONDS`), applies to any project.

--------------------------------
## UNIT / REPRODUCTION
--------------------------------

The before/after shadow contrast on identical real inputs is the reproduction: old planner stops at
96 s with 0 second-song items; fixed planner continues into the reception. A source-shape test also
guards that the min-cut escape precedes the global break (no regression to an unconditional break).

--------------------------------
## FIXED SHADOW
--------------------------------

duration **162.9 s** · items **132** · deterministic. song1 (0–108 s): day/prep/couple. song2
(108–180 s): **60 items** of reception (was 0). It stops at 162.9 s (< 180 s target) for a genuine
reason now, not the false early break.

--------------------------------
## RECEPTION
--------------------------------

coverage: 60 song2 items. quality: bounded visual audit of 6 spread selections (C7367 party,
C7338/C7350 kına dance, C7366/C7436 groom/couple party, C7452 family finale) — all **genuine,
coherent, energetic reception/kına content, not filler and not repeated day material**.
non-redundancy: 130/2638 shots used → strong material remains unused (no overfill).

--------------------------------
## FIRST DANCE
--------------------------------

DJI_0528: selected (6 uses; one first-dance/kiss shot reused 3× across the reception). DJI_0529:
selected (4 distinct shots). C7388/C7389: selected as the first_dance **moment** members.
sequence result: **PARTIAL** — the planner now reaches the reception and selects dance material, but
the first_dance moment is represented by camera crowd-dance shots (C7388/C7389), not the isolated
first-dance-drone → guests-join sequence V7 builds; the isolated drone shot is reused as "kiss".
So it selects items carrying the label, but does not yet build the believable isolated first-dance
STORY. This is a source-moment/sequence-grammar gap (carried forward — out of P6.16 scope).

--------------------------------
## CAKE
--------------------------------

C7309 still selected (positive control holds). source-moment: the shadow's C7309 selection is the
DB shot boundary, not necessarily the exact cutting-action frame V7 chose — the action-phase choice
remains a carry-forward (not solved here).

--------------------------------
## PARTY / KINA / NIGHT
--------------------------------

**COHERENT** — real high-energy kına/party/couple material with night atmosphere and crowd energy
(visually confirmed), matched to the second song's energy.

--------------------------------
## DRONE
--------------------------------

21 drone items across 7 distinct drone assets, used as establishing/transition/party/closing
punctuation (up from 14 items in the truncated baseline). Narratively meaningful, not spammed.

--------------------------------
## BOUQUET / CAUSALITY
--------------------------------

C7450/C7451 bouquet shots enter the late plan; a general causal-order model was NOT added (out of
scope). No catastrophic backward ordering was observed, but bouquet phase-ordering is a
carry-forward for the source-moment/sequence package.

--------------------------------
## FORWARD SAME-SOURCE REUSE
--------------------------------

22 sources reused (31 extra uses): DJI_0528 ×6, DJI_0529 ×4, DJI_0530 ×3, C7450 ×3, etc. Mostly
different shots/segments of a source (forward). One case (DJI_0528 first-dance shot reused 3×) is
borderline redundant — bounded (`max reuse per shot ≤ 5`), not runaway, but a signal for the
source-moment package.

--------------------------------
## STRONG UNUSED SHOTS
--------------------------------

130 / 2638 shots used → **2508 unused**, including many strong reception selects (P6.15.2's 39
dropped-by-V7 pool and more). Positive evidence the fix did NOT "use everything".

--------------------------------
## MUSIC TRANSITION
--------------------------------

The plan now spans both songs (song2 populated), so a transition exists where the baseline had
none. Its smoothness/energy match was not separately engineered (no music-offset change); transition
polish is a carry-forward, not blocking the early-stop fix.

--------------------------------
## INTRO / OUTRO
--------------------------------

intro: unchanged from the coherent baseline head (no regression). outro: ends on a reception family
celebration (C7452) with bouquet (C7451) and drone (DJI_0529) nearby — a plausible reception closing
beat, though not the deliberate V7 drone pull-out bookend (bookend structure is a carry-forward).

--------------------------------
## MUSIC-FIRST
--------------------------------

Not re-measured in depth; beat-rigidity (~91 % in P6.14 vs ~61 % reference) is carried forward and
not addressed by this control-flow fix.

--------------------------------
## V7 / OLD SHADOW / FIXED SHADOW
--------------------------------

| dimension | V7 | old shadow (P6.14) | fixed shadow (P6.16) |
|---|---|---|---|
| duration | 122.76 s | 96.0 s | 162.9 s |
| items | 108 (87 cuts) | 59 | 132 |
| second song used | yes (~43 s) | 0 | 60 items |
| reception | full, coherent | absent | coherent (visual) |
| first dance | isolated drone seq | scored, not selected | selected (camera) — PARTIAL |
| cake | action frame | selected | selected |
| party/kına | yes | no | yes |
| drone | 7 assets punctuation | 14 items | 21 items / 7 assets |
| forward reuse | intentional | minimal | present (1 borderline ×3) |
| strong unused | yes (65 dropped) | n/a | yes (2508 unused) |
| beat rigidity | ~61 % ref | ~91 % | carry-forward |

Success is not V7 shot overlap; it is reaching coherent reception without filler while leaving
strong shots unused — which the fix achieves.

--------------------------------
## GRAMMAR GAP TABLE (after fix)
--------------------------------

| grammar | status |
|---|---|
| FALSE EARLY STOP | **SOLVED** |
| FORWARD SOURCE REUSE | PARTIAL (works; one ×3 redundant) |
| ACTION-PHASE SELECTION | OPEN |
| EVENT IMPORTANCE | PARTIAL (moments now reach reception) |
| SEQUENCE FIT | OPEN (first-dance sequence not built) |
| CAUSAL ORDER | OPEN |
| MUSIC-ENERGY FIT | PARTIAL |
| NON-REDUNDANCY | PARTIAL |
| ADAPTIVE DURATION | PARTIAL (reaches 162.9 s, not forced; stops naturally) |

--------------------------------
## FALSE-EARLY-STOP STATUS
--------------------------------

**FIXED.** Same real inputs: old planner 96 s / 0 second-song items → fixed planner 162.9 s / 60
second-song reception items, deterministic, no filler, strong shots left unused, both quality gates
preserved, no source spam beyond a bounded reuse.

--------------------------------
## SAFETY
--------------------------------

DB: checksum `e8798470…` and mtime `2026-09-18 21:07:36` unchanged; shots 2638 · features 2638 ·
embeddings 2638; persisted AI Rough Cut 129 unchanged; V7 / is edit unchanged; jobs 0 · Elenora
1405 · contamination 0. Resolve writes 0 · timeline writes 0 (shadow harness is write-hardened and
never persists). Full suite 1117 passed, ruff clean, `git diff --check` clean.

--------------------------------
## READY FOR CONTROLLED CANDIDATE ROUGH CUT
--------------------------------

**CONDITIONAL.** The false early stop is genuinely fixed and the reception is coherent, but the
central first-dance storytelling (isolated-drone sequence, action-phase moment, forward-reuse
grammar) is still imperfect — the planner selects reception/first-dance *items* without building the
V7-grammar *sequence*. A source-moment/sequence-grammar pass should precede a candidate rough cut.

READY FOR GENERAL PRODUCTION: **NO.**

--------------------------------
## FINAL VERDICT
--------------------------------

**B** — the false early stop is fixed (the P6.16 objective): the planner now reaches high-value,
coherent reception naturally, leaves strong shots unused, and avoids filler, with both quality gates
intact and 0 writes. But the sequence / source-moment logic still under-builds central reception
storytelling (first dance represented by camera crowd-dance rather than the isolated-drone sequence;
one drone shot reused 3×; action-phase/causal grammar unaddressed). That is the next blocker.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **CONDITIONAL.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.17 — SOURCE-MOMENT / SEQUENCE GRAMMAR FIX (SHADOW ONLY)** — teach the planner to build event
sequences (isolated first dance → guests-join via forward reuse; action-phase moment choice; bounded
non-redundant reuse; causal ordering), validated in shadow against V7, before any candidate rough
cut. Beat rigidity and music-transition polish are secondary carry-forwards.

**DO NOT START.**
