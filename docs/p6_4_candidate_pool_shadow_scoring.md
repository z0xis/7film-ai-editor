# P6.4 — Full Candidate-Pool Shadow Scoring / Representative-Selection Trace

START HEAD: `7db5549`
COMMIT: (this package's commit, see git log)

Shadow/read-only, exactly as scoped. `build_timeline()` was called in-memory
against the real 15A data (it is a pure function — no DB write, no Resolve
call, no file I/O of its own); its returned `TimelinePlan` was inspected and
discarded — never exported, persisted, or written back anywhere. The only
instrumentation is a pass-through wrapper around `_score_candidate()` that
records every call's inputs/outputs without altering its return value or any
other planner behavior (verified: the wrapper is called, `original(...)` is
invoked unmodified, and its exact result is returned and also logged).

--------------------------------
## REPRESENTATIVE SELECTION PATH
--------------------------------

Traced `build_timeline()` (planner.py:1882–~2650) start to finish:

- **candidate pool construction** (:1908–1946): `asset_by_id` built from all
  project assets; shots filtered by `rejected_assets`/`rejected_shots` (none
  supplied here); trimmed via `_without_recording_tail()`; kept only if
  `_available_duration(shot) >= 0.5s`. Quality-gated: `minimum_quality,
  maximum_clipping = _quality_gates(style_profile, long_enough)`, then `good =
  [shot for shot in long_enough if _is_usable(shot, minimum_quality,
  maximum_clipping)]`. **If `good`'s total duration ≥ target_duration:
  `candidates = good`** (else falls back to `long_enough`, unfiltered by
  quality). This is the single most consequential filter in the whole
  pipeline for this shoot — see below.
- **per-cut loop** (:2087 onward): `available_shots = [c for c in candidates
  if c.id not in exhausted]`, then narrowed by a sequence of contextual
  filters (opening/closing ramps, hold eligibility, short-cut readability,
  run-quality), then scored via `_score_candidate()` for every shot still in
  `available_shots`, then `ranked.sort(...)`; `ranked[0]` wins.
- **score terms** (`_score_candidate`, :1700–1880): additive —
  `TECHNICAL_WEIGHT*technical_quality + 0.20*aesthetic_score +
  0.20*story_relevance + MUSIC_FIT_WEIGHT*music_fit + 0.10*style_fit +
  0.10*sequence_continuity - duplicate_penalty - jump_cut_penalty -
  framing_penalty - chronology_penalty - window_penalty - still_life_penalty +
  moment_bonus - distraction_penalty - second_take_penalty + take_bonus -
  backward_penalty - reuse_penalty - obstruction_penalty - table_penalty -
  scale_run_penalty - stillness_penalty + random_jitter`.
- **Moment interaction:** `moment_bonus = MOMENT_BONUS(0.1)` iff
  `missing_moment and chronology_penalty == 0.0` — additive, not a gate.
  `missing_moment = shot.id in wanted_moment_shots` (built from
  `_due_now()`/`_moment_shots_of_the_day()`, unchanged from P6.3).
- **chronology interaction:** `chronology_penalty = CHRONOLOGY_WEIGHT(1.2) *
  max(0, |day_position - progress| - CHRONOLOGY_SLACK(0.08))`; `0.0` when
  `day_position is None` (never evaluated).
- **music interaction:** `music_fit` is one independent additive term,
  computed from `BeatGrid`/section/energy and duration fit — no veto
  relationship with any other term (confirmed by reading the formula: all
  terms are `+`/`-`, none multiply or short-circuit another).
- **no randomness affecting Moment status**: `random_jitter =
  rng.uniform(-0.015, 0.015)` is the only stochastic term, seeded (`seed=3`,
  reused from the real production `timeline_versions` row for 15A) and far
  smaller than `MOMENT_BONUS`.

**GATE A (representative path trace): PASS** — traced via direct code
reading, not inferred; confirmed empirically by instrumented execution below.

--------------------------------
## MISSING DAY_BY_ASSET BEHAVIOR
--------------------------------

Section 2's question, answered by code and confirmed by the instrumented run:

**Answer: (A) — a shot with no timecode remains fully eligible for the
candidate pool and for selection; it only cannot contribute to a Moment's
`moment_day`/timing anchor** (`_day_position()` simply omits it from the
dict; `chronology_penalty` then defaults to `0.0` for it, never (C)
synthesized, never (B) removed). This matches P6.3's finding exactly and is
reconfirmed here: DJI shots appear in `candidates` (they pass the duration
filter) — **but P6.4 found a separate, much larger filter that removes them
anyway, for an unrelated reason (see next section).**

Classification of the missing-chronology effect alone (isolated from the
larger finding below): **MINOR** — it does not by itself remove any shot from
eligibility; it only denies the moment-timing subsystem a data point.

--------------------------------
## THE PRIMARY FINDING: `technical_quality = 0.0` GATE
--------------------------------

Before any Moment/chronology/scoring question could be answered, the
instrumented run showed **cake, kiss, and first_dance never appear in any of
the 136 cuts' scored candidate pools — not once, not even losing.** Only
`ring` and `entrance` members were ever scored at all. This is a much bigger
effect than anything chronology could cause, so it was traced to its root
(read-only SQL, no code change):

```
15A shots:            2638 total, 2327 (88.2%) have technical_quality = 0.0
  by camera type:     drone   941/941  (100.0%) zero
                       sony   1386/1697 (81.7%) zero
  by category:         venue  2327/2508 (92.8%) zero
                        bride/couple/family   0/130 (0%) zero
Elenora (reference):  1405 shots, 0 (0.0%) zero, mean 0.399
```

- **Every single one of C7309's 16 shots (the entire `cake` episode) has
  `technical_quality = 0.0`.**
- **Both of C7228's shots (`kiss`'s only TRUE_MATCH episode) have
  `technical_quality = 0.0`.**
- **All 20 sampled `DJI_0528` shots have `technical_quality = 0.0`** — and by
  the camera-type breakdown, this is universal across all drone footage.
- `ring`'s `C7161` shots (0.26–0.37) and `entrance`'s `C7176`/`C7183` shots
  (0.32–0.46) are real, non-zero, healthy values — exactly the two moments
  that DID get selected.
- Production's `_quality_gates()` sets `minimum_quality = max(0.15,
  median*0.6)`; since the shoot-wide median is `0.0` (88% zero), this
  resolves to the absolute floor **0.15**. `_is_usable()` then rejects any
  shot with `technical_quality < 0.15` — i.e. every one of the 2327 zero-
  quality shots, unconditionally, **before Moment membership, chronology, or
  `moment_bonus` are ever evaluated.**
- Elenora's near-zero rate (0/1405) rules out a systemic bug in
  `_quality_gates`/`_is_usable` themselves; this is a **15A-specific data
  gap**, and its shape — concentrated almost entirely in the `venue`
  fallback category (2327/2508, 92.8%) while the smaller `bride`/`couple`/
  `family` categories are 100% populated — matches P6.0's original finding
  that 15A went through a degraded/fallback analysis path. **This reads as
  the same underlying incident as the missing-embedding gap (P6.0), not a
  new, unrelated one**: whatever analysis pass left `shot_features.embedding`
  NULL for 15A appears to have also left `technical_quality` at its
  uninitialized default (`0.0`, the `Shot` dataclass's own default) for the
  same shots.

Classification of the missing-day-position effect, revised in light of this:
**MATERIAL for `first_dance` specifically (100% of drone footage is excluded
by the SAME shoot-wide quality gap, not by chronology), and moot for `cake`/
`kiss` (they are excluded by the quality gate regardless of chronology).**

--------------------------------
## CAKE
--------------------------------

- pool size at any point: **cake never appeared in any scored pool (0/136
  cuts).**
- Moment members: 8 (all `C7309`)
- due: N/A — moot; none of the 8 members ever reach `available_shots`
- Top-1/Top-3/Top-5: no `cake` member present at any rank, ever
- winner human status: N/A
- rank without Moment bonus / with Moment bonus: **N/A — `moment_bonus`
  cannot matter for a candidate that is never in the scored pool.** This
  *is* the causal answer Section 7 asked for: the causal effect of Moment
  activation on `cake`'s representative selection is **zero**, not because
  the bonus is too small, but because eligibility is decided one filtering
  stage earlier than where `moment_bonus` applies.

**CAKE REPRESENTATIVE: NOT SELECTED.**

**GATE B (cake positive control): FAIL.** Per the package's own Section 24
instruction ("If clean cake Moment does NOT yield a good cake representative:
this is strong evidence of downstream planner representative-selection
failure. Do NOT blame semantics.") — **and this trace localizes the failure
precisely**: it is not representative-*scoring* (Section 20's
aesthetic/technical/motion/chronology/music decomposition question does not
even apply — cake shots never reach scoring), it is **candidate
*eligibility*, gated on a technical_quality data field that has nothing to do
with semantics, embeddings, Moments, or chronology.**

--------------------------------
## FIRST DANCE
--------------------------------

- pool size: **first_dance never appeared in any scored pool (0/136 cuts).**
- Moment members: 8 (6 `DJI_0529`/`DJI_0528`, 2 `C7433`/`C7388`)
- **DJI_0528 eligibility: excluded — `technical_quality = 0.0` (confirmed for
  the sampled shots; drone-wide rate is 100% zero).** Not a chronology
  question at all here; the drone quality gap alone is sufficient to exclude
  it.
- **DJI_0529 eligibility: excluded, same reason** (same camera, same 100%
  zero-quality rate — not individually re-verified shot-by-shot beyond the
  camera-type aggregate, since the aggregate is unambiguous at 941/941).
- **C7433/C7388 eligibility:** not confirmed excluded by the quality gate
  specifically (Sony footage's zero-rate is 81.7%, not 100%) — but they also
  never appeared in any scored pool. Not further isolated in this package
  (would require checking their individual `technical_quality`, not done —
  the cake/drone finding already fully explains `first_dance`'s absence for
  its more important members, and chasing the exact reason for these two
  specifically would not change the primary verdict).
- Top-1/Top-3/Top-5/Top-10: no `first_dance` member present at any rank, ever
- human labels after ranking: N/A (none scored)
- known-good/useful best rank: N/A
- winner: **NON-MOMENT** (no `first_dance` member was ever a candidate)
- Moment bonus causal effect: **zero**, same reasoning as `cake`
- chronology impact: **secondary to and masked by** the quality-gate
  exclusion — P6.3's finding (moment_day anchored on the 2 false-positive
  members) never gets the chance to matter, because none of `first_dance`'s
  members reach the stage where `moment_day`/`due_now` would affect a live
  scoring decision.
- music interaction: N/A (no candidate to interact with music fit)

**FIRST_DANCE REPRESENTATIVE: FAIL** (not selected, and — unlike `cake` —
not merely a downstream-selection question but compounded by a drone-wide
100% technical_quality exclusion that applies before chronology or Moment
membership would ever be reached).

--------------------------------
## KISS
--------------------------------

**Never appeared in any scored pool.** Both of `kiss`'s TRUE_MATCH shots
(`C7228`) have `technical_quality = 0.0`, so they are excluded by the same
gate — independent of and prior to the P6.3 chronology finding.

**Chronology false-negative: previously reported as YES in P6.3's isolated
trace (chronology alone would have dropped both TRUE_MATCH shots as
day-position outliers). Superseded here: it is now moot for this specific
episode** — the quality gate excludes both shots regardless of what
chronology would have done to them. The P6.3 finding remains true and
worth keeping on record (it would matter for a shoot without this quality
gap, or after a future quality-data recovery), but it is not the operative
cause of `kiss`'s absence from the real candidate pool today.

--------------------------------
## RING
--------------------------------

**Chronology useful filtering: YES, confirmed by the live run.** `ring`'s
`C7161` shots have real, healthy `technical_quality` (0.26–0.37) and DO reach
scoring. At cut 12, `5835af5d` (`C7161`, P6.2 PLAUSIBLE_MATCH) won **with
`missing_moment=True` and `moment_bonus=0.1` actually applied** (chronology
penalty exactly `0.0` at that cut) — a genuine, observed, causal Moment-bonus
effect. At cut 8, `0ed9b29d` (the P6.2 FALSE_POSITIVE phone shot) also won,
but with `missing_moment=False` (excluded from `wanted_moment_shots` by
P6.3's day-clustering, exactly as predicted) — **it won on its own base
score, not because of Moment machinery**, so `ring`'s one false-positive
selection is not a Moment-system failure, just an ordinary high-scoring shot
that happens to also be in `ring`'s raw (unfiltered) shortlist.

--------------------------------
## ENTRANCE
--------------------------------

3 `entrance` members were selected (`885d2795`, `a979a3fd`, `7fd9e99b` — all
from `C7176`/`C7183`, both with real technical_quality). Inspecting their
captured components:
- cut 11 (`885d2795`, PLAUSIBLE_MATCH): `missing_moment=True` but
  `moment_bonus=0.0` — `chronology_penalty=0.0762` (not exactly zero, so the
  bonus's strict `==0.0` condition did not fire). Won on its own score
  (0.511) regardless.
- cut 30 (`a979a3fd`, AMBIGUOUS): `missing_moment=False`, won on its own
  merits.
- cut 72 (`7fd9e99b`, AMBIGUOUS): very low score (0.1431), large chronology
  penalty (0.329, far from its due position) — a weak, late leftover
  selection, not moment-driven.

**None of `entrance`'s 3 selections were actually caused by `moment_bonus`**
— all three won on their own scores; `missing_moment` was true for one of
them but the bonus's exact-zero chronology condition didn't fire. This is a
secondary finding: the strict `chronology_penalty == 0.0` equality in the
`moment_bonus` condition (planner.py:1773) is more fragile in practice than
its "moment owed, due now" framing suggests — it only actually pays out when
a shot's day-position happens to fall within `CHRONOLOGY_SLACK` of the
current story progress.

--------------------------------
## MUSIC-FIRST
--------------------------------

`moment_bonus` and `music_fit` are independent additive terms — confirmed
both by reading the formula (P6.3) and by this run's captured components (no
case observed where one term's presence changed another's computation).
**COOPERATIVE**, not competing — but moot for `cake`/`first_dance`/`kiss`
since they never reach a scored cut where the two terms could interact at
all.

--------------------------------
## CURRENT vs SHADOW
--------------------------------

**CAKE:** current (production, no embeddings) — no coverage, not represented.
Shadow (with embeddings + Moments + chronology, this package's real scoring
run) — **still not represented**, for a reason entirely unrelated to
semantics: `technical_quality = 0.0` on every `C7309` shot.

**FIRST DANCE:** current — no coverage. Shadow — **still not represented**,
for the same class of reason (100% of drone footage excluded by the same
quality gate), compounded by the chronology anchoring issue P6.3 found (which
never gets the chance to matter here).

--------------------------------
## ROOT-CAUSE CHAIN
--------------------------------

- embeddings → Moment: **PASS** (P6.1)
- Moment → valid episode: **PASS/CONDITIONAL** (P6.2)
- valid episode → coverage (due/eligible-for-bonus): **PASS** (P6.3, at the
  `moment_of_shot`/`due_now` level — this part of the mechanism is real and
  was reconfirmed working in this run for `ring`)
- coverage → good representative: **FAIL** — not because moment_bonus,
  chronology, or scoring logic misbehaves, but because an **earlier, wholly
  separate filtering stage** (`_is_usable()`'s technical_quality gate)
  removes `cake`'s and `first_dance`'s member shots from the candidate pool
  before any of that machinery runs. `ring` and `entrance`, whose members
  happen to have real technical_quality values, show the coverage mechanism
  does work when eligibility is not blocked upstream.

--------------------------------
## PRIMARY BLOCKER
--------------------------------

**Choose one: B is closest, but the finding is more specific than "missing
drone chronology" alone — it is a shoot-wide `technical_quality = 0.0` data
gap that happens to be 100% for drone footage and ~82–93% for the affected
Sony categories, discovered as this package's primary result. No listed
option names this exactly; reporting as (H) — inconclusive as a single
predefined category, with the specific mechanism stated in full above rather
than forced into "missing chronology" (B) alone, since chronology was shown
to be moot for `cake`/`kiss` (their members are excluded regardless of
chronology).**

If a single label must be chosen: **B, generalized** — a missing/zero
*technical* metadata field (of which chronology's missing timecode is a
second, smaller instance, both concentrated on drone footage) is the primary
remaining blocker, not representative-scoring logic, not Moment
contamination, and not music mapping.

--------------------------------
## PLANNER ARCHITECTURE
--------------------------------

**PARTIAL.** The Moment/coverage/`moment_bonus`/chronology machinery is real
and was shown working correctly for `ring` in this live run. But it is
downstream of an eligibility gate that, for this specific shoot, excludes the
exact footage (`cake`, `kiss`, `first_dance`'s drone members) that P6.1–P6.2
identified as the moment system's best evidence. The planner's architecture
is not broken; the **data it is being asked to plan with is**, in a way this
package's earlier stages (which never inspected `technical_quality`) could
not have surfaced.

--------------------------------
## READY FOR REAL 15A REANALYSIS
--------------------------------

**NO.** A real embedding reanalysis (the natural next step suggested by
P6.1–P6.3) would not fix this: `technical_quality` is a wholly separate field
from the CLIP embedding this whole package series has been investigating, and
repopulating embeddings does nothing to repopulate `technical_quality`.
Reanalysis is not justified until the `technical_quality` gap itself is
understood — same-incident hypothesis or not.

READY FOR PRODUCTION: **NO**

PROVEN:
- Representative-selection path traced exactly (candidate pool construction,
  quality gate, per-cut scoring, `moment_bonus`/`chronology_penalty`
  interaction) via direct code reading and confirmed by a real, instrumented,
  in-memory `build_timeline()` run against the full 2638-shot 15A pool.
- Missing `day_by_asset` (drone timecode) affects only chronology
  timing/penalty, never eligibility — confirmed both by code and by the run.
- **A separate, much larger gap dominates**: `technical_quality = 0.0` for
  88.2% of 15A shots (100% of drone footage, 92.8% of `venue`-category shots)
  vs. 0% for Elenora — `_is_usable()`'s hard `< 0.15` floor excludes all of
  `cake`'s, `kiss`'s, and effectively all of `first_dance`'s member shots
  from the candidate pool before Moment logic runs.
- `ring` and `entrance` (whose members have real technical_quality) DO get
  selected in the live run; one selection (`5835af5d`, `ring`) is a confirmed
  genuine `moment_bonus`-caused pick — proving the coverage mechanism itself
  works when not blocked upstream.
- The `technical_quality` gap's shape (concentrated in the `venue` fallback
  category) matches P6.0's original semantic-fallback finding, suggesting
  one underlying incident rather than two unrelated gaps.

NOT PROVEN:
- Whether `C7433`/`C7388` (first_dance's 2 Sony-camera members) are excluded
  by the same quality gate specifically (not individually checked).
- The exact cause/timing of the `technical_quality = 0.0` gap itself (which
  analysis run, when, why it diverged from Elenora's) — out of this
  package's scope.
- Anything about representative selection quality *among* eligible members,
  for a moment whose members all clear the quality gate (only `ring` gave a
  moment_bonus-caused example; `n=1` is not generalizable).

SAFETY: production DB, code, embeddings, timeline, Resolve, router, verifier
research, `MOMENT_PROMPTS`, thresholds, planner weights, and timecodes are
all unchanged (verified below). `build_timeline()` was called but its output
was inspected in-memory only and never exported, persisted, or written to
Resolve/DB/any timeline artifact.

TESTS: `tests/test_p6_4_candidate_pool_trace.py` (8, new) +
`tests/test_p6_3_day_by_asset_trace.py` (8) +
`tests/test_p6_2_population_and_audit.py` (5) +
`tests/test_shadow_moment_activation.py` (6) — all pass. Full suite
(excluding Resolve-only tests): **978 passed** (971 baseline + 7 net new —
one test file addition). `ruff` clean.

--------------------------------
## PERFORMANCE
--------------------------------

Full `build_timeline()` shadow run (2638-shot pool, 136 cuts, 32,305
`_score_candidate` calls captured): completed in well under a minute
(no embedding inference, no ffmpeg, pure Python scoring). No metadata parsing
failures.

==================================================
GATES
==================================================

- GATE A (representative path trace): **PASS**
- GATE B (cake positive control): **FAIL** — clean Moment, but its members
  never reach scoring at all; downstream planner *eligibility* problem, not
  a semantic one, exactly as Section 24 anticipated
- GATE C (first_dance representative): **FAIL** — its members (especially
  100% of the drone-sourced ones) are excluded before scoring
- GATE D (null drone chronology diagnosis): **PASS** — exact causal effect
  proven (affects only timing, not eligibility), and shown to be secondary
  to the larger technical_quality gap
- GATE E (music-first compatibility): **PASS** — cooperative where it
  applies, moot elsewhere
- GATE F (production isolation): **PASS** (verified below)
- GATE G (next-step identifiability): **PASS** — one concrete subsystem
  identified: `technical_quality` data coverage for 15A (`_is_usable()`'s
  gate, planner.py:1047–1051, fed by `_quality_gates()`, planner.py:731–748)

==================================================
FINAL VERDICT
==================================================

**D — Planner scoring/ranking is not the primary blocker; rather, a
candidate-*eligibility* gate (technical_quality, not chronology, not Moment
contamination, not scoring weights) is primary blocker despite valid
Moments. Chronology's missing-drone-timecode gap (P6.3) is real but
secondary — it would matter once technical_quality is addressed, not before.**

READY FOR REAL 15A REANALYSIS: **NO**
READY FOR PRODUCTION: **NO**

**NEXT RECOMMENDED PACKAGE:** P6.5 — read-only technical_quality data-gap
audit for 15A: trace exactly which analysis pass populates
`shots.technical_quality`, why it defaulted to 0.0 for 88.2% of 15A's shots
(100% of drone footage, 92.8% of `venue`-category Sony footage) while
Elenora's is fully populated, and whether this is the same incident as
P6.0's missing-embedding finding or a second, independent gap. **DO NOT
START.**

==================================================
FINAL SAFETY
==================================================

PRODUCTION CHANGED? NO
DB CHANGED? NO
EMBEDDINGS WRITTEN? NO
REANALYZED? NO
RESOLVE? unchanged, never called
TIMELINE? `build_timeline()` was called (pure function) but its result was
  never exported/persisted/written — no timeline artifact exists on disk or
  in the DB as a result of this package
SOURCE MOMENT? untouched
ROUTER? frozen R4b, untouched
VERIFIER? frozen, untouched
MOMENT PROMPTS? unchanged
THRESHOLDS? unchanged
PLANNER WEIGHTS? unchanged (diff empty; `_score_candidate` was wrapped for
  observation only, original function restored immediately after the run,
  confirmed by an identity check)
TIMECODES? unchanged, no drone clock offset applied or invented
NEW MODEL? none
CONTAMINATION? 0

==================================================
STOP CONDITION
==================================================

P6.4 tamamlandı. STOP — P6.5 başlatılmadı.
