# P6.5 — Technical Quality Provenance / Analysis-Gap Root-Cause Audit

START HEAD: `23801de`
COMMIT: (this package's commit, see git log)

Read-only + one small pre-registered shadow recompute (Gate 17/18), exactly
as scoped. No production fix, no reanalysis, no backfill, no threshold
change, no `_is_usable()` change.

--------------------------------
## TECHNICAL_QUALITY CONTRACT
--------------------------------

- **column:** `shots.technical_quality REAL NOT NULL` (`db.py:53`) — no SQL
  `DEFAULT` clause, so every INSERT must supply a value explicitly.
- **domain default:** `Shot.technical_quality: float = 0.5` (`domain.py:38`)
  — the dataclass's own Python-level default, used only when constructing a
  `Shot` object directly without a DB row (never hit for DB-sourced shots).
- **nullable:** no (schema `NOT NULL`).
- **range:** `[0.0, 1.0]`, `_clamp()`-bounded in the producer.
- **semantic meaning of literal `0.0`:** **(B) — not computed / absence
  represented as zero**, confirmed by direct code reading:
  `measure_frames(frames)` (`vision.py:211`) starts with `if not frames:
  return FrameMetrics(0.0, 0.0, "missing", 0)` — this is an explicit,
  hard-coded sentinel for "no frames were available to measure," not a
  computed low score. `0.0` is a valid mathematical minimum a real
  measurement could also reach in principle, but the *empty-frames* branch
  hard-codes it regardless of what the footage actually looks like.
- **producer function(s):** `measure_frames()` (`vision.py:211-260`,
  producing `FrameMetrics.technical_quality`), fed by `_usable_quality()`
  (`vision.py:194-208`, the real formula: `0.45*sharpness + 0.35*exposure +
  0.20*contrast`, then penalized by clipping/flatness) applied to each
  sampled frame and reduced by `median`.
- **read path / fallback quirk:** `row_to_shot()` (`analysis.py:129-148`,
  the path used to build the full candidate pool for `build_timeline()`)
  reads `float(row["technical_quality"])` **with no fallback** — a stored
  `0.0` passes straight through as `0.0`. Elsewhere, `planner.py:2927`
  (a *different* read path, for reconstructing shots already placed on an
  existing timeline) reads the same column as `float(row["technical_quality"]
  or 0.5)` — **explicitly treating a falsy/zero value as "unknown, use the
  domain default 0.5."** This is an internal inconsistency in the codebase's
  own contract for the same field: one code path already encodes the
  assumption that `0.0` can mean "unknown," the other (the one that matters
  for candidate eligibility) does not apply it.

**GATE A (zero semantics): PASS** — resolved by direct code reading, not
inference: `0.0` from `measure_frames([])` is an explicit missing-input
sentinel, further confirmed by the shadow sample below (Section: Shadow
Sample).

--------------------------------
## WRITE PATHS
--------------------------------

- **normal path:** `_encode_asset()` (`analysis.py:204-229`) — the single
  producer for both `technical_quality` and the CLIP embedding, in the SAME
  function, from the SAME `frame_groups = _shot_frame_groups(asset, ranges)`
  call. No other function writes `shot_features`/`shots.technical_quality`.
- **fallback path:** none distinct — `measure_frames()` is called
  unconditionally on whatever `frame_groups` produced; if a shot's group is
  empty, the `0.0` sentinel above is what gets stored. There is no separate
  "opencv fallback quality" branch — `_fallback()` (`vision.py:303-320`,
  which decides `category`/`shot_scale`/`aesthetic_score`/`confidence` when
  CLIP is unavailable) **reads** `metrics.technical_quality` but does not
  write or alter it.
- **error path:** none found that specifically catches and zeroes
  `technical_quality` — the zero always comes from the empty-frames branch
  of `measure_frames()`, i.e. from `_shot_frame_groups()` failing to read
  any frame for that shot's time range.
- **legacy/migration:** none found — no `ALTER`/`UPDATE` touching
  `technical_quality` anywhere in `db.py`'s migration list
  (`ADDED_COLUMNS`) or elsewhere in the service layer.
- No branch was found that creates a `shot_features`/`shots` row while
  skipping `technical_quality` computation outright — it is always computed,
  the question is only whether `frame_groups[i]` was empty when it ran.

--------------------------------
## _IS_USABLE CONTRACT
--------------------------------

`_is_usable(shot, minimum_quality, maximum_clipping)` (`planner.py:1047-1051`):
`if shot.technical_quality < minimum_quality: return False`. No `None`
handling exists because the field is `NOT NULL` (never `None` for a
DB-sourced `Shot`). No category, moment, or source-type exception exists —
confirmed by reading the function body (2 lines, no conditionals beyond the
quality/clipping checks). `minimum_quality` itself comes from
`_quality_gates()` (`planner.py:731-748`): `max(ABSOLUTE_MIN_QUALITY(0.15),
median(shots' technical_quality) * RELATIVE_MIN_QUALITY(0.6))`. **`0.0` is
therefore always treated as measured, sub-floor quality — there is no
"unknown, don't judge" branch anywhere in this function.** This confirms the
package's Section 3 requirement directly: zero is architecturally
indistinguishable from genuinely bad footage at this gate.

--------------------------------
## 15A DISTRIBUTION
--------------------------------

```
shots: 2638
  technical_quality = 0.0:   2327 (88.2%)
  technical_quality > 0.0:    311 (11.8%)
analysis_version: uniformly "4" for all 2638 (single value, no mixed/legacy versions)
```

**By source type:**
```
                shots   zero-quality   rate
drone (DJI_*)     941            941  100.0%
sony  (C7***)    1697           1386   81.7%
```

**By fallback category:**
```
category   shots   zero-quality   rate
venue       2508           2327   92.8%
bride         71              0    0.0%
couple        49              0    0.0%
family        10              0    0.0%
```
Every zero-quality shot is `venue` category; every `bride`/`couple`/`family`
shot has real, non-zero quality. (`venue` is the `opencv_fallback` category
assigned when face-count is 0 — see `vision.py:303-312`.)

**All 2638 15A shots carry the `opencv_fallback` label** (verified directly:
`labels_json LIKE '%opencv_fallback%'` matches all 2638 rows, 0 carry
`clip_vision`) — this is independent of and total, unlike the partial
technical_quality gap.

--------------------------------
## ELENORA CONTROL
--------------------------------

```
shots: 1405
  technical_quality = 0.0:      0 (0.0%)
  mean technical_quality:   0.399
  embedding populated:   1405/1405 (100%)
```

Elenora's first full "shots" analysis job (`67f62928…`, 2026-09-02T22:02:30 →
23:36:39, **~94 minutes**) completed successfully and produced this fully
populated state directly — no subsequent job needed to backfill anything.
Later Elenora job history shows normal iterative development (explicit
supersessions logged in Turkish — "Yeni hızlı analiz akışına geçirildi" /
"switched to the new fast analysis flow" — and several
`interrupted: backend_restart` entries from this development environment
restarting, unrelated to analysis correctness), but the very first run
already reached full coverage.

--------------------------------
## MOMENT MEMBER IMPACT
--------------------------------

| Moment | members | quality=0 | quality>0 | pass `_is_usable` |
|---|---|---|---|---|
| entrance | 8 | 5 | 3 | 3 |
| ring | 8 | 3 | 5 | 5 |
| kiss | 8 | 8 | 0 | **0** |
| cake | 8 | 8 | 0 | **0** |
| cake_feed | 8 | 8 | 0 | **0** |
| first_dance | 8 | 8 | 0 | **0** |

Exact numeric confirmation of P6.4's empirical finding: `kiss`, `cake`,
`cake_feed`, and `first_dance` lose **100% of their shortlisted members** to
this gate; `ring` and `entrance` lose a minority (3/8 and 5/8 respectively),
which is why they alone reached scoring in P6.4's live run.

--------------------------------
## CURRENT ROUGH CUT SURVIVOR BIAS
--------------------------------

```
Full 15A population (2638 shots): 2508 venue (95.1%), 71 bride, 49 couple, 10 family
Current AI Rough Cut (129 items):    0 zero-quality,  129/129 non-zero
                                     40 venue (31.0%), 41 bride, 40 couple, 8 family
```

**Every one of the 129 rough-cut items has non-zero technical_quality —
literally none of the 2327 zero-quality shots survived to the cut**, exactly
as `_is_usable()`'s unconditional gate predicts. The category mix is
dramatically inverted relative to the full population: `venue` drops from
95.1% of all shots to 31.0% of the cut, while `bride`/`couple`/`family`
(together only 4.9% of all shots) supply 69.0% of the cut. **This
quantitatively explains why the existing rough cut reads as semantically
narrow** — it is not a curatorial choice, it is the necessary shape of
whatever small, real-quality-data subset survives a gate that happens to
strip out 95% of the `venue` bucket specifically.

--------------------------------
## PIPELINE PROVENANCE
--------------------------------

| Stage | 15A | Elenora |
|---|---|---|
| indexing (`index` job) | completed, `"unreadable": []` — every file, including all 10 DJI clips, read successfully at index time | completed |
| shot segmentation (ranges) | present (2638 shots exist with valid `start_frame`/`duration_frames`) | present (1405 shots) |
| frame read for quality (`_shot_frame_groups`) | **succeeded for only 11.8%** (per-shot; see below) | succeeded for effectively 100% (0% zero-quality) |
| technical_quality computation | ran (never skipped), but computed on empty input 88.2% of the time | ran on real input for all shots |
| CLIP model load (`VisionClassifier._load()`) | **failed for the entire run** (100% `opencv_fallback` labels, 0% CLIP-labeled) | succeeded (100% embedding coverage) |
| CLIP embedding | **0/2638 (0%)** | 1405/1405 (100%) |
| semantic classification | 100% face-count heuristic fallback | full CLIP-based |
| `shots` job outcome (DB `jobs` table) | **completed**, progress 1.0, no `error` — but runtime **~291 minutes** (11:35:20 → 16:27:13) | **completed**, progress 1.0, no error, runtime **~94 minutes** for the first successful run |

The 15A "shots" job did not fail, crash, or get cancelled by any visible job
record — it ran to full, successful completion by its own bookkeeping, ~3×
slower than Elenora's comparable successful run, while silently substituting
the fallback path for 100% of its scope. This is architecturally significant:
**neither the job runner nor `VisionClassifier._load()` surfaces a
CLIP-unavailable condition as a job failure** — `_load()`
(`vision.py:274-301`) catches `Exception` broadly, logs a `LOGGER.warning`,
and returns `False`; every caller treats a `False` load result as "use the
fallback," never as an error to propagate. The job then reports success.

--------------------------------
## EMBEDDING + QUALITY RELATIONSHIP
--------------------------------

**Classification: A, with two distinct failure mechanisms inside one shared
incident** (closest to option A, more precise than a single flat "same
event"). Evidence:

1. **The CLIP-load failure is total (100%) and explains the embedding gap
   completely on its own** — `classifier.encode()` returns `None` outright
   when `_load()` fails, for every shot in every call, regardless of that
   shot's individual frame quality. This matches the observed 100%
   embedding-NULL rate exactly, and matches the 100% `opencv_fallback` label
   rate exactly (same `_load()` failure gates both).
2. **The frame-read/technical_quality failure is partial (88.2%, not 100%)**
   and comes from a different function (`_shot_frame_groups()`'s
   `cv2.VideoCapture` reads) inside the *same* `_encode_asset()` call. It is
   not caused by the CLIP failure and does not cause it — they are two
   independent conditionals inside one function, both exercised during the
   same abnormally slow (~291-minute) job run.
3. Both point to the same underlying incident (one degraded 15A "shots" job,
   2026-09-15T11:35–16:27) rather than two unrelated historical problems —
   there is only one `shots` job in 15A's history that could have produced
   this state, and it produced both symptoms together.

This is **not** (C) a technical_quality-specific bug independent of the
embedding issue, and **not** (D) a persistence bug (the shadow sample below
shows the stored values are faithfully read back; the gap is in what was
computed, not in storage/retrieval). It is closer to (B) "related but
separate stages" than a pure (A) "identical mechanism," so it is reported as
a hybrid: one incident, two mechanisms.

--------------------------------
## UNKNOWN-AS-ZERO HAZARD
--------------------------------

**PRESENT.** `0.0` from `measure_frames([])` is architecturally
indistinguishable, once stored, from a genuinely poor `_usable_quality()`
score. `_is_usable()` has no way to tell them apart (Section: `_IS_USABLE
CONTRACT`, above). The codebase already contains a documented awareness of
this exact hazard for the *same field* at a different read site
(`planner.py:2927`'s `or 0.5`) — but that safety net is not applied at the
read site (`row_to_shot()`) that determines candidate-pool eligibility.

--------------------------------
## NULL VS ZERO SEMANTICS
--------------------------------

`shot_features.embedding` (nullable `BLOB`) represents "not analyzed" with
an explicit `NULL` — every downstream consumer (`moments.py`'s queries all
say `WHERE embedding IS NOT NULL`) correctly and unambiguously excludes
unanalyzed shots. `shots.technical_quality` (`NOT NULL REAL`) has no such
channel — "not analyzed" and "analyzed, found to be exactly the floor" both
collapse to the same stored value. **This inconsistency is real and
worth naming precisely**: the codebase's own architecture already solved
this problem correctly for embeddings (explicit nullability) but not for
technical_quality (implicit zero). No schema change is proposed or made
here — diagnosis only, per scope.

--------------------------------
## SHADOW SAMPLE
--------------------------------

**RUN.** Gate 17 satisfied: the exact production functions
(`_shot_frame_groups()`, `measure_frames()`) were importable and runnable
read-only, with no model download and no DB write. Pre-registered (defined
as a module constant before execution) 6-case sample:
`tools/shadow_quality_provenance_sample.py` →
`tools/fixtures/p6_5_shadow_quality_sample.json`.

| case | stored | frames read now | fresh | verdict |
|---|---|---|---|---|
| cake `C7309` (b21ae921) | 0.000 | 3 | **0.434** | stale zero |
| kiss `C7228` (bd091ada) | 0.000 | 3 | **0.466** | stale zero |
| first_dance `DJI_0528` (f5e4fa8a) | 0.000 | 3 | **0.550** | stale zero |
| first_dance `DJI_0529` (cd10866a) | 0.000 | 3 | **0.589** | stale zero |
| ring `C7161` control (c83d488f) | 0.360 | 3 | 0.360 | harness fidelity confirmed |
| entrance `C7176` control (a979a3fd) | 0.349 | 3 | 0.349 | harness fidelity confirmed |

**All 4 pre-registered zero-quality cases produce sensible, plausible,
non-zero fresh values today** (0.43–0.59, comparable in magnitude to the
real stored values on `ring`/`entrance`). **Both controls reproduce their
exact stored values**, ruling out a harness/methodology artifact — the
shadow reproduction is faithful to production behavior. **This is strong,
direct evidence that the stored `0.0` values are stale/incomplete, not a
genuine measured property of this footage** — the underlying video files are
currently readable by the exact same `cv2.VideoCapture`-based code that,
during the original 15A run, apparently could not read them (or a large
fraction of them). Per Section 19, this finding is scoped strictly to
"was it computed," not to whether `0.15` (or any other value) is the right
threshold — that question is explicitly out of scope here.

--------------------------------
## CURRENT REANALYSIS BEHAVIOR
--------------------------------

Traced `_encode_asset()` (analysis.py:204-229) and `_store_features()`
(analysis.py:169-201) as the operative "reanalyze this asset" contract:

- **would recompute embeddings?** Yes — `_encode_asset()` always calls
  `classifier.encode(...)` fresh; nothing skips this based on prior state.
- **would recompute technical_quality?** Yes, same function, same call —
  `measure_frames(frames)` runs unconditionally per shot on each invocation.
- **would alter segmentation?** `ranges` is taken from the asset's
  *existing* `shots` rows first (`existing_rows` query,
  analysis.py:206-220) — **shot boundaries are preserved**, not
  re-detected, when shots already exist for the asset (as they do for all
  362 15A assets). Only assets with zero existing shot rows would fall
  back to fresh `_scene_ranges()` detection.
- **shot IDs stable?** Yes — `_shot_id()` (analysis.py:160-166) is a
  deterministic `uuid5` of `(asset_id, start_frame, duration_frames)`. As
  long as `ranges` is unchanged (guaranteed by the point above, since 15A's
  shots already exist), recomputing produces **identical shot IDs**.
- **timeline references safe?** `_store_features()` replaces only
  `shot_features` rows (`database.replace_rows("shot_features", "asset_id",
  ...)`), atomically, per the function's own docstring ("all of them or none
  of them" — see analysis.py:169-183). It does **not** touch the `shots`
  table itself, `timeline_items`, or `timeline_versions`. The existing
  129-item rough cut's `timeline_items` rows reference `shot_id`s in the
  `shots` table, which a "reanalyze" of this shape never modifies.

**A normal, currently-supported reanalysis run — using the exact code
already in this repository, unmodified — would very plausibly restore both
fields together in one pass**, based on: (a) this environment's CLIP model
is proven to load and encode successfully throughout P5.1–P6.4 (dozens of
real runs, including P6.1's 2638/2638 zero-failure shadow embedding
recovery), and (b) this package's own shadow sample just demonstrated the
exact production frame-reading and quality-measurement code succeeds on
4/4 previously-zero shots, right now, unmodified.

--------------------------------
## REAL REANALYSIS SAFETY
--------------------------------

**CONDITIONAL**, not because of any single defect but because "safe" here
depends on scope not audited in this package:

- SAFE with respect to: shot ID stability, timeline reference integrity,
  and segmentation preservation (all confirmed above for assets that already
  have `shots` rows, i.e. all 362 15A assets).
- **Not confirmed** here: whether the job-orchestration layer that invokes
  `_encode_asset()`/`_label_asset()` across all 362 assets (the "shots" job
  itself) has any interaction with the current 129-item timeline, the
  `jobs` table's one-active-job-per-kind constraint, or any UI/API state
  this package did not inspect. This is a scope boundary, not a finding of
  risk.

--------------------------------
## PRIMARY ROOT CAUSE
--------------------------------

```
15A "shots" job (jobs.id=24b069c9…, 2026-09-15T11:35:20 → 16:27:13, ~291 min,
  status=completed, no error recorded)
→ VisionClassifier._load() failed for this run's duration (exact underlying
  exception not recorded -- caught broadly by vision.py:298's `except
  Exception`, logged only at WARNING level, never surfaced to the job's
  `error` field)
→ classifier.encode(...) returned None for every asset's shots
→ shot_features.embedding stored as NULL for all 2638 15A shots (100%)
→ VisionClassifier._fallback() (face-count heuristic) used for every shot's
  category/scale/aesthetic_score/confidence, all labelled "opencv_fallback"
→ separately, within the same _encode_asset() calls, _shot_frame_groups()
  (cv2.VideoCapture-based) failed to read any frame for 88.2% of shots --
  mechanism/exact per-file cause not determined in this package, but
  demonstrated NOT to be a permanent property of the source files (the
  shadow sample reads them successfully today)
→ measure_frames([]) stored technical_quality=0.0 (the explicit
  no-frames sentinel) for those 2327 shots
→ planner._is_usable() (threshold 0.15, unchanged) excludes all 2327
  zero-quality shots from the candidate pool -- including literally 100%
  of cake's, kiss's, cake_feed's, and first_dance's P6.1-recovered
  shortlist members
→ the existing 129-item AI Rough Cut draws exclusively from the small
  surviving non-zero-quality subset, which is disproportionately
  bride/couple/family rather than venue -- not by curatorial choice, but
  because that is what clears the gate
```

--------------------------------
## BLOCKER ORDER
--------------------------------

P6.3/P6.4's provisional ordering ("1. technical_quality eligibility, 2. then
chronology/timecode, 3. then representative selection") **remains
justified** and is now sharpened: technical_quality's 88.2% exclusion (this
package) is strictly upstream of and larger in effect than the drone
timecode gap (P6.3, 100% of drone but only 1 of the 6 moments' members), and
representative-selection quality (P6.4's `moment_bonus`/`chronology_penalty`
mechanics) cannot be meaningfully evaluated for any moment whose members
never clear this gate in the first place. Order stands: (1) technical_quality
completeness, (2) drone chronology completeness, (3) representative
selection among eligible members.

--------------------------------
## PLANNER STATUS
--------------------------------

**SUPPORTED**, reaffirmed from P6.4 — the coverage/`moment_bonus`/chronology
machinery itself was already shown working (`ring`'s `5835af5d` selection).
Nothing in this package implicates the planner's scoring or selection logic;
the entire finding here is upstream, in data completeness.

--------------------------------
## READY FOR CONTROLLED REAL 15A REANALYSIS
--------------------------------

**CONDITIONAL.** The evidence assembled across P6.1–P6.5 is now
substantially stronger than at any prior checkpoint: the embedding gap
(P6.0/P6.1), the technical_quality gap (this package), and their shared
originating job are all identified with concrete evidence, and this
package's own shadow sample demonstrates the underlying fix path (a normal
`_encode_asset()` re-run) would very likely work today, with shot IDs and
timeline references provably stable. It remains CONDITIONAL rather than YES
because: (1) this is diagnosis, not verification at scale — only 4
zero-quality shots were sampled, not all 2327; (2) the job-orchestration
layer's interaction with the current 129-item timeline during a live
reanalysis was not audited; (3) per this package's own strict scope, no
reanalysis may be authorized from within a diagnostic package — that
decision point is for the user, informed by this report.

READY FOR PRODUCTION: **NO**

PROVEN:
- `technical_quality = 0.0` is an explicit "no frames measured" sentinel
  (`measure_frames([])`, `vision.py:218`), not a computed low-quality score
  — confirmed by code and by the shadow sample.
- `_is_usable()` has no unknown-vs-measured distinction; `0.0` is always
  treated as sub-floor real quality (`planner.py:1047-1051`).
- 88.2% of 15A's 2638 shots (100% of drone, 92.8% of `venue`-category Sony
  footage) carry this stale-zero sentinel; Elenora carries none (0/1405).
- The gap correlates with, but is not identical in rate to, the 100%
  embedding-NULL/100% `opencv_fallback`-label gap — both trace to the same
  single 15A "shots" job (2026-09-15, ~291 min, completed without a
  recorded error) but via two distinct mechanisms (total CLIP-load failure;
  partial frame-read failure) inside it.
- `kiss`, `cake`, `cake_feed`, and `first_dance` lose 100% of their P6.1
  shortlist members to this gate; `ring` (3/8) and `entrance` (5/8) lose a
  minority — exactly matching P6.4's live-run outcome.
- The current 129-item rough cut is 100% non-zero-quality shots and is
  disproportionately `bride`/`couple`/`family` relative to the full
  population — quantifying the "narrow" cut as a direct, mechanical
  consequence of this gate, not a separate curatorial issue.
- A pre-registered, code-faithful shadow sample shows all 4 tested
  zero-quality shots produce plausible non-zero values (0.43–0.59) when the
  exact production quality function runs today; both non-zero controls
  reproduce their stored values exactly.
- A normal supported reanalysis (`_encode_asset()`/`_store_features()`)
  preserves shot IDs and does not touch `timeline_items`/`timeline_versions`
  — the existing 129-item rough cut's references would not be invalidated
  by this specific write path.

NOT PROVEN:
- The exact underlying exception that caused `VisionClassifier._load()` to
  fail during the 2026-09-15 run (not recorded in the `jobs.error` field;
  only a `LOGGER.warning` call exists in code, and log files were not
  inspected in this package).
- The exact per-file/per-shot mechanism behind the 88.2% frame-read failure
  (codec correlation is strong for drone — 100% HEVC, 100% zero — but the
  Sony/h264 zero-quality shots, 81.7% of that camera's footage, were not
  further isolated).
- Full-population confirmation (only 4 of 2327 zero-quality shots were
  sampled) — the shadow sample is strong, pre-registered evidence, not a
  complete audit.

SAFETY: production DB, code, embeddings, `technical_quality` values,
timeline, Resolve, router, verifier research, `MOMENT_PROMPTS`, thresholds,
`_is_usable()`, and planner weights are all unchanged (verified below). The
shadow sample only *read* video files and *read* the DB; it never wrote
anywhere.

TESTS: `tests/test_p6_5_quality_provenance.py` (5, new) +
`tests/test_p6_4_candidate_pool_trace.py` (8) +
`tests/test_p6_3_day_by_asset_trace.py` (8) +
`tests/test_p6_2_population_and_audit.py` (5) +
`tests/test_shadow_moment_activation.py` (6) — all pass. Full suite
(excluding Resolve-only tests): **983 passed** (978 baseline + 5 new).
`ruff` clean.

==================================================
GATES
==================================================

- GATE A (zero semantics): **PASS**
- GATE B (producer provenance): **PASS** — exact write path identified
  (`_encode_asset` → `measure_frames` ← `_shot_frame_groups`)
- GATE C (15A vs Elenora causal difference): **PASS** — pipeline divergence
  identified (CLIP-load failure total; frame-read failure partial; both
  traced to one job run, contrasted against Elenora's clean first run)
- GATE D (same-root-cause diagnosis): **PASS** — classified as one incident,
  two mechanisms, with code + DB + job-log evidence
- GATE E (current reanalysis effect): **PASS** — traced exactly, and
  empirically supported by the shadow sample; a normal reanalysis would
  very plausibly restore both fields
- GATE F (reanalysis safety): **CONDITIONAL** — safe on the axes audited
  (shot ID stability, timeline reference integrity); job-orchestration
  interaction with the live timeline not audited
- GATE G (production isolation): **PASS** (verified below)

==================================================
FINAL VERDICT
==================================================

**A — 15A is a stale/incomplete analysis state (one degraded "shots" job
that silently fell back to OpenCV for 100% of its scope while also failing
frame reads for 88.2% of shots); a normal, currently-supported reanalysis
run should restore both embeddings and technical_quality, and the specific
write path involved does not disturb shot IDs or the existing 129-item
timeline's references. This is CONDITIONAL, not YES, purely because this
package's evidence is a diagnosis and a 4-shot confirmatory sample, not a
full-population verification or an audit of the job-orchestration layer's
live-timeline interaction.**

READY FOR CONTROLLED REAL 15A REANALYSIS: **CONDITIONAL**
READY FOR PRODUCTION: **NO**

**NEXT RECOMMENDED PACKAGE:** P6.6 — controlled, explicitly-authorized real
15A reanalysis dry-run audit: read-only inspection of the job-orchestration
layer's behavior when a "shots" reanalysis is queued against a project that
already has a bound timeline (does it require pausing/locking anything?
does `jobs_one_active_per_kind` interact with any in-progress state?), to
close GATE F before any actual reanalysis is authorized. **DO NOT START.**

==================================================
FINAL SAFETY
==================================================

PRODUCTION CHANGED? NO
DB CHANGED? NO
TECHNICAL QUALITY WRITTEN? NO
EMBEDDINGS WRITTEN? NO
REANALYZED? NO
RESOLVE? unchanged, never called
TIMELINE? unchanged — `129` items, unmodified
PLANNER? unchanged (diff empty)
ROUTER? frozen R4b, untouched
VERIFIER? frozen, untouched
MOMENT PROMPTS? unchanged
THRESHOLDS? unchanged (`ABSOLUTE_MIN_QUALITY`/`RELATIVE_MIN_QUALITY`/
  `_is_usable()` all read-only inspected, never modified)
SCHEMA? unchanged
NEW MODEL? none
CONTAMINATION? 0

==================================================
STOP CONDITION
==================================================

P6.5 tamamlandı. STOP — P6.6 başlatılmadı.
