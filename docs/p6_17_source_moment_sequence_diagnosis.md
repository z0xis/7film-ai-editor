# PACKAGE 06.17 — SOURCE-MOMENT / EVENT-SEQUENCE GRAMMAR

START HEAD: `f019942`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Diagnosed the P6.16 first-dance/source-moment failure, attempted one bounded fix, and — because both
variants failed a hard gate — **shipped no planner change**. The evidence identifies chronology
(drone missing timecode) as the true blocker. Shadow-only; no timeline/Resolve/DB write; no persisted
timeline; planner reverted to the P6.16 state (0-line diff). Fixture:
`tools/fixtures/p6_17_sequence_diagnosis.json`; tests: `tests/test_p6_17_sequence_diagnosis.py`.

--------------------------------
## P6.16 BASELINE
--------------------------------

duration 162.9 s · items 132 · song2 60 items · reception coherent · first dance represented by
camera crowd-dance (C7388/C7389) · one DJI_0528 shot reused 3×. Reproduced deterministically before
any change.

--------------------------------
## PRIMARY SEQUENCE FAILURE
--------------------------------

classification: **CHRONOLOGY_DOMINATES_TRUE_EVENT** (drone missing timecode), with a secondary
**REDUNDANCY_GUARD_TOO_WEAK**. evidence below.

--------------------------------
## FIRST-DANCE PRE-FIX
--------------------------------

first_dance shortlist members split cleanly by chronology:
- cameras C7388 / C7384 / C7389 / C7276: **timecoded** (`day_position` ~0.78 → anchored to the
  reception progress); C7388 = generic crowd/party dancing.
- drones DJI_0528 (isolated couple-alone first dance) / DJI_0529 (couple on floor): **no timecode**
  (`day_position = None`).

score/sequence reasons: the isolated first-dance drone DJI_0528 (`df3a49bf`) has the strongest
content (`story_relevance 0.928`, tq 0.556) but carries `reuse_penalty 0.247` — and its own use count
is 0, so the entire penalty is `ASSET_REUSE_PENALTY(0.06) × asset_reuse_count(~4)`, incurred because
**another DJI_0528 shot (a kiss angle) was over-used 3×**, inflating the asset counter and suppressing
the asset's distinct sibling shots. Separately, being timecodeless, the drone cannot anchor to the
reception, so the timecoded crowd camera wins the first_dance slot.

--------------------------------
## FIX (attempted, not shipped)
--------------------------------

file: `apps/api/sevenfilm/services/planner.py` (`reuse_penalty`). logic: waive/reduce
`ASSET_REUSE_PENALTY` for moment shots so a distinct angle of an owed moment competes on its own
merit (the per-shot reuse charge kept), mirroring the existing "a moment the film owes is never
suppressed for X" pattern. why general / bounded: one condition on `moment_shot`, no IDs, applies to
any moment.

--------------------------------
## UNIT REPRODUCTION (before/after of the attempt)
--------------------------------

- **full waiver:** first dance → isolated drones (DJI_0528/DJI_0529); redundancy fixed (max same-shot
  reuse 1); BUT **reception COLLAPSED to 94.4 s / 0 song2** — moment shots front-loaded the day and
  the deliverable-share stop fired early. **REJECTED** by the section-26 reception regression gate.
- **half waiver (× 0.5):** reception preserved (163.4 s / 59 song2); DJI_0529 enters first_dance; BUT
  DJI_0529 (a reception dance drone) is placed at **26.4 s in the day/prep section** — chronologically
  misplaced because it has no `day_position` to anchor it to the reception; and the DJI_0528 kiss shot
  is still reused 3×. **REJECTED** — not a clean improvement; introduces a misplaced drone and does
  not fix redundancy.

Because both variants fail a hard gate, no planner change was shipped.

--------------------------------
## FIXED SHADOW
--------------------------------

**None shipped.** The planner remains at the P6.16 state (132 items / 162.9 s / 60 song2), verified by
a 0-line planner diff and by the P6.16 shadow reproducing exactly.

--------------------------------
## FIRST DANCE — RESULT
--------------------------------

classification: **GENERIC_DANCE_ONLY** (unchanged from P6.16). The planner still represents first
dance with timecoded camera crowd-dance; the genuine isolated first-dance drone cannot be correctly
placed because it has no timecode. A bounded scoring tweak either regresses reception or misplaces the
drone — it cannot chronologically anchor chronology-less event footage.

--------------------------------
## DJI_0529 / DJI_0528 / C7388 / C7389
--------------------------------

DJI_0528 / DJI_0529: genuine first-dance drone material, but timecodeless → float chronologically.
C7388 / C7389: timecoded crowd/party dance — valid PARTY shots (event identity ≠ isolated first
dance), which anchor correctly and win the first_dance slot.

--------------------------------
## CAKE / BOUQUET / SPARKLER (transfer)
--------------------------------

These are **camera** events (C7309 cake, C7451 bouquet, C7404 sparkler) — all **timecoded** — so they
place correctly and are not affected by the chronology gap. The sequence problem is concentrated on
the **chronology-less drone** reception material (first dance). This confirms the blocker is
chronology, not a general source-moment scoring defect.

--------------------------------
## SOURCE REUSE / NON-REDUNDANCY
--------------------------------

The DJI_0528 kiss shot reused 3× (P6.16 finding) persists at baseline. The attempted moment-reuse
relief did not cleanly fix it (full waiver fixed it but collapsed reception; half waiver left it).
Redundancy remains OPEN.

--------------------------------
## RECEPTION REGRESSION
--------------------------------

Preserved — because no change was shipped. (The full-waiver experiment's reception collapse is why it
was rejected.)

--------------------------------
## MUSIC-FIRST / TRANSITION / OUTRO
--------------------------------

Unchanged from P6.16 (no code change). Beat rigidity and transition polish remain carry-forwards.

--------------------------------
## V7 / P6.14 / P6.16 / P6.17
--------------------------------

| dimension | V7 | P6.14 old | P6.16 | P6.17 |
|---|---|---|---|---|
| duration | 122.76 s | 96.0 s | 162.9 s | 162.9 s (unchanged) |
| reception | full | absent | coherent | coherent |
| first dance | isolated drone seq | not selected | camera crowd | camera crowd (unchanged) |
| redundancy | forward reuse | n/a | one shot ×3 | one shot ×3 (unchanged) |
| planner change | — | — | early-stop fix | **none (rejected)** |

--------------------------------
## GRAMMAR GAP TABLE
--------------------------------

FALSE EARLY STOP: **SOLVED** (P6.16) · FORWARD SOURCE REUSE: PARTIAL · SOURCE-MOMENT CHOICE: OPEN ·
EVENT-SEQUENCE CONTINUITY: OPEN · REDUNDANCY: OPEN · CAUSAL ORDER: OPEN · ACTION-PHASE: OPEN ·
**CHRONOLOGY: OPEN — now the PRIMARY blocker for drone-covered events** · MUSIC TRANSITION: PARTIAL ·
BEAT RIGIDITY: OPEN.

--------------------------------
## SAFETY
--------------------------------

planner changed: **NO** (0-line diff). DB writes 0 · Resolve writes 0 · timeline writes 0. DB checksum
`e8798470…` and mtime `2026-09-18 21:07:36` unchanged; shots/features/embeddings 2638; 129-cut / V7 /
is edit unchanged; jobs 0 · Elenora 1405 · contamination 0. Temporary frames deleted; none committed.
Full suite 1124 passed, ruff clean.

--------------------------------
## READY FOR CONTROLLED CANDIDATE ROUGH CUT
--------------------------------

**NO** — first-dance representation is not materially more event-correct; a bounded scoring change
cannot place the chronology-less drone first-dance material. The chronology gap must be addressed
first.

READY FOR GENERAL PRODUCTION: **NO.**

--------------------------------
## FINAL VERDICT
--------------------------------

**C** — sequence/reuse logic *can* be nudged (the reuse relief moved the isolated drones into
contention), but **chronology still causes timecoded generic dance footage to beat the true
(chronology-less) first-dance drone material**, and forcing the drone in without chronology either
collapses reception or misplaces it. The genuine blocker for central first-dance storytelling is the
drones' missing timecode, which is out of P6.17's scope to reconstruct.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.18 — DRONE / MISSING-TIMECODE CHRONOLOGY (SHADOW ONLY)** — derive or infer a chronology /
day-position anchor for the 10 timecodeless drone clips (from content, ordering, or adjacent
timecoded material) so genuine drone event footage (first dance, reception) can be placed at the
correct story position, validated in shadow against V7 — WITHOUT reconstructing camera timecode or
changing production data. Redundancy and source-moment/action-phase remain secondary carry-forwards.

**DO NOT START.**
