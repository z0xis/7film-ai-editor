# PACKAGE 06.29 — SOURCE-MOMENT / ACTION-START RANKING

START HEAD: `91f14f2b261e8702f0f72b40eb33b4d5bb1d5121`

## Existing WIP safety

Uncommitted files found and preserved unchanged:

- `services/shadow_source_moment.py`
- `tools/shadow_source_moment_eval.py`
- `tests/test_shadow_source_moment.py`
- `tests/test_shadow_source_moment_eval.py`
- `docs/job-guvenligi-ve-source-moment-durumu.md`

They implement an older Elenora/54-case four-gate experiment whose frozen scratch corpus is absent.
That methodology does not generate P6.20 within-shot action-start proposals, so P6.29 neither
overwrites nor imports it. New files build beside it; there is no conflict in production because
neither module is imported by the planner.

## Root cause

Production path:

`build_timeline()` → selected shot + speed → source duration rounded up for retime →
`_source_range_for_duration()` → fixed handle (min of shot/8 and 0.2 s) + already-consumed source →
`_best_offset()` → candidate offsets from stored 0.5 s windows → maximize the minimum
`_window_score()` → `TimeRange(shot.start + offset, source_frames, source_rate)` → timeline duration.

The score contains relative sharpness, face-edge and bystander penalties (or sharpness only for
still categories). It has no `ACTION_START`, `SUBJECT_READY`, `CAMERA_SETTLED`, or
`MEANINGFUL_INTERACTION_START` representation. Across the frozen P6.20 plan, 87/132 source-ins are
at the initial handle; none starts at the exact detected boundary because the handle is always
applied. Median offset inside the detected shot is 0.20 s, P90 1.04 s, max 2.04 s; 29/132 begin
more than 0.5 s in. All 26 slow-motion items satisfy their source requirement, but this guards
duration only—not meaningful onset.

## Method (frozen before V7)

Candidate starts: original plus deterministic 0.20 s steps, capped at +1.0 s and at
`shot_end - required_source_frames`. The required length is source length after retime calculation,
so a proposal cannot shorten the timeline or break slow motion.

Temporal evidence: dense 10 fps proxy samples before and after each candidate. Components remain
separate: YuNet subject visibility/edge clearance, global-motion-compensated residual action onset,
P6.28 post-window camera settle, Laplacian technical usability, obstruction clearance, histogram
continuity, and beat proximity. Beat proximity is recorded as zero/neutral because source-in does
not change the cut's timeline beat; it cannot override visual evidence.

Classification: a trim requires reliable evidence, semantic continuity, no technical regression,
two independent improvements, and either a camera-settle case or subject-readiness plus action-onset.
Ambiguous evidence is `REVIEW`; insufficient evidence is `UNKNOWN`; intentional detail/venue starts
are preserved when already usable and settled.

## P6.20 shadow

- items: 132
- `KEEP_ORIGINAL`: 106
- `TRIM_PROPOSAL`: 0
- `REVIEW`: 26
- `UNKNOWN`: 0
- trim delta median / P90 / max: N/A (no trustworthy proposal)

There are no top trim proposals. This is not hidden as a success: high-confidence bad lead-ins were
not demonstrated.

## Temporal visual validation

Reviewed dense temporal strips/proxy segments, not isolated frames:

- `C7311` at source 260 (`REVIEW`): couple interaction is already underway; later frames are
  progression, not a cleaner action start. Trimming would discard useful onset.
- `C7194` at source 10 (`REVIEW`): deliberate rotating/reveal portrait; high residual motion is
  intentional camera language, not dead lead-in.
- `C7215` at source 260 (`REVIEW`): bride's van interaction is already underway.
- `C7219` (`KEEP_ORIGINAL`): held wide couple portrait correctly preserved.
- `DJI_0523` (`KEEP_ORIGINAL`): slow establishing movement correctly preserved.
- `C7309` (`KEEP_ORIGINAL`): selected segment already shows cake interaction; no safe within-shot
  later start dominates it.

Useful trims: 0. False trims applied: 0. Intentional stills/establishing shots were not trimmed.
Camera-settle and action-onset numerical candidates remained `REVIEW` when independent evidence did
not agree. No clear P6.20 item matching the user's exact “subjects have not started yet” complaint
was found. The original playback-positive shot/timecode remains unidentified.

## V7 post-hoc benchmark

Features, gates and thresholds were frozen before loading V7. Six P6.20 items map to a V7 human
source-in inside the same detected shot: closer 0, farther 0, unchanged 6. Median human-start
distance remains 70 frames before and after. With zero proposals, this supplies no directional
usefulness evidence.

### C7309 qualitative control

P6.20 uses source 760 and 1635; V7's verified action phase is source 3332. That human choice belongs
to a different detected shot/phase. P6.29's hard unit—do not replace the selected shot—correctly
prevents crossing to it, but also means this method cannot reproduce V7's setup→action preference.
No C7309 hardcode was added.

## False-positive and duration audit

Establishing: DJI shots kept. Portrait: `C7219` kept; `C7194` review only. Held moment: no trim.
Slow reveal: `C7194` review only. Invalid duration proposals are rejected at generation; all proposed
grid positions retain the exact source-frame requirement, including slow motion. Source-out behavior
is otherwise unchanged.

## Production status and safety

**BLOCKED.** The factorized layer is deterministic and conservative, but success criteria B/C/E
are not met: no real bad lead-in was confidently detected, no useful trim was visually confirmed,
and V7 agreement did not improve. Synthetic success is not production evidence.

DB writes: 0 (read-only SQLite URI; SHA-256 unchanged). Resolve writes: 0. Timeline changes: 0.
`build_timeline()` changes: 0. P6.20/V7/is edit changes: 0. P6.28 remains shadow-only. No event-model,
external download, or long-form Kurdish wedding archive was accessed.

Tests: 13 targeted P6.29 tests passed; full suite **1207 passed** (baseline 1194); repository-wide
Ruff and `git diff --check` passed.

Final verdict: **D — exact positive evidence is insufficient.** One bounded next milestone only:
capture the complained-about P6.20 playback shot ID/timecode and a short before/after proxy segment,
then use it as a locked positive recall check. Do not start P6.30 or production integration yet.
