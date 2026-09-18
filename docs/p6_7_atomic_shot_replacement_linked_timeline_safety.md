# PACKAGE 06.7 — ATOMIC SHOT REPLACEMENT FIX

START HEAD: `a2531da`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Scope was deliberately narrow: convert `_label_asset()`'s `shots` persistence to the existing
atomic `Database.replace_rows()` pattern, and prove linked-timeline behaviour on
success/failure/cancellation/re-segmentation. No planner, `technical_quality`, `_is_usable()`,
embedding, moment-prompt, schema, or FK-policy change.

--------------------------------
## BEFORE
--------------------------------

**`_label_asset()` persistence** (HEAD `a2531da`):

```python
database.execute("DELETE FROM shots WHERE asset_id = ?", (asset.id,))
for ordinal, row in enumerate(rows):
    ...
    database.insert("shots", {...})   # one commit per row
```

**Transaction behavior:** the bare `DELETE` committed on its own (via `Database.execute` →
`connection()` context manager), then each `insert()` opened, wrote and committed its own
connection. There was a real window in which an asset's old shots were gone and only some of
its new shots were written.

**Timeline risk:** `shots.id` is a deterministic `uuid5` of `sevenfilm:{asset_id}:{start}:{dur}`.
A crash or backend restart between the `DELETE` and the completion of the insert loop left the
`shots` table missing rows a `timeline_items` row still references. P6.6 reproduced exactly this
on a temp clone of the real 129-item AI Rough Cut (`shot_present_after_delete=false`,
`timeline_item_now_dangling=true`). `PRAGMA foreign_keys` is OFF on normal connections, so
nothing at the DB layer prevented the mid-operation inconsistency.

--------------------------------
## FIX
--------------------------------

**Exact code change** (`apps/api/sevenfilm/services/analysis.py`, `_label_asset`): the bare
`DELETE` + per-row `insert()` loop is replaced by building the complete replacement set in memory
first, then a single call:

```python
new_rows = []
for ordinal, row in enumerate(rows):
    ...
    new_rows.append({... same fields as before ...})
database.replace_rows("shots", "asset_id", asset.id, new_rows)
```

**`replace_rows` usage:** the same helper `_store_features()` already uses for `shot_features`.
It runs `DELETE FROM shots WHERE asset_id = ?` and every `INSERT` inside one
`connection()` context manager — one transaction, one commit at the end, `rollback()` on any
exception.

**Row preparation:** every row dict is assembled in the loop before `replace_rows` is called.
If row construction raises (bad classification, malformed `metrics_json`), the delete never runs.

**Transaction:** single connection, single transaction. `insert()` and `replace_rows()` share
identical value serialization (`json.dumps(v)` for `list`/`dict`, else `v`), so `labels_json`
and every other field are written byte-identically to the old path.

--------------------------------
## OUTPUT EQUIVALENCE
--------------------------------

- **old vs new:** identical. A dedicated test rebuilds the pre-fix `DELETE`+insert-loop on the
  same inputs and asserts every `shots` column (except the `created_at` timestamp) matches the
  new atomic path.
- **IDs:** unchanged. The id written to `shots` is `row["shot_id"]` read verbatim from the
  `shot_features` row (itself `_shot_id(asset_id, source_range)`); nothing is regenerated.
- **boundaries:** unchanged (`start_frame`/`duration_frames`/`frame_rate` copied from features).
- **fields:** all preserved — category, shot_scale, technical_quality, aesthetic_score,
  motion_score, confidence, duplicate_group, labels_json, analysis_version, brightness,
  saturation, highlight_clipping, face_ratio, face_edge, created_at. No field loss, no new
  default, no semantic change.

--------------------------------
## TEMP CLONE TEST MATRIX
--------------------------------

Run against a fresh migrated temp DB seeded 15A-like (project + asset + shot_features + shots +
a linked timeline item). The production DB is never opened (conftest also pins
`SEVENFILM_DATA_ROOT` to a temp dir). File: `tests/test_p6_7_atomic_shot_replacement.py`.

**A — same-id success**
- shots: replaced in place; ids unchanged (`s1`,`s2`).
- timeline reference: resolves (shots row present); `get_timeline()` returns the item.

**B — forced failure (NOT NULL violation on 2nd insert, mid-transaction)**
- shots: old rows fully present (`s1`,`s2`); neither new row visible — full rollback.
- timeline reference: resolves.

**C — pre-build failure (classifier raises before replace_rows)**
- shots: unchanged (`s1`,`s2`).
- timeline reference: resolves. Proves build-first / replace-second.

**D — cancellation at asset boundary**
- shots: with `cancel_requested` seen at the first boundary, no asset is labelled; both assets
  keep their prior shots. A companion test labels asset A fully (atomic) then cancels before
  asset B — A is fully replaced, B untouched. No partial replacement is possible because each
  asset's write is one atomic call and `raise_if_cancelled` is never inside `_label_asset`.
- timeline reference: resolves.

**E — changed-boundary success (re-segmentation → new ids)**
- old shot_id: `old-1` (referenced by the timeline item).
- new shot_id: `new-1`,`new-2`.
- timeline reference: the `shots`-table reference now **dangles** (`old-1` row removed).
- result: the delivered rough cut **still renders** — `timeline_items.shot_id` is deliberately
  not a FK and `get_timeline()` LEFT JOINs shots, falling back to the item's own descriptive
  copy with neutral scores (`technical_quality=0.5`, `category` from the item row). Atomicity is
  not violated; this is a distinct reference-migration concern, not a partial-write corruption.

--------------------------------
## ATOMICITY
--------------------------------

**PASS.** `shots` replacement is one rollback-safe transaction; forced failure (B) and pre-build
failure (C) both leave the old state fully intact; no partial rows are ever observable.

--------------------------------
## CROSS-TABLE SHOTS/FEATURES
--------------------------------

**SAFE.** In `analyze_shots()`, encoding (`shot_features`) is pass 1 and labelling (`shots`) is
pass 2, and on a supported reanalysis the encode pass is skipped because features already exist —
so `shots` is derived from unchanged `shot_features` rows via the same deterministic ids. A failed
`shots` replacement leaves old shots + unchanged features, and every surviving `shots.id` still
matches a `shot_features.shot_id` (verified by test). No cross-table inconsistency is introduced,
and no giant cross-table transaction is warranted by current evidence.

--------------------------------
## SEGMENTATION BEHAVIOR
--------------------------------

- **does real reanalysis re-segment?** NO, in the supported path. `POST /api/projects/{id}/shots`
  creates a `shots` job with an empty checkpoint and calls `analyze_shots()`; it does **not**
  delete `shot_features` or `shots` first. `analyze_shots()` skips `_encode_asset()` for any asset
  that already has features (`if not _asset_features(...)`), so segmentation is not re-run and the
  label pass reuses the persisted feature shot_ids.
- **can IDs change?** NO in the supported reanalysis path. IDs only change if `shot_features` are
  absent (forcing `_encode_asset`), and even then ranges are re-derived from existing `shots`
  rows and `_split_long_range` is idempotent on already-split (≤5s) segments; a true boundary
  change requires wiping both tables and re-running scene detection, which the supported path
  does not do.

--------------------------------
## SUCCESSFUL REANALYSIS REFERENCE HAZARD
--------------------------------

**CONDITIONAL / ABSENT in the supported path.** A successful supported reanalysis preserves shot
ids, so no timeline reference is orphaned. The hazard is only PRESENT if a future path re-segments
(wipes features/shots and re-detects), which would change ids — and even then the delivery layer
tolerates it (see LINKED TIMELINE SAFETY / case E). This is a reference-migration question,
explicitly out of P6.7's atomicity scope.

--------------------------------
## LINKED TIMELINE SAFETY
--------------------------------

- **failed reanalysis:** SAFE. Old shots survive; the reference resolves (cases B, C).
- **successful same-id reanalysis:** SAFE. Ids preserved; the reference resolves (case A). This is
  the supported reanalysis path.
- **successful changed-id reanalysis:** the `shots`-table reference dangles, BUT the delivered
  timeline still renders via LEFT JOIN + the item's own copy with neutral scores (case E). Not a
  crash/partial corruption; a deliberate design tolerance. Not reachable by the supported path.

--------------------------------
## DEGRADED-SUCCESS HAZARD
--------------------------------

**carry forward: PRESENT.** P6.7 fixes replacement atomicity only. It adds no embedding/quality/
semantic readiness gate. Whether a reanalysis that finishes with weak/incomplete outputs is
correctly detected as degraded remains a separate concern for a future controlled-reanalysis /
robustness package.

--------------------------------
## READY FOR CONTROLLED REAL 15A REANALYSIS
--------------------------------

**CONDITIONAL.** The atomicity blocker is fixed and the supported reanalysis path is ID-stable
(no re-segmentation, no orphaned references), and even a hypothetical changed-id case keeps the
delivered timeline renderable. Remaining conditions before authorizing a real run: (1) confirm on
a temp clone of the *actual* 15A DB that its `shot_features` are present so the encode pass is
skipped and ids are stable; (2) the degraded-success detection question is still open. These are
verification/authorization steps, not code blockers.

--------------------------------
## READY FOR PRODUCTION
--------------------------------

**NO.**

PROVEN:
- `shots` replacement is atomic and rollback-safe (unit-proven B/C).
- Output is byte-identical to the prior logic (equivalence test).
- Shot ids are reused from features, not regenerated.
- Supported reanalysis does not re-segment and does not change ids.
- Linked timeline resolves on success and on failure; delivery survives even a dangling ref.
- Production DB, timeline, Resolve, embeddings untouched; full suite green (1020), ruff clean.

NOT PROVEN:
- Behaviour against a live SIGKILL of the real backend (relied on SQLite transaction rollback as
  the proxy; documented limitation). DB journal mode not altered.
- That a real 15A reanalysis run produces non-degraded outputs (degraded-success detection open).
- Any changed-id / reference-migration guarantee beyond the LEFT-JOIN delivery tolerance.

SAFETY:
- No real 15A reanalysis, no production job enqueued, no production DB write (checksum
  `738ce224…` unchanged, mtime `2026-09-16 23:46`), no timeline/Resolve mutation, no planner/
  `technical_quality`/`_is_usable()`/embedding/FK/schema change.

TESTS:
- `tests/test_p6_7_atomic_shot_replacement.py`: 12 tests (mechanism, equivalence, matrix A–E,
  empty semantics, cross-table consistency).
- `tests/test_p6_6_orchestration_safety.py`: updated to assert the fix landed (13 tests).
- Full suite: 1020 passed. Ruff: clean.

--------------------------------
## GATES
--------------------------------

- GATE A — ATOMIC REPLACE: **PASS**
- GATE B — SAME-ID TIMELINE SAFETY: **PASS**
- GATE C — FAILURE ROLLBACK: **PASS**
- GATE D — CANCELLATION: **PASS**
- GATE E — OUTPUT EQUIVALENCE: **PASS**
- GATE F — SUCCESSFUL RESEGMENTATION SAFETY: **PASS (conditional)** — the supported path provably
  does not change boundaries, and even a changed-boundary case keeps the delivered timeline valid
  via LEFT-JOIN fallback. The `shots`-table reference itself does dangle under changed ids, so a
  future re-segmenting path would need explicit reference handling.
- GATE G — PRODUCTION ISOLATION: **PASS** (must-pass).

--------------------------------
## FINAL VERDICT
--------------------------------

**A/B boundary — reported as B (conservative).**

The atomicity blocker is fixed (verdict A conditions met for the supported path: ID-stable, no
orphaning). But because the codebase *can* re-segment and change ids if `shot_features` are ever
cleared, and the delivered timeline then relies on LEFT-JOIN fallback rather than a live shots
reference, the honest classification is **B**: atomicity fixed; a successful re-segmentation can
still leave the `shots`-table reference dangling (delivery survives, but the reference does not).
The supported reanalysis path does not trigger this, so a controlled real run is not code-blocked
by it.

READY FOR CONTROLLED REAL 15A REANALYSIS: **CONDITIONAL** (verify real-15A features present on a
temp clone; degraded-success detection still open).

READY FOR PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.8 — Supported-reanalysis segmentation-stability verification on a temp clone of the real 15A
DB.** Single purpose: prove on the actual 15A data that `shot_features` are present so the encode
pass is skipped and every reanalysis-produced `shots.id` is byte-identical to the current id (no
orphaned timeline references), producing the go/no-go evidence for a controlled real run.

**DO NOT START.**
