# PACKAGE 06.23 — REFERENCE EXTRACTION FIDELITY + TIER-2 SEMANTIC ENRICHMENT

START HEAD: `7b03f47`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Fixed the V7 audio-extraction bug (the "one song" contradiction) and semantically enriched all 18
render-only references with the project's own CLIP model. Shadow-only; `build_timeline` untouched
(0-line production diff); no DB/Resolve/timeline write. Code: `tools/refbrain/{enrich_tier2,build_corpus,
retrieval,stage1,eval_holdout}.py`; corpus + enrichment (gitignored): `data/reference_editor/`; fixtures:
`tools/fixtures/p6_23_v7_audio_fidelity.json`, `p6_22_{corpus_summary,retrieval_examples,holdout}.json`;
tests: `tests/test_p6_23_extraction_fidelity.py`.

--------------------------------
## V7 EXTRACTION CONTRADICTION
--------------------------------

actual music sources: **TWO** — Alex Warren – Ordinary (track 1, 3.5→80.3s) and Garnic … Wella Kole
(track 2, 77.9→123.8s), overlapping ~77.9–80.3s (**~2.34s crossfade**), with **SFX_ENTRANCE_v2 at
80.04s** exactly on the seam, plus opening crickets SFX (intro) and a bouquet SFX at 119.6s.
P6.22 extracted: **one song** — because the trace read only `GetItemListInTrack("audio", 1)`, i.e. the
first of four audio tracks.
root cause: **EXTRACTION_BUG** (single audio-track read). The prior audits were correct; P6.22 was wrong.
fix: read ALL audio tracks; classify music (.mp3) vs SFX (`SFX_*.wav`) vs visual-transition (.mov);
detect the song seam, the crossfade overlap and the entrance SFX; store them as first-class
`ReferenceMusicSection` + a music-transition descriptor.

--------------------------------
## V7 FIDELITY
--------------------------------

video: 87 shots, all mapped to 15A categories/scales/chronology (unchanged, correct).
music: **2 songs** (was 1). transition: **77.92s, crossfade 2.34s, energy up**. SFX: opening
(crickets), **entrance @80.04s**, bouquet @119.6s — all captured. events: cake (C7309), first-dance
region (DJI_0528 + cameras), reception/party, drone bookends, bouquet — all representable in the trace.
intro: drone + venue establish. outro: final wide + drone.

--------------------------------
## REFERENCE INVENTORY
--------------------------------

18 Tier-2: all present as `data/references/media/*.mkv`, video + audio available, shot-detected and
CLIP-enriched (42–129 shots each; all shots model-detected). Elenora evidence: **NOT FOUND** — no
rendered Elenora human film, FCPXML/OTIO, or human timeline is present; the DB "REVIZE" timelines are
AI-generated (confirmed P6.22). Only Elenora's 1405 analysed shots exist. (Per §22, a second Tier-1 is
not required for Stage-1; the enriched Tier-2 set is the sequence-grammar source.)

--------------------------------
## TIER-2 ENRICHMENT
--------------------------------

shots: shot-detected with PySceneDetect AdaptiveDetector (deterministic). semantic shots: **every**
Tier-2 shot carries a CLIP category + shot scale (the project's own `VisionClassifier`,
clip-vit-base-patch32) with a confidence, a motion magnitude + band (calm/medium/energetic), and a
normalized story position. scale: wide/medium/close_up/detail (unknown allowed). motion: per-shot frame
difference. audio/music: render-only refs carry no separate music source (single mixed track), so
per-song IDs are not fabricated; structural energy is left to a later pass. events: episodes built from
category runs. transitions: category-change transitions. All labels tagged MODEL-DETECTED with model id
and confidence (observed vs inferred kept distinct).

--------------------------------
## CORPUS V2
--------------------------------

edits: 20 (2 Tier-1, 18 Tier-2) · shots: **1336 (all semantic)** · sequences: 5144 · episodes: **695**
(was 102) · transitions: **675** (was 100) · music sections: 2 · music transitions: 1 · schema
`p6.22.1`, build_version **2**, versioned + fingerprinted, provenance preserved.

--------------------------------
## RETRIEVAL V2
--------------------------------

features: story position, event/category pattern, scale pattern, motion, duration, source reuse — not
duration statistics alone. explainability: every hit logs reference_id, sequence_id, similarity, matched
attributes, `why`, and now a real scale pattern from detected shots. deterministic: byte-identical
corpus + holdout across repeated runs (test-guarded).

--------------------------------
## 15A HOLDOUT
--------------------------------

V7 excluded: YES · is edit excluded: YES · leakage clean (18 Tier-2 refs active, 0 held-out present).
generated plan (learned category arc, 8 story slots):
`[COUPLE, COUPLE, COUPLE, COUPLE, COUPLE, PARTY_KINA, PARTY_KINA, PARTY_KINA]` — a couple-portrait-led
first half moving to a party second half, **learned from the 18 references**, with per-slot pacing and
scale roles from retrieved sequences.

--------------------------------
## ABLATION
--------------------------------

| mode | event/role order |
|---|---|
| semantic retrieval ON | `[COUPLE×5, PARTY_KINA×3]` (reference-learned) |
| retrieval OFF | `[OTHER, PREPARATION, PREPARATION, CEREMONY, FIRST_DANCE, PARTY_KINA×2, OUTRO]` (canonical) |
| aggregate style-profile only | same canonical arc as OFF |

does ROLE/EVENT ORDER change?: **YES.** Retrieval now changes the *structure*, not merely the durations
(the P6.22 failure — "only pacing changed" — is resolved). The retrieval order differs from both the
off and the aggregate canonical arcs.

--------------------------------
## POST-HOC V7 COMPARISON
--------------------------------

V7 used only after generation: **YES** (retrieval/scoring/tuning never see V7; its structure is
extracted algorithmically post-hoc). event coverage: low. order / category-arc agreement: **0.125**
(1/8 position bins). Why modest: V7's own category arc is **bride/prep-heavy**
(`[PREPARATION, BRIDE, BRIDE, BRIDE, COUPLE, BRIDE, GROOM, BRIDE]`), while the 18 references' central
tendency is **couple-portrait + party** — a genuine style divergence between this one V7 edit and the
reference set, not an extraction error. intro: both establish early (partial align). music transition:
V7's is now correctly represented (2 songs, crossfade, entrance SFX). reception: both reach PARTY_KINA
late. outro: canonical arc closes on OUTRO; the learned arc closes on PARTY_KINA (no OUTRO event token —
see cake control).

--------------------------------
## CAKE POSITIVE CONTROL
--------------------------------

V7 cake verified: **YES** (C7309 cake clips present, in the post-hoc event order). automatic detection
(Tier-2 learned arc): **NO**. Verdict: **SEMANTIC_EXTRACTION_MISS**, not "reference has no cake." The
CLIP shot-category vocabulary (bride/groom/couple/venue/party/ceremony/detail/family) has **no cake,
first-dance, bouquet or entrance event class**, so the reference-learned arc cannot carry those tokens.
This is the exact remaining blocker (below), stated as a detection limit, not an absence.

--------------------------------
## ELENORA
--------------------------------

human rich edit found?: NO. human final render found?: NO. tier: n/a. Only Elenora's analysed shots
exist in the DB; no human timeline / render / FCPXML / OTIO was found.

--------------------------------
## STAGE-1 TRANSFER
--------------------------------

does cross-project reference evidence now change structure?: **PARTIAL / YES.** After enrichment the
retrieval-learned arc drives the event order (differs from off/aggregate, leakage-clean) — so structure
transfer is real. But the transferred structure is at the **shot-category** level (couple→party) and
agreement with the specific V7 edit is modest (0.125), because (a) fine wedding events (cake, first
dance, bouquet, entrance) are not in the CLIP vocabulary — SEMANTIC_EXTRACTION_MISS — and (b) the
reference set's style diverges from this V7.

--------------------------------
## NOT YET SOLVED (carried forward)
--------------------------------

shaky-shot: not addressed (camera-stability hard filter — later). source moment: not addressed
(source-in / action-start ranking — later; is edit provides the selection evidence). Stage-2: not built
(no build_timeline integration — deliberately). fine-event detection: the top new item (below).

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0 (read V7/is edit audio only;
timeline count still 12). timeline changes: 0. build_timeline: 0-line diff. Corpus + enrichment under
gitignored `data/`; only code + small fixtures + tests + docs committed (no media/frames/audio). TESTS:
full suite **1163 passed**, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**B — semantics improved and retrieval now materially changes held-out Stage-1 structure (not just
pacing), but event/role-order transfer is still weak, and ONE exact blocker remains.** The V7 audio
contradiction is fixed (extraction bug, not a wrong prior audit); the 18 references are genuinely
semantic now (category/scale/motion/episodes), the corpus is deterministic and leakage-clean, and the
reference-learned arc drives the order. The blocker is the **event vocabulary**: the CLIP shot-category
model detects who/where (bride/couple/venue/party), not the fine wedding EVENTS (cake, first dance,
bouquet, entrance), so the learned arc is coarse and cannot reproduce V7's event-level sequence.

NEXT STEP — **ONE milestone (do not start):** **Add a fine wedding-EVENT detector to the Tier-2
enrichment** — targeted CLIP text prompts (and/or SFX-anchored cues, e.g. the entrance/bouquet SFX
pattern seen in V7) for CAKE / FIRST_DANCE / BOUQUET / ENTRANCE on top of the existing shot categories —
so episodes and the learned arc can carry event-level tokens. Then re-run this exact leave-one-project-out
holdout + ablation. If the learned arc then reproduces V7's event order at the event level while staying
leakage-clean, proceed to Stage-1 → Stage-2 shadow integration.

**DO NOT START IT.**
