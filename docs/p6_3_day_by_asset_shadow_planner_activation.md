# P6.3 — Day-by-Asset Chronology / Shadow Planner Activation Trace

START HEAD: `7463bb2`
COMMIT: (this package's commit, see git log)

Read-only + shadow only, exactly as scoped. No timeline generated, no
`build_timeline()` call, no production write, no prompt/threshold change.

--------------------------------
## DAY_BY_ASSET CONTRACT
--------------------------------

Traced to `apps/api/sevenfilm/services/planner.py:996` (`_day_position`) and
`:1024` (`_timecode_seconds`), called at `:1980` as
`day_by_asset = _day_position(list(asset_by_id.values()))`.

- **definition:** `day_by_asset[asset_id]` = where in the shooting day that
  asset's recorded timecode sits, normalized 0.0 (first clip rolled, after the
  day is cut at its largest silence gap) to 1.0 (last clip rolled).
- **input field:** `MediaAsset.timecode` (DB column `media_assets.timecode`,
  a `TEXT` field, format `HH:MM:SS:FF` or `HH:MM:SS;FF`) — the camera's own
  embedded timecode, **not** file `creation_time`/EXIF/mtime, and not
  filesystem ingest order.
- **range:** float 0.0–1.0 (confirmed empirically: min 0.0, max 1.0 across 352
  mapped 15A assets).
- **normalization:** cuts the day at its largest inter-clip gap (so a
  reception past midnight stays one continuous evening rather than wrapping),
  then linearly scales elapsed seconds from that origin by the total span.
- **fallback for missing timecode:** the asset is **excluded from the dict
  entirely** ("left out rather than guessed at, and carries no pressure" —
  the code's own comment). Downstream, `day_by_asset.get(asset_id)` returns
  `None` for these, and both `_moment_shots_of_the_day()` and
  `_score_candidate()` treat `None` as "no chronology signal" (kept
  unconditionally in day-clustering; `chronology_penalty` stays `0.0`).
- **is it the same contract for Elenora?** Yes — `_day_position()` is one
  unparameterized function called identically for any project; it is not
  15A-specific or Elenora-specific.
- **does planner assume monotonic chronology?** Yes, for whichever assets
  have a parseable timecode — it assumes each asset's embedded timecode
  reflects real shooting order within one continuous day, cut only at the
  single largest gap.

**GATE P1 (contract identity): PASS.** `tools/shadow_day_by_asset.py` imports
and calls `_day_position`/`_timecode_seconds` directly (verified by identity
assertion in `tests/test_p6_3_day_by_asset_trace.py`) — no reimplementation.

--------------------------------
## 15A METADATA COVERAGE
--------------------------------

- assets total: **362**
- mapped (parseable timecode): **352**
- missing: **10** — and **all 10 are drone clips**: `DJI_0522.MOV` through
  `DJI_0531.MOV`. Zero Sony/camera (`C7xxx.MP4`) assets are missing a
  timecode; zero parse failures among the 352.
- ties: `C7161.MP4`'s single asset backs 4 of `ring`'s 8 shortlist shots (same
  asset, expected — not a data problem).
- outliers: none found among the 352 mapped assets — spot-checked earliest 10
  (`C7101`–`C7110`, 0.0–0.028) and latest 10 (`C7443`–`C7452`, 0.944–1.0),
  both form a smooth, monotonically-increasing sequence matching the asset
  numbering, consistent with a single continuous shoot day.
- **drone behavior:** DJI `.MOV` files carry no embedded timecode field that
  `_timecode_seconds()` can parse (their `media_assets.timecode` column is an
  empty string). This is a **systematic, camera-type-correlated gap**, not
  random missingness.

**GATE P1: PASS** (contract itself is sound and correctly reproduced).
**GATE P2 (chronology coverage): CONDITIONAL** — 352/362 (97.2%) of assets are
mapped, which would read as "PASS" in isolation, but the missing 3% is not a
random small subset: it is **100% of the drone footage**, and drone footage is
where 6 of `first_dance`'s 8 shortlisted shots live. Coverage is high overall
but structurally zero for one camera type that matters directly to one of the
two primary moments under test.

--------------------------------
## CHRONOLOGY SANITY
--------------------------------

- earliest: `C7101.MP4` (day_position 0.0)
- latest: `C7452.MP4` (day_position 1.0)
- cake (`C7309.MP4`, timecode `20:16:59:48`): **0.5646**
- first_dance's only two timed members — `C7433.MP4` (`20:44:21:28` →
  **0.9206**) and `C7388.MP4` (`20:34:01:20` → **0.7862**); the other 6
  members (all `DJI_0528`/`DJI_0529`) have **no day_position**.
- entrance episode (`C7204`/`C7205`/`C7203`, ≈19:58): **0.320–0.327**
- kiss (`C7228`, `20:03:34:02`): **0.3901**
- ring (`C7161`, `19:48:33:28`): **0.1947**

No contradictions found: `C7161`(ring, 0.195) → `C7176`/`C7183`/`C7204`/
`C7205`/`C7203`(entrance, 0.24–0.33) → `C7228`/`C7233`(kiss, 0.39–0.41) →
`C7309`/`C7310`(cake/cake_feed, 0.56–0.57) → `C7348`(0.68) →
`C7388`/`C7433`(0.79–0.92) — this is a coherent, plausible real reception
order (ring detail → arrival → kiss → cake → dancing), not an inversion.

--------------------------------
## CAKE PLANNER TRACE
--------------------------------

- Moment valid: **YES** (P6.2: 8/8 TRUE_MATCH)
- day position: **0.5646**, identical for all 8 members (single source asset
  `C7309`) — the cleanest possible chronology anchor.
- `_moment_shots_of_the_day` (spread ±0.05): **8/8 kept**, 0 dropped.
- `_due_now()` at story start (all 6 moments unshown): **False** — `ring`
  (0.195, the day's earliest moment) is due first. This is architecturally
  correct, not a failure: moments become due in day order, and `cake` is the
  4th-earliest of the 6.
- moment_bonus: `MOMENT_BONUS = 0.1` (unchanged constant), applied uniformly
  to every kept member once `cake` becomes due and none of its shots has
  already been shown — since all 8 members share the exact same chronology
  position, `chronology_penalty` is identical (and near 0, since the moment
  is due at that point in the edit) across all 8, so the bonus does not
  arbitrarily favor one over another on chronology grounds.
- **A precise numeric base-score / post-bonus-rank comparison against the
  full competing candidate pool was not computed** — doing so requires
  assembling the complete real `_score_candidate()` input set (technical
  quality, aesthetic, motion, music `BeatGrid`/section/energy, style profile,
  reuse/asset-usage state) for the full 2638-shot pool at a specific cut,
  which is effectively re-running `build_timeline()`'s per-cut candidate loop
  — the package's "no full timeline, isolate scoring logic" boundary was
  honored by stopping at the deterministic parts (`moment_day`, `_due_now`,
  day-clustering) rather than approximating the rest with fabricated numbers.

**CAKE: WOULD REPRESENT — YES.** Chronology anchor is clean, single-episode,
un-contradicted; the moment becomes due in its correct day-order slot with no
structural blocker.

--------------------------------
## FIRST_DANCE PLANNER TRACE
--------------------------------

- Moment valid/useful: **YES, with mixed shot-level precision** (P6.2: 1
  TRUE_MATCH, 5 PLAUSIBLE_MATCH, 2 FALSE_POSITIVE)
- members: 8 — `cd10866a`/`6d804937`/`202d960b`/`3b04178c`/`8081ef29`
  (`DJI_0529`, PLAUSIBLE_MATCH), `f5e4fa8a` (`DJI_0528`, TRUE_MATCH,
  known-verified), `24bbfc53` (`C7433`, FALSE_POSITIVE), `393b5d06`
  (`C7388`, FALSE_POSITIVE)
- **known-good member present: YES** (`f5e4fa8a`)
- day positions: only 2/8 members are timed — `C7433` (0.9206) and `C7388`
  (0.7862), i.e. **exactly the two FALSE_POSITIVE members**. The 6 real
  drone-sourced members (1 TRUE_MATCH + 5 PLAUSIBLE_MATCH) all have
  `day_position = None`.
- `moment_day["first_dance"]` = median of the 2 timed values = **0.9206** —
  **anchored entirely on `C7433`, a FALSE_POSITIVE shot**, because it is
  simply the only kind of member `_day_position()` can see.
- `_moment_shots_of_the_day` (spread ±0.05): **7/8 kept**, only `393b5d06`
  (`C7388`, the other FALSE_POSITIVE, distance 0.1344 from the 0.9206 anchor)
  dropped. All 6 drone shots are kept unconditionally (`where is None` always
  passes the filter).
- `_due_now()` at story start: **False** (as expected — `first_dance` is the
  day's latest moment, due only after the other 5 have been shown).
- moment_bonus: `MOMENT_BONUS = 0.1`, applied identically to all 7 kept
  members once due — **crucially, this includes no preference among them**:
  the 6 `None`-day drone shots get `chronology_penalty = 0.0` unconditionally
  (never evaluated against `progress`), while `C7433` itself (the one
  remaining timed member) sits exactly at its own moment_day so its
  chronology penalty is also ≈0 at that point in the edit. **Chronology gives
  the planner no signal within `first_dance`'s own membership to prefer the
  known-good `f5e4fa8a` or the plausible `DJI_0529` shots over the
  false-positive `C7433`** — selection among them would fall entirely to the
  other `_score_candidate()` terms (technical quality, aesthetic score, music
  fit, etc.), which were not compared here (same full-pool-assembly boundary
  as for `cake`, above).
- preferred member: **UNKNOWN** — cannot be determined without the full
  candidate-pool scoring pass excluded above.
- human audit quality of preferred member: **N/A** (preferred member unknown)

**FIRST_DANCE: WOULD REPRESENT — VALID/USEFUL, coverage-only.** The moment
does become due (no structural block) and does carry at least one
known-genuine shot among its eligible members, so **moment coverage is
healthy**. But **representative-shot selection is chronology-blind for this
specific moment** (its own day-position anchor is a false positive, and its
best members carry no chronology signal at all) — this is exactly the
coverage-vs-representative-quality split the package asked to distinguish
(Section 23): **coverage = works, representative selection = unproven /
potentially arbitrary with respect to quality**.

--------------------------------
## ENTRANCE
--------------------------------

- day position: 0.3233 (median of all 8, all timed)
- `_moment_shots_of_the_day`: **4/8 kept** — dropped `0237cda9` (`C7233`,
  PLAUSIBLE_MATCH, isolated at 0.4055), `7fd9e99b`/`a979a3fd` (`C7176`,
  both AMBIGUOUS, posed-decor shots at 0.242), and `885d2795` (`C7183`,
  PLAUSIBLE_MATCH, bride-walking-in shot at 0.260). Kept: `3972bb9b`/
  `0e41f14f` (`C7204`, PLAUSIBLE), `9a4ed279` (`C7205`, PLAUSIBLE), `a04a606a`
  (`C7203`, AMBIGUOUS) — the four-shot corridor-walking cluster.
- planner activation: chronology filtering keeps a plausible-majority subset
  (3 PLAUSIBLE + 1 AMBIGUOUS of 4), dropping one genuinely useful shot
  (`885d2795`) alongside the two posed/ambiguous ones — a mixed effect, not a
  clean improvement or a clean harm.
- **planner would represent candidate? YES** (the kept 4-shot cluster is a
  real walking-through-venue episode with a stable chronology anchor).
- **semantic validity remains: PLAUSIBLE** — no frame in either the P6.2
  audit or this trace confirms the exact prompt's "guests applaud" element,
  so this is not upgraded to VERIFIED here.

--------------------------------
## KISS / RING
--------------------------------

**RING** — day position 0.1947 (median of 8; 4 members share one asset,
`C7161`). Kept 4/8: **exactly the 4 `C7161` PLAUSIBLE_MATCH shots**; dropped
all 4 non-`C7161` members, which happen to be the moment's 2 AMBIGUOUS and
**both** FALSE_POSITIVE shots (`5476176d`, `0ed9b29d`). **This is a clean
positive interaction**: chronology filtering independently converges on
exactly the semantically-useful subset, raising the kept-set's effective
precision from 4/8 useful to 4/4.

**KISS** — day position 0.4469 (median of 8, all timed). Kept 4/8: `a0240fc9`
(PLAUSIBLE), `706a148f` (PLAUSIBLE), `9793d369` (AMBIGUOUS), `642f3479`
(PLAUSIBLE). **Dropped 4/8 — including BOTH of the moment's only TRUE_MATCH
shots** (`bd091ada`, `06ea0fb7`, both `C7228`, at day_position 0.3901,
distance 0.0568 from the 0.4469 median — just outside the ±0.05 spread).
**This is a genuine negative interaction**: the chronology filter, tuned on a
different (Elenora) shoot's spread characteristics per its own code comments,
removes the best evidence for `kiss` on this shoot because the true-positive
episode sits marginally (0.007 of a day-fraction) outside the fixed 0.05
window relative to this particular shortlist's median. Not tuned or reported
as a recommendation to change the threshold — reported as observed behavior
only, per the package's explicit no-tuning instruction.

--------------------------------
## INTRO
--------------------------------

opening_sign result: **0/27 true, carried forward from P6.2 unchanged.**

Does another intro semantic mechanism exist? Searched `planner.py` for other
opening-related logic: `OPENING_RAMP_DAY_LIMIT`/`OPENING_DAY_LIMIT` (both used
at `day_by_asset.get(shot.asset_id, 0.0) <= limit`, lines 2219/2223) are
**pacing/day-position gates**, not semantic content selectors — they restrict
which shots are eligible for the opening by *when in the day* they were
filmed, using the same `day_by_asset` traced above, but say nothing about
*what* is in frame.

**INTRO ROOT PROBLEM:** semantic recovery (P6.1) activates
`project_opening_signs()`, but on 15A it returns no genuine welcome-sign
candidate (P6.2). The planner's only other opening-relevant mechanism is a
day-position pacing gate that has no content-awareness of its own. **SEMANTIC
RECOVERY DOES NOT BY ITSELF SOLVE INTRO CONTENT** for 15A — confirmed, not
just carried forward.

--------------------------------
## OUTRO
--------------------------------

- closing pacing: `CLOSING_DAY_FLOOR` (line 2536,
  `day_by_asset.get(shot.asset_id, 1.0) >= CLOSING_DAY_FLOOR`) is a real,
  working day-position gate — late-day assets (`C7440`–`C7452`, positions
  0.93–1.0) are the eligible pool for closing material by construction.
- closing content semantics: no equivalent to `project_opening_signs()`
  exists for closings in `moments.py` — the outro has pacing (which assets
  are *allowed* late) but no semantic *preference* for what kind of late
  content to close on (e.g., a "goodbye"/"departure" prompt). Confirms the
  P6.0-era distinction cleanly: **closing pacing exists; closing semantic
  resource does not.** Not implemented here, per scope.

--------------------------------
## MUSIC-FIRST INTERACTION
--------------------------------

`_score_candidate()`'s additive score includes `MUSIC_FIT_WEIGHT * music_fit`
alongside `+ moment_bonus` (both independent additive terms, planner.py
:1831-1855) — they do not gate or veto each other; `moment_bonus` is a flat
`+0.1` added on top of whatever `music_fit` already contributed. Neither term
can drive the score negative-infinite or force a selection outright: a shot
with a bad music fit but active `moment_bonus` still pays the same
`MUSIC_FIT_WEIGHT` penalty other shots at that cut pay. This means **moment
coverage and music-first sequencing structurally cooperate rather than
compete** — `moment_bonus` nudges the ranking, it does not override music
fit. No tuning performed; this is a description of the existing constant
arithmetic, confirmed by reading the score formula, not by running it.

--------------------------------
## CURRENT vs SHADOW
--------------------------------

**CURRENT 129-item rough cut (production, unchanged):** `moments=None` is
implicitly what production `build_timeline()` receives for 15A today (no
embeddings, `project_moments()` returns nothing usable) — no moment coverage
mechanism engages at all; category-share `_story_coverage_warning()` (the
separate, weaker mechanism) is the only story-related signal in play.

**SHADOW (this package's evidence):**
- cake: would become due in correct day order, 8/8 clean members, no
  structural blocker — **coverage would activate**.
- first_dance: would become due in correct day order, carries a known-genuine
  member — **coverage would activate**, but which specific shot represents it
  is chronology-blind and unproven.
- entrance/ring/kiss: all three show real `_moment_shots_of_the_day`
  chronology effects (ring positively, kiss negatively, entrance mixed) —
  the mechanism is live and consequential, not inert.

--------------------------------
## ROOT-CAUSE CHAIN
--------------------------------

1. missing embeddings → moment activation: **PASS** (P6.1 — 6/6 moments
   activate on the real full population)
2. moment activation → human-valid episode: **PASS** (P6.2 — 5/6 moments have
   at least one human-confirmed valid episode; cake and, more weakly,
   cake_feed/first_dance/kiss/ring/entrance)
3. human-valid episode → planner activation (coverage): **PASS** for
   cake and first_dance (both would become due, no structural blocker)
4. planner activation → correct representative selection: **CONDITIONAL /
   UNPROVEN** — cake's uniform chronology makes this a non-issue; for
   first_dance, chronology offers no preference signal among members at all,
   and for kiss, chronology actively excludes the best evidence. Full
   resolution requires the same full-candidate-pool scoring pass excluded
   above (a materially separate, larger computation).

--------------------------------
## PLANNER ARCHITECTURE VERDICT
--------------------------------

**PARTIAL.** Coverage (moment activation → due-now → eligibility) is real and
demonstrated working for the two primary moments under test. Representative
selection within a moment is not demonstrated — for `first_dance`
specifically, the chronology layer is structurally blind to which member is
good vs. a confusable, and for `kiss` it actively works against the best
evidence on this particular shoot.

--------------------------------
## READY FOR REAL 15A REANALYSIS
--------------------------------

**CONDITIONAL.**

READY FOR PRODUCTION: **NO**

PROVEN:
- `day_by_asset` contract traced exactly, reproduced via the real production
  function (no reimplementation) — GATE P1 PASS.
- 352/362 (97.2%) of 15A assets get a chronology position; the missing 10 are
  systematically all drone clips.
- `cake`'s moment_day is clean and uncontradicted; the moment would become
  due with no structural blocker.
- `first_dance`'s moment coverage would activate too (known-genuine member
  present, no structural block), but its moment_day is anchored on its 2
  false-positive members specifically, because those are the only members
  with any chronology signal.
- Chronology filtering has a real, measurable, moment-specific effect: it
  improves `ring`'s effective precision (drops both false positives), has a
  mixed effect on `entrance`, and removes both true-positive shots from
  `kiss`.
- `moment_bonus` and `music_fit` are independent additive terms — no
  veto/override relationship found; moment coverage does not structurally
  fight music-first sequencing.
- Intro: confirmed no other semantic (content-aware) intro mechanism exists
  beyond the day-position pacing gate — semantic recovery alone does not
  solve intro content for 15A.
- Outro: pacing gate exists (`CLOSING_DAY_FLOOR`); no semantic closing
  resource exists, matching the intro finding's shape.

NOT PROVEN:
- The actual shot each moment would select once due (requires the full
  `_score_candidate()` input assembly across the 2638-shot pool at a specific
  cut — out of this package's read-only/no-full-timeline scope).
- Whether `first_dance`'s eventual representative would be `f5e4fa8a`
  (known-genuine), a `DJI_0529` plausible shot, or `C7433`/`24bbfc53`
  (false-positive) — chronology gives no basis to prefer any of them.

SAFETY: production DB, code, embeddings, timeline, Resolve, router, verifier
research, `MOMENT_PROMPTS`, thresholds, and planner code all unchanged
(verified below).

TESTS: `tests/test_p6_3_day_by_asset_trace.py` (8 tests, new) +
`tests/test_p6_2_population_and_audit.py` (5) +
`tests/test_shadow_moment_activation.py` (6) = 19/19 passed. Full suite
(excluding Resolve-only tests): **971 passed** (963 baseline + 8 new). `ruff`
clean.

--------------------------------
## PERFORMANCE
--------------------------------

`shadow_day_by_asset.py`: single SQL query over 362 rows + pure-Python
`_day_position()` call — runtime <0.5s, no metadata parsing failures.
`shadow_planner_trace.py`: single SQL query over 42 shot ids + in-memory
dict operations — runtime <0.5s. No embeddings recomputed (reused P6.1's
frozen moment fixture, no `.npz` regeneration).

==================================================
GATES
==================================================

- GATE P1 (day_by_asset contract): **PASS**
- GATE P2 (chronology coverage): **CONDITIONAL** — 97.2% mapped, but the gap
  is 100% of drone footage, which is directly relevant to first_dance
- GATE P3 (cake activation): **PASS** — clean moment, no blocker
- GATE P4 (first_dance activation): **CONDITIONAL** — coverage activates;
  representative quality unproven/chronology-blind
- GATE P5 (music-first compatibility): **PASS** — additive, non-vetoing terms
- GATE P6 (production isolation): **PASS** (verified below)

==================================================
FINAL VERDICT
==================================================

**B — Moments are useful and do activate planner coverage for cake and
first_dance, but representative-shot selection within a moment remains
unproven (first_dance) or actively works against the best evidence on this
shoot (kiss's chronology filter). One bounded shadow fix — either a full
candidate-pool scoring pass to observe actual representative selection, or a
review of the ±0.05 day-spread constant's sensitivity on non-Elenora
material — is needed before a real reanalysis, not because the architecture
is broken, but because "would it show up" and "would it show up well" are
different questions and only the first is answered here.**

READY FOR REAL 15A REANALYSIS: **CONDITIONAL**
READY FOR PRODUCTION: **NO**

**NEXT RECOMMENDED PACKAGE:** P6.4 — full-candidate-pool shadow scoring trace
for one cut window around each of `cake`'s and `first_dance`'s due-now point,
to observe actual representative-shot selection (closing the "coverage vs.
representative quality" gap this package identified but could not close
within its read-only/no-full-timeline scope). **DO NOT START.**

==================================================
FINAL SAFETY
==================================================

PRODUCTION CHANGED? NO
DB CHANGED? NO
EMBEDDINGS WRITTEN? NO
REANALYZED? NO
RESOLVE? unchanged
TIMELINE? none generated
SOURCE MOMENT? untouched
ROUTER? frozen R4b, untouched
VERIFIER? frozen, untouched
MOMENT PROMPTS? unchanged
THRESHOLDS? unchanged
PLANNER CODE? unchanged (diff empty)
NEW MODEL? none
CONTAMINATION? 0

==================================================
STOP CONDITION
==================================================

P6.3 tamamlandı. STOP — P6.4 başlatılmadı.
