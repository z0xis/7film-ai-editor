# PACKAGE 06.24 — FINE WEDDING EVENT UNDERSTANDING

START HEAD: `43a25b4`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Built a fine wedding-EVENT detector for the 18 render-only references — multi-frame per shot + CLIP
prompt ensembles (positive minus confusable negatives) + temporal smoothing + a soft story-position
prior — and validated it visually. Result is a decisive, honest **negative**: zero-shot CLIP cannot
reliably tell fine wedding events apart. Shadow-only; `build_timeline` untouched (0-line diff); no
DB/Resolve/timeline write. Code: `tools/refbrain/event_detect.py`; detection (gitignored):
`data/reference_editor/tier2_events/`; fixture: `tools/fixtures/p6_24_event_detection.json`; tests:
`tests/test_p6_24_fine_events.py`.

--------------------------------
## EVENT TAXONOMY
--------------------------------

classes: PREPARATION, ENTRANCE, CEREMONY, RING, KISS, CAKE, FIRST_DANCE, BOUQUET, PARTY, KINA,
SPARKLER_SENDOFF, plus UNKNOWN. phases (designed, not reached — see result): CAKE {setup/cutting/
reaction}, FIRST_DANCE {establish/couple-isolated/progression/guests-join}, BOUQUET {setup/throw/
reaction}, ENTRANCE {prep/entry/reaction}. EVENT is kept distinct from CATEGORY (a COUPLE category shot
can belong to prep/ceremony/first-dance/cake/bouquet/party).

--------------------------------
## METHOD
--------------------------------

frames per shot: **3** (early/mid/late, deterministic). CLIP prompts: per-event **ensembles** —
positive prompts minus **confusable negatives** (e.g. FIRST_DANCE positive "newlywed couple performing
their first dance alone" minus "a crowd of guests dancing"). temporal context: 3-shot neighbour
smoothing (0.6/0.2/0.2). motion / scale: carried from P6.23. story-position prior: a soft Gaussian per
event, added with a small weight and recorded separately (a prior, never a hard label). audio/SFX
support: available but not required (most references have no SFX). No new model was trained (§17).

--------------------------------
## TIER-2 EVENT ENRICHMENT
--------------------------------

references: 18 · shots: 1062 scored · model: clip-vit-base-patch32 (deterministic).
event counts (argmax): CEREMONY 390 · BOUQUET 214 · SPARKLER_SENDOFF 155 · RING 105 · PARTY 54 ·
FIRST_DANCE 53 · KISS 42 · UNKNOWN 35 · PREPARATION 6 · ENTRANCE 5 · KINA 3 · **CAKE 0**.
confidence: LOW 971 · MEDIUM 56 · UNKNOWN 35 · **HIGH 0**.

The distribution is already implausible: these references are visibly couple-portrait- and party-heavy,
yet the detector labels 37% CEREMONY and hardly any PREPARATION, and never once picks CAKE.

--------------------------------
## VISUAL VALIDATION (stratified, multiple references)
--------------------------------

precision on the sampled predictions: **0.0** (0 of 13 correct).

| predicted | what the frame actually shows |
|---|---|
| CAKE | (never predicted anywhere — 0 shots) |
| FIRST_DANCE ×4 | couple **portraits** (indoors / hallway / garden / with bouquet) — not dancing |
| BOUQUET ×2 | a crowd lifting a person; a blurry night dance crowd |
| CEREMONY ×2 | a woman standing in the ocean at sunset; an empty beach at sunset |
| SPARKLER_SENDOFF ×2 | night party, hands raised; night party under red light |
| RING ×2 | groom adjusting a **cufflink**; groom adjusting a **watch** (prep detail) |
| PARTY ×1 | empty decorated reception tables (a venue/detail shot) |

--------------------------------
## CONFUSIONS
--------------------------------

first dance vs party: **unreliable** — FIRST_DANCE fires on any couple-together shot, including static
portraits; it does NOT isolate a real first dance. cake vs cake-detail/setup: **cannot even detect
cake** (0 argmax). entrance vs walking: ENTRANCE barely fires (5). bouquet vs bride: BOUQUET over-fires
on crowds/lifts. kina vs party: KINA barely fires (3). ceremony vs static/scenery: CEREMONY over-fires
massively, including on beach/ocean/sunset scenery. Net: no fine-event distinction is reliable.

--------------------------------
## CORPUS V3 / RETRIEVAL V3
--------------------------------

**Deliberately NOT built on these labels.** Promoting a detector with 0.0 sampled precision and a
wrong learned arc into the retrieval/planning corpus would inject false structure — the exact "research
theater" failure the packages warn against. The detection is stored as evidence
(`data/reference_editor/tier2_events/`, gitignored) and summarised in the fixture, tagged unreliable.
The reliable P6.23 coarse-semantic corpus remains the working corpus.

--------------------------------
## 15A HOLDOUT / ABLATION
--------------------------------

V7 excluded: YES · is edit excluded: YES. The fine-event **learned arc** (dominant argmax event per
story-position bin, over the 18 refs) is:
`[CEREMONY, CEREMONY, CEREMONY, CEREMONY, BOUQUET, BOUQUET, SPARKLER_SENDOFF, SPARKLER_SENDOFF]`.
Versus the reliable P6.23 coarse arc `[COUPLE×5, PARTY_KINA×3]` and V7's own bride/prep-heavy arc.

does fine event evidence materially change structure?: **YES, but toward WRONG labels.** The fine-event
arc differs from the coarse arc, but it is built on 0.0-precision detections (ceremony/bouquet/sparkler
over-firing), so the change is a degradation, not an improvement. Post-hoc V7 agreement does not
improve — CAKE and FIRST_DANCE, the two events that matter for V7, are exactly the ones the detector
misses.

--------------------------------
## FIRST DANCE ACCEPTANCE
--------------------------------

real first-dance distinction: **FAIL.** generic crowd dance rejected/disambiguated: **NO.** Evidence:
the four highest-scoring FIRST_DANCE predictions are all couple portraits (not dancing at all); scores
are ~0.07 (noise-level). The detector keys on "couple together," not on dancing, so it cannot separate
a real first dance from a portrait or from crowd dancing.

--------------------------------
## CAKE ACCEPTANCE
--------------------------------

setup: not detected. action: not detected. episode: none. V7 post-hoc positive control: V7 **verifiably
contains cake** (C7309, with cutting action), yet CAKE is never the argmax event in any of the 1062
scored reference shots. Verdict: **SEMANTIC_EXTRACTION_MISS** (confirmed, now even with a dedicated
multi-frame event detector), not "no cake."

--------------------------------
## POST-HOC V7
--------------------------------

event coverage: not improved. event-order agreement: not improved. intro / reception / outro: unchanged
from P6.23. cake: missed. first dance: missed. music transition role: correctly represented since P6.23
(2 songs, crossfade, entrance SFX) — that part stands.

--------------------------------
## NOT YET SOLVED (carried forward)
--------------------------------

camera stability (shaky shots) — open. source-moment boundaries (cut-in before the action) — open.
Stage-2 integration — not started. Fine-event perception — the blocker this package set out to remove,
now proven to need a stronger approach than zero-shot CLIP.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0 (timeline count still 12).
timeline changes: 0. build_timeline: 0-line diff. Detection under gitignored `data/`; only code + one
small fixture + tests + docs committed (no media/frames). Temporary validation frames deleted. TESTS:
full suite **1169 passed**, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**C — CLIP + temporal context is insufficient for fine wedding events.** Multi-frame sampling, prompt
ensembles with confusable negatives, temporal smoothing and a position prior together still give 0.0
sampled precision, 0 cake detections, first-dance/portrait confusion, and 91% LOW / 0% HIGH confidence.
The failure is proven with visual evidence (as §17 required before escalating), so we do not integrate
these labels. The reliable layer remains P6.23's coarse category arc + fixed music fidelity.

NEXT STEP — **ONE bounded perception milestone (do not start):** replace zero-shot prompting with a
**small supervised event probe**: hand-label a few hundred shots (across the 18 refs + V7/is-edit, with
V7 still held out of any 15A evaluation) for the fine events, then train a lightweight **linear/kNN
probe on the existing CLIP image features over short multi-shot windows** (still no large VLM). Validate
it against the same held-out visual sample and re-run this exact holdout/ablation. Only if the probe
reaches usable precision on CAKE and FIRST_DANCE (the acceptance events) does fine-event structure enter
Stage-1; Stage-2 integration remains after that.

**DO NOT START IT.**
