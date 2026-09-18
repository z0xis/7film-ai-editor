# PACKAGE 06.8 — REAL-15A TEMP-CLONE ID-STABILITY VERIFICATION

START HEAD: `c10ba22`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Purpose: close the last go/no-go question empirically — does today's supported `shots` reanalysis
path, run against an isolated temp clone of the REAL production DB, preserve the 2638 canonical
15A shot ids and leave the 129-item AI Rough Cut intact. No feature regeneration, no model, no
production write. Harness: `tools/p6_8_real15a_idstability_probe.py`; fixture:
`tools/fixtures/p6_8_real15a_idstability.json`; tests: `tests/test_p6_8_real15a_idstability.py`.

--------------------------------
## PRODUCTION BASELINE
--------------------------------

- assets: **362**
- shots: **2638**
- features: **2638** (all `embedding IS NULL` — 15A is 100% opencv_fallback)
- timeline items (AI Rough Cut `47dcab29…`): **129**
- technical_quality zero: 2327 · Elenora embedding: 1405 · active jobs: 0 · analysis_version: all "4"
- DB checksum: `738ce224467562482795a5cd2ffc6d9d2fe00c823fbe02d0d285f62921d3f6c2`, mtime `2026-09-16 23:46:03`

--------------------------------
## SUPPORTED PATH
--------------------------------

- **entry:** `POST /api/projects/{id}/shots` → `_create_job_or_409(..., "shots", {})` → `analyze_shots()`.
- **feature reuse:** yes — `analyze_shots()` gates encode with `if not _asset_features(asset.id)`; all
  362 assets already have features, so encode is skipped for every asset.
- **encode skipped?** YES (empirically: `_encode_asset` invocations = 0).
- **segmentation skipped?** YES (`_scene_ranges` = 0; boundaries derived from persisted features).
- **label path:** `_label_asset()` per asset, reusing each feature row's persisted `shot_id`.
- **atomic replace:** `Database.replace_rows("shots", "asset_id", asset.id, new_rows)` (the P6.7 fix).
- The heavy `_measure_shot_windows` pass was stubbed in the probe (it writes only `shot_windows`
  and reads `shots`, so it cannot alter any `shot_id`); its skip does not weaken the id contract.

--------------------------------
## TEMP CLONE
--------------------------------

- path: `/tmp/p68_tempdb/clone.sqlite3` (+ a second clone for the rollback case).
- initial checksum: `738ce224…` — **matches production initially: true**.
- cleanup: `shutil.rmtree(/tmp/p68_tempdb)` at end — clone deleted.

--------------------------------
## BEFORE / AFTER SHOTS
--------------------------------

- before count: **2638** · after count: **2638**
- **shot_id equality: YES** · **boundary equality: YES**
- full-row manifest hash identical: `71a7aa3526f105c35a67bc2a3e24f26bd61004c4272dc6b79cf0ba9b11bfa46c` (before == after)
- **row classification: A (EXACT ROW IDENTITY)** — id, boundaries, category, shot_scale,
  technical_quality, confidence, analysis_version all identical.
- assets exact: **362 / 362** · differing assets: **none**.

--------------------------------
## SHOT_FEATURE RELATIONSHIP
--------------------------------

- shots with features: **2638** · features without shots: **0** · shots without features: **0**.
- 1:1 canonical relation preserved.

--------------------------------
## TIMELINE
--------------------------------

- before resolved: **129 / 129** · after resolved: **129 / 129**
- before item count: **129** · after item count: **129**
- item manifest equal? **YES**
- new dangling references: **0**

--------------------------------
## SEGMENTATION
--------------------------------

- was segmentation invoked? **NO**.
- evidence: `_scene_ranges` = 0 and `_encode_asset` = 0 (instrumented call counts), plus exact
  id/boundary equality on all 362 assets. Both a code-path proof and an empirical proof.

--------------------------------
## HEAVY ANALYSIS PATH
--------------------------------

- CLIP invoked? **NO** (`VisionClassifier.encode` = 0; `classify_features(None, …)` short-circuits
  before `_load()`).
- quality recompute? **NO** — `technical_quality` is read from the persisted `metrics_json`, not
  recomputed; the 2327 tq-zero shots are reproduced unchanged.
- scene detection? **NO**.

--------------------------------
## REAL-DATA FAILURE ROLLBACK
--------------------------------

- asset: `0008751c-9764-5653-8f9e-87a201c079be` (4 shots).
- forced failure: a NOT NULL `category` violation injected into the last row of that asset's
  atomic `replace_rows` call (mid-transaction).
- old rows preserved? **YES** (all 4 ids unchanged).
- timeline preserved? YES (references unaffected).
- partial rows? **NONE** — full rollback.
- other asset untouched? **YES**.
- result: **PASS** on real 15A-shaped data.

--------------------------------
## DEGRADED-SUCCESS HAZARD
--------------------------------

**PRESENT (carried forward).** Because the supported path is ID-stable *by reusing existing
features*, it is also a **no-op for quality**: it reproduces the identical 2638 shots, including
the 2327 tq-zero shots and the zero-embedding state. A run intended to *remediate* degraded
analysis must run the re-encode path (features absent/cleared), which is a **different path** whose
id-stability is NOT proven by P6.8 (re-encode re-derives ranges; ids could drift if boundaries
change). Future protocol: a real remediation reanalysis must (a) decide explicitly whether it is a
same-features relabel (proven safe here) or a re-encode (unproven), and (b) enforce mandatory
postconditions + snapshot/rollback (below).

--------------------------------
## REAL-RUN BACKUP PLAN (for P6.9)
--------------------------------

Before any real controlled run, capture and retain until all postconditions pass:
1. full SQLite copy of `data/sevenfilm.sqlite3` (timestamped, off to the side).
2. DB sha256 checksum.
3. 15A shot manifest (id, asset_id, start_frame, duration_frames, frame_rate, category, confidence).
4. shot_features manifest (shot_id, asset_id, analysis_version, embedding-present flag).
5. timeline manifest (all 129 items: id, position, shot_id, source range).
6. jobs manifest (active/terminal state).
7. asset manifest (362 ids + paths).
Resolve project need not be backed up — the DB path is independent and no code writes Resolve in
this call graph (verified P6.6/P6.7). **Rollback:** on any failed postcondition, stop, restore the
SQLite copy over the live DB (checksum-verified), and re-run the manifests to confirm restoration.

--------------------------------
## MANDATORY POSTCONDITIONS (for P6.9, after a real run)
--------------------------------

1. 15A project exists.
2. assets = 362.
3. canonical shots sane (count within expected bound; no NULL boundaries).
4. every shot/timeline reference resolvable OR explained by expected re-segmentation.
5. AI Rough Cut still 129 items, manifest equal.
6. embedding population materially restored (if a re-encode run).
7. technical_quality zero rate materially reduced (if a re-encode run).
8. analysis_version no longer degraded fallback where applicable.
9. no project contamination (no rows crossing project_id).
10. no unexpected shot-ID drift beyond what the chosen path intends.
11. moments can be recomputed.
12. DB backup retained until all checks pass.

--------------------------------
## GO / NO-GO
--------------------------------

CONTROLLED REAL 15A REANALYSIS: **GO (bounded)** — GO for the *supported same-features relabel*
path, which is proven ID-stable and timeline-safe on the real data. **NOT** authorized for a
re-encode/quality-remediation run without a further id-stability audit of that path (see hazard).

READY FOR PRODUCTION: **NO.**

PROVEN:
- Supported `shots` reanalysis on the real 15A clone is byte-identical (classification A): 2638
  ids/boundaries/rows unchanged, 362/362 assets stable.
- No re-segmentation, no CLIP, no scene detection, no quality recompute on this path.
- 129-item AI Rough Cut fully resolvable and manifest-identical before and after; 0 new dangling.
- 1:1 shot↔feature relation preserved.
- Atomic replacement rolls back cleanly on a forced failure against real 15A-shaped data.
- Production DB checksum + mtime unchanged; clone deleted.

NOT PROVEN:
- ID-stability of a *re-encode* (feature-regeneration) reanalysis — the path a real quality
  remediation would use.
- That a real run would actually improve quality (degraded-success detection still open).
- Behaviour under a literal process SIGKILL (SQLite transaction rollback used as the proxy).

SAFETY:
- No production DB write (checksum `738ce224…`, mtime `2026-09-16 23:46:03` unchanged), no job
  enqueued, no real reanalysis, no timeline/Resolve/embedding/technical_quality/planner/router/
  verifier/schema change, contamination 0. Temp clone deleted.

TESTS:
- `tests/test_p6_8_real15a_idstability.py`: 10 tests (probe hygiene, production isolation, GATE
  A–F). Full suite: **1030 passed**. Ruff: clean.

--------------------------------
## GATES
--------------------------------

- GATE A — ACTUAL 15A ID STABILITY: **PASS** (classification A).
- GATE B — ALL-ASSET STABILITY: **PASS** (362/362).
- GATE C — TIMELINE INTEGRITY: **PASS** (129 unchanged, 0 new dangling).
- GATE D — FEATURE RELATIONSHIP: **PASS** (1:1).
- GATE E — SEGMENTATION SKIP: **PASS** (0 encode/scene/CLIP invocations).
- GATE F — REAL-DATA ROLLBACK: **PASS**.
- GATE G — PRODUCTION ISOLATION: **PASS** (must-pass).

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — the actual 15A temp-clone proves the supported reanalysis path is ID-stable and
timeline-safe; a controlled real reanalysis on that path is authorized as the next bounded
experiment. Recorded with one explicit boundary: this authorization is for the same-features
relabel path only; a re-encode/quality-remediation run is a distinct, not-yet-proven path.

READY FOR CONTROLLED REAL 15A REANALYSIS: **YES** (bounded to the supported same-features path).
READY FOR PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.9 — Controlled Real 15A Reanalysis with Snapshot / Rollback / Mandatory Postconditions**
(one purpose: execute the bounded real run behind a verified backup and the 12 postconditions
above, deciding same-features-relabel vs re-encode up front).

**DO NOT START.**
