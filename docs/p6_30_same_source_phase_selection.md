# PACKAGE 06.30 — SAME-SOURCE PHASE / MOMENT SELECTION

START HEAD: `ba754e4674b010af580e37f06908bb1f072d9025`

## Root cause audit

Same-source sibling phases exist: **YES**. The frozen P6.20 plan has 132 items from 101 assets;
99/101 selected assets contain multiple detected shots (median 5 siblings, max 501).

Current planner explicitly models phase: **NO**. Detected shots are independent candidates. The
planner has category/scale/style/quality scores, exact-shot reuse penalties, a forward-only bonus for
consecutive same-asset use, and P6.19's distinct-shot phase count for asset reuse. Those mechanisms
distinguish exact repetition from forward reuse, but no descriptor or score represents
`SETUP/ACTION_BUILD/ACTION/REACTION/RESOLUTION`, interaction strength, or action phase. An early
sibling can beat a later sibling on ordinary shot score; source time is evidence only when the same
asset is used consecutively.

This proves that phase selection is an architectural layer the planner does not explicitly have. It
does **not** prove that this missing layer caused the user's observed defect.

## Blocking provenance finding

The package premise treats V7 `C7309 source=3332` and P6.20 `source=760/1635` as coordinates in the
same source-frame system, then concludes that V7 selected another detected phase. They are not.

- DB source: C7309 is 1992 frames at 50 fps.
- Raw V7 trace: `left=3332`, physically outside that source.
- V7 raw item schema has only `(name, timeline_start, timeline_duration, left)`; it records neither
  per-item speed nor the source timebase used by Resolve's offset.
- The known V7 item is slow motion. Normalizing the doubled offset gives `3332 / 2 = 1666`.
- Frame 1666 lies inside detected shot `1625–1750`.
- P6.20 already selected that exact shot and source range `1635–1740`; the normalized human point is
  only 31 source frames after its in-point and lies inside the selected range.

Temporal strip review of P6.20's `1635–1740` range shows the couple already performing the cake
interaction throughout. It is not the alleged earlier static phase. Therefore C7309 does not support
the wrong-detected-shot hypothesis after source-time normalization.

This is not isolated: of 87 V7 items mapped to current 15A assets, 15 raw offsets lie outside their
physical source duration. The trace lacks the metadata required to distinguish 1×, 0.5×, other
retimes, or another Resolve source-timebase. A post-hoc phase benchmark built from raw `left` would
silently label wrong shots as the human phase.

## Method status

Phase grouping: audited chronologically from DB, but no selector executed.

Descriptor / compatibility / ranking: deliberately not frozen. Without trustworthy human-phase
coordinates, feature choices could not be validated directionally and C7309 would be a false oracle.
Implementing a ranker anyway would violate the instruction not to tune or claim success from one
misbound control.

P6.29 composition: not run. Phase selection must precede action-start refinement, but there is no
valid selected phase to refine in this package.

## P6.20 shadow

- items: 132
- `KEEP_PHASE`: 0
- `SWITCH_PHASE`: 0
- `REVIEW`: 0
- `UNKNOWN`: 132

Reason: phase selector intentionally withheld because the V7 source-coordinate benchmark is invalid.
No top switches exist; no timeline substitution analysis was fabricated.

## C7309 control

- baseline detected phase: shot `5e6f…`, frames `1625–1750`; selected `1635–1740`
- raw alleged human phase: `3332` (invalid/out of range)
- slow-motion-normalized human point: `1666`
- normalized human detected phase: the **same** shot `5e6f…`
- generic method preferred later action: **NOT TESTED / premise falsified**

## V7 post-hoc

Method frozen first: N/A—stopped before method design.

Mapped raw items: 87. Invalid/out-of-source-range items: 15. Mapped multi-phase assets, agreement,
toward/away counts and median source-time distance: **not reportable** until every V7 item has
canonical source-in coordinates. P6.29's earlier six-case raw-offset comparison is also not a valid
phase benchmark; its zero-proposal conclusion is unchanged, but its reported mapping coverage was
under-counted by this timebase problem.

## False-positive, duration and safety audit

No setup, portrait, establishing, action, reaction or resolution phase was switched. No duration or
slow-motion proposal was generated. The audit helper includes half-open chronological containment and
source-duration guards for the future corrected benchmark.

Production status: **BLOCKED**. DB opened read-only and SHA-256 remained unchanged. Resolve writes: 0.
Timeline changes: 0. `build_timeline()` changes: 0. P6.20/V7/is edit changes: 0. P6.28 remains
shadow-only. Existing untracked source-moment WIP files remain unchanged. No event-model research,
external download, or long-form Kurdish wedding archive was accessed.

Tests: 8 targeted provenance/coordinate tests passed; full suite **1215 passed** (baseline 1207);
repository-wide Ruff and `git diff --check` passed.

## Final verdict

**E — methodology conflict invalidates the experiment.** The specified positive control and human
benchmark use un-normalized Resolve offsets. C7309, once normalized, is evidence for the same selected
phase—not a different phase.

One next milestone only: **P6.30.1 — canonical V7/is-edit source-coordinate extraction**. Re-extract
each rich-reference item with media source frame rate, retime/speed, and canonical source-in/out,
then verify every coordinate is inside the asset before reopening phase ranking. Do not start P6.31.
