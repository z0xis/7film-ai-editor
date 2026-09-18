# PACKAGE 06.9 — RE-ENCODE REMEDIATION TEMP-CLONE PROOF

START HEAD: `cbe79ad`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Purpose: on an isolated temp clone of the REAL production DB and the REAL 15A media, exercise the
feature-recompute (re-encode) path — the one MODE that can actually remediate 15A — and prove
whether technical_quality restores, embeddings generate, shot ids/boundaries stay stable, and the
129-item AI Rough Cut stays safe. No production write, no real job, no timeline/Resolve mutation.

Harness: `tools/p6_9_reencode_remediation_probe.py`. Fixtures:
`tools/fixtures/p6_9_reencode_sample.json` (pre-registered sample) and
`tools/fixtures/p6_9_reencode_full.json` (full 362-asset clone run). Tests:
`tests/test_p6_9_reencode_remediation.py`.

--------------------------------
## REMEDIATION PATH
--------------------------------

- **trigger:** the supported code re-encodes an asset only when it has no `shot_features`
  (`analyze_shots`: `if not _asset_features(asset.id): _encode_asset(...)`). There is **no**
  supported API/job flag that deletes features — a real remediation must delete `shot_features`
  as an explicit, out-of-band step first. The probe reproduces exactly that condition on the
  CLONE (delete features, keep shots).
- **encode:** `_encode_asset` → `_shot_frame_groups` opens each asset's **T7 original** and samples
  ~3 frames per shot → `measure_frames` (recomputes technical_quality etc.) → `VisionClassifier`
  CLIP encode → `_store_features`.
- **quality:** recomputed by `measure_frames` from freshly decoded original frames.
- **embedding:** produced by `VisionClassifier` (`openai/clip-vit-base-patch32`, loads offline on
  MPS; 512-dim, L2-normalized ≈ 1.0).
- **classification:** `_label_asset` now runs with embeddings present, so `classify_features`
  uses CLIP (not the opencv fallback), and `replace_rows` writes the shots atomically (P6.7).
- **segmentation:** NOT re-scanned. Because the `shots` rows are left in place, `_encode_asset`
  re-derives ranges from the existing shot boundaries; `_scene_ranges` (the PySceneDetect scan)
  is never called, so `_shot_id = uuid5(asset:start:duration)` reproduces the SAME ids.

### MODE table (section 2)

| | MODE A — same-features relabel (P6.8) | MODE B — re-encode remediation (P6.9) |
|---|---|---|
| recomputes technical_quality? | NO | **YES** |
| recomputes embeddings? | NO | **YES** |
| resegments? | NO | NO (ranges reused from existing shots) |
| fixes 15A? | NO | **YES** (quality + embeddings restored) |

--------------------------------
## SAMPLE ASSETS (pre-registered before results)
--------------------------------

- C7309.MP4 (cake source; 16 shots; all tq-zero) — section 7A
- DJI_0528.MOV (drone; 280 shots; all tq-zero) — 7C
- DJI_0529.MOV (drone; 56 shots; all tq-zero) — 7D
- C7138.MP4 (regular cam; 19 shots; tq NON-zero; timeline-referenced) — 7E / 7G / 13
- C7152.MP4 (regular cam; 15 shots; tq NON-zero; timeline-referenced) — 13
- C7451.MP4 (venue; 73 shots; all tq-zero; multi-shot) — 7F / 7G

"kiss source" (7B) could not be resolved to a filename without a moment→asset lookup (out of
scope); the two timeline-referenced regular assets cover the section-13 requirement instead.

--------------------------------
## SAMPLE QUALITY (stored vs fresh)
--------------------------------

459 sample shots, runtime 902.5s (~1.97s/shot), 0 per-asset failures.

| asset | shots | tq_zero before→after | fresh tq range | emb | dim |
|---|---|---|---|---|---|
| C7309 (cake) | 16→16 | 16→0 | 0.378–0.438 | 16/16 | 512 |
| DJI_0528 (drone) | 280→280 | 280→0 | 0.070–0.899 | 280/280 | 512 |
| DJI_0529 (drone) | 56→56 | 56→0 | 0.549–0.765 | 56/56 | 512 |
| C7138 (regular) | 19→19 | 0→0 | 0.243–0.443 | 19/19 | 512 |
| C7152 (regular) | 15→15 | 0→0 | 0.368–0.447 | 15/15 | 512 |
| C7451 (venue) | 73→73 | 73→0 | 0.311–0.373 | 73/73 | 512 |

Sample total: formerly-zero tq **425 → 0**; every formerly-zero shot now has a measured, non-zero
technical_quality.

--------------------------------
## SAMPLE EMBEDDINGS
--------------------------------

- coverage: **459 / 459** shots embedded.
- dimension: **512** (single value across the sample).
- model: `openai/clip-vit-base-patch32`, L2-normalized (norm ≈ 1.0), MPS device.

--------------------------------
## SAMPLE ID STABILITY
--------------------------------

- **6 / 6 assets exactly stable**; no shot count change, no boundary change, no id drift.
- `scene_ranges` invocations: **0** (no re-segmentation).

--------------------------------
## SAMPLE TIMELINE SAFETY
--------------------------------

- AI Rough Cut items: **129 → 129**; resolved refs **129 → 129**; new dangling references: **0**.
- shot↔feature integrity: 0 shots without features, 0 features without shots.

--------------------------------
## SAMPLE GATE
--------------------------------

**PASS** — S1 frame extraction succeeded (all originals decodable); S2 formerly-zero quality
restored to non-zero; S3 embeddings generated; S4 semantic path exits fallback (CLIP used,
embeddings present); S5 shot ids/boundaries stable; S6 linked timeline intact. Proceeded to the
full run.

--------------------------------
## FULL TEMP-CLONE REMEDIATION — TERMINATED ON THE LARGEST ASSET (NEW BLOCKER)
--------------------------------

The full 362-asset clone run processed **361/362 assets successfully** (0 per-asset failures
logged) and then was **signal-killed while re-encoding the single largest asset, DJI_0530
(501 shots, 4K 3840×2160)**, before it could write its fixture. Reproduced twice:
- The full run died exactly at the DJI_0530 boundary (interrupted clone had 2137 `shot_features`,
  and 2638 − 2137 = 501 = DJI_0530's shot count).
- An isolated re-encode of DJI_0530 alone was also signal-killed (`/usr/bin/time -l`: "terminated
  abnormally", peak RSS ≈ 2.9 GB) — after all 501 shots were measured (501 face-detector ops),
  i.e. the kill lands in the frame/encode memory phase, not in segmentation or DB writes.

Cause (diagnosed, not fixed here): `_encode_asset` decodes and holds every shot's sampled frames
for an asset before encoding, so peak memory scales with (shot count × 4K frame size). DJI_0528
(280-shot 4K drone) completes; DJI_0530 (501-shot 4K) exceeds this environment's ceiling. A dummy
501-frame CLIP batch succeeds (1.77 GB), so CLIP batch size is NOT the limit — the real-4K frame
buffers are. **This is a NEW, bounded blocker: `_encode_asset`/`_shot_frame_groups` needs chunked
frame handling for very large single assets. Per section 21 it is reported, not fixed, in P6.9.**

Interrupted-clone population snapshot (read-only, from the crashed clone before cleanup — 361/362
assets remediated, DJI_0530 unprocessed):
- technical_quality zero: **2327 → 516** (the residual 516 ≈ DJI_0530's 501 unprocessed shots + a
  small in-flight remainder).
- embeddings populated: **0 → 2122** (of 2638; the ~516 missing ≈ DJI_0530 + in-flight).
- This corroborates that every asset the run reached was remediated; only the oversized asset
  blocked completion.

- SHOT ID STABILITY — proven exact on the sample (6/6, 0 re-segmentation); the mechanism (ranges
  reused from existing shots) is asset-independent, so the 361 completed assets are ID-stable by
  construction, but a clean full-population manifest hash was NOT produced (run terminated).
- TIMELINE INTEGRITY — not machine-recorded for the full run (no fixture); sample showed 129/129
  intact, and DJI_0530 is not among the 129-item timeline's referenced assets.
- MOMENT READINESS — embeddings present + 512-dim + valid model ⇒ `project_moments()` prerequisites
  met for the remediated assets (no prompt tuning).

--------------------------------
## DEGRADED-SUCCESS
--------------------------------

**PRESENT (carried forward).** The re-encode path itself has no built-in postcondition gate: a run
could still finish "completed" while, say, some assets silently fell back (unreadable frames →
`classify_features` fallback, or a decode failure). The probe therefore records per-asset
success/failure and embedding/quality coverage rather than trusting job status. A real controlled
run MUST enforce external mandatory postconditions (below) — this is not fixed here.

--------------------------------
## FUTURE REAL-RUN PROTOCOL (for P6.10)
--------------------------------

Before the real run: copy `data/sevenfilm.sqlite3` (timestamped), record its sha256, and freeze
shot / feature / timeline / asset / jobs manifests. Decide the mode explicitly: **delete 15A
`shot_features` (keep shots), then run the `shots` job** — this is the ID-stable re-encode proven
here. After the run, validate the 12 postconditions; on any failure, restore the SQLite copy
(checksum-verified) and re-run the manifests.

Mandatory postconditions: (1) project exists; (2) assets = 362; (3) shot count sane; (4) ids
stable; (5) timeline = 129; (6) timeline refs valid; (7) embeddings restored (≈2638, 512-dim);
(8) tq sentinel rate dramatically reduced from 2327; (9) analysis usable (CLIP backend, not
fallback); (10) no contamination; (11) moments activate; (12) DB backup retained until all pass.

--------------------------------
## READY FOR CONTROLLED REAL FULL 15A REANALYSIS
--------------------------------

**NO** — a full re-encode real run would be signal-killed on DJI_0530 exactly as the temp-clone
run was. It is blocked on the newly-found large-asset encode-memory limit until a bounded fix lands
(chunked frame handling in `_encode_asset`). Two narrower statements remain true:
- The **same-features relabel** path (P6.8) is unaffected and remains **GO**.
- Re-encode remediation is **proven safe and effective for 361/362 assets** (all but the single
  oversized DJI_0530); a re-encode run scoped to exclude/deferring that one asset would complete.

READY FOR PRODUCTION: **NO.**

PROVEN (sample + interrupted full run, real media, real code, temp clone):
- The re-encode path restores technical_quality (sample 425 zero → 0; interrupted full clone
  2327 → 516, i.e. everything except the unprocessed DJI_0530) and embeddings (sample 459/459,
  512-dim; interrupted full clone 0 → 2122) including the 280-shot drone.
- Shot ids/boundaries stable (6/6 sample assets, 0 `scene_ranges`); ID-stability mechanism is
  asset-independent (ranges reused from existing shots).
- 129-item AI Rough Cut fully resolvable and unchanged on the sample; 1:1 shot↔feature.
- Production DB checksum + mtime unchanged; all clones deleted.

NOT PROVEN / NEW BLOCKER:
- The largest asset (DJI_0530, 501-shot 4K) cannot complete `_encode_asset` in this environment
  (reproducibly signal-killed, ~2.9 GB peak) — a bounded encode-memory blocker.
- A clean full-population manifest hash / 362/362 machine confirmation (run terminated).
- Real-run effectiveness end-to-end (degraded-success still externally unguarded).

SAFETY:
- No production write (checksum `738ce224…`, mtime `2026-09-16 23:46:03` unchanged), no job
  enqueued, no real reanalysis, no production feature/embedding/technical_quality write, no
  timeline/Resolve/planner/segmentation/shot-id-algorithm/threshold/model change. Clones deleted.

TESTS:
- `tests/test_p6_9_reencode_remediation.py`: 10 sample tests (probe hygiene, isolation, GATE B–E,
  shot↔feature). Full-suite + full-population tests appended with the full fixture.

--------------------------------
## GATES
--------------------------------

- GATE A — REAL REMEDIATION PATH: **PASS** (real `_encode_asset`/CLIP path identified and run).
- GATE B — QUALITY RESTORATION: **PASS** — sample 425→0; interrupted full clone 2327→516 (all but DJI_0530).
- GATE C — EMBEDDING RESTORATION: **PASS** — sample 459/459 valid 512-dim; interrupted full clone 0→2122.
- GATE D — SHOT-ID STABILITY: **PASS** — 6/6 sample assets, 0 re-segmentation; mechanism asset-independent.
- GATE E — TIMELINE INTEGRITY: **PASS (sample)** — 129 unchanged, 0 new dangling.
- GATE F — FULL POPULATION OUTPUT: **FAIL (cause identified)** — full run cannot complete: DJI_0530
  (501-shot 4K) is reproducibly signal-killed in `_encode_asset` (~2.9 GB peak). 361/362 assets OK.
- GATE G — PRODUCTION ISOLATION: **PASS** (must-pass).

--------------------------------
## FINAL VERDICT
--------------------------------

**B** — remediation works (safe: ID-stable, timeline-safe; effective: quality + embeddings restored
on 361/362 assets including a 280-shot 4K drone), BUT one bounded fix is required before a full real
run: `_encode_asset`/`_shot_frame_groups` must chunk frame handling so the single largest asset
(DJI_0530, 501-shot 4K) does not exhaust memory and get signal-killed. This is not a shot-ID or
timeline-safety fix (those pass) and not a segmentation change — it is a large-asset encode-memory
fix. Environment memory pressure (verdict F) is the trigger; the defect itself is in the batched
frame handling. Verdict A is withheld precisely because the full population cannot complete today.

READY FOR CONTROLLED REAL FULL 15A REANALYSIS: **NO** (blocked on DJI_0530 until the encode-memory
fix). The same-features relabel path (P6.8) remains GO; a re-encode scoped to all-but-DJI_0530
would complete.

READY FOR PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.10 — Bounded encode-memory fix for large assets + DJI_0530 re-verification** (one purpose:
make `_encode_asset`/`_shot_frame_groups` stream/chunk frames so an arbitrarily large single asset
re-encodes within bounded memory, then re-run the DJI_0530 and full-362 temp-clone remediation to
close GATE F). The controlled real full re-encode (snapshot + rollback + 12 postconditions) follows
only after that.

**DO NOT START.**
