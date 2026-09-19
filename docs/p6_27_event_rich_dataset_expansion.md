# PACKAGE 06.27 — EVENT-RICH WEDDING DATASET EXPANSION

START HEAD: `daaf222`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Tried to build ≥8 independent weddings with CONFIRMED FIRST_DANCE and CAKE_ACTION episodes from external
final wedding films, before any model comparison. A thorough temporal re-audit of all 18 finals (broader
candidate recall) plus a reconnaissance of the one accessible real documentary wedding (Elenora Mustafa,
raw) shows the accessible archive cannot reach the gate. No model was trained. Shadow-only;
`build_timeline` untouched (0-line diff); no DB/Resolve/timeline write. Code reused:
`tools/refbrain/temporal_audit.py`; fixtures: `tools/fixtures/p6_27_{coverage.json,temporal_audit_v3.jsonl}`;
tests: `tests/test_p6_27_dataset_expansion.py`.

--------------------------------
## ARCHIVE INVENTORY (bounded search — no home-dir crawl)
--------------------------------

external wedding finals found: **18** — the supplied cinematic reference highlight films
(`data/references/media`). These are the "~20 wedding videos" already in hand; they are couple/party
CINEMATIC edits, structurally light on documentary first-dance and cake-cutting.
raw-only weddings found: **1** — `ELENORA MUSTAFA` (`/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/
CLIP/`, 345 raw MP4 clips, no final edit). Reconnaissance (68-frame sample across the wedding) confirms a
real Turkish wedding with genuine reception dancing (couple + halay/crowd) and prep — usable, but raw and
singular.
client wedding finals accessible: **0** — no documentary client-wedding final films are present in any
project path.
15A excluded: **YES** (V7 / is edit / 15 Ağustos never audited for training).

--------------------------------
## ANNOTATION DATASET
--------------------------------

total weddings audited in motion: 18 finals (+ Elenora reconnaissance). total temporally-verified event
records (P6.26 + P6.27): 22. Every FINAL_EDIT verdict carries `temporal_verified: true` + evidence; the
Elenora entry is flagged RAW/CANDIDATE (needs span annotation). 15A training examples: **0**.

--------------------------------
## FIRST_DANCE (thorough temporal audit of all 18 finals)
--------------------------------

confirmed weddings: **0** — no unambiguous isolated reception first-dance in any cinematic final.
probable weddings: **9** (VHpqYteMbTg, b-Rqq_B2nKY, 50edMEI-3Fw, 1117083593, 1074649838, 1180464792,
U8MbInvJ9xs, tYSML45z5HM, 1050693600) — ALL ambiguous vs couple portrait / slow embrace / styled twirl,
and therefore **unsafe as precision-first positives**.
confirmed episodes: 0.
confusable negatives captured: couple portrait, styled twirl, couple walk, couple embrace, generic
couple dance, party dance, crowd dance (rejected regions: MgWLLzMnHR8 garden twirl, Fbq4SM sparkler
entrance, QYfupWEw urban walk, p1vkOMWvN7U cliff elopement).

--------------------------------
## CAKE_ACTION
--------------------------------

confirmed weddings: **1** (MgWLLzMnHR8 — gloved hand cutting a tart, couple serving + toast).
probable action weddings: **4** (1143362002, b-Rqq_B2nKY, tYSML45z5HM, 50edMEI-3Fw — couple at cake /
small-cake interaction / sparkler presentation).
setup-only weddings: **3** (1151600045, 1117083593, 1199148509 — tiered cake or dessert table, no
cutting). confirmed episodes: 1.
negatives: cake detail, cake table setup, couple near cake, sparkler-near-cake — all present as
confusables.

--------------------------------
## OTHER EVENTS (from the audits, not the blockers)
--------------------------------

PARTY: abundant (≥9 weddings) — reliably supervised (P6.25 P 0.88 / R 0.96). BOUQUET: 2 (1050693600,
U8MbInvJ9xs). ENTRANCE: 2 (50edMEI-3Fw, _sjJtpPP36E). CEREMONY: ~5. PREPARATION: ~3. KINA: only genuinely
present in Elenora (a Turkish wedding) — absent from the cinematic finals.

--------------------------------
## SPLITS
--------------------------------

Not formed. Grouped train/validation/held-out splits require ≥ the gate's worth of confirmed positive
weddings; with 0 confirmed FIRST_DANCE and 1 confirmed CAKE_ACTION there is nothing to split without
same-wedding leakage. group leakage: N/A (no split built).

--------------------------------
## COVERAGE GATE
--------------------------------

threshold: ≥ 8 independent CONFIRMED positive weddings per acceptance event.
FIRST_DANCE ≥ 8: **FAIL** — max achievable ≈ 1 (0 from 18 finals + up to 1 from Elenora once annotated).
CAKE_ACTION ≥ 8: **FAIL** — max achievable ≈ 2 (1 confirmed + up to 1 from Elenora).
The gate was **not weakened**; the exact maximum available is reported.

--------------------------------
## DATA QUALITY AUDIT
--------------------------------

The 9 "probable" first-dances were each viewed as a dense temporal strip. Every one is a couple-focused
romantic shot (embrace / sway / veil flourish / lift) that a human cannot separate from a first dance
without external context (an announcement, a cleared floor, watching guests) — exactly the confusion the
package warns against. Labelling any as CONFIRMED would inject portrait-like "first dances" and corrupt
the reference grammar, so they stay PROBABLE. This is a data-provenance limit of cinematic edits, not an
annotation error.

--------------------------------
## PUBLIC DATA
--------------------------------

used: **NO.** Not reached — the blocker is *documentary wedding* coverage, and public action clips
(Kinetics "cutting cake", USAA "wedding dance") are generic action, not first-dance and not editorial
evidence; they remain a possible perception-only supplement for a later step, pending a licence/size
audit not performed here.

--------------------------------
## 15A
--------------------------------

training usage: **0** · validation usage: **0** · V7 used: **NO** · model trained: **NO**.

--------------------------------
## NOT YET STARTED
--------------------------------

static-vs-temporal representation comparison: **NOT STARTED** (gated on sufficient labels). Stage-1
integration: NOT STARTED. Stage-2 integration: NOT STARTED.

--------------------------------
## STILL OPEN (carried forward)
--------------------------------

camera stability (shaky shots): open. source-moment / action-start ranking: open.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0. timeline changes: 0. build_timeline:
0-line diff. Strips / Elenora frames under gitignored `data/` and scratch (deleted after review); only
code + small fixtures + tests + docs committed (no media/frames). TESTS: full suite **1188 passed**, ruff
clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**E — the available local archive does not expose enough event-rich external weddings; the user must
provide / point to additional wedding finals.** A thorough temporal audit (correcting the earlier
recall) confirms the 18 cinematic reference films yield **0 confirmed** first-dances and **1 confirmed**
cake-action, and the only accessible real documentary wedding (Elenora) is raw and singular. Maximum
achievable coverage is ≈ 1 first-dance and ≈ 2 cake-action weddings — far below the ≥ 8 gate — so the
math the user flagged is decisive: adding one or two weddings cannot establish grouped cross-wedding
validation. The "~20 wedding videos in hand" are the cinematic *reference* films, which are
event-sparse; the user's real **client documentary weddings** (with clear first-dance, kına and
cake-cutting) are not in any accessible project path.

EXACT ADDITIONAL COVERAGE REQUIRED: a path to (or copies of) **≥ 8–10 independent documentary wedding
final films** (ideally the user's own 7Film client weddings — traditional Turkish weddings that contain
a clear reception first-dance, kına and cake-cutting), so ≥ 8 confirmed positive weddings per acceptance
event can be span-annotated with confusable negatives, split by wedding, with ≥ 2 reserved as an
external held-out perception test.

NEXT STEP — **ONE milestone (do not start):** **the user points me to the client-wedding-finals archive
directory** (a bounded, project-associated path). Then P6.28 span-annotates FIRST_DANCE and CAKE_ACTION
across those documentary finals (+ Elenora), temporally verified, split by wedding — targeting ≥ 8
confirmed positive weddings each. Only once the coverage gate passes does P6.29 run the controlled
static-vs-temporal-CLIP-vs-small-video-encoder representation comparison on a common grouped
train/val/held-out set, with 15A/V7 final-test-only. No model training, no representation change, and no
Stage-2 until the gate passes.

**DO NOT START IT.**
