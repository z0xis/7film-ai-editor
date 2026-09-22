# Package 06.30.2 — Offline-Media Rich-Reference Coordinate Recovery

## Outcome

The original media is unavailable and was not searched for. Nevertheless, the open
Resolve project preserves enough editorial metadata for reliable source-time
benchmarking. The offline fidelity gate passes.

Resolve 21.1.0.14 was connected read-only with project `15 Ağustos`. Both required
timelines were present. Every source item in the V7 primary video track and `is edit`
exposed direct source-frame IN/OUT, source-time IN/OUT, speed, native FPS, stored
frame count, timecode, and offline state.

## Canonical domain

The recovered domain is **canonical source time** plus **logical source frames** in
the project-stored native rate. These are not described as physically decoded
frames because the media is offline.

Primary method: `RESOLVE_EXPLICIT_SOURCE_FRAME`. Local source seconds are the
explicit logical source frame divided by the project-stored source FPS. Raw
`GetLeftOffset`/`GetRightOffset` values are retained only as forensic evidence.
They are never a fallback.

Reverse playback preserves the direction of source IN/OUT. Bounds and duration
checks use the ordered range and absolute consumed duration. Constant speed uses
the explicit `GetSpeed().Percentage` value.

## Capture and independent exports

| Measure | V7 primary video | `is edit` |
|---|---:|---:|
| Timeline items | 87 | 187 |
| Source-time canonicalized | 87 | 187 |
| Logical-frame canonicalized | 87 | 187 |
| Ambiguous | 0 | 0 |
| Stored FPS coverage | 87 | 187 |
| Stored duration coverage | 87 | 187 |
| Retime coverage | 87 | 187 |
| Offline | 87 | 187 |
| Bounds failures | 0 | 0 |
| Duration failures | 0 | 0 |

V7 also contains 21 video-layer items on tracks 2–3. They were captured, but the
87-item benchmark population is the primary story track matching the historical
V7 trace.

Read-only FCPXML 1.10 and OTIO exports both succeeded. FCPXML contains asset start,
duration, rate and linear `timeMap` data. OTIO contains missing-media available
ranges, source ranges, rational rates and `LinearTimeWarp` effects. OTIO exactly
cross-checked all primary items within Resolve's one-frame boundary convention:
87/87 V7 and 187/187 `is edit`.

## C7309 regression

- raw left/right: 3332 / 602
- Resolve explicit logical source range: 1666–1691
- canonical local source start: 33.32 seconds
- project source FPS: 50
- project-stored length: 1992 logical frames
- speed: 0.5x
- method: `RESOLVE_EXPLICIT_SOURCE_FRAME`
- OTIO cross-check: exact within one frame
- heuristic `/2`: not used

The earlier numerical result happens to match because Resolve explicitly records
0.5x for this item. The authority is the source-frame API and OTIO time-warp—not
division of a raw left offset. P6.20 starts at frame 1635, only 31 logical frames
from V7, with overlapping ranges in the same detected shot. C7309 is therefore an
effectively-same-moment control, not evidence for a different phase.

## P6.20 ↔ V7 measurement audit

The frozen 132-item P6.20 plan was compared to the nearest canonical V7 range for
the same source asset. Classification uses DB detected-shot boundaries and range
overlap; no selector was tuned or added.

| Class | Count |
|---|---:|
| A — same detected shot, different source-in | 5 |
| B — same source, materially different region | 41 |
| C — source asset absent from V7 | 81 |
| D — effectively the same moment | 5 |

Median nearest-V7 distance among same-source items is 258 logical frames. Class C
dominates the full plan, while true same-shot source-in errors are only 5/132.
Same-source different-region cases exist, but they are not the primary disagreement
class. The evidence points first to upstream semantic shot/source selection rather
than further source-in micro-ranking.

This comparison describes plan/reference disagreement, not rejected-alternative
ground truth and not proof that every V7 choice must be copied.

## Architectural conclusion

- Source-moment benchmarking: **available**.
- Source-in refinement: measurable but not the main failure class.
- Same-source phase selection: material secondary class.
- Upstream source/shot selection: dominant disagreement and the next layer to
  investigate.

V7 remains independently valid for shot order, duration, sequences, pacing, music
placement and transitions, intro/outro, visible reuse, and overall timeline grammar.
Offline media limits physical decoding and rejected-alternative visual analysis; it
does not invalidate these timeline-level facts.

## Safety

Resolve calls were read-only except explicit serialization to local ignored `work/`
FCPXML/OTIO artifacts. No project state, timeline, clip, V7, `is edit`, P6.20,
production DB, or `build_timeline()` mutation occurred. The DB audit used
`mode=ro` and verified its SHA-256 before and after. Existing untracked user WIP was
left untouched.
