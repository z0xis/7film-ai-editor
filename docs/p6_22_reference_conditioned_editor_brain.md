# PACKAGE 06.22 — REFERENCE-CONDITIONED EDITOR BRAIN FOUNDATION

START HEAD: `25999fc`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Built the Stage-1 foundation only: a structured reference-edit corpus (not one aggregate profile),
deterministic sequence retrieval, and a read-only Stage-1 story/sequence planner — plus a
leave-one-project-out holdout and a retrieval ablation. Nothing is wired into `build_timeline`; no
production DB / Resolve / timeline write. Code: `tools/refbrain/{schema,build_corpus,retrieval,stage1,
eval_holdout}.py`; corpus (gitignored, media-derived): `data/reference_editor/`; committed fixtures:
`tools/fixtures/p6_22_{corpus_summary,retrieval_examples,holdout}.json`; tests:
`tests/test_p6_22_reference_brain.py`.

--------------------------------
## REFERENCE INVENTORY
--------------------------------

total: 20 ingested edits · tier1: 2 (rich) · tier2: 18 (render-only)

| reference | project | tier | kind | source↔timeline | evidence |
|---|---|---|---|---|---|
| IS EDIT - AI CUT V7 | 15A | 1 | narrative | yes (Resolve) | order, source in/out, category, scale, chronology, music |
| is edit | 15A | 1 | selects | yes (Resolve) | order(=filename), source in/out, category, scale, chronology |
| 18 references | external | 2 | render_only | **no** | shot durations, bpm, section medians, story position |

Critical evidence facts (proved during the build):
- **The sevenfilm DB contains NO human edits.** Every timeline in it (incl. the Elenora "REVIZE"
  variants) carries planner scores + Turkish reasons — all AI-generated. The genuine human edits (V7,
  is edit) live in Resolve.
- **Elenora**: 1405 shots in the DB, but its human final edit is not in the DB and not in the open
  Resolve project — so no rich Elenora human edit was ingestable this package. Only its shots exist.
- **The 18 references are render-only** (final video + the style-profile per-film summaries). The only
  per-shot evidence available for them without new media analysis is **shot duration** — no per-shot
  category/scale/motion/source. So they are Tier-2.

--------------------------------
## CORPUS
--------------------------------

edits: 20 · shots: 1493 · sequences: 5772 · event episodes: 102 · transitions: 100
tier-1 edits: 2 · tier-2 edits: 18 · schema version: `p6.22.1`
entities: ReferenceEdit / ReferenceShot / ReferenceSequence / ReferenceTransition /
ReferenceEventEpisode / ReferenceMusicSection — each keeps a back-pointer to the edit that produced it
(provenance preserved; no anonymous aggregate-only learning). Versioned with a source fingerprint
(DB `e8798470…`, style-profile hash).

--------------------------------
## TIER-1 EVIDENCE
--------------------------------

V7 (narrative, 87 shots, ONE song): mapped 87/87 clips to 15A shots for category/scale, with asset-level
`day_position` chronology. Teaches sequence order, source-moment selection, forward reuse, intro/outro
placement, music-relative pacing. is edit (selects, 187 shots): ordered by **source filename**, i.e. a
curated selects bin, not a narrative — it teaches *which raw moments the editor kept* (SELECTED vs
STRONG_UNUSED/ALTERNATE_PHASE), not sequence order.

--------------------------------
## TIER-2 EVIDENCE
--------------------------------

18 render-only references: per-shot duration sequences + section medians + bpm + story position. They
can teach **pacing / section duration / story-position structure**. They **cannot** teach source-moment
choice or event/sequence grammar (no per-shot semantics without new media analysis). This limit is the
crux of the verdict below.

--------------------------------
## RETRIEVAL
--------------------------------

descriptor: [story_position, mean_shot_duration, mean_scale, source_reuse, drone_fraction, window_frac]
plus structured attributes (story_role, event_type, scale/category pattern, forward_progression).
index: in-memory over 5772 sequences. top-k: cosine over the descriptor + attribute-agreement bonus,
deterministic (ties broken by sequence_id). Every hit logs reference_id, sequence_id, similarity,
matched attributes and a `why`. Retrieval returns **grammar, never target shot ids** (asserted in tests).

--------------------------------
## 15A HOLDOUT
--------------------------------

target excluded?: **YES** — V7 and is edit are removed from the retrieval corpus; leakage check clean
(0 held-out references present; 18 active references, all Tier-2). The 15A target context (available
events, duration, music sections) is derived from **15A's own footage**, no human-edit leakage.

available events (from 15A footage): CAKE, CEREMONY, FIRST_DANCE, OTHER, OUTRO, PARTY_KINA, PREPARATION.

--------------------------------
## RETRIEVED HUMAN ANALOGUES (holdout)
--------------------------------

intro: Tier-2 refs (e.g. `ref:p1vkOMWvN7U`) — early-position, longer-duration sequences.
preparation / build: Tier-2 mid-position sequences.
reception entry / first dance / party / outro: Tier-2 sequences at the matching story positions.
All analogues are Tier-2 (render-only) because the only rich (Tier-1) references are the held-out 15A
edits. Every retrieval is logged with provenance in `p6_22_retrieval_examples.json`.

--------------------------------
## REFERENCE ABLATION
--------------------------------

| mode | role/event order | sequence durations |
|---|---|---|
| retrieval ON (holdout) | canonical arc | [33.0, 30.6, 23.0, 21.8, 21.0, 12.7, 12.2, 25.6] |
| retrieval OFF | canonical arc (same) | [28.8, 28.8, 21.6, 21.6, 21.6, 14.4, 14.4, 28.8] |
| aggregate profile only | canonical arc (same) | [26.1, 22.1×6, 21.4] |

differences: retrieval **does** change pacing (durations differ from OFF and from aggregate-only), so
the new layer is doing real work — **but only on pacing.** The role/event ORDER is identical across all
three modes. Because the only cross-project evidence is render-only (no per-shot events), retrieval can
condition pacing but cannot yet drive sequence structure; the ordering is still a canonical wedding arc.

--------------------------------
## STRUCTURAL COMPARISON TO V7
--------------------------------

V7 used only after generation: **YES** (retrieval/scoring/tuning never see V7; V7 structure is extracted
algorithmically post-hoc, not hardcoded).

event coverage: 0.80 (holdout plan covers 4/5 of V7's distinct events; misses CAKE as a distinct slot,
adds CEREMONY). event order: agreement 0.167 by LCS — low, because V7's real event stream is dominated
by PREPARATION interleaved between events, and the plan's arc is coarse. intro: plan has a first-class
INTRO_ESTABLISH slot (V7 opens on a drone + venue establish — structurally aligned). transition: plan
marks a RECEPTION_ENTRY energy-up seam; V7 uses one song with an internal energy lift. reception: both
reach PARTY_KINA late. outro: both close with a RESOLUTION_OUTRO / final wide.

--------------------------------
## ELENORA HOLDOUT
--------------------------------

Not performed: Elenora's human final edit is not available (DB timelines are all AI-generated; its human
Resolve edit is not in the open project). Only Elenora's 1405 shots exist. Ingesting a rich Elenora
human edit is the top item for the next milestone (see below).

--------------------------------
## MUSIC-STRUCTURE PLAN
--------------------------------

Stage-1 emits an energy curve (low→…→high→low) and transition intents with an energy delta per seam.
Gap stated honestly: the current music analyzer provides beat grid + coarse energy sections, **not**
phrase-level structure (intro/verse/build/peak/breakdown). Stage-1 therefore reasons at energy-band
level, not phrase level. No phrase data was invented.

--------------------------------
## STAGE-1 OUTPUT (holdout, abstract — no shots)
--------------------------------

| # | role | event | energy | dur target (s) | shot-scale roles |
|---|---|---|---|---|---|
| 0 | INTRO_ESTABLISH | OTHER | low | 33.0 | (from retrieved ref pattern) |
| 1 | PREPARATION | PREPARATION | low | 30.6 | … |
| 2 | BUILD | PREPARATION | medium | 23.0 | … |
| 3 | RECEPTION_ENTRY | CEREMONY | medium | 21.8 | … |
| 4 | FIRST_DANCE | FIRST_DANCE | medium | 21.0 | … |
| 5 | PARTY_BUILD | PARTY_KINA | high | 12.7 | … |
| 6 | CLIMAX | PARTY_KINA | high | 12.2 | … |
| 7 | RESOLUTION_OUTRO | OUTRO | low | 25.6 | … |

Full plan (with per-slot retrieved provenance) in `tools/fixtures/p6_22_holdout.json`.

--------------------------------
## DETERMINISM
--------------------------------

Corpus extraction, retrieval and Stage-1 planning are all deterministic — same inputs → byte-identical
corpus.json and byte-identical holdout output across repeated runs (verified; test guards it).

--------------------------------
## CURRENT STYLE PROFILE ROLE
--------------------------------

`7film-style-profile.json` is preserved and demoted to a **global pacing prior / fallback** (the
`aggregate` Stage-1 mode). It is no longer the entire reference-learning system; the corpus is.

--------------------------------
## NOT YET SOLVED (carried forward)
--------------------------------

shaky-shot filter: not addressed (needs a stability/technical-quality signal; the editor saw shaking
shots survive selection). source-moment boundaries: not addressed (clips beginning before the action —
needs source-boundary ranking; is edit provides SELECTED-vs-alternative evidence for it). Stage-2 shot
filling: not built — Stage-1 emits abstract roles only, deliberately.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0 (read V7/is edit only; timeline
count 11→…→12 unchanged from P6.20; no new/edited/deleted timeline). timeline changes: 0. build_timeline:
untouched (0-line diff). Corpus stored under gitignored `data/`; only code + small structured fixtures +
tests + docs committed (no media/frames/audio). TESTS: full suite **1157 passed**, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**C — the reference corpus is currently too sparse for reliable cross-project SEQUENCE retrieval, and
the exact missing evidence is now known.** The foundation itself works: the corpus is structured and
provenance-preserving, retrieval is deterministic and returns grammar (not shot ids), the holdout is
leakage-clean, and retrieval measurably conditions pacing. **But** cross-project *sequence-structure*
transfer could not be demonstrated because (1) the only rich human narrative edits are 15A (V7, is edit)
and must be held out; (2) the 18 cross-project references are render-only, so — without new per-shot
analysis — they teach pacing, not event/sequence grammar; (3) no second project's rich human edit was
ingestable (Elenora's human edit is not accessible). Result: in the holdout, retrieval changed pacing
but not sequence order (the order stayed a canonical arc). This is an **evidence** gap, not a leakage or
algorithm-soundness failure (not D; only partly B).

NEXT STEP — **ONE milestone (do not start):** **Enrich the cross-project evidence, then re-test transfer.**
Concretely: (a) run the existing shot-detection + CLIP/scale analysis on the 18 render-only reference
videos to give them per-shot semantics (turning them into sequence-grammar evidence, not just
durations); and (b) ingest at least one *rich human narrative edit from a second project* (Elenora's
human Resolve edit, or another). Only with rich multi-project sequence evidence can Stage-1's role/event
ORDER — not just its pacing — become reference-driven, at which point re-run this exact holdout and
ablation. If that milestone makes retrieval change the role order in the holdout while staying
leakage-clean, proceed to Stage-1 → Stage-2 integration (shadow first).

**DO NOT START IT.**
