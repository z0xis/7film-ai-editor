# PACKAGE 06.10 — BOUNDED-MEMORY LARGE-ASSET ENCODE

START HEAD: `f1c2e69`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Purpose: fix the P6.9 large-asset memory blocker (DJI_0530 signal-kill) without changing re-encode
semantics, and close GATE F by completing the full 15A temp-clone remediation. Only bounded-memory
code changed. Harness: `tools/p6_10_bounded_encode_probe.py`; fixtures:
`tools/fixtures/p6_10_{equivalence,dji_0528,dji_0530,full}.json`; tests:
`tests/test_p6_10_bounded_encode.py`.

--------------------------------
## P6.9 RESIDUAL-15 RECONCILIATION
--------------------------------

expected completed shots outside DJI_0530: 2638 − 501 = **2137**
observed embeddings in the interrupted clone: **2122** → difference **15**.

initial hypothesis: the 15 were genuinely-unreadable middle frames (empty frame group →
`measure_frames([])` → tq 0, no embedding).

**Resolved by the clean full run:** the completed 362/362 run (below) shows `tq_zero_after = 0`
and `embedding_null_after = 0` — i.e. **zero residual shots** (`tq_zero_shots: []`,
`embedding_null_shots: []`). So the 15 were **an artifact of the interrupted P6.9 OLD-path run**,
not a persistent set of unreadable frames: they were null-embedding rows captured at the moment
the process was signal-killed mid-DJI_0530, and every one of them re-encodes cleanly when its
asset runs to completion under the fixed path. There is no residual degraded population.

systemic blocker? **NO** — reconciled to zero. Frame decoding is identical between the old and new
paths (same absolute seeks); the discrepancy was purely the interrupted run's transient state.

--------------------------------
## LEGACY MEMORY BEHAVIOR
--------------------------------

- materialisation: `_shot_frame_groups` returned a list holding **every shot's** sampled frames
  (up to 3 decoded 4K frames each) for the whole asset at once.
- memory scaling: O(shot_count × frame_pixels × 3). DJI_0530 = 501 × 3 × (3840×2160×3 B ≈ 25 MB)
  ≈ up to ~37 GB attempted.
- DJI_0530 peak (legacy): ~2.9 GB reported at the moment of the kill (the process was signal-killed
  while allocating far more).
- failure mode: signal-kill (SIGKILL under memory pressure) during the frame/encode phase — after
  all 501 shots were measured.

--------------------------------
## FIX
--------------------------------

- chunk unit: shots (representative middle frames).
- chunk size: `_ENCODE_CHUNK_SHOTS = 32` (deterministic; a memory bound, not a semantic knob).
- raw frame lifetime: `_shot_frame_groups` is now a **generator** yielding one shot's frames at a
  time; `_encode_asset` measures each shot immediately and keeps only its middle frame, so a shot's
  non-representative frames are released before the next shot is decoded. Resident representative
  frames are capped at the chunk size.
- feature accumulation: only compact results grow — a `FrameMetrics` list and an `{position: 512-d
  vector}` dict (kilobytes).
- persistence: unchanged — one `_store_features` (atomic `replace_rows`) at the very end.
- atomicity: preserved. `_store_features` runs only after every chunk succeeds, so a failure partway
  through persists nothing (proven by a unit test injecting a mid-encode failure).

--------------------------------
## SEMANTIC EQUIVALENCE
--------------------------------

- FrameMetrics: **PASS** — identical (`metrics_exact: true`, `tq_exact: true` on C7309 & C7152,
  legacy vs chunked).
- embedding: **PASS** — CLIP batch-vs-chunk `max_abs_delta 0.0`, `min_cosine 1.0`; per-asset
  legacy-vs-chunked embedding `min_cosine 1.0`.
- feature rows: **PASS** — same shot ids, same row set.
- shot IDs: **PASS** — ranges reused from existing shots; ids unchanged.

Classification: **EXACT** (not merely numeric-equivalent) on the tested assets.

--------------------------------
## FAILURE ROLLBACK
--------------------------------

**PASS** — a unit test injects an exception on the second encode chunk of a 70-shot asset;
`shot_features` for that asset is left empty (no partial persistence), confirming asset-level
atomicity across the chunk boundary.

--------------------------------
## DJI_0528 REGRESSION
--------------------------------

shots: 280→280 · quality: tq-zero 280→0 (range 0.07–0.899) · embeddings: 280/280 (512-dim,
norm 1.0) · IDs: stable · peak RSS 3.09 GB · runtime 435 s · result: **PASS** (matches the P6.9
sample outcome under the new path).

--------------------------------
## DJI_0530
--------------------------------

shots: 501 · chunks: ⌈501/32⌉ = 16 · runtime: 720.6 s · peak RSS: **4.41 GB**
before quality-zero: 501 · after quality-zero: **0**
before embeddings: 0 · after embeddings: **501/501** (512-dim, norm 1.0)
shot IDs: **stable** · boundaries: **stable**
result: **PASS** — the asset that was reproducibly signal-killed under the legacy path now
completes. Peak RSS (4.41 GB) is dominated by the fixed CLIP/torch/MPS footprint, not asset-wide
frame retention; the catastrophic O(shots × frame) materialisation (~37 GB) is eliminated.

--------------------------------
## FULL 362-ASSET TEMP-CLONE RUN
--------------------------------

completed assets: **362 / 362** · completed shots: **2638** · runtime: **4580 s (76.3 min)** ·
errors: **none** · peak RSS: **4.52 GB** (bounded; the whole 362-asset run held steady, no kill).

--------------------------------
## TECHNICAL QUALITY
--------------------------------

before: 2327 / 2638 zero · after: **0 / 2638 zero** · remaining-zero shots: **none**
(`tq_zero_shots: []`). Every formerly-zero shot — camera and drone — now has a measured non-zero
technical_quality.

--------------------------------
## EMBEDDINGS
--------------------------------

before: 0 / 2638 · after: **2638 / 2638** · dims 512, L2-normalized · null after: **0**
(`embedding_null_shots: []`).

--------------------------------
## SHOT ID STABILITY
--------------------------------

assets exact: **362 / 362** · shots: **2638 → 2638** (set unchanged).

--------------------------------
## TIMELINE
--------------------------------

before: 129 · after: **129** · resolved before/after: **129 / 129** · new dangling: **0**.

--------------------------------
## SHOT-FEATURE INTEGRITY
--------------------------------

shots without features: **0** · clean 1:1.

--------------------------------
## DRONE STATUS
--------------------------------

DJI_0528 and DJI_0530 individually proven above (280/280 and 501/501 restored). Remaining drone
clips are covered by the full run. Timecode remains a separate known issue — NOT addressed here.

--------------------------------
## MOMENT READINESS
--------------------------------

Embeddings restored at 512-dim from `openai/clip-vit-base-patch32` (the model `project_moments()`
consumes); prerequisites met for the remediated assets. No planner research reopened, no prompt
tuning.

--------------------------------
## MEMORY BLOCKER
--------------------------------

**RESOLVED** — the O(shots × frame) asset-wide frame materialisation is replaced by bounded
(32-shot) retention; DJI_0530 completes.

--------------------------------
## PRODUCTION RE-ENCODE TRIGGER
--------------------------------

**UNRESOLVED / UNSUPPORTED** — there is still no supported API/job flag that re-encodes an asset
whose features exist. Remediation is triggered only by deleting `shot_features` (done on the temp
clone). A real production run therefore still needs a safe, supported trigger + snapshot/rollback;
the memory fix alone does not authorize it.

--------------------------------
## DEGRADED-SUCCESS HAZARD
--------------------------------

**PRESENT** — unchanged; the pipeline can still report "completed" while some assets fall back. The
harness detects it externally (per-asset failures, embedding-null and tq-zero enumeration). A real
run must enforce these as mandatory postconditions. Not fixed here.

--------------------------------
## READY FOR CONTROLLED REAL FULL RE-ENCODE
--------------------------------

**CONDITIONAL** — the memory blocker is fixed and the full 362-asset population now remediates
safely and completely on the temp clone (2327→0 tq-zero, 0→2638 embeddings, 362/362 ids stable,
129 timeline intact). What remains before a real production run is orchestration/safety, not
remediation capability: (a) a safe supported re-encode trigger (still unresolved — remediation is
triggered only by deleting features), and (b) snapshot/rollback + the 12 mandatory postconditions
with external degraded-success detection.

READY FOR PRODUCTION: **NO.**

PROVEN:
- Chunked `_encode_asset` is semantically exact vs the legacy path (metrics/tq/embeddings/ids).
- DJI_0530 (the P6.9 blocker) completes: 501/501, tq-zero→0, 501 embeddings, ids stable.
- DJI_0528 regression clean; asset-level atomicity holds across chunk failure.
- Full 362/362 clone remediation completes: tq-zero 2327→0, embeddings 0→2638, 362/362 ids stable,
  129-item timeline intact, 0 shots without features, 0 residual (the P6.9 "15" was an interrupted-
  run artifact, reconciled to zero).

STILL OPEN (separate packages, not remediation capability):
- A safe supported production re-encode trigger (no API/job flag exists; features must be deleted).
- Degraded-success detection inside the product (external-only today).

SAFETY:
- No production write (checksum `738ce224…`, mtime `2026-09-16 23:46:03` unchanged), no production
  feature deletion, no job/real reanalysis, no timeline/Resolve/planner/segmentation/shot-id-
  algorithm/model/timecode change. Only bounded-memory code + tests + harness + docs. Clones deleted.

TESTS:
- `tests/test_p6_10_bounded_encode.py`: 4 chunking unit tests + 4 fixture gates (equivalence,
  DJI_0528, DJI_0530). Full suite + full-population assertion appended with `p6_10_full.json`.

--------------------------------
## GATES
--------------------------------

- GATE A — RESIDUAL SHOT ACCOUNTING: **PASS** (15 = unreadable-frame shots; reconciled).
- GATE B — SEMANTIC EQUIVALENCE: **PASS** (exact).
- GATE C — DJI_0530 MEMORY: **PASS** (completes, no signal-kill).
- GATE D — DJI_0530 OUTPUT: **PASS** (quality + embeddings restored, ids stable).
- GATE E — FULL POPULATION: **PASS** — 362/362 assets, 0 failures, 2638 shots.
- GATE F — FULL FEATURE RESTORATION: **PASS** — tq-zero 2327→0, embeddings 0→2638, 0 residual.
- GATE G — TIMELINE / ID SAFETY: **PASS** — 362/362 ids stable, 129 timeline intact, 0 dangling.
- GATE H — PRODUCTION ISOLATION: **PASS** (must-pass).

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — the large-asset memory blocker is fixed; the chunked path is semantically exact, DJI_0530
completes, and the full 362-asset temp-clone remediation succeeds with no residual degraded
population (tq-zero 2327→0, embeddings 0→2638, ids/timeline safe). Only production re-encode
triggering/orchestration and the mandatory-postcondition protocol remain before a real run.

READY FOR CONTROLLED REAL FULL 15A RE-ENCODE: **CONDITIONAL.**
READY FOR PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.11 — Safe Production Re-Encode Trigger / Snapshot-Rollback Protocol** (define and implement a
supported, reversible way to invalidate features and re-encode on the real DB, behind a verified
snapshot, the 12 mandatory postconditions, and external degraded-success detection). The controlled
real full re-encode runs under that protocol.

**DO NOT START.**
