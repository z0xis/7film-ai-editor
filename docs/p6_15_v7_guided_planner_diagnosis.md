# PACKAGE 06.15 — V7-GUIDED PLANNER STORY VALIDATION

START HEAD: `10dcce8`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Read the human-acceptable **V7** edit from the live Resolve project (read-only), mapped it, and
compared it to the P6.14 shadow planner to diagnose why the planner stops early. No Resolve write,
no timeline write, no DB write, no planner code change (fix deferred with proven root cause).
Fixture: `tools/fixtures/p6_15_v7_diagnosis.json`; tests: `tests/test_p6_15_v7_planner_diagnosis.py`.

--------------------------------
## REFERENCE TIMELINES
--------------------------------

- **İS Edit** exact name: `"is edit"` (index 3) — 187 video / 173 audio items — SOURCE/SHOT-ASSEMBLY
  reference (the manual material layout).
- **V7** exact name: `"IS EDIT - AI CUT V7"` (index 10) — 50 fps, 3 video / 4 audio tracks, 108
  video / 22 audio items — ACCEPTABLE EDITORIAL REFERENCE. **duration 122.76 s.**
- Version lineage present: `IS EDIT - AI CUT V1..V7`. `Timeline 11` is a byte-identical duplicate
  of V7 (same 108/22 structure) — noted, treated as the same reference.

--------------------------------
## V7 MUSIC USE
--------------------------------

- song 1 "Alex Warren – Ordinary": timeline 3.5 → 80.26 s (76.76 s used).
- song 2 "Wella Kole": timeline 77.92 → 123.78 s (45.86 s used).
- **transition**: a ~2.3 s crossfade (77.92–80.26), preceded by a long DJI_0525 drone hold
  (73.84–79.04) and marked by `SFX_ENTRANCE_v2.wav` at 80.04 s. Song 2 = the energetic
  reception/party half.
- energy relationship: song 1 (day) ~1.54 s median cut; song 2 (reception) ~0.75 s median cut —
  **cuts shorten as energy rises**, matching the manual grammar. The historical "second song
  entered on a weak section" is addressed in V7 by placing the entrance/reception at the song-2
  crossfade with an entrance SFX.

--------------------------------
## V7 KEY MOMENTS
--------------------------------

entrance: at the song-2 crossfade (~80 s, C7246 + entrance SFX) · ceremony: portrait/couple
montage in song 1 · ring/kiss: within the song-1 couple montage (not isolated long holds) ·
**cake**: C7308/C7309/C7310 fast ~1 s montage at 91–94 s · **first dance**: DJI_0528 aerial, reused
forward (src 1202 → 10500) at 82.7 s and 94 s · party/night: rapid 0.5–1 s montage 95–119 s with
DJI_0530/0531 aerial cutaways · **drone**: DJI_0524 (intro + outro), DJI_0525 (transition hold),
DJI_0528 (first dance ×2), DJI_0530 (party ×3), DJI_0531 (party) — 5 assets, 7 placements.

--------------------------------
## V7 EDITING GRAMMAR
--------------------------------

shot duration: ~1.5 s (song 1) → ~0.75 s (song 2). same-source progression: sources reused with
**forward-progressing source-in** (DJI_0528 1202→10500; DJI_0530 2370→10480→35144; C7196 510→1684;
C7351 1944→3354; C7404 1102→2352; C7451 82→8976). sequence continuity: **COHERENT** (forward reuse,
event mini-sequences: cake, first dance, party). intro: aerial establishing (DJI_0524) + title over
opening crickets SFX before music enters. outro: bouquet-catch SFX + DJI_0524 drone pull-out —
**COHERENT** closing beat.

--------------------------------
## P6.14 REPRODUCTION
--------------------------------

duration ~96.0 s · items 59 · nominal target 180 s · deterministic · **second music segment: 0
items** (never reached). Distinct source assets 49, reuse 10. Instrumented: **0 source
exhaustions** (`_source_range_for_duration` never returned None) — the pool never ran out.

--------------------------------
## V7 vs P6.14 (three-way where relevant)
--------------------------------

| dimension | V7 (human) | P6.14 shadow |
|---|---|---|
| duration | 122.76 s | 96.0 s |
| songs used | 2 (crossfade at ~78–80 s) | 1 (never enters song 2) |
| reception/night | ~43 s (80–123 s) | absent |
| cake | C7308/09/10 montage | C7309 selected (1) |
| first dance | DJI_0528 aerial ×2 | scored, **not selected** |
| kiss | in couple montage | **never scored** |
| drone | 5 assets / 7 placements | 7 assets / 14 items |
| source reuse | many, forward-progressing | mostly single-use |
| cut grammar | 1.5 s → 0.75 s by energy | ~1.5 s, single section |
| beat rigidity | looser (manual) | 91% within 120 ms (vs 61% ref) |

The planner is **semantically rich** (drones, categories, cake) but **stops in the day episode**
and never builds the reception/second-song half that makes V7 acceptable.

--------------------------------
## EARLY-STOP DIAGNOSIS
--------------------------------

is ~96 s actually erroneous vs V7? **YES.** V7 demonstrates ~27 s more coherent story
(reception/cake/first-dance/party over song 2) that the planner never builds.

last successful slot: item 59 at ~95 s · first failure: the next slot's candidate pool.
candidate funnel: 0 source exhaustions; candidate pool non-empty.

**mechanism (proven, planner.py:2329–2345):** the `_cut_run_score` window-quality gate
(`UNUSABLE_RUN_SCORE = 0.25`) found no remaining shot whose `shot_windows` could carry a cut of the
requested length at that slot, AND `current_frame ≥ target_duration × MINIMUM_DELIVERABLE_SHARE`
(0.5 × 180 s = 90 s), so the loop **deliberately breaks**: *"Nothing left worth cutting to, and
enough film to hand over."* It is NOT source exhaustion, NOT an empty candidate pool, NOT missing
semantics/embeddings.

root cause primary class: **SCORING_WEIGHT / CANDIDATE_ELIGIBILITY** — the cut-run window gate plus
the 50%-deliverable early-exit terminate the edit before the reception story, even though coherent
later material exists (V7 proves it) and the planner would reuse/relax to reach it.
secondary: **MUSIC_SECTION_SELECTION** (never transitions to song 2), **CHRONOLOGY** (drone
timecode; ring duration), **TARGET_FILL** policy (180 s target miscalibrated vs V7's 123 s).

--------------------------------
## FIRST DANCE / ENTRANCE / CEREMONY / KISS / CAKE / DRONE / PARTY
--------------------------------

- **first dance**: V7 uses the genuine DJI_0528 aerial (reused forward). Planner scores it (6/8) but
  never selects it — primarily because the plan stops before the reception/song-2 window where the
  first dance lives (early-stop), compounded by drone timecode. Class: EARLY_STOP + SCORING.
- **entrance**: V7 places it at the song-2 crossfade with an entrance SFX; planner has one thin
  entrance shot at the very start — it lacks the song-transition entrance structure.
- **ceremony**: WEAK in both (only 21 ceremony shots; V7 also carries little isolated ceremony).
  Not the primary blocker.
- **kiss**: never reaches scoring in the planner because the plan truncates before its window;
  V7 folds kiss into the couple montage rather than an isolated beat.
- **cake**: works in both — positive control (C7309). 
- **drone**: both use drones well; the remediation genuinely enabled this (old cut: 0).
- **party/night**: V7 dedicates song 2 to it; planner never reaches it.

--------------------------------
## MUSIC TRANSITION
--------------------------------

V7 crossfades song 1→2 at ~78–80 s with an entrance SFX and a preceding drone hold — a deliberate,
smooth reception hand-off. The planner never places anything in song 2 (0 items ≥108 s), so it has
**no transition at all**. This is the concrete current form of the historical "weak second-song
transition" complaint, now caused by the early-stop rather than by music offsets.

--------------------------------
## SEQUENCE CONTINUITY
--------------------------------

V7: coherent, forward source reuse, event mini-sequences (cake, first dance, party). Shadow:
acceptable within its 96 s, mostly single-use sources, no later-story sequences. The editor's
grammar (intentional forward reuse) is something the planner underuses.

--------------------------------
## REAL REMAINING BLOCKERS
--------------------------------

| issue | class | evidence |
|---|---|---|
| plan ends ~96 s, no reception/song 2 | SCORING_WEIGHT / CANDIDATE_ELIGIBILITY (cut-run + 50%-share early-exit) | planner.py:2329–2345; 0 source exhaustions; V7 has 27 s more coherent story |
| never transitions to song 2 | MUSIC_SECTION_SELECTION | 0 items ≥108 s |
| first dance / kiss absent | downstream of early-stop (+ CHRONOLOGY for drones) | scored-not-selected / never-scored |
| 180 s target | TARGET_FILL policy | V7 is 123 s; target miscalibrated |
| over-beat-rigid | BEAT_RIGIDITY | 91% vs 61% reference |

--------------------------------
## DURATION CONCLUSION
--------------------------------

180 s hard requirement? **NO.** V7 duration 122.76 s · shadow 96.0 s. Fixing the target alone does
**not** help: the 96 s stop is the cut-run / 50%-share early-exit, which would still fire at 96 s
even against a 123 s target (96 > 0.5×123 = 61.5). **The early-stop gate, not the target number, is
the blocker.** Acceptable-duration principle: a coherent edit that reaches the reception (~like V7's
123 s) passes; a 180 s edit padded with filler fails; a shorter coherent edit can pass.

--------------------------------
## SAFETY
--------------------------------

DB checksum before `e8798470…` == after · mtime unchanged (`2026-09-18 21:07:36`) · features 2638 ·
embeddings 2638 · 129-item AI Rough Cut unchanged · İS Edit unchanged · V7 unchanged · jobs 0 ·
Elenora 1405 · contamination 0. Resolve: **READ-ONLY** (only `GetTimelineByIndex` /
`GetItemListInTrack`; no Set/Add/Delete). No timeline writes.

--------------------------------
## READY FOR CONTROLLED CANDIDATE ROUGH CUT
--------------------------------

**NO** — the planner stops before the reception/second-song story that makes V7 acceptable; a
candidate cut now would omit cake-climax/first-dance/party. One bounded fix to the early-stop /
cut-run gate (and the song-2 transition it prevents), shadow-validated, is required first.

READY FOR GENERAL PRODUCTION: **NO.**

PROVEN:
- V7 (human-acceptable) is 122.76 s, two songs with a reception crossfade at ~78–80 s, drone-rich,
  forward source reuse, coherent intro/outro — the real editorial reference (not 180 s).
- The planner's 96 s stop is a deliberate early-exit (planner.py:2329–2345: cut-run window gate +
  50%-deliverable share), NOT source exhaustion, and is erroneous relative to V7's later story.
- Production, İS Edit, V7, and the 129-cut are all untouched (read-only).

NOT PROVEN / DEFERRED:
- The exact bounded fix (deferred to its own shadow-validated package — this is diagnosis).

TESTS:
- `tests/test_p6_15_v7_planner_diagnosis.py`: 7 read-only guards (V7 reference facts, transition,
  reuse, shadow early-stop not exhaustion, cut-run mechanism, no-fix-in-diagnosis). Full suite 1093
  passed, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**C** — the restored semantics reach scoring, but the main remaining blocker is planner
story/candidate scoring: the `_cut_run_score` window gate plus the 50%-deliverable early-exit
terminate the edit at ~96 s, before the reception/second-song story that makes V7 acceptable. A
strong **G** finding stands alongside it: the previous 180 s target was materially misleading (V7 is
~123 s), so planner duration policy should be reframed around a coherent-story endpoint, not a fixed
number — but the target is not the direct cause of the stop.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO.**
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.16 — BOUNDED PLANNER EARLY-STOP / RECEPTION-COVERAGE FIX (SHADOW VALIDATION FIRST)** — relax
the cut-run / 50%-deliverable early-exit so the planner continues into the second-song reception
story (allowing forward source reuse as V7 does) instead of stopping at ~half length; validate
entirely in shadow against V7 (no timeline write) before any candidate rough cut. Reframe the
duration policy around a coherent-story endpoint (~V7's 123 s), not the 180 s number.

**DO NOT START.**
