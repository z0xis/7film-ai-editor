# PACKAGE 06.26 — TEMPORAL GROUND-TRUTH AUDIT + EVENT-RICH EVIDENCE

START HEAD: `3839197`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Re-audited the 18 external references for FIRST_DANCE and CAKE **in motion** (dense temporal frame
strips, not contact-sheet stills) to establish real temporal ground truth before changing the model or
acquiring data. The contact-sheet limitation is confirmed, but with proper temporal evidence the two
acceptance events still lack cross-wedding support. Shadow-only; `build_timeline` untouched (0-line
diff); no DB/Resolve/timeline write. Code: `tools/refbrain/temporal_audit.py`; strips (gitignored):
`data/reference_editor/temporal_audit/`; fixtures: `tools/fixtures/p6_26_{temporal_audit.jsonl,
audit_summary.json}`; tests: `tests/test_p6_26_temporal_audit.py`.

--------------------------------
## P6.25 GROUND-TRUTH AUDIT
--------------------------------

contact-sheet limitation confirmed: **YES.** A single thumbnail cannot separate a couple portrait, a
styled couple twirl, a slow couple dance, a reception first dance and a crowd dance. P6.25's
"FIRST_DANCE = 0" was a thumbnail-audit artifact, not proof of absence — this package re-audited in
motion.

--------------------------------
## TEMPORAL RE-AUDIT — 18 REFERENCES
--------------------------------

method: for each candidate region (existing CAKE spans; reception couple-runs; and every reference's
party onset) a dense 8-frame strip across the time window was reviewed for motion/action.

FIRST_DANCE:
- confirmed weddings: **0** (no unambiguous isolated reception first-dance)
- probable weddings: **4** (VHpqYteMbTg B&W dip-dance in a dark room; b-Rqq_B2nKY couple under string
  lights; 50edMEI-3Fw couple dancing in a dim room before the balloon party; 1117083593 couple dancing
  amid clapping guests) — all AMBIGUOUS vs couple portrait / crowd
- rejected regions: **4** (MgWLLzMnHR8 daytime garden twirl = portrait; Fbq4SM_Qpgg sparkler
  walk-through = entrance; QYfupWEw_S4 urban couple walking = portrait; p1vkOMWvN7U cliff elopement =
  portrait)

CAKE:
- action (cutting/serving) confirmed weddings: **1** (MgWLLzMnHR8 — gloved hand cutting a fruit tart,
  then couple serving + toast)
- action probable weddings: **3** (1143362002, b-Rqq_B2nKY, tYSML45z5HM — couple at tiered cake with
  sparkler presentation / interaction)
- setup only: 1 (1151600045 — bride beside a tiered cake, little action)

BOUQUET / ENTRANCE: bouquet toss confirmed in 2 (1050693600, U8MbInvJ9xs); entrance (confetti / crowd
walk-in) in 2 (50edMEI-3Fw, _sjJtpPP36E) — noted from the earlier audit, not the acceptance blockers.

--------------------------------
## DATA SUFFICIENCY
--------------------------------

FIRST_DANCE: **INSUFFICIENT_CROSS_WEDDING_SUPPORT** — 0 confirmed, 4 probable (ambiguous). Fewer than
~5 independent confirmed positive weddings, and the probables carry a high portrait/crowd false-positive
risk, so a precision-first classifier cannot be trained or grouped-validated.
CAKE_ACTION: **INSUFFICIENT_CROSS_WEDDING_SUPPORT** — 1 confirmed + 3 probable = 4 weddings (< 5), with
cake-action entangled with the sparkler/party context it appears in.

--------------------------------
## ADDITIONAL EXTERNAL WEDDING EVIDENCE
--------------------------------

local archive searched: bounded — only project-configured paths and DB-registered media (no home-dir
crawl).
additional human weddings found: **YES** — `ELENORA MUSTAFA`, a separate non-15A real wedding, is
locally accessible (345 raw clips at `/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP/`, files
present; it backs both the DB "elenora" and "İS" projects).
ingested: **not yet** — it is **raw footage, not a final human edit**, so it carries no editorial
grammar and its events must be located and span-annotated before use. A traditional wedding of this kind
very likely contains a clear first dance and cake-cutting, making it the concrete next-step evidence
source.
path required?: **NO** (`EXTERNAL_WEDDING_ARCHIVE_PATH_REQUIRED` does not apply — a separate archive was
found).

--------------------------------
## PUBLIC SUPPLEMENT
--------------------------------

used?: **NO.** Not reached — local separate-wedding evidence (Elenora Mustafa) exists and should be
tried first, and no representation comparison was run (below). Kinetics-700 "cutting cake" / USAA
wedding actions remain a *possible* perception-only supplement for a later step (they must never be used
as editorial grammar), pending a licence/size audit — not performed here.

--------------------------------
## DATASET V2
--------------------------------

weddings audited: 18. temporally-verified event spans recorded: 13 (5 cake, 8 first-dance candidates),
each with `temporal_verified: true` + evidence + decision. positive windows for acceptance events:
first-dance 0 confirmed / 4 probable; cake-action 1 confirmed / 3 probable. confusable negatives
captured: 4 rejected first-dance regions (portrait/entrance/elopement). 15A training examples: **0**.

--------------------------------
## REPRESENTATIONS
--------------------------------

static CLIP / multi-frame CLIP / temporal video model: **not compared.** Per §13/§7 this comparison is
gated on having sufficient temporally-verified labels for the acceptance events; with 0 confirmed
first-dance and < 5 cake-action weddings, comparing static vs temporal representations would be
premature and uninterpretable. runtime / memory: n/a (not run).

--------------------------------
## GROUPED EXTERNAL VALIDATION
--------------------------------

Not re-run for the acceptance events (insufficient labels). The P6.25 grouped result stands as the
reference point: PARTY P 0.88 / R 0.96 (features discriminative with supervision); CAKE P 0.67 / R 0.25;
FIRST_DANCE untrainable.

--------------------------------
## V7 TEST-ONLY
--------------------------------

model frozen first: n/a (no new model trained — the audit produced no promotable classifier). V7
training use: **NO**. The P6.25 V7 cake control (frozen external probe misses V7's C7309 cake; predicts
COUPLE_PORTRAIT) stands and was not altered. No V7 inspection was used to tune anything in this package.

--------------------------------
## CORPUS PROMOTION
--------------------------------

passing classes: none new. failing classes: FIRST_DANCE, CAKE_ACTION (insufficient support). shadow
promotion: **none** — the P6.23 coarse corpus remains the working layer; PARTY remains the only reliably
supervised event (from P6.25), not promoted into planning here.

--------------------------------
## STAGE-1 SHADOW
--------------------------------

Not run (no new event evidence justified it).

--------------------------------
## STILL OPEN (carried forward)
--------------------------------

camera stability (shaky shots): open. source-moment / action-start ranking: open. Stage-2 integration:
not started. Fine-event perception for CAKE_ACTION / FIRST_DANCE: blocked on cross-wedding labelled
evidence.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0. timeline changes: 0. V7 / is edit:
not used. build_timeline: 0-line diff. Strips under gitignored `data/` (deleted after review); only code
+ small audit fixtures + tests + docs committed (no media/frames). TESTS: full suite **1182 passed**,
ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**D — even after a proper temporal re-audit, the external wedding evidence remains insufficient for the
acceptance events.** The methodology criticism was correct (thumbnails under-count temporal actions),
and watching in motion did surface 4 *probable* first-dances and 4 cake-action weddings — but 0
*confirmed* isolated first-dances and < 5 confirmed cross-wedding examples for either event, with high
portrait/crowd/sparkler confusion. This is a real evidence gap, not a leakage or representation failure
(so not E/F), and it is not correct to claim the references contain no first dance (the probables exist).

EXACT ADDITIONAL EVENT COVERAGE REQUIRED: ≥ ~5–8 **independent weddings** each with a **clearly isolated
reception first-dance** (couple-focused, guests secondary/later-joining) and ≥ ~5 with a **clear
cake-cutting action**, span-annotated with confusable negatives (couple portrait, styled twirl, crowd
dance, entrance, cake-table setup, sparkler-without-cutting). The curated cinematic reference set is
couple/party-dominated and structurally light on both events.

NEXT STEP — **ONE milestone (do not start):** **event-annotate the discovered separate-project wedding
footage (ELENORA MUSTAFA, raw) for FIRST_DANCE and CAKE_ACTION**, using the same temporal-strip
verification and strict grouping (still external to 15A; V7/is edit test-only). If it — together with
one or two more traditional weddings that actually contain these events — yields ≥5 confirmed positive
weddings per acceptance event, THEN run the static-vs-temporal representation comparison and the grouped
probe + V7 control. Only if CAKE_ACTION and FIRST_DANCE then clear the precision-first gate does the
event layer enter a shadow corpus; Stage-2 integration remains after that.

**DO NOT START IT.**
