# Package 06.31 — Upstream Shot / Source Selection Disagreement Audit

## Result

The dominant 15A failure is not source-in refinement and is not a broad candidate
eligibility failure. It is high-level story/sequence intent, with secondary
sequence-state, local-ranking, and quality-gate effects. A read-only Elenora
counterfactual reproduces the upstream source-selection divergence and shows that
nearly every human-selected moment survives the production eligibility gates.

No selector, ranker, weight, planner behavior, or timeline was changed.

## 15A reference pipeline

The three evidence layers remain separate: 362 analysed assets, 187 canonical
`is edit` selects, and 87 canonical V7 primary-track items. All 87 V7 ranges overlap
an `is edit` range. V7 therefore follows the human pipeline raw → selects → final.

P6.20 behaves differently:

| P6.20 relation to `is edit` | Items |
|---|---:|
| Exact/overlapping curated moment | 12 |
| Same source, different moment | 62 |
| Source outside curated pool | 58 |
| Unknown | 0 |

Outside-select P6.20 shots have lower median technical quality (0.3505) than
overlapping curated choices (0.417), but the distributions overlap. Quality is a
secondary filter signal, not a complete preference model.

The canonical P6.20/V7 classes remain A=5, B=41, C=81, D=5. Class C separates
cleanly into 58 P6 sources outside `is edit` and 23 curated sources that V7 did not
use. These are disagreements, not automatically errors.

## Eligibility and exact score replay

Twelve cases were selected by editorial section and disagreement class, never by
item index. Every human alternative existed in the analysed pool. One failed the
production quality gate, seven were usable but removed by contextual/story
narrowing before scoring, and four reached the exact frozen `_score_candidate`.

All four scored alternatives lost. The repeated winning terms were aesthetic score,
story relevance, and reuse/duplicate state; technical quality and chronology were
less frequent. The clearest failure was reception: `C7388.MP4` beat the human
`C7310.MP4` interaction by 0.9602 because the human option paid duplicate/reuse
penalties and received weaker current story relevance. This is a locally consistent
score producing a poorer sequence decision.

## Temporal visual audit

The audit reviewed five-frame strips on both sides for eight section-stratified
outside-select comparisons and four same-source/different-region controls.

| Verdict | Count |
|---|---:|
| Human clearly better | 3 |
| P6.20 clearly better | 0 |
| Both valid | 6 |
| Different editorial intent | 3 |
| Inconclusive | 0 |

Only 3/12 are defensible wrong-source cases. The sample explicitly rejects the
equation “different source = error.” The intro choices are often individually valid
but do not construct the human opening progression. Reception over-selects generic
energy without equivalent interaction/progression. The outro lacks a first-class
resolution role and closes on overhead dance coverage instead of the human night
pull-out.

Class B is genuinely different-region evidence: 41 material cases, zero nearby or
overlapping controls under the half-second boundary.

## Elenora Tier-1 verification

Resolve 21.1.0.14 exposed project `EM WD` and exact timeline `Elenora Mustafa
Wedding Day`, separate from `TEST - Music First V1` and from the SQLite `REVIZE`
outputs. The user-provided provenance identifies it as the human final. It maps to
the authorised Desktop Elenora raw tree.

- Timeline: 50 fps, 177.08 seconds
- Source-linked video items: 167
- Audio items: 122 + 3
- Canonical Resolve coordinates: 167/167
- OTIO cross-check: 167/167
- Bounds/duration failures: 0/0
- Raw assets: 345
- Human-used assets: 115; unused: 230
- Reused assets: 31; 52 additional uses
- Consecutive reuse: 40 forward, 12 backward, 0 overlap

All 167 human moments map to analysed shots. 164 meet the half-second duration
guard and 166/167 pass the production quality gate. Eligibility is therefore not a
plausible dominant cross-project blocker.

The read-only current-planner counterfactual produced 116 items from 101 assets.
Only 49 assets overlap the 115 human-used assets; 52 planner assets are outside the
human final and 66 human-used assets are absent from the counterfactual. This does
not prove every human choice is superior, but it independently reproduces the
upstream selection divergence despite near-complete human-shot eligibility.

## Architectural conclusion

- Candidate eligibility: not material as the main cause.
- High-level story/sequence intent: main.
- Local ranking: secondary.
- Reuse/novelty state: secondary.
- Quality filtering: secondary.

The next bounded milestone should be **reference-conditioned Stage-1 → existing
shot-selection shadow integration**. It should pass explicit editorial roles and
sequence state into the unchanged selector and measure whether the human-eligible
pool is used more coherently. It must remain shadow-only; no production timeline is
recommended yet.

## Safety

Resolve capture and FCPXML/OTIO export only serialized read-only metadata to ignored
`work/` artifacts. SQLite access was read-only; planner counterfactuals ran in memory
with no persistence. V7, `is edit`, Elenora, P6.20, `build_timeline`, weights, and
P6.28 production state were untouched. The unrelated long-form archive was not
accessed.
