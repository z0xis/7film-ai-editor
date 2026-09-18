# PACKAGE 06.14 — SHADOW PLANNER / STORY COVERAGE VALIDATION

START HEAD: `0a477f3`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Ran the EXACT production planner (`build_timeline`) in memory over the P6.12-remediated production
state, with NO persistence and NO timeline write, and instrumented the candidate funnel. Harness:
`tools/p6_14_shadow_planner.py` (write-hardened, never calls `persist_timeline`); fixture:
`tools/fixtures/p6_14_shadow_plan.json`; tests: `tests/test_p6_14_shadow_planner.py`.

--------------------------------
## SAFETY
--------------------------------

DB checksum before `e8798470…` · after `e8798470…` (identical) · mtime unchanged
(`2026-09-18 21:07:36`) · writes **0** · timeline writes **0** · Resolve writes **0** · existing
129-item AI Rough Cut untouched · active jobs 0 · pre/post manifest identical.
`build_timeline` takes no database and cannot write; the harness additionally replaced every
DATABASE write method with a hard raise for the run.

--------------------------------
## SHADOW PLAN
--------------------------------

duration **96.0 s** (target **180.0 s**) · items **59** · **deterministic** (seed 1 twice → same
ids/order) · music tracks 2 · music segments 2 (`[0,108] [108,180]`).
category_counts: couple 20, bride 13, venue 9, groom 8, detail 3, bride_prep 2, party 2, family 1,
groom_prep 1 (9 categories) · distinct sources 49.

--------------------------------
## CANDIDATE FUNNEL
--------------------------------

| moment | members | usable | scored | selected | note |
|---|---|---|---|---|---|
| cake | 8 | 8 | 8 | 1 (C7309) | positive control PASS |
| cake_feed | 8 | 8 | 8 | 2 (C7309) | selected |
| ring | 8 | 8 | 5 | 2 (C7161, C7221) | control PASS (but short — see below) |
| entrance | 8 | 8 | 5 | 1 (C7219) | selected |
| first_dance | 8 | 8 | 6 | **0** | scored, not selected |
| kiss | 8 | 7 | **0** | 0 | never reaches scoring |

Score entry is proven directly (instrumented `_score_candidate`), not inferred from `_is_usable`.

--------------------------------
## CAKE
--------------------------------

C7309: candidate ✓ · scored ✓ (8/8 members) · selected ✓ (1 item, C7309) · chronology known ·
visual: TRUE_MATCH (P6.13). **Positive control PASS** — the story-coverage mechanism works end to
end for cake.

--------------------------------
## FIRST DANCE
--------------------------------

semantic: restored (DJI_0528/0529 in shortlist) · usable 8/8 · scored 6/8 · **selected 0**.
The planner's own warning: *"Kiss and first dance couldn't enter the edit — they have shots but
other cuts were preferred."* DJI_0528/0529 footage IS selected elsewhere as general drone coverage
(14 drone items), but the specific first-dance moment members are not chosen and there is no
dedicated first-dance sequence. Root cause is downstream of semantics: the plan stops at 96 s
(early-day, first song only) and never builds the reception/night story where the first dance
lives — compounded by the drones' missing timecode. Answer to "does semantic restoration discover
the true first dance?": **YES** (discovery solved); selection/placement is the remaining problem.

--------------------------------
## KISS
--------------------------------

usable 7/8 · **scored 0** · selected 0. Kiss members never reach `_score_candidate` — the plan
truncates at 96 s before their (later, reception) due-now window is offered. Not a semantic gap; a
placement/coverage-truncation effect.

--------------------------------
## RING
--------------------------------

scored 5/8 · selected 2, but the planner warns: *"ring entered too short (1.06 s) because its
footage is in the lower half of the shoot"* — a chronology/available-duration effect. Story-coverage
mechanism works (ring reaches scoring and selection), but timing/duration is chronology-limited.

--------------------------------
## ENTRANCE
--------------------------------

scored 5/8 · selected 1 (C7219, couple/entrance). Actual entrance coverage: one entrance-tagged
couple shot at the very start; not a built-out salon-entrance sequence. Precision not visually
audited beyond the intro; reported as present-but-thin, not "solved".

--------------------------------
## CEREMONY
--------------------------------

**WEAK/ABSENT.** Planner warning: *"almost no footage for these story sections: detail (1%),
ceremony (1%)"*. Ceremony has only 21 shots in the whole project and no dedicated moment; the plan
carries essentially no ceremony coverage. Classify: **WEAK**.

--------------------------------
## NIGHT / PARTY / KINA
--------------------------------

coverage: thin in the built plan (party 2 items) because the plan ends at 96 s and never enters the
second (energetic) song. The final selected shot (C7292) is in fact a night-party dancing scene
(guests under fairy lights), so energetic night material IS discovered and can be selected — but the
second-song energetic section is never built. music relationship: **BROKEN for the second song**
(the energetic track's whole window 108–180 s is empty).

--------------------------------
## DRONE
--------------------------------

available: 10 assets, all usable · **selected: 14 items across 7 distinct drone assets**
(DJI_0528×3, DJI_0526×2, DJI_0527×2, DJI_0529×2, DJI_0530×2, DJI_0531×2, DJI_0523×1). The old
129-item cut had **0** drone coverage. This is a large, concrete improvement from the remediation —
drones now provide establishing/aerial coverage. chronology-known: NO (expected; timecode missing)
— placement is day-position-blind for drones.

--------------------------------
## INTRO
--------------------------------

first items: C7219 (couple, entrance moment) → DJI_0526 (detail, aerial) → DJI_0523 (venue, aerial)
→ DJI_0528 (couple, aerial) → party… An aerial-establishing intro anchored on a couple/entrance
shot. opening_signs did not visibly drive it. Result: **PARTLY_COHERENT / reasonable** — it
establishes venue and couple via drone establishing shots. (No false opening-sign shot dominates.)

--------------------------------
## OUTRO
--------------------------------

last items: C7336 (family) → C7329 (couple) → C7292 (night party dancing). The final shot is an
energetic night celebration (visually confirmed), which is a plausible closing beat — but the plan
simply ends at 96 s with no first-dance/cake climax and no built second-song finale. No causal
order error was observed in the last three, but the ending is truncated. Classify:
**PARTLY_COHERENT** (energetic final image, but no real climax sequence).

--------------------------------
## MULTI-SONG TRANSITION
--------------------------------

transition at 108 s. **No items exist at or after 108 s** — the transition window is empty and the
second song plays over nothing. music: second track never used; visuals: none. energy match: N/A.
result: **BROKEN** — this is the concrete, current form of the historical "weak second-song
transition/outro" complaint: the planner does not build into the second song at all.

--------------------------------
## MUSIC-FIRST GRAMMAR
--------------------------------

Single built segment (segment 0): 59 items, median shot **1.54 s**. Beat rigidity: the planner
aligned **91%** of cuts to within 120 ms of a beat, versus the reference edits' **61%** — i.e. the
current planner is **more beat-rigid than the manual grammar** (the §18 concern is real). Energy-vs-
duration / slow-motion buckets could not be compared across sections because only one section was
built.

--------------------------------
## SEQUENCE CONTINUITY
--------------------------------

The plan is largely single-shot-per-source (49 distinct sources over 59 items), so there are few
same-source runs to progress; cake (C7309) contributes the main mini-sequence (cake + cake_feed).
No backward source-time jump was flagged in the audited intro/outro. Continuity is acceptable
within the built 96 s; the larger issue is missing later-story sequences, not local jumps.

--------------------------------
## OLD 129 VS NEW SHADOW
--------------------------------

| dimension | old 129 (degraded) | new shadow (remediated) |
|---|---|---|
| items | 129 | 59 |
| built duration | ~full | 96 s / 180 s target |
| categories | 4 (bride, couple, family, venue) | 9 (adds groom, party, detail, bride_prep, groom_prep) |
| drone coverage | 0 | 14 items / 7 assets |
| cake | (n/a under fallback) | C7309 selected |
| ring | — | selected (short) |
| first_dance / kiss | — | discovered, not selected |

The new plan is **qualitatively far richer** (real semantic categories, drone coverage, cake) but
**quantitatively shorter** and truncated before the reception/night story. Higher item count in the
old cut is not better — it was built from 4 fallback categories.

--------------------------------
## ROOT-CAUSE TABLE
--------------------------------

| issue | primary blocker | evidence |
|---|---|---|
| plan ends at 96/180 s; 2nd song empty | SCORING_WEIGHT / planner coverage | warning "no usable place remained in remaining footage"; 0 items ≥108 s despite 2620 usable shots |
| kiss never scored | MOMENT_DUE_TIMING (truncation) | usable 7, scored 0 — plan stops before kiss's reception window |
| first_dance not selected | SCORING_WEIGHT + CHRONOLOGY | scored 6, selected 0; warning "other cuts preferred"; drones timecode-less |
| ring too short | CHRONOLOGY | warning "footage in the lower half of the shoot" |
| ceremony absent | MOMENT_VOCABULARY / semantic sparsity | warning "ceremony 1%"; only 21 ceremony shots, no ceremony moment |
| over-beat-rigid | MUSIC grammar (weight) | 91% within 120 ms vs 61% reference |

--------------------------------
## CHRONOLOGY
--------------------------------

proven next blocker? **PARTIAL.** Chronology concretely limits ring (duration) and leaves the
first-dance drones day-position-blind, and the truncation interacts with due-now timing. But the
**primary** blocker is that the planner does not build past 96 s / into the second song at all —
a planner story-coverage / selection issue, not chronology alone. Chronology is a real secondary
contributor (drone timecode; ring placement), not the single cause.

--------------------------------
## READY FOR CONTROLLED CANDIDATE ROUGH CUT
--------------------------------

**NO** (not yet). The remediation clearly flows through the planner (cake, ring, entrance, drones
selected; first-dance discovered) and the plan is deterministic and semantically far richer, but it
builds only ~half the target and omits the reception/night story (kiss, first dance, second song).
A candidate rough cut now would ship a truncated edit. A bounded planner story-coverage fix should
come first, validated in shadow.

READY FOR GENERAL PRODUCTION: **NO.**

PROVEN:
- Restored semantics flow through the real planner: moment members reach `_score_candidate`
  (proven by instrumentation), cake/ring/entrance selected, drones now provide 14 items/7 assets
  (old: 0), category diversity 4→9. Plan is deterministic. Production untouched (0 writes).

NOT PROVEN / BLOCKERS:
- The plan builds only 96/180 s and never enters the second song → kiss/first-dance/night story
  absent (primary: planner coverage/selection weighting).
- Chronology (drone timecode, ring placement) is a secondary contributor.
- ceremony vocabulary/coverage; over-beat-rigidity vs manual grammar.

TESTS:
- `tests/test_p6_14_shadow_planner.py`: 9 read-only guards (harness write-guarded, production
  unchanged, deterministic, cake/ring reach scoring+selected, first_dance scored-not-selected,
  kiss never scored, plan undershoots target/second song empty, drone coverage vs old zero, richer
  categories). Full suite 1086 passed, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**C** — the restored semantics reach scoring, but the planner's story-coverage/weighting still
fails to build the full target and to select important known moments (kiss, first dance) — the plan
truncates at ~96 s and never enters the reception/night story or the second song. Chronology is a
secondary contributor (verdict B factors present but not primary). A bounded planner story-coverage
fix, validated in shadow first, is the next step — not a candidate rough cut yet.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.15 — BOUNDED PLANNER STORY-COVERAGE FIX (SHADOW VALIDATION FIRST)** — diagnose and bound-fix
why `build_timeline` stops at ~half the target and de-prioritizes kiss/first-dance/second-song
coverage, validated entirely in shadow (no timeline write) before any candidate rough cut.

**DO NOT START.**
