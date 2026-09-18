# PACKAGE 06.18 — DRONE RELATIVE CHRONOLOGY / EVENT ANCHORING

START HEAD: `e590d7f`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Recovered shadow-only chronology for the timecodeless drone shots by embedding-consensus over the
timecoded camera backbone, validated by a camera holdout, and injected it into the planner through a
shadow wrapper. No production `day_position` written, no DB/timeline/Resolve write, no scoring change
(the P6.17 relief stays reverted; planner 0-line diff). Tool: `tools/p6_18_drone_chronology.py`;
fixtures: `tools/fixtures/p6_18_{holdout,drone_chronology,shadow_summary}.json`; tests:
`tests/test_p6_18_drone_chronology.py`.

--------------------------------
## BASELINE
--------------------------------

duration 162.9 s · items 132 · song2 60 · first dance = camera crowd-dance (C7388/C7389) · 12 drone
items placed before 70 s (they float, `day_position = None`). Deterministic.

--------------------------------
## DRONE INVENTORY
--------------------------------

| asset | shots | dur | timecode | embedded creation_time (drone clock) |
|---|---|---|---|---|
| DJI_0522 | 14 | 33 s | none | 00:03:58 |
| DJI_0523 | 10 | 25 s | none | 00:04:54 |
| DJI_0524 | 21 | 53 s | none | 00:05:34 |
| DJI_0525 | 14 | 35 s | none | 00:08:00 |
| DJI_0526 | 19 | 48 s | none | 00:09:26 |
| DJI_0527 | 11 | 27 s | none | 00:11:09 |
| DJI_0528 | 280 | 706 s | none | 00:31:00 |
| DJI_0529 | 56 | 140 s | none | 01:07:04 |
| DJI_0530 | 501 | 1261 s | none | 02:00:07 |
| DJI_0531 | 15 | 37 s | none | 02:21:10 |

941 drone shots total; 1697 timecoded camera shots as anchors.

--------------------------------
## AVAILABLE CHRONOLOGY SIGNALS
--------------------------------

| signal | available? | reliability |
|---|---|---|
| camera SMPTE timecode (19:33→20:50) → `day_position` | yes | AUTHORITATIVE (the trusted backbone) |
| drone embedded `creation_time` (`format.tags`) | **yes** | USEFUL — monotonic with filename order, but on the drone's own (offset) clock; used only as a relative-ordering / monotonicity check |
| filename order DJI_0522→0531 | yes | weak prior (agrees with creation_time) |
| CLIP embeddings | yes | primary inference signal |
| `brightness` (day/night) in metrics | yes | coarse band (not needed here) |
| DB `created_at` (import time, 2026-09-15) | yes | UNRELIABLE (import, not filming) |
| V7 / is-edit timings | — | **forbidden as labels** |

--------------------------------
## INFERENCE METHOD
--------------------------------

method: for each drone shot, cosine-similarity to all 1697 camera anchors; take the top-K=25 above a
0.55 similarity floor; robust `day_position` = median of their day_positions; dispersion = 75th
percentile absolute deviation. confidence: **HIGH** (support ≥ 8, dispersion ≤ 0.12), **MEDIUM**
(≥ 5, ≤ 0.20), else **LOW** / **UNRESOLVED**. fail-closed: a drone shot with insufficient/scattered
support gets no inferred value. Drone `creation_time` order is used only to check asset-level
monotonicity (never to set values). No V7/is-edit leakage.

--------------------------------
## CAMERA HOLDOUT VALIDATION
--------------------------------

sample 300 · **median error 0.027** · **p90 0.154** · mean 0.062 · **event-region accuracy 0.767**
(hiding a camera's day_position and inferring it from the others). The estimator is objectively
accurate to a few percent of the day for cameras.

--------------------------------
## DRONE CHRONOLOGY
--------------------------------

tiers: HIGH 74 · MEDIUM 312 · LOW 554 · UNRESOLVED 1. asset-median day_position (creation-time order):
0522 0.51 · 0523 0.49 · 0524 0.51 · 0525 0.52 · 0526 0.51 · 0527 0.68 · 0528 0.54 · 0529 0.55 ·
0530 0.54 · 0531 0.69. **asset-monotonic fraction 0.889** (broadly follows the drones' own clock).
The reception drones cluster near ~0.5 because the timecoded camera span is the evening reception and
a wide aerial is visually similar to many reception cameras.

--------------------------------
## DJI_0528 (first dance) / DJI_0529
--------------------------------

The isolated first-dance drone shot (`df3a49bf`, DJI_0528) is inferred at day_position **0.409 (HIGH,
support 25, dispersion 0.11)** — visually it matches *earlier* wide/venue cameras, not the late
reception close crowd-dance (C7388 sits at day_position 0.786). This is the generic-visual-similarity
confound (§10): a wide night aerial of a couple resembles earlier wide couple/venue footage. DJI_0529
(`44a0e83c`) is inferred at 0.457 (MEDIUM). So the inferred drone chronology places the first-dance
drone *before* the reception progress (~0.66), which does not help it win the reception slot.

--------------------------------
## SHADOW A / B / C
--------------------------------

| condition | items | dur | song2 | first_dance selected | drones < 70 s |
|---|---|---|---|---|---|
| A baseline (no overlay) | 132 | 162.9 s | 60 | C7388/C7389 | 12 |
| B HIGH only | 132 | 162.9 s | 60 | C7388/C7389 | 12 |
| C HIGH+MEDIUM | 131 | 163.4 s | 59 | C7388/C7389 | 10 |

Deterministic; no DB writes in any condition.

--------------------------------
## FIRST DANCE — RESULT
--------------------------------

classification: **GENERIC_DANCE_ONLY (unchanged).** Injecting the validated drone chronology does NOT
change the first_dance selection — the camera crowd-dance still wins. Two reasons: (1) the reuse/asset
penalty from P6.17 (the isolated first-dance drone paid 0.247 because a sibling DJI_0528 shot was
over-used) is untouched — and P6.18 is forbidden from reviving the reuse relief; (2) the inferred
day_position (~0.41–0.55) anchors the drone *before* the reception progress, so chronology does not
tip it in at the reception slot.

--------------------------------
## DRONE MISPLACEMENT
--------------------------------

before (baseline): 12 drone items < 70 s. after (HIGH+MEDIUM): 10. A slight reduction, not a fix — the
early drones (DJI_0524/0526 establishing) are partly legitimate intro material, and the reception
drones' ~0.5 estimate keeps them mid-edit. No new misplacement was introduced.

--------------------------------
## RECEPTION REGRESSION
--------------------------------

**None.** song2 stays 60 (HIGH) / 59 (HIGH+MEDIUM); duration ~163 s; deterministic. The overlay is
safe — it neither collapses reception (unlike the P6.17 full waiver) nor front-loads.

--------------------------------
## SOURCE PROGRESSION / CAKE CONTROL
--------------------------------

The overlay only overrides `day_position` for confident drone shots; timecoded camera shots
(incl. cake C7309) are untouched — same day_position, same behaviour (regression control holds).

--------------------------------
## CHRONOLOGY QUALITY
--------------------------------

HIGH 74 · MEDIUM 312 · LOW 554 · UNRESOLVED 1 (of 941). Camera holdout median error 0.027, event-region
0.767, asset monotonicity 0.889. The method is validated and fail-closed; coverage is partial by
design (LOW/UNRESOLVED shots keep no inferred value).

--------------------------------
## PRODUCTION DESIGN RECOMMENDATION
--------------------------------

If eventually adopted: **compute chronology dynamically at planner input time** (option B) or store
**event/episode anchors** (option C) — NOT a single asset-level `day_position` (drone assets span
minutes of an event), and do not persist absolute values while the reception estimate is only ~0.5.
Do not persist now — the estimate is accurate on the camera manifold but the reception-drone cluster
is not discriminative enough to change planner behaviour on its own.

--------------------------------
## SAFETY
--------------------------------

DB writes 0 · Resolve writes 0 · timeline writes 0 · planner 0-line diff. DB checksum `e8798470…` and
mtime `2026-09-18 21:07:36` unchanged; shots/features/embeddings 2638; 129-cut / V7 / is edit
unchanged; jobs 0 · Elenora 1405 · contamination 0. Temporary frames deleted; none committed. Full
suite 1131 passed, ruff clean.

--------------------------------
## READY FOR NEXT PLANNER FIX
--------------------------------

**YES** — chronology is validated and recoverable and can be injected safely, so the next planner fix
(redundancy / asset-reuse) can be tested with chronology stabilized in shadow.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

--------------------------------
## FINAL VERDICT
--------------------------------

**C** — event-region chronology is recovered and objectively validated (camera holdout median 0.027,
region accuracy 0.767, asset monotonicity 0.889), and injecting it is safe (no reception regression,
no new misplacement). But **chronology alone does not fix first-dance placement**: the camera
crowd-dance still wins because the redundancy / asset-reuse penalty (P6.17) is the primary remaining
blocker, and the reception-drone estimate (~0.5) is not discriminative enough on its own. Chronology
is stabilized; redundancy/scoring is next.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.19 — REDUNDANCY / ASSET-REUSE PENALTY FIX WITH CHRONOLOGY FIXED IN SHADOW** — with the validated
drone chronology overlay applied in shadow, address the asset-reuse penalty so a distinct angle of an
owed moment (the isolated first-dance drone) is not suppressed by an over-used sibling shot, and
prevent the same shot phase repeating 3×, validated in shadow against V7 — without collapsing
reception (the P6.17 full-waiver failure) and without persisting chronology or changing production
data.

**DO NOT START.**
