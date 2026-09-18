# PACKAGE 06.12 — CONTROLLED REAL 15A FORCE-REENCODE

START HEAD: `db395f2`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

The first authorized mutation of the real 15A production feature state. Executed via the supported
P6.11 `force_reencode=true` path, behind a verified SQLite-backup snapshot, an immutable PRE
manifest, and the strict read-only postcondition validator. Orchestrator:
`tools/p6_12_controlled_reencode.py`; evidence: `tools/fixtures/p6_12_run_result.json`; snapshots +
manifests under `data/backups/` (gitignored, retained).

--------------------------------
## FIRST ATTEMPT (interrupted, rolled back)
--------------------------------

Started against the historical PRE state (checksum `738ce224`). Intentionally interrupted by the
user because it was contending with a concurrent DaVinci Resolve editing session. At interruption
it had reached ~1436/2638 fresh embeddings (encode pass mid-flight; label pass not yet run).
The writer was terminated (per-asset writes are atomic → no torn asset; no journal/wal sidecar;
`integrity_check = ok`), `lsof` confirmed no other writer on the DB, and a controlled rollback
restored the verified PRE snapshot. Logical PRE state was confirmed restored exactly (all counts +
shot-id / boundary / timeline manifest hashes == PRE; embeddings 0; tq-zero 2327; Elenora 1405).

Note: the restored file checksum became `d8d79cc5` (SQLite backup/restore re-paginates the file).
The P6.12 gate was corrected to be **semantic** (manifest hashes), not byte-checksum equality.

--------------------------------
## RETRY (accepted)
--------------------------------

PRE (retry baseline): checksum `d8d79cc5` (recorded, not gated); semantic gate PASS —
assets 362, shots 2638, features 2638, embeddings 0, tq-zero 2327, timeline 129/129, Elenora 1405,
active jobs 0, integrity ok; shot-id / boundary / timeline hashes == known PRE.
new verified snapshot: `data/backups/sevenfilm-pre-p6_12-20260918-162747.sqlite3`
(SQLite online-backup, integrity ok) — marked *PRE-P6.12-RETRY ACCEPTED-RUN ROLLBACK SNAPSHOT*;
the original `…-141915` snapshot is also retained.
job id: `087697c9-181f-444d-8046-28d397abb604` · force_reencode=true · project 15A ·
intended assets 362 · runtime **5988 s (~100 min)** (extended by concurrent Resolve I/O + the real
`_measure_shot_windows` pass) · final status **completed**.

--------------------------------
## POST FEATURE STATE
--------------------------------

assets 362 · shots 2638 · features 2638
technical_quality zero: **2327 → 0**
embeddings populated: **0 → 2638** (dim 512, L2-normalized, `openai/clip-vit-base-patch32`)
shots without features: 0 · features without shots: 0

--------------------------------
## DRONE STATUS
--------------------------------

All restored (tq-zero 0, embeddings full):
DJI_0522 14/14 · DJI_0523 10/10 · DJI_0524 21/21 · DJI_0525 14/14 · DJI_0526 19/19 ·
DJI_0527 11/11 · DJI_0528 280/280 · DJI_0529 56/56 · DJI_0530 501/501 · DJI_0531 15/15.
(Drone timecode remains a separate known issue — NOT addressed here.)

--------------------------------
## SHOT / SEGMENTATION SAFETY
--------------------------------

shot IDs: identical to PRE (hash match) · boundaries: identical (hash match) · per-asset shot
counts: unchanged. No re-segmentation (the force path reuses existing `shots` boundaries).

--------------------------------
## TIMELINE SAFETY
--------------------------------

before 129 · after **129** · resolved **129/129** · timeline manifest hash == PRE (unchanged).
No new dangling references. The existing AI Rough Cut is intact and fully resolvable.

--------------------------------
## CROSS-PROJECT SAFETY
--------------------------------

Elenora embeddings 1405 → **1405** (unchanged); Elenora shots unchanged. Contamination 0. No
unexpected cross-project mutation.

--------------------------------
## STRICT VALIDATOR
--------------------------------

**PASS** (`validation.ok = true`, `failures = []`). All mandatory checks: project exists;
assets 362; shots 2638; features 2638; shots-without-features 0; features-without-shots 0;
embeddings 2638; embedding dim 512 / norm sane; technical_quality zero 0; shot-id set == PRE;
boundaries == PRE; timeline items 129; timeline resolved 129/129; timeline manifest == PRE;
Elenora unchanged; no active/orphan force job.

--------------------------------
## ROLLBACK
--------------------------------

required: NO (retry accepted) · performed: NO · both snapshots retained (original + accepted-run).
(First attempt: rollback was required and performed successfully — logical PRE restored.)

--------------------------------
## MOMENT READINESS (read-only)
--------------------------------

Production `semantic_readiness(15A)` now reports **FULL** (was DEGRADED): 2638/2638 full, 0
degraded — the app's own logic confirms the restored embeddings are visible and the semantic
prerequisites for `project_moments()` are awake. No planner run, no prompt tuning, no timeline
created.

--------------------------------
## RESOURCE REPORT
--------------------------------

runtime ~100 min (vs ~76 min clean P6.10 baseline) · peak RSS ~4.5 GB class (bounded, P6.10 fix) ·
DaVinci Resolve running throughout (T7 I/O + MPS contention — the cause of the slowdown, not a
correctness issue) · one writer only.

--------------------------------
## PRODUCTION DB CHECKSUM / MTIME
--------------------------------

PRE (retry) checksum `d8d79cc5…`, POST checksum `e8798470…` — the change is expected and
authorized (fresh features written). `integrity_check = ok`. mtime advanced accordingly.

--------------------------------
## PRODUCTION STATE ACCEPTED
--------------------------------

**YES.**

READY FOR PLANNER / STORY VALIDATION: **YES** (read-only prerequisites met; no planner run here).
READY FOR GENERAL PRODUCTION: **NO.**

PROVEN:
- Real 15A feature state remediated via the supported force path: tq-zero 2327→0, embeddings
  0→2638 (512-dim), all 10 drones restored incl. DJI_0530 501/501.
- Shot IDs, boundaries, and the 129-item timeline are byte-identical to PRE (hash match); Elenora
  and all other projects untouched; contamination 0.
- Strict validator PASS; job completed; snapshots retained; production integrity ok.
- First-attempt interruption + rollback proved the safety path end-to-end on real data.

NOT PROVEN / OUT OF SCOPE:
- Planner/story quality of a rough cut built on the new features (P6.13, read-only first).
- Drone timecode (separate known issue).
- Generic (non-force) degraded-success hazard (unchanged by design).

SAFETY:
- Real production force-reencode OCCURRED and is ACCEPTED (authorized). Production features
  changed (embeddings restored); checksum changed `d8d79cc5→e8798470` (authorized). Shot IDs,
  boundaries, timeline UNCHANGED. Resolve/planner/segmentation/model/timecode UNCHANGED. Elenora
  UNCHANGED. Contamination 0. Snapshots retained under data/backups/ (not committed).

TESTS:
- `tests/test_p6_12_controlled_reencode.py`: 4 (semantic checksum-independent gate, validator
  accept/reject, orchestrator gate shape, accepted-run evidence).
- `tests/test_semantic_capability.py`: production-regression test updated to guard the new FULL
  state (was asserting the old DEGRADED state).
- Full suite: **1068 passed**. Ruff clean.

--------------------------------
## GATES
--------------------------------

- GATE A — PREFLIGHT: **PASS** (semantic baseline exact; media 362/362; CLIP ready).
- GATE B — SNAPSHOT: **PASS** (verified SQLite-backup snapshot, integrity ok, retained).
- GATE C — REAL FORCE JOB: **PASS** (supported force job completed all 362 assets).
- GATE D — FEATURE RESTORATION: **PASS** (2638/2638 embeddings, 0 tq-zero).
- GATE E — ID / SEGMENTATION: **PASS** (shot ids + boundaries unchanged vs PRE).
- GATE F — TIMELINE: **PASS** (129/129 unchanged/resolved).
- GATE G — CROSS-PROJECT: **PASS** (Elenora untouched, contamination 0).
- GATE H — STRICT VALIDATOR: **PASS** (all mandatory checks).
- GATE I — ROLLBACK SAFETY: **PASS** (snapshots verified & retained; first-attempt rollback
  restored PRE correctly).

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — Real 15A force-reencode retry completed and the strict validator fully passed. The
production semantic feature state is ACCEPTED: technical_quality and CLIP embeddings restored for
all 2638 shots across 362 assets, with shot ids, boundaries, and the 129-item timeline preserved
and all other projects untouched.

READY FOR PLANNER / STORY VALIDATION: **YES.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.13 — Production Semantic / Moment Activation Validation** (read-only first; no new timeline
yet).

**DO NOT START.**
