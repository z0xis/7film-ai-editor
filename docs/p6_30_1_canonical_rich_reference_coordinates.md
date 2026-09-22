# Package 06.30.1 — Canonical Rich-Reference Source Coordinates

## Result

The canonical domain is **physical decoded source frames in the asset's native
timebase**. The existing V7 and `is edit` traces cannot yet be converted into that
domain authoritatively. The fidelity gate therefore fails, and neither P6.29 nor
P6.30 was re-benchmarked.

This is an evidence failure, not a conversion failure hidden by a heuristic. In
particular, `raw_left / 2` is not accepted as a coordinate rule.

## Root cause and inventory

Both legacy traces store four item values: source filename, timeline start,
timeline duration, and an unlabeled Resolve `left` value. The timeline-level rate
is 50 fps. They do not store per-item native source timebase, source-out, speed,
retime curve, or an authoritative source-frame/source-time value.

The Resolve 21.1 scripting surface offers the read methods needed for a future
authoritative capture: `GetSourceStartFrame`, `GetSourceEndFrame`,
`GetSourceStartTime`, `GetSourceEndTime`, `GetSpeed`, timeline settings, and media
pool clip properties. A strictly read-only probe was added. It was attempted both
inside and outside the sandbox, but no Resolve scripting instance was available.
No matching V7/`is edit` FCPXML or OTIO artifact exists in the repository.

## Coordinate model

`canonical_source_coordinates.py` accepts only either:

1. direct Resolve source-frame IN/OUT values, or
2. direct Resolve source-time IN/OUT values plus the native rational FPS.

It preserves all legacy offsets for provenance but never automatically converts
them. Canonical ranges must be half-open, positive, and within physical asset
bounds. When timeline duration and an authoritative constant speed ratio are
available, consumed source duration is validated as:

`timeline_frames / timeline_fps × speed_ratio × source_fps`

Here `speed_ratio` explicitly means source-time divided by timeline-time. Missing
or inconsistent evidence produces `UNKNOWN_COORDINATE`, never a guessed value.

## Current fidelity measurements

| Timeline | Video items | Asset mapped | Canonicalized | Ambiguous | Raw offsets outside physical bounds |
|---|---:|---:|---:|---:|---:|
| V7 | 87 | 87 | 0 | 87 | 15 |
| `is edit` | 187 | 187 | 0 | 187 | 4 |

Canonical bounds violations are reported as zero only because no guessed
canonical range was emitted. Bounds and duration gates remain untested, rather
than passed.

## Controls

Synthetic controls cover rational FPS, 50/25 and 25/25 timebases, normal speed,
0.5x and 0.25x source consumption, one-frame rounding tolerance, strict physical
bounds, and same-asset exact/forward range relations. These validate the model,
not the missing V7 metadata.

C7309 remains the regression control:

- raw Resolve `left`: 3332
- trace timeline FPS: 50
- DB source FPS: 50/1
- physical source length: 1992 frames
- per-item retime/speed: unavailable
- canonical source IN/OUT: unknown
- old `/2` value: 1666, explicitly non-canonical

Therefore no claim is made about whether C7309 is the same detected shot as the
P6.20 range. The prior same-phase conclusion used an unproven transform.

## Fidelity gate and architecture

Gate status: **FAIL**. Near-complete authoritative coverage, duration consistency,
normal/retimed controls, same-source reuse, and C7309 cannot be proven from the
available trace. Consequently the A/B/C/D disagreement distribution is not
computed, the exact playback-positive is not identified, and no architectural
preference among source-in refinement, same-source phase selection, or upstream
source selection is justified.

The next evidence-driven milestone is a read-only recapture while the correct
Resolve project is open, using the probe's direct source-frame/time and speed
fields, followed by FCPXML/OTIO cross-check only if those APIs remain ambiguous.
No selector work should resume before that gate passes.

## Safety

The SQLite audit opens the production database with `mode=ro` and verifies its
SHA-256 before/after. The Resolve probe contains no setters, timeline selection,
creation, deletion, import, export, or mutation call. `build_timeline`, P6.20, V7,
`is edit`, Stage-1/Stage-2, P6.28, event research, music planning, and the excluded
long-form archive were untouched.
