# PACKAGE 06.15.1 — V7 BOUNDED VISUAL REFERENCE AUDIT

START HEAD: `3db4272`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Actually inspected representative frames of the V7 edit (extracted read-only from proxies,
inspected, then deleted — no personal media committed) instead of inferring content from metadata.
Read-only throughout; no Resolve/timeline/DB/planner change. Fixture:
`tools/fixtures/p6_15_1_v7_visual_audit.json`; tests: `tests/test_p6_15_1_v7_visual_audit.py`.

--------------------------------
## V7 CONFIRMATION
--------------------------------

timeline `IS EDIT - AI CUT V7` · duration 122.76 s · 108 video / 22 audio items · 50 fps · two
songs (Ordinary 3.5–80.26, Wella Kole 77.92–123.78) with a ~2.3 s crossfade. Confirmed as the
reference (Timeline 11 is a duplicate; not used).

--------------------------------
## INTRO — VISUAL AUDIT
--------------------------------

result: **COHERENT.** The first shot is a **night drone aerial (DJI_0524)** establishing the
illuminated forest wedding venue with the reception glowing among the trees and city lights on the
horizon, over opening crickets SFX before the music enters at 3.5 s. It establishes location, event
and night atmosphere, then progresses into the prep/couple montage — an establishing intro, not a
random montage.

--------------------------------
## ENTRANCE
--------------------------------

result: at the song-2 crossfade (~80 s), C7246 + `SFX_ENTRANCE_v2`. The entrance is structural
(marks the day→reception hand-off) rather than a long isolated salon-entrance sequence.

--------------------------------
## CEREMONY
--------------------------------

coverage: **WEAK** (thin, consistent with sparse ceremony footage in the shoot). Folded into the
song-1 couple/portrait montage rather than a dedicated mini-sequence.

--------------------------------
## RING / KISS
--------------------------------

Folded into the song-1 couple montage; not isolated long holds. Present as context, not headline
beats — the editor did not build them as standalone sequences.

--------------------------------
## CAKE
--------------------------------

sequence C7308 / C7309 / C7310 (~91–94 s). **COHERENT / TRUE_MATCH** — C7309 at src 3332 shows the
couple at the multi-tier cake **mid-cut (the action moment)**; the editor picks the action, not a
static pose.

--------------------------------
## FIRST DANCE — CRITICAL
--------------------------------

shots: DJI_0528 at src 1202 and src 10500. **COHERENT — a real sequence built by forward reuse.**
Visually confirmed (not metadata): src 1202 = a wide aerial of the **isolated first dance** (bride
and groom alone on the floor, guests seated watching); src 10500 = later in the same clip, **guests
have joined** the dance floor. The same drone source is advanced forward to show event progression
(couple's first dance → open dancing). result: **the true first dance is genuine and sequenced.**

--------------------------------
## PARTY / KINA / NIGHT
--------------------------------

visual energy: **HIGH.** The bride appears in an ornate traditional (kına) outfit dancing
energetically among guests (C7325), with DJI_0530 aerial party cutaways — a real, energetic
reception/kına section matching the energetic song 2.

--------------------------------
## MUSIC TRANSITION
--------------------------------

visuals before: a long DJI_0525 drone hold (73.84–79.04). transition: song-1→song-2 crossfade
(~77.9–80.3) + `SFX_ENTRANCE_v2` at 80.04. visuals after: entrance (C7246) → reception. result:
**COHERENT** — a deliberate hand-off from the calmer day section to the energetic reception, marked
audibly (entrance SFX) and visually (drone hold → entrance).

--------------------------------
## DRONE — VISUAL ROLE
--------------------------------

DJI_0524 ESTABLISHING (intro) + OUTRO (pull-out) — a **symmetric bookend**; DJI_0525 TRANSITION
hold; DJI_0528 FIRST_DANCE (×2, forward); DJI_0530/0531 PARTY_CONTEXT. Drone is **meaningful story
punctuation**, not decoration.

--------------------------------
## SAME-SOURCE REUSE
--------------------------------

**GOOD_FORWARD_REUSE**, visually confirmed: DJI_0528 (1202→10500: isolated dance → guests join) and
C7451 (82→8976: bride holds bouquet → bride throws). Later uses provide genuinely different, useful,
forward-progressing moments.

--------------------------------
## CONTINUITY / CAUSAL ORDER
--------------------------------

bouquet: **COHERENT** — C7451 src 82 (bride holds the bouquet, guests cheering — SETUP) → C7451 src
8976 (bride throws, guests reach up — THROW), in correct causal order, with the bouquet SFX on the
throw. No recipient-before-throw, result-before-action, or reaction-before-cause errors were
observed in the audited sequences. outro: **COHERENT.**

--------------------------------
## OUTRO — CRITICAL
--------------------------------

final shots: C7452 → **DJI_0524 drone pull-out** (with the bouquet SFX just before). result:
**COHERENT** — the bouquet throw resolves the event and the film closes on a drone pull-out that
**bookends the DJI_0524 intro establishing**. Appropriate final energy/emotion.

--------------------------------
## PACING / MUSIC-FIRST
--------------------------------

result: **STRONG.** Song 1 (day) runs ~1.5 s cuts on calmer prep/couple material; song 2
(reception) runs ~0.5–1 s cuts on higher-motion party/dance material, with long drone holds as
breathing points (transition, outro). Shorter cuts correspond to higher visual energy — the
music-first relationship holds.

--------------------------------
## WHY V7 IS ACCEPTABLE (observed properties only)
--------------------------------

- real reception coverage over an energetic second song (80–123 s);
- a genuine first-dance sequence built from forward drone reuse (establishing → guests join);
- cake action, kına/party energy, a causally-correct bouquet throw;
- a symmetric drone bookend (intro establish-in / outro pull-out);
- a smooth song crossfade transition marked by an entrance SFX;
- forward same-source reuse that advances events rather than repeating them.

--------------------------------
## V7 WEAKNESSES
--------------------------------

- very fast (~0.5 s) party cuts border on frenetic in places;
- ceremony coverage is thin;
- ring/kiss are context, not built beats;
- overlay film-burn transitions are stylistic decoration, not content.

--------------------------------
## P6.15 EARLY-STOP REINTERPRETATION
--------------------------------

Does useful coherent story exist after the planner stop? **YES.** V7's most important beats — the
isolated first dance, guests-join dancing, the cake-cutting action, the kına/party reception, the
causal bouquet throw, and the drone outro bookend — **all live after the ~80 s song-2 transition**,
exactly the region the P6.14 planner never builds (it stops at ~96 s inside the day story). The
visual evidence **strengthens the FALSE-EARLY-STOP diagnosis**: the planner is not stopping because
the remaining material is weak; the remaining material is the heart of the film.

--------------------------------
## P6.16 DESIGN REQUIREMENTS (evidence-backed)
--------------------------------

1. Do not stop before the reception when coherent later episodes exist — relax the cut-run /
   50%-deliverable early-exit (planner.py:2329–2345).
2. Transition from the calmer day section to the energetic second song / reception.
3. Allow forward same-source reuse to build event sequences (first dance, bouquet).
4. Treat first dance as a sequence (establishing → progression), not an isolated candidate.
5. Preserve event causality (setup before action; throw before catch).
6. Resolve the film on an ending beat (drone pull-out / bouquet) that bookends the intro.
7. Reframe duration around a coherent-story endpoint (~123 s like V7), not a fixed 180 s.

--------------------------------
## SAFETY
--------------------------------

Resolve writes: **0** (read-only `GetTimelineByIndex`/`GetItemListInTrack` only; frames read from
proxies). DB writes: **0** (checksum `e8798470…` and mtime `2026-09-18 21:07:36` unchanged).
timeline changes: **0** (129-cut, İS Edit, V7 all unchanged). features 2638 · embeddings 2638 ·
jobs 0 · Elenora 1405 · contamination 0. Extracted frames deleted; none committed.

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — V7 visually confirms coherent, high-value later story material (first dance, cake, reception,
bouquet, drone outro) exactly where the planner stops, strengthening the planner false-early-stop
diagnosis. (A **C** treatment also applies — V7 is acceptable in large part because of its music
transition, forward-reuse sequencing and causal outro — but the decisive evidence is that real
coherent story exists after the stop, i.e. verdict A.)

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO** (P6.16 fix first).
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.16 — BOUNDED PLANNER EARLY-STOP / RECEPTION-COVERAGE FIX (SHADOW VALIDATION FIRST)** — relax
the cut-run / 50%-deliverable early-exit so the planner continues into the second-song reception
(with forward same-source reuse), reframe duration around a coherent-story endpoint (~123 s), and
validate entirely in shadow against V7 before any candidate rough cut. The P6.16 design requirements
above are the evidence-backed acceptance criteria.

**DO NOT START.**
