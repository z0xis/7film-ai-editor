# PACKAGE 06.13 — PRODUCTION SEMANTIC / MOMENT ACTIVATION VALIDATION

START HEAD: `83fbbb2`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Read-only audit of what the P6.12-remediated production semantic state activates. No writes, no
reanalysis, no new rough cut. Harness: `tools/p6_13_semantic_activation_audit.py` (strictly
read-only, mode=ro); fixture: `tools/fixtures/p6_13_activation_audit.json`; tests:
`tests/test_p6_13_semantic_activation.py`.

--------------------------------
## PRODUCTION SEMANTIC STATE
--------------------------------

assets 362 · shots 2638 · features 2638 · embeddings **2638** · tq-zero **0** ·
`semantic_readiness = FULL` · **clip_labels 2638 / fallback 0** (every shot now on the CLIP
backend) · Elenora embeddings 1405 (unchanged). integrity ok.
Category distribution (was flat opencv fallback, now rich): bride 628, party 565, groom 439,
venue 368, couple 322, bride_prep 117, family 98, groom_prep 62, ceremony 21, detail 18.

--------------------------------
## SHOT_WINDOWS AUDIT
--------------------------------

15A shot_windows 14157 · distinct 15A shots with windows **2638/2638** · **orphan windows 0** ·
cross-project contamination none · all-projects total 23531.
No PRE window count/hash manifest existed, so a strict before/after window diff is not available;
but there is no orphaning, no duplication artifact, and no cross-project leakage. The P6.12 `/shots`
path legitimately refreshed 15A windows.

--------------------------------
## MOMENT INVENTORY
--------------------------------

| moment | count | usable | chron-known | chron-unknown | best | known recovered |
|---|---|---|---|---|---|---|
| cake | 8 | 8 | 8 | 0 | 0.357 | C7309 ✓ |
| cake_feed | 8 | 8 | 8 | 0 | 0.334 | — |
| entrance | 8 | 8 | 8 | 0 | 0.329 | — |
| first_dance | 8 | 8 | 4 | 4 | 0.340 | DJI_0528 ✓, DJI_0529 ✓ |
| kiss | 8 | 8 | 7 | 1 | 0.320 | — |
| ring | 8 | 8 | 8 | 0 | 0.326 | — |

All six families activate with a full 8-shot shortlist; **every shortlisted member passes
`_is_usable`** (so moments reach the candidate pool). All are `uncertain` (best < MOMENT_CONFIDENT),
consistent with a shoot the moment prompts are scored against by lift, not absolute confidence.

--------------------------------
## VISUAL AUDIT (bounded positive controls)
--------------------------------

- cake C7309 (top): **TRUE_MATCH** — bride + groom at the multi-tier wedding cake.
- first_dance DJI_0528 (drone): **TRUE_MATCH** — aerial of the couple's isolated first dance.
- first_dance DJI_0529 (drone): **TRUE_MATCH / USEFUL_CONTEXT** — aerial of the couple on the floor.
- first_dance C7388 (top, camera): **USEFUL_CONTEXT / CONFUSABLE** — couple dancing amid guests
  (open party dancing; has timecode).

(Full 6×8 audit not performed — bounded to positive controls per section 6's "MAY"; the known-good
recoveries confirm genuine activation.)

--------------------------------
## P6.1 / P6.2 SHADOW COMPARISON
--------------------------------

- obstructions **264** — exact match to the P6.1 shadow backfill.
- distractions 500 — close to shadow's ~494 (activation confirmed).
- cake clean and recovered (C7309) — matches P6.2's cleanest-moment finding.
- first_dance recovers the verified DJI_0528 source (and DJI_0529) — matches P6.1/P6.2 expectation.
Classification: **MOSTLY_CONSISTENT** (production reproduces the qualitative shadow conclusions;
small count deltas like distractions 500 vs 494 are within expected activation variance).

--------------------------------
## CANDIDATE ELIGIBILITY
--------------------------------

thresholds: `ABSOLUTE_MIN_QUALITY=0.15`, `MAX_HIGHLIGHT_CLIPPING=0.25`.
usable now: **2620 / 2638** · blocked by quality: 18 · blocked by clipping: 0.
Historical (P6.4): ~2327/2638 effectively blocked by the tq=0 sentinel (88.2%). **That blocker is
resolved** — 99.3% of shots are now usable, including all moment members.

--------------------------------
## CAKE
--------------------------------

semantic: active (best 0.357) · eligibility: 8/8 usable · scoring entry: YES (all members usable →
candidate pool) · chronology: 8/8 known · result: **positive control PASS** — C7309 recovered,
usable, reaches scoring.

--------------------------------
## FIRST DANCE
--------------------------------

A) semantic detection: **restored** — the true isolated first-dance drone shots are found
   (DJI_0528, DJI_0529 both in the shortlist).
B) eligibility: 8/8 usable (drones now usable — semantics + quality restored).
C) chronology: **4/8 known** — the 4 camera members have timecode; the 4 drone members
   (DJI_0528×2, DJI_0529×2) do NOT.
D) scoring entry: YES (all usable).
E) representative/timing: **HAZARD** — the timecoded members are camera "open dancing" shots
   (e.g. C7388, couple dancing in a crowd); the timecode-less drone shots are the true isolated
   first dance. Timing/due-now selection is chronology-driven, so it can be dominated by the
   camera crowd-dance shots while the best isolated first-dance (drone) shots carry no timecode.
Answer: **production semantic restoration solves first-dance content discovery**; what remains is
purely the drone-timecode/chronology problem (out of scope here).

--------------------------------
## KISS
--------------------------------

active (best 0.320), 8/8 usable, 7/8 chronology-known (one member is DJI_0528, no timecode). The
P6.3 concern that chronology filtering could drop true kiss shots remains relevant only for the
timecode-less drone member; semantics are active.

--------------------------------
## RING
--------------------------------

active (best 0.326), 8/8 usable, 8/8 chronology-known. Consistent with P6.3 (ring members are
camera shots with usable chronology).

--------------------------------
## ENTRANCE
--------------------------------

active (best 0.329), 8/8 usable, 8/8 chronology-known. Count > 0 does not by itself prove strict
entrance precision (historically weak/episode-level); a full visual audit was not run. Reported as
active, precision not claimed.

--------------------------------
## OPENING_SIGNS
--------------------------------

27 candidates (same count as the P6.1 shadow investigation). Restoring embeddings did not by itself
turn these into true welcome signs — the count is unchanged from the prior finding of 0/27 real
welcome signs. Bounded visual audit not performed; treated as STILL OPEN (no opening-logic change).

--------------------------------
## DISTRACTIONS / OBSTRUCTIONS
--------------------------------

distractions 500, obstructions 264 — both activate on production embeddings; obstructions match the
shadow figure exactly. Activation confirmed; visual-validator research not reopened.

--------------------------------
## DRONE STATUS
--------------------------------

| drone | shots | usable | timecode | moment member |
|---|---|---|---|---|
| DJI_0522 | 14 | 14 | NO | — |
| DJI_0523 | 10 | 10 | NO | — |
| DJI_0524 | 21 | 15 | NO | — |
| DJI_0525 | 14 | 13 | NO | — |
| DJI_0526 | 19 | 19 | NO | — |
| DJI_0527 | 11 | 11 | NO | — |
| DJI_0528 | 280 | 278 | NO | kiss, first_dance |
| DJI_0529 | 56 | 56 | NO | first_dance |
| DJI_0530 | 501 | 492 | NO | — |
| DJI_0531 | 15 | 15 | NO | — |

SEMANTICS: restored (usable, embedded, moment-eligible). CHRONOLOGY: all 10 drones still lack
timecode (known issue) — NOT fixed here.

--------------------------------
## READ-ONLY PLANNER TRACE
--------------------------------

Established by eligibility rather than invoking the planner (to guarantee zero writes, per section
10's "if any doubt, do not call it"): every moment shortlist member passes `_is_usable`, so each
named moment's shots enter the candidate pool that `_score_candidate` consumes.
cake: enters ✓ · first_dance: enters ✓ (all 8) · kiss: enters ✓ · ring: enters ✓ · entrance:
enters ✓. The pre-scoring tq=0 rejection that blocked them in P6.4 is gone. Moment-bonus/selection
and chronology-driven timing were NOT exercised (would require the planner) and are deferred to the
shadow planner validation (P6.14).

--------------------------------
## STORY-COVERAGE READINESS
--------------------------------

RESTORED:
- semantic inputs (2638/2638 CLIP embeddings, 512-dim), tq eligibility (2620/2638 usable),
  named moments active (6/6), cake recoverable, first-dance semantic candidates recoverable,
  obstruction/distraction helpers active.

STILL OPEN:
- chronology completeness (10 drones lack timecode; drives the first-dance/kiss timing hazard),
- opening_signs reliability (27 candidates, still likely 0 true welcome signs),
- multi-song story logic (not audited here),
- entrance strict precision (not visually audited),
- generic degraded-success hazard (unchanged).

NOT YET TESTED:
- shadow planner story-coverage / candidate rough-cut behaviour on the remediated features (P6.14),
- moment-bonus and representative-selection effects inside the planner.

--------------------------------
## PRODUCTION DB SAFETY
--------------------------------

checksum before `e8798470…` · checksum after `e8798470…` (identical) · mtime unchanged
(`2026-09-18 21:07:36`) · writes: **0**. The audit is strictly read-only (mode=ro).

--------------------------------
## READY FOR SHADOW PLANNER VALIDATION
--------------------------------

**YES.**
READY FOR NEW ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

PROVEN:
- The remediation genuinely activated production semantics: 2638 CLIP embeddings, tq eligibility
  restored (2620/2638 usable, was ~311), all 6 moment families active, cake (C7309) and first-dance
  (DJI_0528/0529) recovered and visually confirmed, helpers active (obstructions exact match).
- Moment members reach the candidate pool (`_is_usable` passes for all shortlisted members).
- Cross-project (Elenora) untouched; shot_windows clean (0 orphans); production unchanged by audit.

NOT PROVEN:
- Planner story-coverage / rough-cut selection behaviour (P6.14).
- Chronology-dependent timing (drone timecode still missing) — first-dance timing hazard present.
- opening_signs precision; entrance strict precision; multi-song logic.

TESTS:
- `tests/test_p6_13_semantic_activation.py`: 9 read-only accepted-production guards (semantic full,
  eligibility resolved, 6 families active+usable, known-good recovered, windows clean, helpers,
  chronology gap = 10 drones, first-dance hazard, audit tool is read-only). Full suite 1077 passed,
  ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — production semantic remediation is genuinely active; moment/story prerequisites now reach
candidate eligibility/scoring (the P6.4 tq=0 blocker is resolved and all moment members are usable).
Remaining blockers are primarily chronology (drone timecode), opening/entrance precision, and
planner behaviour — not semantic activation.

READY FOR SHADOW PLANNER VALIDATION: **YES.**
READY FOR NEW ROUGH CUT: **NO.** · READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.14 — Shadow Planner / Story Coverage Validation (no timeline write).**

**DO NOT START.**
