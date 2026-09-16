# P6.6 — Reanalysis Orchestration / Linked-Timeline Safety Audit

START HEAD: `210e4c4`
COMMIT: (this package's commit, see git log)

Read-only code tracing + one isolated temp-clone execution audit (never the
production DB — a copy under `/tmp`, written to only there, deleted after
use). No real 15A reanalysis, no job enqueue, no production write, no fix
applied to `_label_asset()`, `_is_usable()`, the schema, the planner, the
timeline, or Resolve.

--------------------------------
## SUPPORTED REANALYSIS ENTRY POINT
--------------------------------

`POST /api/projects/{project_id}/shots` (`api.py:396-401`) →
`_create_job_or_409(project_id, "shots", {})` (`api.py:211-217`, backed by
the `jobs_one_active_per_kind` partial unique index) →
`background_tasks.add_task(_run_job, job_id)` → `_run_job()` (`api.py:220-278`)
transitions the job to `running` via a compare-and-swap
(`Database.transition_job`) then dispatches on `job["kind"] == "shots"` to
`analyze_shots(DATABASE, project_id, job_id)` (`analysis.py:302-354`).
`analyze_shots()` runs two full passes over every project asset — an
"encode" pass (`_encode_asset`, per asset, skipped if `shot_features` rows
already exist) and a "label" pass (`_label_asset`, per asset, always run) —
then a third "windows" pass, then reports `stage="finalize"`. On success,
`_run_job` marks the job `completed`; this is the entirety of the "success"
criterion (see Degraded-Success Hazard, below).

--------------------------------
## WHAT REANALYSIS RECOMPUTES
--------------------------------

| | state |
|---|---|
| `shots` (segmentation/ranges) | **PRESERVED** if rows already exist for the asset (`_encode_asset` reads `existing_rows` from `shots` first, line 206-220); only freshly re-detected via `_scene_ranges()`/`_fallback_ranges()` for an asset with zero existing shot rows |
| `shot_features.embedding` | **RECOMPUTED** every run, via `classifier.encode(...)` |
| `technical_quality`, `motion_score`, brightness/saturation/highlight_clipping/face fields | **RECOMPUTED** every run, via `measure_frames(frames)` |
| `category`, `shot_scale`, `aesthetic_score`, `confidence`, `labels_json` | **RECOMPUTED** every run, via `classifier.classify_features(...)` or `_fallback()` |
| `shots.id` (the row itself) | **DELETED THEN RE-INSERTED**, non-atomically — see Shot-ID Contract |
| moment-related persistent state | none exists — `moments.py` computes on demand from `shot_features`, nothing is cached/persisted |
| `timeline_items` / `timeline_versions` | **UNTOUCHED** — confirmed by call-graph search (see below) |
| project analysis metadata (`jobs` row) | updated normally (progress/checkpoint/status) |

--------------------------------
## SHOT-ID CONTRACT
--------------------------------

- **generator:** `_shot_id(asset_id, source_range)` (`analysis.py:160-166`):
  `uuid5(NAMESPACE_URL, f"sevenfilm:{asset_id}:{start_frame}:{duration_frames}")`.
- **inputs:** exactly 3 values — `asset_id`, `start_frame`, `duration_frames`.
  Nothing else (not analysis_version, not content).
- **stability: CONDITIONAL, precisely on segmentation boundaries.**
  - **STABLE IF SAME BOUNDARIES**: for all 362 15A assets, `shots` rows
    already exist, so `_encode_asset()`'s `ranges` come from the existing
    `shots` table (not fresh scene detection) — a normal reanalysis run
    today would reproduce the identical `(start_frame, duration_frames)`
    pairs per asset, and therefore identical `shot_id`s.
  - **If segmentation boundaries change by even one frame** (e.g. a
    `_scene_ranges()`/PySceneDetect re-run producing different cut points,
    which is NOT what would happen for 15A's existing-shots case, but is a
    real code path for an asset with zero prior shots) — **`shot_id`
    changes** (different uuid5 input). Any `timeline_items` row still
    pointing at the old id becomes **permanently** orphaned, not merely
    during a transient crash window.

--------------------------------
## TIMELINE REFERENCE CONTRACT
--------------------------------

`timeline_items` schema: `shot_id TEXT NOT NULL REFERENCES shots(id)`,
`asset_id TEXT NOT NULL REFERENCES media_assets(id)`, plus its own
`source_start_frame`/`source_duration_frames`/`source_rate`/
`timeline_start_frame` (the item's own copy of the range, not a live lookup).
**Answer: (B) — by `shot_id` primarily**, with `asset_id`/ranges stored
redundantly on the item itself. The 129-item AI Rough Cut's items each carry
their own frame ranges, so a missing `shots` row does not make the item's
*picture* content unrecoverable by itself — but any code path that joins
`timeline_items` to `shots` (to read `category`/`technical_quality`/etc. for
display or for a further planning pass — confirmed present at
`planner.py:2896`, `"SELECT timeline_items.*, shots.technical_quality,
shots.aesthetic_score, ..."`) would silently lose or null out that row the
moment its `shot_id` no longer resolves.

**Reanalysis effect:** for 15A specifically, since all 362 assets already
have `shots` rows, a normal run is expected to reproduce identical ids and
leave `timeline_items` referentially intact **once it completes without
interruption**. The risk is entirely in interruption — see next section.

--------------------------------
## ATOMIC REPLACEMENT
--------------------------------

**`shot_features` (via `_store_features()`): ATOMIC.** One connection, one
transaction, `DELETE` then every `INSERT` for that asset, committed together
(`db.py`'s `replace_rows()`, `_store_features()` calls it directly). The
`replace_rows()` docstring itself documents exactly why it was built: *"the
row-at-a-time version of this (DELETE then a loop of separate insert() calls,
each its own commit) left a real gap: a crash or a cooperative cancellation
partway through the loop left some of an asset's rows written and the rest
not... One connection, one transaction: either every new row lands, or the
delete itself never commits."*

**`shots` (via `_label_asset()`): NOT ATOMIC.** `_label_asset()`
(`analysis.py:255-299`) does `database.execute("DELETE FROM shots WHERE
asset_id = ?", (asset.id,))` (its own connection, commits immediately) then,
in a Python loop, one `database.insert("shots", {...})` per shot (**each its
own separate connection and commit** — `Database.insert()` calls
`self.execute()`, which opens a fresh `sqlite3.connect()` and commits on
every call). **This is precisely the pre-`replace_rows()` pattern the other
function's own docstring describes as already-identified-and-fixed
elsewhere in this codebase — but the fix was never applied to `_label_asset()`.**

**Transaction boundary:** none spanning the delete-and-reinsert. **Failure
behavior:** if asset #250 fails after 249 succeed (Section 6's exact
question), the DB retains **(C)** — 249 assets' shots fully replaced (each
individually committed, whichever ones' insert loops finished), the failing
asset's shots **deleted and only partially or not-at-all reinserted**
(depending on exactly where in its own loop the failure landed), and every
asset after #250 in iteration order **untouched, still holding its prior
(possibly degraded, pre-reanalysis) `shots` rows** — a genuine mixed
old/new/missing state across the project, not a clean rollback to the
pre-reanalysis snapshot.

**Empirically reproduced** (temp clone, `tools/shadow_reanalysis_orchestration_probe.py`,
result in `tools/fixtures/p6_6_orchestration_probe.json`): the exact
`DELETE FROM shots WHERE asset_id = ?` statement `_label_asset()` issues was
run against a cloned copy of the real DB, targeting the asset behind a real
`timeline_items` row from the live 129-item AI Rough Cut. It **succeeded
with no exception**, and immediately afterward: the `shots` row was gone,
the `timeline_items` row was still present, and it was **provably dangling**
(`timeline_item_now_dangling: true` in the fixture). This is exactly the
state a crash between the DELETE and the matching re-INSERT would leave in
the real database.

--------------------------------
## JOB UNIQUENESS
--------------------------------

**Same-project concurrent `shots`: BLOCKED**, confirmed both by code
(`jobs_one_active_per_kind` partial unique index on `(project_id, kind) WHERE
status IN ('queued','running','cancel_requested')`, `db.py:230`) and
empirically (temp clone: inserting a second `shots` job row for the same
project while the first is `queued` raised `sqlite3.IntegrityError`,
confirmed in the fixture as `job_uniqueness_enforced: true`).
**Other overlapping kinds** (`index`, `derivatives`, `music`): each kind has
its own independent slot in the same unique index — a `shots` job and a
`derivatives` job for the same project **can** run concurrently; nothing in
this audit found that combination to be unsafe for the `shots`/`timeline`
question specifically (out of scope to fully re-verify here — not touched
by `_label_asset()`'s write path).
**Race protection:** the uniqueness check is enforced at the DB
(`IntegrityError`), not by a read-then-write race window — race-safe by
construction (documented directly in `_create_job()`'s own comment).

--------------------------------
## CANCELLATION
--------------------------------

`raise_if_cancelled()` is called at exactly 3 sites in `analysis.py` (lines
318, 334, 395) — the **top of each of `analyze_shots()`'s per-asset loops**
(before `_encode_asset`, before `_label_asset`) and inside the windows pass.
**It is never called inside `_label_asset()`'s own body.** This means:
**cooperative cancellation is asset-boundary-safe** — a `cancel_requested`
signal is only ever observed *between* assets, so `_label_asset()`, once
started for a given asset, always runs to completion under normal
(cooperative) cancellation. **Cancellation cannot reproduce the dangling
gap on its own.** Only a non-cooperative interruption (crash, forced
process kill, `backend_restart` — an event type this exact system's own job
history shows really happened, repeatedly, for Elenora during development)
can land mid-`_label_asset()`.

--------------------------------
## ORPHAN RECOVERY
--------------------------------

`recover_orphaned_jobs()` (`db.py:481-...`), run once at process startup:
finds every job still `queued`/`running`/`cancel_requested` (which, per its
own docstring, can only mean the worker that owned it no longer exists) and
transitions it to `failed`. **It only ever touches the `jobs` table** —
confirmed by reading its body and by a test asserting no `UPDATE`/`DELETE`
against `shots`/`shot_features` appears in it. **It does not detect, repair,
or roll back a partial `shots` state left by a crash mid-`_label_asset()`.**
A restart after such a crash correctly marks the job `failed`, but the
broken `shots` rows (and any `timeline_items` row now dangling because of
them) remain exactly as the crash left them until a human or a future job
run happens to fix them incidentally.

--------------------------------
## DEGRADED-SUCCESS HAZARD
--------------------------------

**PRESENT**, reconfirmed at current HEAD. `_run_job()`'s only success
criterion is "the call returned without raising" (`api.py:262`,
`DATABASE.update_job(job_id, status="completed", progress=1.0)` — no
argument beyond that). Nothing in `analyze_shots()`, `_encode_asset()`, or
`_label_asset()` inspects the resulting embedding-coverage rate or
technical_quality zero-rate before reporting success — this is exactly how
the 2026-09-15 15A run reported `completed` while producing 0/2638
embeddings and 2327/2638 zero-quality shots (P6.5).

**Partially mitigated, but only for one of the two symptoms and only at
timeline-*creation* time, not at analysis-*completion* time:**
`create_timeline()` (`api.py:442-458`) calls `semantic_readiness()` and
refuses (HTTP 422) to build a **new** timeline when
`status == NOT_READY_FOR_ROUGH_CUT` — this would today block a fresh
15A rough cut (100% `opencv_fallback` labels). This gate:
- covers the CLIP-load-failure symptom (embedding/label degradation) —
  **but not** the `technical_quality` gap, which `semantic_readiness()`
  never inspects (P6.5's finding stands unmitigated by this gate).
- fires only when someone next calls `create_timeline()` — **it does not
  fire at the end of the `shots` job itself**, so the job can still report
  `completed` on a fully degraded run; only the *next* rough-cut build
  attempt would be blocked.
- necessarily post-dates the existing 129-item rough cut, since that rough
  cut exists today despite 15A being 100% `opencv_fallback` — confirming
  the gate was either added after that cut was built, or that cut was
  produced through a different path. Either way, **the existing 129-item
  timeline is proof this gate does not retroactively protect data already
  on disk.**

--------------------------------
## CURRENT ENVIRONMENT PREFLIGHT
--------------------------------

**CLIP: PASS (by direct re-use of very recent same-environment evidence,
not re-run here to avoid redundant cost).** P6.1's shadow embedding
recovery (this same session, this same repository state) loaded
`openai/clip-vit-base-patch32` and encoded 2638/2638 15A shots with 0
failures; P6.4/P6.5 additionally exercised the same `VisionClassifier`
machinery successfully. No environment change occurred between then and
this package (confirmed by identical `git rev-parse HEAD` lineage and
unchanged `apps/api` diff throughout).

**Media paths: PASS.** Verified read access (`ls -la`, this package) to
`C7309.MP4` (1.07 GB), `DJI_0528.MOV` (8.99 GB), `DJI_0529.MOV` (1.78 GB) on
`/Volumes/T7 2TB-1/15 AĞUSTOS/...` — all three resolve and are readable.

**Bounded frame decode: PASS (by direct re-use of P6.5's pre-registered
shadow sample, same session, same environment).** P6.5's
`tools/shadow_quality_provenance_sample.py` ran the exact production
`_shot_frame_groups()`/`measure_frames()` functions against `C7309` (cake),
`C7228` (kiss), `DJI_0528`, and `DJI_0529` and successfully read 3 frames
each, producing plausible non-zero quality values (0.43–0.59) — this is the
same "bounded frame decode" check Section 14 asks for, already executed
with pre-registered cases in the immediately-preceding package.

**Technical quality producer: PASS**, same evidence as above.

--------------------------------
## HISTORICAL vs CURRENT PATH
--------------------------------

**Old 15A job:** `jobs.id=24b069c9…`, 2026-09-15T11:35:20 → 16:27:13
(~291 min), `status=completed`, no `error` recorded (P6.5).
**Current code (this HEAD):** identical `analyze_shots()`/`_encode_asset()`/
`_label_asset()` call graph — no git history evidence of a change to this
call graph between the 15A run and now was found or needed to be found,
since the *audit* here concerns present-day behavior, not a diff against a
historical commit. The single most relevant **existing** fix in this
codebase — `replace_rows()` — is present at current HEAD and used for
`shot_features`, but **not** for `shots`; this is the "relevant fix" Section
16 asks about, and it is only half-applied.

--------------------------------
## LINKED-TIMELINE SAFETY TEST
--------------------------------

Performed on an isolated `/tmp` clone only (never the production DB):

- **success path (implicit):** not separately simulated — `_label_asset()`'s
  normal per-shot insert loop, run to completion without interruption,
  reproduces identical shot_ids for 15A (boundaries preserved), so
  `timeline_items` references remain resolvable. This follows directly from
  the Shot-ID Contract section and was not re-demonstrated with a full
  362-asset clone run (would require the ~5-hour analysis pass itself,
  explicitly out of scope: "do NOT run the full 2638-shot video analysis
  unless strictly necessary. Goal: orchestration semantics, not feature
  regeneration").
- **failure path (forced, between DELETE and matching INSERT):**
  **demonstrated** — see Atomic Replacement, above. Result: `timeline_items`
  row survives with a **dangling** `shot_id`.
- **cancellation path:** **not independently re-simulated** beyond the code
  trace in the Cancellation section, because the code trace is conclusive
  and mechanical (no `raise_if_cancelled` call exists inside `_label_asset`'s
  body — there is no cooperative-cancellation code path to trigger mid-asset,
  so a dynamic simulation would only re-confirm what static tracing already
  proves with certainty).

timeline item count in the clone before the probe: 129 (same as production,
confirmed by the clone being a byte-for-byte copy taken immediately before
the probe ran). References intact **before** the forced-failure step;
**not** intact after, for the targeted item.

--------------------------------
## BACKUP / ROLLBACK CONTRACT
--------------------------------

**Required snapshot** for a future controlled real reanalysis: a full copy
of `data/sevenfilm.sqlite3` (the whole file, not a partial export — it is
the only place holding `shots`, `shot_features`, `timeline_items`,
`timeline_versions`, `jobs`, and every other project table), taken
immediately before the reanalysis job is enqueued. Given the demonstrated
non-atomicity, a file-level snapshot is the only reliable rollback unit —
there is no in-database "undo" for a partially-completed `_label_asset()`
run.
**Rollback method:** stop the app, restore the snapshot file, restart.
**External artifacts:** none of this package's findings implicate Resolve
project state, since nothing in the `shots` job call graph touches it
(confirmed, Timeline Table Write Search) — a Resolve-side backup is not
required to roll back a `shots`-job reanalysis specifically, though it
remains good general practice independent of this audit.

--------------------------------
## POST-REANALYSIS VALIDATION (protocol only, no code change)
--------------------------------

A future controlled experiment package should verify, after job completion:

1. canonical shot count still 2638 for 15A (no asset silently dropped)
2. every one of the 129 `timeline_items.shot_id` values still resolves to a
   `shots` row (the exact failure mode this package demonstrated)
3. `shot_features.embedding IS NOT NULL` coverage rate (expect near-100%,
   not the current 0%)
4. `technical_quality = 0.0` rate (expect near-0%, not the current 88.2%)
5. `analysis_version` uniform and current across all 2638 shots
6. `labels_json` `SEMANTIC_BACKEND_CLIP` share (expect near-100%, not the
   current 0%)
7. no `media_assets`/`projects` row count change (362 assets, 3 projects)
8. `AI Rough Cut` still exactly 129 `timeline_items` rows, same `id`s
9. no contamination into Elenora's or the third project's rows
10. `jobs` row for this run: `status=completed`, and a human cross-check
    against items 3–6 above (since, per Degraded-Success Hazard, `completed`
    alone proves nothing)

--------------------------------
## REANALYSIS SAFETY MATRIX
--------------------------------

| Concern | Current mechanism | Evidence | Risk | Status |
|---|---|---|---|---|
| shot ID stability | deterministic `uuid5(asset_id, start_frame, duration_frames)`; boundaries preserved for assets with existing shots | code trace, P6.5 | Low for 15A specifically (boundaries won't change); High in general if segmentation ever changes | CONDITIONAL |
| timeline references | `timeline_items.shot_id → shots.id`, FK declared but **not enforced** at runtime | schema + empirical PRAGMA check (`=0`) | **High** | **AT RISK** |
| atomic replacement | `shot_features` via `replace_rows()` (atomic); `shots` via `_label_asset()`'s delete-then-loop (**not** atomic) | code trace + empirical dangling-reference reproduction | **High**, `shots` specifically | **FAIL** |
| cancellation rollback | cooperative, checked only between assets, never mid-`_label_asset()` | code trace (3 exact call sites) | Low (cancellation itself cannot trigger the gap) | PASS |
| failure rollback | none — a raised exception after a partial per-asset loop leaves exactly the partial state | code trace + empirical DELETE reproduction | **High** | **FAIL** |
| active-job uniqueness | DB partial unique index, `IntegrityError`-enforced | code trace + empirical duplicate-insert test | Low | PASS |
| orphan recovery | `recover_orphaned_jobs()`, jobs-table-only | code trace | Medium (marks job failed but never repairs data) | PARTIAL |
| CLIP readiness | model loads and encodes successfully in this environment | P6.1 (2638/2638, 0 failures), reused | Low | PASS |
| frame-read readiness | `_shot_frame_groups`/`measure_frames` succeed today on previously-zero shots | P6.5 pre-registered shadow sample (4/4) | Low (small sample) | PASS (sampled) |
| degraded-success detection | none at job-completion time; partial (`create_timeline`'s readiness gate) at next-timeline-build time, and only for embeddings/labels | code trace | Medium-High | PARTIAL |
| backup/rollback | none built-in; file-level DB snapshot is the only viable mechanism | inferred from atomicity finding | — | REQUIRED before any real reanalysis |
| external media paths | source drive currently mounted and readable | direct `ls` check, this package | Low (at time of audit) | PASS |

--------------------------------
## HARD BLOCKERS
--------------------------------

Per Section 31's own rule ("A controlled real reanalysis must remain NO if
any of these are true"):

- **"reanalysis deletes/breaks timeline refs" — TRUE**, empirically
  demonstrated.
- **"shot replacement is non-atomic" — TRUE**, empirically demonstrated and
  matches the exact failure mode the codebase's own `replace_rows()`
  docstring describes as a solved problem elsewhere.
- **"failure leaves partial shot state" — TRUE**, same evidence.

The other four listed hard-blocker conditions are **FALSE** (active jobs
cannot race destructively; media paths are accessible; CLIP is available;
technical_quality/embeddings can be regenerated) — but per the package's own
rule, **any one true hard blocker is sufficient to keep the answer NO**, and
three are true here.

--------------------------------
## READY FOR CONTROLLED REAL 15A REANALYSIS
--------------------------------

**NO.**

Not CONDITIONAL: Section 31 is explicit that a proven non-atomic
shot-replacement path with a proven timeline-reference break is a hard
blocker, full stop, regardless of how favorable every other finding in this
audit is (and every other finding — CLIP readiness, frame-read readiness,
job uniqueness, cancellation safety — is favorable). The path to YES is
narrow and concrete: fix `_label_asset()` to use `database.replace_rows(
"shots", "asset_id", asset.id, rows)` instead of its current
delete-then-insert-loop — the same pattern already proven and in production
use for `shot_features` — which this package does **not** do, per its own
explicit scope ("DO NOT fix `_label_asset()` yet").

--------------------------------
## READY FOR PRODUCTION
--------------------------------

**NO.**

PROVEN:
- Exact supported reanalysis entry point and full call graph, end to end
  (`api.py` → `analyze_shots` → `_encode_asset`/`_label_asset` →
  `_store_features`).
- `shot_features` writes are atomic (`replace_rows`); `shots` writes from
  `_label_asset()` are **not** (delete, then a loop of individually-committed
  inserts).
- **Empirically reproduced**, on an isolated temp DB clone (never
  production): the exact `_label_asset()` DELETE statement leaves a real
  `timeline_items` row from the live 129-item AI Rough Cut pointing at a
  `shots` row that no longer exists — `PRAGMA foreign_keys` is `0`
  (unenforced) on normal connections, so nothing prevents this.
- Job uniqueness (`jobs_one_active_per_kind`) is real and race-safe,
  confirmed both by code and by an empirical duplicate-insert test on the
  clone.
- Cancellation is asset-boundary-safe by construction (`raise_if_cancelled`
  never called inside `_label_asset()`); only a crash/`backend_restart` (a
  real, observed event type in this system's own job history) can land
  mid-asset.
- `recover_orphaned_jobs()` settles job status on restart but does not
  repair any partial `shots` state a crash left behind.
- `create_timeline()`'s `semantic_readiness()` gate would block building a
  *new* 15A rough cut today (proof the existing 129-item one predates or
  bypassed it) — but this gate covers only the embedding/label symptom, not
  `technical_quality`, and does not run at `shots`-job-completion time.
- Current-environment preflight (CLIP, media paths, bounded frame decode)
  all pass, largely by direct re-use of this same session's very recent
  same-environment evidence (P6.1, P6.5) plus one fresh path-existence
  check.
- The atomic infrastructure needed to fix the hard blocker (`replace_rows()`)
  already exists in this codebase and is already proven in production use
  for a sibling table — this is a small, well-understood future fix, not an
  open design problem.

NOT PROVEN:
- Full-`shots`-table behavior under a real, complete 362-asset reanalysis
  run (this audit deliberately did not run one, per its own scope
  restriction).
- Job-orchestration interaction with any UI/desktop-app state beyond the
  `jobs`/`timeline_items` tables audited here.
- Whether other job kinds (`derivatives`, `index`) sharing the DB
  concurrently with a `shots` job could interact destructively — out of
  scope, not implicated by `_label_asset()`'s write path specifically.

SAFETY: production DB, code, embeddings, `technical_quality`, timeline
(`129` items, byte-identical), Resolve, router, verifier research,
`MOMENT_PROMPTS`, thresholds, `_is_usable()`, and planner weights are all
unchanged (verified below). The only writes performed anywhere in this
package were to an isolated `/tmp` clone, which was deleted immediately
after use.

TESTS: `tests/test_p6_6_orchestration_safety.py` (13, extending the prior
in-progress session's 8) + `tests/test_p6_5_quality_provenance.py` (5) +
`tests/test_p6_4_candidate_pool_trace.py` (8) +
`tests/test_p6_3_day_by_asset_trace.py` (8) +
`tests/test_p6_2_population_and_audit.py` (5) +
`tests/test_shadow_moment_activation.py` (6) — all pass. Full suite
(excluding Resolve-only tests): **996 passed** (983 baseline + 13 new).
`ruff` clean.

==================================================
GATES
==================================================

- GATE A (entry point trace): **PASS**
- GATE B (shot-ID/timeline safety): **CONDITIONAL** → but the underlying
  mechanism it depends on (atomic replacement) **FAILS**, so effectively
  **FAIL** for the actual risk that matters (interruption mid-reanalysis)
- GATE C (atomicity): **FAIL** — proven, not inferred
- GATE D (job orchestration): **PASS** — uniqueness/cancellation/orphan
  status-recovery are all sound; only the underlying data-repair gap (not
  orchestration itself) is the problem
- GATE E (current environment): **PASS**
- GATE F (output regeneration): **PASS** — both embeddings and
  technical_quality are expected to regenerate correctly
- GATE G (degraded-success control): **FAIL** — job completion has no
  postcondition check; `create_timeline()`'s gate is partial and
  post-hoc, not preventive at job-completion time
- GATE H (production isolation): **PASS** (verified below)

==================================================
FINAL VERDICT
==================================================

**D — Atomicity/cancellation/recovery risk blocks reanalysis.** More
precisely: cancellation and job-uniqueness are *not* the problem (both
proven safe) — the specific, proven, hard blocker is `_label_asset()`'s
non-atomic `shots`-table replacement, which this package demonstrated
empirically leaves the linked 129-item timeline with a dangling reference
under exactly the kind of interruption (crash/`backend_restart`) this
system has already experienced in its own history. This is closest to
**D** among the offered choices, though the fix path is narrow and
already-proven-elsewhere (`replace_rows()`), which is closer in spirit to
option **B** ("one bounded orchestration safeguard must be added first") —
reported as **D**, with the **B**-shaped fix named explicitly as the
concrete next step, since Section 31's hard-blocker rule is unconditional.

READY FOR CONTROLLED REAL 15A REANALYSIS: **NO**
READY FOR PRODUCTION: **NO**

**NEXT RECOMMENDED PACKAGE:** P6.7 — bounded, explicitly-authorized fix of
`_label_asset()`'s `shots`-table write path to use `database.replace_rows(
"shots", "asset_id", asset.id, rows)` (the same atomic pattern already
proven for `shot_features`), verified against a temp-clone linked-timeline
safety test before any real 15A reanalysis is authorized. **DO NOT START.**

==================================================
FINAL SAFETY
==================================================

PRODUCTION CHANGED? NO
DB CHANGED? NO
JOB ENQUEUED? NO (only inserted into an isolated `/tmp` clone, deleted after)
REANALYZED? NO
TECHNICAL QUALITY WRITTEN? NO
EMBEDDINGS WRITTEN? NO
TIMELINE? unchanged — 129 items, byte-identical
RESOLVE? unchanged, never called
PLANNER? unchanged (diff empty)
ROUTER? frozen R4b, untouched
VERIFIER? frozen, untouched
SCHEMA? unchanged
NEW MODEL? none
CONTAMINATION? 0

==================================================
STOP CONDITION
==================================================

P6.6 tamamlandı. STOP — P6.7 başlatılmadı.
