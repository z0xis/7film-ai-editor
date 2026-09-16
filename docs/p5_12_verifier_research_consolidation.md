# P5.12 — Verifier Route Consolidation / Research Decision Gate

Documentation-only. No model downloaded, no inference run, no code added this package.

## Root problem (unchanged since P5.3)

Qwen3-VL-4B-Instruct single-frame finds real story-critical events (first_dance episodes,
cake_cutting) with genuine, replicated value — but can hallucinate within an *already-supported*
event family. Proven case: `C7349`, a solo folk-costume performer, classified `first_dance` with
a fabricated "bride+groom paired dancing" claim. The current allowlist accepts this by
construction, because `first_dance` is on the supported list. This is the verifier problem this
whole research arc (P5.5-P5.11) exists to solve. It is not being broadened back into general
wedding-video understanding here.

## What Qwen actually proved

**VALUE** (real, replicated across P5.3/P5.4): found 4 genuine first-dance episodes (including
one on drone footage no prior process had catalogued) and 1 genuine cake-cutting episode, purely
from generic router signals with zero oracle information; correctly rejected most hard negatives
(cake-visible-only, ordinary crowd dancing, henna ritual scenes) as "none."

**TRUST LIMIT** (equally real): raw precision on the full real-data sample was ~60% (6 TP / 4 FP
across 91 calls, P5.4); allowlist-accepted precision was ~86% with one confirmed harmful accept
inside the supported-event family (P5.4); three separate ceremony_action hallucinations were
found, two with fabricated subjects/objects (P5.3/P5.4); self-reported confidence was uniformly
0.92-0.98 on both correct and hallucinated calls, i.e. useless as a discriminator (P5.2/P5.4).

**QWEN IS USEFUL ≠ QWEN IS SAFE TO AUTO-ACCEPT.** This distinction is the spine of every package
since P5.4 and remains the frame for this consolidation.

## Route-by-route evidence chain

### Route 1 — Same-model self-verification (P5.5, P5.6)
- **P5.5** (single targeted atomic prompt): caught C7349 (0 harmful accepts in its 7-call test),
  but its exclude-inconsistency handling incidentally cost a genuine positive (C7261), dropping
  coverage to 5/6 (83%). A follow-up paraphrase check showed the same frame gave a *different*
  answer under different wording — proof the single-prompt signal is phrasing-sensitive, not a
  stable ground truth.
- **P5.6** (4 independently pre-registered prompts, 4 pre-registered voting rules): the known
  harmful case was **accepted by all four policies (M1-M4)** — worse than the single prompt it
  replaced. A stable hallucination was found (2 of 4 prompts agreeing on a false "paired,
  dancing" read). Ordinary-dance negatives frequently received false pair-support from 3 of 4
  prompts.
- **STATUS: same-model multi-prompt voting — CLOSED (falsified).** Single targeted prompt — **NOT
  SOLVED**, remains an imperfect heuristic with a demonstrated phrasing-sensitivity failure mode,
  not a validated verifier.

### Route 2 — Face / person count (P5.2-P5.9, YuNet + detectors)
- YuNet face counts overlap between genuine and harmful cases; drone footage frequently yields
  0 faces on real first-dance subjects (altitude/angle); C7349 itself showed multiple faces.
- **STATUS: CLOSED as an event/relationship verifier.** May persist as generic descriptive
  metadata (e.g. shot_scale hints), never as a decision gate.

### Route 3 — Generic object detection (P5.8, P5.9)
- SSDLite320: cheap, architecturally independent from Qwen, but false-contradicted ~40% of
  genuine first-dance frames at nearly every tested threshold; caught the harmful case only at
  the single tightest grid corner; cake detection was 0/2 on real wedding footage.
- Faster R-CNN MobileNetV3-320: materially better recall everywhere (drone: 0→2 persons; cake:
  0→1 hit) — and this made safety **worse**, not better: false contradiction rose to 20-80%
  depending on threshold, and the drone episode gained a new false-veto risk SSDLite's poor
  recall had accidentally avoided. C7349/C7261 separability was **NONE across all 12
  pre-registered grid cells** — every cell either accepted both or rejected both together.
- **STATUS: CLOSED for relationship verification** — explicitly not because detector accuracy
  was too low (Faster R-CNN's accuracy was good), but because **object presence does not encode
  relationship**, and no amount of box-level recall changes that. Cake *presence* (not cutting
  action) may persist as auxiliary metadata only.

### Route 4 — Single-frame pose geometry (P5.10, P5.11)
- KeypointRCNN recall was sufficient everywhere it mattered — including C7349, C7261, and both
  drone frames — removing "recall" as a possible excuse before any geometry was computed
  (explicit two-phase design, per P5.10's own falsification-first requirement).
- Three pre-registered features (normalized pair distance, mutual-facing evidence, pair
  dominance), frozen before inspection: **C7349** (harmful) measured distance=3.2 (close),
  dominance=0.74 (high); **C7261** (genuine) measured distance=8.6 (far), dominance=0.24 (low) —
  **inverted relative to naive intuition** on two of three features. Mutual-facing was
  SUPPORTED for 16/17 cases regardless of ground truth (near-constant, non-discriminating); its
  one CONTRADICTED reading fell on a genuine positive, not the harmful one. The single highest
  pair-dominance value in the whole 17-case set belonged to a true-negative ordinary-dance frame.
- **STATUS: CLOSED as currently defined.** Per its own pre-registered decision rule (both cases
  had usable skeletons; the failure is in what the geometry represents, not detection recall) —
  **another pose extractor (MediaPipe/RTMPose) is explicitly not justified by this evidence.**

### Route 5 — Generic action/video classification (audited, not tested — P5.10)
Eliminated at the scoping stage: Kinetics-family vocabularies contain "dancing," never "first
dance," and cannot structurally express the needed distinction regardless of model quality.
**STATUS: CLOSED at the scoping level** (no inference run, elimination was on vocabulary grounds).

### Route 6 — Standalone optical flow
Already found insufficient as a discriminator in prior Source Moment research (pre-dates this
verifier arc); not retested. **STATUS: CLOSED (prior evidence, not reopened).**

## Closed routes table

| Route | Signal type | Independent from Qwen? | Critical failure | Status |
|---|---|---|---|---|
| Same-Qwen multi-prompt voting | language/same-model | No | All 4 policies accept the harmful case | **FALSIFIED** |
| Same-Qwen single targeted prompt | language/same-model | No | Phrasing-sensitive, cost a genuine positive | **NOT SOLVED** (imperfect heuristic, not closed as unusable) |
| YuNet face count | geometric/CV | Yes | Overlaps TP/FP, 0 on real drone positives | **CLOSED** |
| Generic person count | geometric/CV | Yes | Same box-level limitation | **CLOSED** |
| SSDLite object detection | CNN detector | Yes | ~40% false contradiction, cake 0/2 | **CLOSED** |
| Faster R-CNN object detection | CNN detector | Yes | NONE separability across 12/12 cells; false contradiction up to 80% | **CLOSED** |
| Box geometry (size/proximity/dominance) | geometric | Yes | No relationship representation by construction | **CLOSED** |
| Single-frame pose geometry (KeypointRCNN + pair features) | CNN+keypoints | Yes | Inverted on 2/3 features, near-constant on 3rd | **CLOSED** |
| Generic action-class label | video model | Yes | Vocabulary cannot express "first dance" | **CLOSED (scoping-level)** |
| Standalone optical flow | motion | Yes | Prior Source Moment finding: insufficient | **CLOSED (prior evidence)** |
| Limb-level interaction proximity | geometric (unrun) | Yes | — | **UNTESTED** |
| Temporal pair coordination/persistence | motion+identity (unrun) | Yes | — | **UNTESTED** |
| True HOI/relationship model | learned relation (unrun) | Yes | No mature small local candidate found | **UNTESTED / IMMATURE** |
| Second independent VLM | language | Partial (same risk class) | Not attempted, deliberately not defaulted to | **NOT RECOMMENDED BY DEFAULT** |
| Episode-level (multi-frame-from-same-episode) verification | aggregation strategy (unrun) | N/A (architecture, not a signal) | — | **UNTESTED, STRATEGIC** |
| Custom labeled verifier/data | learned, user-specific (unrun) | Yes | Requires dataset investment | **UNTESTED, LARGE INVESTMENT** |

## Auxiliary signals still useful (explicitly not verifiers)

- Faster R-CNN cake *presence* (not cutting-action) — descriptive metadata only.
- KeypointRCNN pose *availability* (whether a skeleton exists at all) — descriptive only.
- Object detector coarse person structure — descriptive only.

**AUXILIARY METADATA ≠ TRUSTED VERIFIER.** None of these are revived as decision gates by this
consolidation.

## Event semantic layers (conceptual map, not implemented)

```
L1 Physical presence      -- face/object/person detectors: TESTED, CLOSED as verifiers
L2 Pair relationship      -- pose geometry: TESTED, CLOSED; limb-level/temporal: UNTESTED
L3 Action                 -- Qwen itself; generic action models: CLOSED (vocabulary)
L4 Event context          -- Qwen partially; episode-level aggregation: UNTESTED
L5 Editorial/story meaning -- out of scope for a frame-level verifier entirely
```

`first_dance` plausibly requires L2 + L3 + some L4. Every signal tested so far tops out at L1, or
weakly touches L2 without succeeding. This is the most concrete output of the whole research arc:
**the missing information is not at the layer any tested signal operates on.**

## Is first_dance a pure single-frame visual fact?

Often, no. A generic couple-dance frame can be visually identical to a first-dance frame; the
distinguishing information (this is *the* dance, not *a* dance) plausibly depends on sequence
context, surrounding guests, chronology relative to other reception events, and duration —
information a single still frame structurally cannot carry regardless of which model reads it.
This reframes the entire research arc's ceiling: no frame-level model, however well chosen, may
ever fully solve this by construction. Documented as an architectural finding; not implemented.

## Revisiting the product goal

The editor does not strictly need perfect atomic first_dance classification per frame — it needs
story-critical event *coverage*. A strategic alternative not implemented here: Qwen proposes
candidate episodes, a sequence-level redundancy/confidence/coverage layer reasons over multiple
candidate frames from the same episode, with conservative fallback for ambiguous cases, instead
of demanding one frame-level verifier be perfect. Documented as a strategic option only.

## False positive vs. false negative cost

A harmful false positive (ordinary/solo shot mislabeled `first_dance`) risks inserting a wrong
moment into a precision-first automated cut. A false negative (a real first-dance candidate
abstained) risks silently dropping a likely-unique story beat — first dances typically happen
once per wedding, so there may be no redundant candidate to fall back on. This asymmetry is
exactly why "abstain everything for safety" is not a real solution — it trades one failure mode
for a more silent, harder-to-detect one. No resolution attempted here; stated as the tension any
future architecture must hold.

## P5.5 practical ceiling analysis

P5.5's single targeted prompt: caught the one known harmful case in its own small test, 0 harmful
accepts observed there, but cost one genuine positive and was shown phrasing-sensitive by a
follow-up check. **Not production-safe** — explicitly not claimed as such anywhere in this
research arc. As a **shadow-only reference heuristic** while further research is paused, it is
better than the plain allowlist (P5.4's D0, which had a confirmed harmful accept) on the tiny
sample tested, and costs nothing to keep dormant. **Recommendation: retain as shadow reference,
not deploy, not deprecate.**

## Research ROI (qualitative only, no fabricated numbers)

| Route | Research cost | Expected info gain | Deployment complexity | Likelihood of solving C7349 |
|---|---|---|---|---|
| Limb-level interaction (reuse cached KeypointRCNN output) | LOW | MEDIUM | LOW | UNKNOWN — plausible but real occlusion/perspective/drone-resolution risk |
| Temporal pair coordination/persistence | MEDIUM-HIGH | MEDIUM | MEDIUM-HIGH | UNKNOWN — may help solo-vs-pair, explicitly may NOT help ordinary-vs-first dance |
| Mature HOI/relationship model | HIGH (immature ecosystem) | HIGH (in principle) | HIGH | PROMISING in principle, UNKNOWN in practice — no small candidate exists yet |
| Custom labeled verifier/data | HIGH | HIGH | HIGH | PROMISING but requires investment this package cannot estimate away |
| Pause research (freeze) | none | n/a | n/a | n/a |

## Limb-level interaction — honest audit

Tempting precisely because it's the one feature (F6) P5.11 deliberately did not compute
post-hoc. Would wrist/arm proximity to a partner's body distinguish C7349 from C7261 generically?
Plausible, not evidenced. Real risks: occlusion, partial/cropped limbs (exactly C7261's known
issue), dance-gesture variability, crowd contact in group scenes, and drone-scale resolution
limits already observed to degrade keypoint confidence. Not recommended by default just because
it is the one untested feature — that reasoning alone is not evidence.

## Temporal coordination — honest audit

Potentially more semantically relevant than a single static frame: a real pair's relative
geometry should persist across a short window, while an incidental bystander's apparent pairing
with a performer should not. But ordinary couple dancing *also* persists over time — temporal
persistence could plausibly help separate solo-performer-plus-bystander from any interacting
pair, but has no obvious mechanism to separate an interacting ordinary-dance pair from a
first-dance pair. This limitation is stated explicitly, not glossed over.

## HOI / relationship models

Theoretically the most directly-matched task class (P5.10's own conclusion) — but practically
immature: 2026 research literature shows mostly large-foundation-backbone approaches, no mature
small permissively-licensed off-the-shelf candidate identified. Parked, not pursued.

## Custom labeled verifier / user data

The only route that could, in principle, actually learn this user's specific event semantics
rather than relying on generic pretrained representations that have now been shown, across five
independent signal families, not to carry the needed distinction. Real costs: data collection,
labeling discipline, leakage control (exactly what this whole research arc has practiced), scale,
and long-term maintenance. Not started; flagged as the most likely correct long-term route if
Strategy B's bounded experiment also fails.

## Decision matrix

| Route | Genuinely new signal? | Evidence already available? | Info gain | Eng. cost | Deploy complexity | Known-risk coverage | Recommendation |
|---|---|---|---|---|---|---|---|
| P5.5 shadow heuristic | No (already tested) | Yes | n/a | none (already built) | n/a (shadow only) | Partial (small N) | **Retain, shadow only** |
| Limb-level interaction | Yes (untested) | Partial (recall infra exists) | Medium | Low | Low | Unknown | Candidate for Strategy B, IF pursued |
| Temporal pair coordination | Yes (untested) | No | Medium | Medium-High | Medium-High | Unknown, partial by design (won't solve ordinary-dance) | Weaker Strategy B candidate |
| HOI/relationship model | Yes | No (immature ecosystem) | High (theoretical) | High | High | Unknown | Not practical now |
| Episode-level verifier | N/A (architecture) | No | Unknown | Medium | Medium | Unknown | Strategic, not a Strategy B model test |
| Custom labeled verifier | Yes (learns user data) | No | High (theoretical) | High | High | Unknown | Long-term Strategy C candidate |
| Pause research | — | — | — | — | — | — | **Selected — see below** |

## Held-out requirement for any future feature work

P5.11 already exposed both C7349 and C7261 in the course of falsifying box/pose geometry. Any
future geometric feature (e.g. limb-level proximity) invented with knowledge of these two cases'
outcomes is hindsight-contaminated. **Requirement, binding on any future package that revisits
this space:** C7349/C7261 may remain regression cases, but a claimed success must also be
validated on fresh held-out cases that were not used to design the feature — exactly the
discipline this research arc has followed throughout (P5.6's pre-registered prompts, P5.8/9's
frozen threshold grids, P5.11's frozen feature set).

## Data adequacy

The hard-case corpus this entire arc has used is small: a handful of confirmed genuine positives,
one confirmed harmful supported-category false positive (N=1). No route tested here — including
the ones classified CLOSED — can support a robust production-precision estimate from this corpus
alone. This is itself part of the case for a custom-data route eventually, and a reason no
strategy in this report claims statistical confidence beyond what N actually supports.

## Current production blockers (independent of this research)

1. **Verifier trust**: no independent signal robustly distinguishes C7349-class hallucination
   from genuine supported events (this package's core finding).
2. **Router cost**: R4b's real escalation rate is ~28-34% of shots (P5.4) — far from the
   "selective" tier originally targeted; unresolved regardless of verifier outcome.
3. **Corpus size**: the evaluation corpus is too small to make a statistical safety claim even if
   a verifier were found — a separate, later blocker from either of the above.

## Strategy decision

**STRATEGY A — Freeze verifier research. Keep P5.5 as shadow-only reference. Return to other
editor subsystems.**

**Why:** Five independent signal families (same-model voting, face count, two object detectors,
single-frame pose geometry) have now been tested with real inference against a consistent,
disciplined, pre-registered evaluation methodology, and every one has been closed or falsified —
not on recall or accuracy grounds, but because none of them structurally represents the
information layer (L2 relationship / L3 action-in-context) the problem actually requires. The
two remaining candidates with genuinely new information (limb-level interaction, temporal
coordination) are both honestly audited above as uncertain, with real, specific failure risks
identified in advance — neither clears the bar of "clear test, bounded cost, likely to produce a
useful architectural decision either way" strongly enough to justify Strategy B over pausing,
especially against a corpus too small to make the resulting claim statistically meaningful even
if the test succeeded. HOI and custom-data routes are both real long-term options but neither is
"one bounded next experiment" — they are their own multi-package investments. Strategy A is not
"give up" — it is a disciplined stop after real, cumulative, well-documented negative evidence,
with the door explicitly left open (Section 25's held-out requirement, Section 21's custom-data
scoping) rather than closed.

## Held-out requirement (restated for any future resumption)

Binding on P5.13+ if verifier research is ever resumed: any new geometric or learned feature must
be pre-registered before inspecting results, and validated on cases beyond C7349/C7261, which are
now contaminated reference points for feature design (though they remain valid regression tests).

## Production decision

**READY FOR PRODUCTION INTEGRATION: NO.**
1. A harmful supported-event false positive is proven, not hypothetical.
2. No independent verifier route tested has robustly solved it.
3. The evaluation corpus is too small to support a safety claim even where results looked
   favorable.
4. Router selectivity (R4b, ~28-34%) remains a separate, unresolved cost/precision problem.

This is not softened by Strategy A's pause — pausing research does not change the current
evidence, it only stops spending further effort chasing a signal class unlikely to close the gap.

## Router status (kept separate, not resolved by this package)

R4b remains a shadow candidate only. Real escalation ~28-34% of R4b-selected shots — well above
the originally hoped-for selective tier. This is an independent, still-open production blocker,
not something verifier research addresses.

## Source Moment / planner separation

This consolidation concerns semantic event trust for a deep verifier only. Source Moment, music
timing, planner/event coverage logic, and timeline generation are separate subsystems, untouched
by and unrelated to this finding, and not conflated with it anywhere in this report.

## Proven
- Five independently-architected signal families, tested with real inference under a consistent
  pre-registration discipline, all fail to solve the C7349-class hallucination problem — a broad,
  reproducible negative result, not a single failed experiment.
- The failure mode is consistent across families: every tested signal operates at the
  physical-presence layer (L1) or weakly/inconsistently at L2; none reaches the
  relationship-in-context layer the problem needs.
- Qwen's underlying semantic value (finding real episodes) is real and separate from its safety
  limitation — both are established facts, not assumptions.

## Not proven
- That limb-level interaction or temporal coordination would fail if actually tested — both
  remain genuinely open, honestly audited, not ruled out, simply not prioritized under a bounded
  research budget with a small corpus.
- That HOI models are truly unusable — only that no mature small candidate was identified in this
  audit's timeframe.
- Any quantitative production-precision estimate — the corpus is too small to support one.

## Safety
```
PRODUCTION CHANGED: NO
DB CHANGED: NO (362 assets / 2638 shots / Elenora 345 unchanged)
REANALYZED: NO
RESOLVE: unchanged
TIMELINE: 129 items unchanged
SOURCE MOMENT: unchanged (hashes identical)
ROUTER: frozen R4b, unchanged
NEW MODEL DOWNLOADED: NO
NEW PACKAGE INSTALLED: NO
TRAINING: NO
CONTAMINATION: 0
```
SSDLite, Faster R-CNN, and KeypointRCNN weights from P5.8/P5.9/P5.11 remain locally cached,
untouched, not re-benchmarked this package.

## Tests
No code added — pure documentation consolidation. Full suite re-run for safety confirmation
(expected unchanged from P5.11's 963/963).
