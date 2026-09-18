# PACKAGE 06.11 — SAFE FORCE-REENCODE TRIGGER / SNAPSHOT-ROLLBACK

START HEAD: `9680c45`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Purpose: give the proven re-encode engine a **supported, no-pre-delete production trigger**, plus a
consistent snapshot/restore method and a strict read-only postcondition validator, so a future
controlled real run (P6.12) has a safe protocol. No production mutation. Code:
`apps/api/sevenfilm/api.py`, `apps/api/sevenfilm/services/analysis.py`; harness/validator:
`tools/p6_11_reencode_safety.py`; fixture: `tools/fixtures/p6_11_realforce.json`; tests:
`tests/test_p6_11_reencode_safety.py`.

--------------------------------
## CURRENT PATH
--------------------------------

normal reuse behavior: `POST /api/projects/{id}/shots` → `shots` job → `analyze_shots()`; the
encode pass is skipped for any asset that already has `shot_features`
(`if not _asset_features(...): _encode_asset(...)`), so a re-run only relabels — it never
recomputes technical_quality/embeddings. This is why 15A stays degraded.

force behavior (new): a single explicit flag flips the encode gate to
`if force_reencode or not _asset_features(...)`. Nothing else changes — crucially `_encode_asset`
already (P6.7/P6.10) reads boundaries from the existing `shots`, builds fresh rows in bounded
memory, and writes them via `_store_features`' atomic `replace_rows`, which is the only statement
that mutates `shot_features`.

--------------------------------
## NEW SUPPORTED TRIGGER
--------------------------------

- request/API: `ShotAnalysisRequest { force_reencode: bool = False }`, an **optional** body on the
  existing `POST /api/projects/{id}/shots` (an empty POST keeps the old behaviour). Pydantic bool
  validation; project scope unchanged; no wildcard / cross-project form.
- job payload: the flag is stored in the `shots` job checkpoint (`{"force_reencode": true}`) and
  read back in `_run_job`, so the job row is itself an audit record of a force run.
- default: `false` — ordinary reanalysis is byte-for-byte unchanged.
- audit metadata: job kind `shots` + `checkpoint_json.force_reencode`; the 202 response echoes
  `force_reencode`; per-asset progress/heartbeat already recorded by `update_job_progress`.

--------------------------------
## NO-PREDELETE CONTRACT
--------------------------------

**PASS.** Real-media proof on C7309 (16 shots that already had features, tq=0, embedding NULL): a
spy `Database` counted **0** standalone `DELETE FROM shot_features` before the atomic store
(`feature_deletes_before_store: 0`); the only `shot_features` mutation was the single
`replace_rows` inside `_store_features`. Old rows stay intact until a complete fresh set is ready.

--------------------------------
## SEGMENTATION / ID CONTRACT
--------------------------------

scene detector invoked: **0** (`_scene_ranges` never called — ranges come from existing `shots`).
shot IDs: **stable** (C7309 before==after). boundaries: **unchanged** (reused from `shots`).

--------------------------------
## REAL-MEDIA FORCE TEST
--------------------------------

asset: C7309 · existing features before: **16 present** (not deleted) · encode invoked: **yes**
(despite features present) · quality: tq-zero **16 → 0** (min 0.378) · embedding: **0 → 16**
(512-dim) · IDs: **stable** · timeline: unaffected · prod checksum: unchanged · result: **PASS** —
this is the decisive proof that the trigger problem is solved (recompute over existing features via
the supported flag, no manual feature deletion).

--------------------------------
## FAILURE ATOMICITY
--------------------------------

- encode failure: **PASS** — a unit test forces `_encode_asset` to raise under `force_reencode`;
  the asset's old `shot_features` remain byte-for-byte, the job raises (→ status failed).
- store failure: covered by the P6.7/P6.10 atomicity of `replace_rows` (single transaction,
  rollback on error) — old rows preserved.
- cancellation: `raise_if_cancelled` is at the asset boundary; an asset is either fully re-encoded
  (atomic replace) or untouched — no partial asset (inherited from the encode/label design).

--------------------------------
## IDEMPOTENCY
--------------------------------

A second force run recomputes the same asset from the same boundaries → same shot ids, same feature
count, equivalent quality/embeddings (the P6.10 equivalence result: CLIP is batch-order independent;
metrics are deterministic from the same frames). A rerun is therefore safe; no checkpoint/resume
machinery is needed — snapshot + simple rerun is the resume strategy.

--------------------------------
## JOB TRUTHFULNESS
--------------------------------

**PASS (already correct).** `_run_job` marks the job `failed` on any exception, and `analyze_shots`
propagates a per-asset `_encode_asset` failure. A force run cannot report success while an asset
failed. An interrupted run may leave a MIXED state (some assets fresh, others still old) but never a
partially-written asset — this is documented and is exactly why the strict validator (not job
status) gates acceptance.

--------------------------------
## SNAPSHOT METHOD
--------------------------------

SQLite mode: production is `journal_mode=delete` (no WAL, no `-wal`/`-shm` sidecars),
`integrity_check = ok`.
method: **SQLite online backup API** (`sqlite3.Connection.backup`) — a transactionally consistent
image even with a concurrent reader, not a bare `cp`.
integrity verification: `PRAGMA integrity_check` on every snapshot and restore.
restore proof: a test snapshots a seeded DB, destructively mutates the working copy, restores, and
asserts the full manifest is byte-identical again with `integrity_check = ok`.

--------------------------------
## STRICT POSTCONDITION VALIDATOR
--------------------------------

`validate_postconditions(db_path, pre_manifest)` — **read-only**, compares POST state to a frozen
PRE manifest for invariants and asserts remediation goals absolutely; returns `{ok, failures[]}`
with no warning-only acceptance. Checks: project exists; assets == pre; shots == pre; features ==
shots; shots-without-features == 0; features-without-shots == 0; embeddings == shots; tq-zero == 0;
shot-id set unchanged; boundaries unchanged; timeline items == pre; timeline resolved == items;
timeline manifest unchanged; Elenora embeddings/shots unchanged (cross-project); no active/orphan
shots job.
success fixture: passes on a clean seeded state.
failure injections (each FAILs with the right check named): tq=0, missing embedding, missing
feature row, changed boundary, timeline-count mismatch, cross-project (Elenora) mutation, active
job present.

--------------------------------
## CROSS-PROJECT SAFETY
--------------------------------

The validator freezes and re-checks Elenora's embedding/shot counts; a mutation there FAILs
validation. Force-reencode is scoped to one `project_id`; no all-projects form exists.

--------------------------------
## CONCURRENCY
--------------------------------

Re-uses the existing partial unique index on active `(project_id, kind)`: a second concurrent
`shots` job (force or not) for the same project raises `IntegrityError` → 409. Proven by test.

--------------------------------
## DEGRADED-SUCCESS
--------------------------------

generic architecture: **PRESENT** (unchanged — the generic job layer can still mark non-force work
"completed" while degraded; not touched here).
controlled force workflow: **MITIGATED/CLOSED** — acceptance requires job success AND strict
validator PASS; a mixed/partial/degraded outcome fails validation and is not accepted.

--------------------------------
## FUTURE REAL-RUN PROTOCOL (P6.12)
--------------------------------

preflight: correct project id; 362/362 media reachable; CLIP loads (clip-vit-base-patch32, 512-d,
MPS); free disk for snapshot; no active analysis job; `integrity_check` PASS; production DB path
positively verified; freeze PRE manifest (this project + Elenora). Recommend running while active
DaVinci editing is paused (T7 I/O + MPS contention + ~76-min runtime) — operational guidance, not a
correctness gate.
snapshot: `snapshot_db(prod, timestamped_backup)`; verify checksum + integrity; retain.
run: `POST /shots {force_reencode:true}` (one job; concurrency-guarded).
validate: `validate_postconditions(prod, pre_manifest)` after job `completed`.
accept: ONLY if job completed AND validator PASS.
rollback: on job failure/crash/cancel/validator FAIL, restore the verified snapshot
(`restore_db`) and re-freeze manifests. No automatic live DB swap (explicit, controlled restore).

--------------------------------
## READY FOR CONTROLLED REAL 15A FORCE-REENCODE
--------------------------------

**YES (conditional on operator protocol)** — the supported no-pre-delete trigger, consistent
snapshot/restore, and strict validator are proven; the engine itself was proven in P6.10. The real
run is now an operational procedure (preflight → snapshot → run → validate → accept/rollback), the
subject of P6.12.

READY FOR PRODUCTION: **NO.**

PROVEN:
- Explicit `force_reencode` trigger recomputes assets whose features already exist, with **no
  pre-delete** (0 deletes before the atomic store), same shot ids, no re-segmentation — on real media.
- Default behaviour unchanged (feature reuse); job fails truthfully on per-asset failure; encode
  failure preserves old features; concurrency guarded.
- Consistent SQLite backup-API snapshot + verified restore round-trip.
- Strict read-only validator PASSes clean state and FAILs every injected degraded state incl.
  cross-project mutation.

NOT PROVEN / OUT OF SCOPE:
- No real production run performed (P6.12).
- Generic (non-force) degraded-success hazard remains PRESENT by design.

SAFETY:
- No production write (checksum `738ce224…`, mtime `2026-09-16 23:46:03` unchanged), no production
  feature deletion, no job/real reanalysis, no snapshot/restore against production, no
  timeline/Resolve/planner/segmentation/shot-id-algorithm/model/timecode change. Only trigger
  plumbing + tools + tests + docs. Temp clone deleted.

TESTS:
- `tests/test_p6_11_reencode_safety.py`: 15 tests (trigger default/force/no-features, encode-failure
  atomicity, concurrency, snapshot round-trip, validator success + 7 failure injections, real-media
  fixture). Full suite: 1064 passed. Ruff clean.

--------------------------------
## GATES
--------------------------------

- GATE A — EXPLICIT SAFE TRIGGER: **PASS** (force flag, no feature pre-delete).
- GATE B — BACKWARD COMPATIBILITY: **PASS** (default false; reuse unchanged).
- GATE C — ASSET ATOMICITY: **PASS** (encode/store failure preserves old features).
- GATE D — ID / SEGMENTATION SAFETY: **PASS** (existing shots reused; 0 scene calls).
- GATE E — REAL-MEDIA FORCE TEST: **PASS** (C7309 recomputed via the trigger, features present).
- GATE F — SNAPSHOT / RESTORE: **PASS** (backup API + verified restore).
- GATE G — STRICT POSTCONDITIONS: **PASS** (detects every injected degraded state).
- GATE H — JOB / CANCEL / CONCURRENCY: **PASS** (truthful failure; 409 guard; boundary cancel).
- GATE I — PRODUCTION ISOLATION: **PASS** (must-pass).

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — safe explicit force-reencode trigger proven (no pre-delete, id/segmentation-safe, atomic),
consistent snapshot/restore proven, strict validator proven. A controlled real 15A force-reencode
can be the next package, executed under the preflight → snapshot → run → validate → accept/rollback
protocol.

READY FOR CONTROLLED REAL 15A FORCE-REENCODE: **YES** (under the defined protocol).
READY FOR PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.12 — Controlled Real 15A Force-Reencode with Verified Snapshot / Rollback / Mandatory
Postconditions** — the first authorized mutation of the real 15A feature state, behind the protocol
above.

**DO NOT START.**
