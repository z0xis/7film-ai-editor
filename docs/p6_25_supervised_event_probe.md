# PACKAGE 06.25 — SUPERVISED WEDDING EVENT PROBE

START HEAD: `0f5dd68`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Built a small supervised temporal event probe trained ONLY on external references (V7 / is edit strictly
test-only, never seen in training/label/threshold/feature fitting), to test whether the CLIP features
carry fine wedding-event signal once supervised. Answer: the pipeline works and features ARE
discriminative given labels (PARTY), but the external reference set does not contain enough labelled
CAKE — and no isolable FIRST_DANCE — evidence to reach acceptance. Shadow-only; `build_timeline`
untouched (0-line diff); no DB/Resolve/timeline write. Code: `tools/refbrain/{probe_features,event_probe,
v7_control}.py`; features/thumbs (gitignored): `data/reference_editor/probe/`; committed fixtures:
`tools/fixtures/p6_25_{event_annotations.jsonl,probe_results.json,v7_control.json}`; tests:
`tests/test_p6_25_event_probe.py`.

--------------------------------
## ANNOTATION DATASET
--------------------------------

external references annotated: 18 (visual contact-sheet inspection of one thumbnail per shot). episodes:
32 labelled spans → 222 labelled shots. 15A labels used in training: **0** (guarded by test).

per-event labelled shots (weddings): PARTY 109 (9) · COUPLE_PORTRAIT 37 (4) · CEREMONY 26 (5) ·
PREPARATION 18 (3) · **CAKE 8 (5)** · OTHER 16 (2) · BOUQUET 4 (2) · ENTRANCE 4 (2) ·
**FIRST_DANCE 0 (0)**.

Data-sufficiency audit: the 18 references are cinematic destination / elopement / couple-portrait films.
PARTY is abundant; CAKE is rare (5 weddings, 8 shots — several are the cinematic tiered-cake or
cake-cutting moment); **FIRST_DANCE could not be reliably isolated in any external reference** (couple
dancing is indistinguishable from couple portrait or crowd dance in these edits) — so it has zero
positive labels.

--------------------------------
## SPLIT
--------------------------------

train / validation weddings: grouped **leave-one-wedding-out** (the same wedding never appears in both).
group leakage: NO (grouped by reference id). This prevents appearance/couple/venue leakage from a
random shot split.

--------------------------------
## FEATURES
--------------------------------

Per shot, temporal: mean CLIP embedding (3 frames) + 0.5·prev-shot mean + 0.5·next-shot mean +
(late−early) intra-shot delta + shot-scale one-hot + motion band + story position. Reuses P6.23/P6.24
features; no new model trained.

--------------------------------
## MODELS TESTED
--------------------------------

linear: logistic regression (balanced). kNN: k=5. MLP: not needed. selected: linear (reported).

--------------------------------
## EXTERNAL VALIDATION (grouped leave-one-wedding-out, linear)
--------------------------------

| event | precision | recall | F1 | support |
|---|---|---|---|---|
| PARTY | **0.88** | **0.96** | 0.92 | 109 |
| PREPARATION | 0.38 | 0.67 | 0.48 | 18 |
| CEREMONY | 0.42 | 0.50 | 0.46 | 26 |
| COUPLE_PORTRAIT | 0.37 | 0.30 | 0.33 | 37 |
| CAKE | 0.67 | 0.25 | 0.36 | 8 |
| BOUQUET | 0.00 | 0.00 | 0.00 | 4 |
| ENTRANCE | 0.00 | 0.00 | 0.00 | 4 |
| OTHER | 0.00 | 0.00 | 0.00 | 16 |

Decisive positive: **PARTY reaches P 0.88 / R 0.96** under grouped LOWO — so, unlike zero-shot P6.24
(0.0 precision), the CLIP features DO carry the signal when supervised. The failure in P6.24 was the
zero-shot prompting, not the representation.

--------------------------------
## FIRST DANCE
--------------------------------

portrait confusion / crowd-dance confusion: **not evaluable** — there are **0 labelled FIRST_DANCE
positives** in the external references (they contain no isolable first-dance episode). precision /
recall: n/a. INSUFFICIENT_LABELLED_EVIDENCE.

--------------------------------
## CAKE
--------------------------------

static-cake vs action: not separable at this support. actual cake precision 0.67, recall 0.25 (8 shots
across 5 weddings). CAKE is predicted as PARTY 4×, CAKE 2×, CEREMONY 1×, COUPLE_PORTRAIT 1× — i.e. cake
is confused with the party/sparkler context it appears in. Below the promotion gate.

--------------------------------
## ABSTENTION
--------------------------------

threshold: not tuned — with CAKE/FIRST_DANCE below/without evidence there is nothing to promote, so a
confidence threshold would be premature. The probe abstains (UNKNOWN) in folds where a class has no
training support.

--------------------------------
## V7 TEST-ONLY POSITIVE CONTROL
--------------------------------

model frozen before V7 test: YES. V7 used in training: NO. cake: V7's verified cake shot (C7309,
shot 51) is predicted **COUPLE_PORTRAIT** (cake probability 0.057) — **MISS**; 0 V7 shots predicted CAKE.
first dance: not testable (no FIRST_DANCE class). generic dance confusion: n/a. Note the positive
transfer: the frozen probe labels **20 V7 reception shots as PARTY**, confirming the supervised signal
generalises where evidence exists — just not for cake.

--------------------------------
## CORPUS PROMOTION
--------------------------------

**FAIL.** reason: CAKE precision 0.67 (< 0.80) with recall 0.25 and a V7 positive-control miss;
FIRST_DANCE has no labelled evidence at all. Per the precision-first gate, event predictions are NOT
promoted into the working corpus, and no Corpus V4 / Stage-1 shadow was built. The P6.23 coarse corpus
remains the working layer.

--------------------------------
## STAGE-1 SHADOW
--------------------------------

Not run (gated on promotion PASS, which did not occur).

--------------------------------
## NOT YET SOLVED (carried forward)
--------------------------------

camera stability (shaky shots): open. source-moment boundaries (cut-in before the action): open.
Stage-2 integration: not started. Fine-event acceptance (CAKE, FIRST_DANCE): blocked on labelled
evidence.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0. timeline changes: 0. V7 / is edit:
read-only, never in training. build_timeline: 0-line diff. Features/thumbnails under gitignored `data/`;
only code + small label/result fixtures + tests + docs committed (no media/frames). TESTS: full suite
**1176 passed**, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**D — label quantity / coverage is insufficient to evaluate the acceptance events.** The methodology is
sound and the CLIP features are discriminative under grouped leave-one-wedding-out supervision (PARTY
P 0.88 / R 0.96, and PARTY transfers to V7) — which rules out "features insufficient" (not C). But the
18 external references contain only **8 CAKE shots across 5 weddings** (probe below the 0.80 gate and a
V7 cake-control miss) and **0 isolable FIRST_DANCE** examples, so the two mandatory acceptance events
cannot be trained or validated. This is an evidence gap, not a leakage or algorithm failure (not E, not
the leakage case).

WHAT ADDITIONAL ANNOTATIONS ARE REQUIRED: reference films that actually CONTAIN, clearly, (a) multiple
**cake-cutting** episodes and (b) multiple **isolated first-dance** episodes — the current cinematic
reference set is couple/party-dominated and largely lacks both. Concretely: ≥ ~8–10 weddings each with a
clear cake-cutting sequence and an isolated first-dance sequence, annotated at span level with confusable
negatives (couple portrait, crowd dance, cake-table setup).

NEXT STEP — **ONE milestone (do not start):** **acquire and annotate an event-rich reference set for the
two acceptance events.** Source additional human wedding edits (or full films) that visibly contain
cake-cutting and isolated first-dance, extend the span-annotation set (still external-only, V7/is edit
test-only), re-extract features, and re-run this exact grouped leave-one-wedding-out probe + V7 control.
Only if CAKE and FIRST_DANCE clear the precision-first gate does the event layer enter a shadow corpus;
Stage-2 integration remains after that.

**DO NOT START IT.**
