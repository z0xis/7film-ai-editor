# P6.28 — Camera stability / shaky-shot gate (shadow only)

START HEAD: `df6b27b96001df0deb1a73a1193a1a6e9ce998f0`

## Root cause

`measure_frames()` scores focus, exposure and contrast. Its `motion_score` is the mean absolute
pixel difference between a few representative frames. Neither value models a camera trajectory,
frequency or jerk. A sharply exposed frame remains high-quality while the camera shakes, and a
smooth pan can have more raw frame difference than a static shaky shot. The production quality gate
therefore has no signal capable of separating those cases.

## Shadow method

`services/stability.py` tracks up to 240 corners between temporally dense adjacent frames, fits a
global partial-affine transform with RANSAC, accumulates translation/rotation into a camera
trajectory, and measures trajectory acceleration plus repeated direction reversals. Smooth pan,
tilt and drone movement may have large total displacement but low jerk. Hard `UNSTABLE` requires
all three: reliable global tracks, high normalized jerk and repeated reversals. Low texture,
foreground-dominated motion and short evidence abstain as `UNKNOWN`; ambiguous motion is `REVIEW`.

It is not imported by `planner.py`, `analysis.py` or `vision.py`. No schema or planner weight changed.

## Bounded visual validation

Temporal strips and proxy playback were used, not isolated frames:

- stable moving negative: P6.20 `DJI_0523`, smooth dusk drone motion — `STABLE`, jitter 0.301;
- static/stable negative: `C7219`, posed couple — `STABLE`, jitter 0.161;
- intentional handheld/orbit negative: `C7223`, large smooth reframing around bride and plants —
  conservatively `REVIEW`, not rejected (jitter 18.211, reversal 0.056);
- ambiguous foreground/static case: `C7192`, subjects dominate a short clip — `REVIEW`, not rejected
  because global-track confidence is 0.666;
- synthetic controlled positive with alternating 5–6 px global displacement — `UNSTABLE`;
- textureless/low-confidence sequence — `UNKNOWN`.

False-positive audit: zero of the 132 P6.20 selections was hard-rejected. 57 were `STABLE`, 42
`REVIEW`, 33 `UNKNOWN`. The high-jitter intentional orbit remained review because it lacked repeated
direction reversals. This is the desired precision-first behavior, but it also exposes the blocker:
the user's exact complained-about shot was not recorded by shot id/timecode, so the real positive
cannot be proven caught. Synthetic separation alone is insufficient to activate a production gate.

## P6.20 shadow impact

Frozen plan `49991347e0d406ea`: 132/132 items measured. Hard rejects: 0; replacement requirements: 0;
duration 162.94 s → 162.94 s; coverage unchanged. This is an ablation only—no replacement plan or
timeline was created. The result is evidence against silently deploying thresholds: without a
labeled real shaky positive, tightening the gate would begin rejecting intentional movement.

## Safety and verdict

The evaluator opens SQLite read-only and verifies the DB SHA-256 before/after. It reads existing 15A
local proxies only. Resolve calls: 0. Planner calls: 0. V7, is edit and the P6.20 candidate are
untouched. No source archive, long-form Kurdish wedding archive, external data, event model or
download was accessed.

Tests: 6 focused stability tests passed; full suite **1194 passed** (P6.27 baseline was 1188);
repository-wide Ruff passed. The full-suite invocation needs the repository root on `PYTHONPATH`
because an existing test imports another test module as `tests.*`; with the repository's expected
path setup there are no failures.

**VERDICT: SHADOW METRIC BUILT; PRODUCTION ACTIVATION BLOCKED.** The method is deterministic and
correct on controlled jitter, preserves validated intentional motion, and abstains conservatively,
but real-positive recall cannot be established without the complained-about P6.20 shot id/timecode.
Do not wire it into `build_timeline()` yet.

Next milestone only after this blocker is resolved: P6.29 source-moment / action-start ranking. It is
not started here.
