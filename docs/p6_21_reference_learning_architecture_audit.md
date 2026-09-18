# PACKAGE 06.21 — FULL-EDIT FAILURE / REFERENCE-LEARNING ARCHITECTURE AUDIT

START HEAD: `1db0873`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Read-only architecture audit. No planner change, no timeline mutation, no DB/Resolve write. Proves what
the 2 completed projects + ~18 reference edits actually do at runtime, via a controlled shadow ablation
and a full input→runtime trace. Tool: `tools/p6_21_reference_ablation.py`; fixture:
`tools/fixtures/p6_21_reference_ablation.json`; tests: `tests/test_p6_21_reference_architecture.py`.

--------------------------------
## USER VERDICT
--------------------------------

P6.20 acceptable?: **NO.** The P6.20 "A — acceptable AI first pass" conclusion is **withdrawn** — it
was based largely on sparse extracted frames, which cannot judge rhythm, transition quality, flow,
timing or watchability. failed dimensions (per the editor): **intro, music transitions, overall edit
flow, outro** — not just first dance.

--------------------------------
## REFERENCE INVENTORY
--------------------------------

| source | location | format | runtime status |
|---|---|---|---|
| 7Film style profile | `data/references/7film-style-profile.json` | aggregate JSON (~15 scalar/array stats) | **ACTIVE (the only one)** |
| profile backups | `…json.backup`, `.backup2` | JSON | DEAD |
| 18 reference videos | `data/references/media/*.mkv` | video | ANALYSIS-INPUT ONLY |
| 18 yt-dlp metadata | `data/references/info/*.info.json` | JSON | DEAD at runtime |
| reference links | `data/reference-links.txt`, `youtube-accessible.txt`, `vimeo-authenticated.txt` | text | DEAD at runtime |
| profile producers | `scripts/analyze_references.py`, `tools/references/learn_scale_shares.py` | offline scripts | produce the JSON (ACTIVE output) |
| V7 / is edit / AI Rough Cut | Resolve timelines | timeline | **EVALUATION-ONLY** (not read by planner) |
| Elenora project | DB (1405 shots/embeddings) | DB rows | **not read for 15A** (separate project) |
| all `tools/shadow_*`, `tools/p6_*`, `docs/p6_*` | repo | scripts/markdown | SHADOW_ONLY / DOCS_ONLY |

--------------------------------
## 18 REFERENCES
--------------------------------

found: **yes** (18 videos + 18 info JSONs + a per-film summary array in the profile).
processed: **yes**, offline, by `scripts/analyze_references.py` (+ `learn_scale_shares.py`).
stored: as **aggregate statistics** in one JSON — median BPM, shot-duration percentiles, per-section
(intro/build/core/finale) median cut lengths, beat-alignment ratios, `story_arc` (10 progress bands ×
category shares), `held_shots`, `scale_shares`, `visual_profile`. The per-film `references[]` array
carries only summary numbers.
runtime-active: **only in aggregate.** The planner reads the profile's aggregate fields; it reads the
per-film array exactly once — `style_profile.get("reference_count")` (planner.py:1967) — to print the
Turkish warning "18 referanstan çıkarılan 7Film ritim profili uygulandı". No individual reference
edit's shot sequence, transition, or structure is ever retrieved or imitated.

--------------------------------
## COMPLETED PROJECTS
--------------------------------

15 Ağustos: the target project. Its own media analysis (shots, CLIP embeddings, moments, windows,
rejections, music) drives the plan. Its embeddings are used **only to compare its own shots to each
other** (second-take/duplicate detection) — not against references.
Elenora / other: present in the DB (1405 shots/embeddings) but **not read when planning 15A**;
`build_timeline` is single-project-scoped (`project_assets/shots/embeddings(project_id)`).
cross-project learning?: **NO.** There is no cross-project representation and no runtime consumption of
one project's edit when planning another.

--------------------------------
## RUNTIME DEPENDENCY GRAPH
--------------------------------

`build_timeline(project_id, assets, shots, music, frame_rate, target_duration, style_profile, seed,
windows_by_shot, rejected, moments, distractions, obstructions, opening_signs, table_settings,
embeddings)` — provenance of each input:

| input | source | reference-derived? | used at runtime? |
|---|---|---|---|
| assets, shots | target project DB | no | YES |
| embeddings (CLIP) | target project `shot_features` | no (this-project only) | YES (self-similarity) |
| moments, distractions, obstructions, opening_signs, table_settings | target project analysis | no | YES |
| windows_by_shot, rejected | target project analysis / editor | no | YES |
| music | `plan_music(project songs, target, style_profile)` | switch-*timing* only | YES |
| **style_profile** | `data/references/7film-style-profile.json` | **YES (aggregate of 18)** | YES (soft) |
| target_duration, seed, frame_rate, name | user/project | no | YES |

Every reference influence flows through the single `style_profile` input.

--------------------------------
## REFERENCE ABLATION (shadow, no writes)
--------------------------------

| condition | style_profile | items | plan hash |
|---|---|---|---|
| A normal | 18-ref aggregate | **132** | `d8440b23ca358968` |
| B no-reference | None | **77** | `426051dccaa461f4` |
| C neutral-arc | scalars only (arc/scale/hold stripped) | **73** | `fc485b615767f1ed` |

normal plan hash: `d8440b23…` · no-reference plan hash: `426051dc…` · **different (A≠B)**.
So the references **are** runtime-active: removing them collapses the deliverable from 132 to 77 items
(the arc/share/hold rules are what let sequences run to the target). **But** the influence is entirely
**distributional/pacing** — how many shots, how long, which category share, where songs switch — not
sequence construction. C (arc stripped) collapses similarly, confirming the arc drives *coverage/share*,
not *ordering as a narrative*.

--------------------------------
## V7 RUNTIME INFLUENCE
--------------------------------

**NO.** V7 (and "is edit") are **evaluation-only / research-only**. `build_timeline` never reads any
timeline_items; the `timeline_items` accesses in planner.py are `persist_timeline` (output) and
`load_timeline` (reading back a saved plan). None of the editorial grammar V7 demonstrates — day→
reception progression, calm→energetic sectioning, forward source reuse, first-dance sequence,
action>setup, causal ordering, event mini-sequences, music-transition behaviour, intro establishment,
outro resolution — reaches runtime as anything learned from V7. Where similar behaviour exists (opening
detail ramp, closing wide shape, arc shares) it is distilled from the **18 aggregate references**, not
from V7.

--------------------------------
## REFERENCE FINDINGS → RUNTIME
--------------------------------

| finding (from references / P6.x) | in runtime? | how / where |
|---|---|---|
| median shot duration / percentiles → pace | YES (soft) | `_energy_scale`, `_preferred_cut_seconds` (planner 300–321) |
| beats-per-cut by energy | YES (soft) | `_beats_per_cut` (251–253) |
| section (intro/build/core/finale) median cut | YES (soft) | `_reference_section_duration` (284–294) |
| beat alignment ratio | PARTIAL | `beat_alignment_ratio_120ms` (2800) — used in a warning/measure |
| story_arc category shares | YES (soft penalty) | `_band_shares`/`_share_overrun` (880–915) |
| scale shares | YES (soft penalty) | `_scale_overrun` (218–234) |
| held-shot frequency/length | YES (soft) | `_held_share`/`_held_seconds` (523–539) |
| visual brightness profile | YES (soft) | `_reference_visual_fit` (1054–1091) |
| opening = detail ramp | YES (rule) | `OPENING_SECONDS/CATEGORIES/DETAIL_CUTS` (384–402) |
| closing = wide, late-day | YES (rule) | `CLOSING_SCALE/DAY_FLOOR` (1430–1460) |
| song switch point from arc | YES | `story_switch_points`/`_arc_boundaries` (music 47–106) |
| **same-source forward progression** | PARTIAL | reuse penalties (P6.19) — local, not sequence-aware |
| **action-phase > setup selection** | **NO** (runtime) | diagnosed P6.15/P6.17, never implemented |
| **event mini-sequence continuity** | **NO** | no event model |
| **first-dance sequence** | **NO** | GENERIC_DANCE_ONLY (P6.17/P6.18/P6.19) |
| **bouquet / causal ordering** | **NO** | no causal model |
| **music-transition policy (energy/phrase/crossfade)** | **NO** | songs concatenated at a cursor |
| **intro/outro as constructed sequences** | **NO** | only duration ramps |

--------------------------------
## FULL EDIT FAILURE
--------------------------------

intro: a progress-indexed ramp (first ~5 cuts steered to `detail`, lengths from `OPENING_SECONDS`) on a
chronological greedy loop — no constructed opening concept; it cannot build an establishing sequence,
so on this shoot it front-loads mixed day/night drone/couple material.
music architecture: two songs **windowed then concatenated at a cursor**; switch point from the arc, not
from the visual seam or cross-song phrase matching; **no crossfade at the seam** (only the final song
fades). This is the core of the "bad transition" complaint.
rhythm: `desired` cut length per iteration from pace/energy/beat targets → **beat-grid-driven cutting**;
reception body is near-uniform ~0.5 s. It is BEAT GRID → CUT, not MUSIC PHRASE/ENERGY/STORY → INTENT →
SEQUENCE → CUT TIMING.
sequence: the edit is **a list of locally high-scoring shots**, not event mini-sequences; there is no
beginning/progress/end model for cake, first dance, party, bouquet, or outro.
story arc: represented **only** as `progress = current_frame / target_frames` selecting preferred
categories/shares. No explicit build / transition / climax / resolution states.
outro: a **duration ramp** lengthening the last cuts + a wide/late-day closing preference — not a
constructed resolution beat.

--------------------------------
## MUSIC TRANSITION MODEL
--------------------------------

what runtime actually does: `join_tracks` lays each song sequentially at a cursor; `choose_window`
picks each song's **own** source window to match a slot energy (first=low, last=high); the song1→song2
boundary is a target/arc division. No reasoning about outgoing vs incoming energy at the seam, no
phrase-boundary matching between songs, no bridge/transition shot, no crossfade, no SFX. It is
**concatenation of two energy-windowed tracks**.

--------------------------------
## INTRO / OUTRO MODEL
--------------------------------

what runtime actually does: intro = a fixed 5-value opening duration ramp + a "steer first 2 cuts to
detail, keep them early-in-day" rule; outro = a closing duration ramp + "prefer a wide, late-day frame".
Both are **emergent constraints on the same greedy loop**, not first-class INTRO/OUTRO/BOOKEND/
RESOLUTION states. There is no CLOSING_ACTION or FINAL_EMOTIONAL_BEAT concept.

--------------------------------
## SEQUENCE MODEL
--------------------------------

what runtime actually does: none. A single `while current_frame < target_frames` loop scores every
remaining candidate each step and appends the best. Continuity/reuse/second-take are **local pairwise**
penalties between neighbouring shots. There is no event segmentation, no per-event sub-plan, no
ordering policy beyond chronology + progress-indexed category preference.

--------------------------------
## CURRENT ARCHITECTURE CLASS
--------------------------------

**B — RULE/HEURISTIC PLANNER WITH REFERENCE-DERIVED CONSTANTS** (bordering C for the sequence layer).
Evidence: one aggregate reference input; all influence is soft pacing/share/rule nudges; the engine is a
greedy semantic-shot + music-grid fill-to-duration loop with duration ramps. It is **not** a
reference-conditioned editor (A): no reference edit, sequence, transition or cross-project representation
is retrieved or imitated at runtime.

--------------------------------
## WHY THE REFERENCES DID NOT TRANSFER
--------------------------------

1. **References collapse to ~15 aggregate statistics.** Individual edits' sequencing/transitions/intro-
   outro construction are averaged away before runtime; only distributions survive.
2. **No sequence-level representation.** The planner is a greedy per-shot scorer; there is no event
   model and no notion of a shot's role inside an event's begin→progress→end.
3. **No music-phrase / transition architecture.** Songs are energy-windowed and concatenated; the seam
   is unmodelled (no cross-song matching, no crossfade).
4. **No learned transition / intro / outro policy.** These are duration ramps and category nudges, not
   states derived from how references actually open, hand over, and close.
5. **No reference/cross-project retrieval.** V7, "is edit", the 18 edits and Elenora never enter runtime
   as queryable editorial evidence — they are evaluation/analysis only. The system can measure whether
   it matches them but has no channel to imitate them.

--------------------------------
## WHAT TO KEEP
--------------------------------

Worth keeping (solid, reusable): CLIP features, semantic categories, technical-quality **filter**, music
analysis + beat grid, moment detection, chronology (incl. the P6.18 drone estimator, shadow), the reuse
accounting (P6.19), the Resolve exporter + source-range/retime handling, the shadow-harness test
methodology. These are the correct primitives.

--------------------------------
## WHAT MUST CHANGE
--------------------------------

The **decision layer**. Replace the single greedy fill-to-duration loop (+ ramps) with a
reference-conditioned, two-stage story/sequence planner, and give the references a runtime channel
richer than one aggregate JSON. The current scoring loop is kept as the second stage.

--------------------------------
## ONE ARCHITECTURAL DIRECTION
--------------------------------

name: **Reference-conditioned two-stage editor (story/sequence planner → shot/timing planner) with a
reference-edit retrieval corpus.**

design:
- **Stage 1 — story/sequence plan.** Segment the shoot into EVENTS (prep, entrance, ceremony, cake,
  first dance, party/kına, bouquet, outro) from moments + chronology + categories. Build a global arc
  (intro → build → transition → reception → climax → resolution) and, per event, an ordered
  mini-sequence template (establish → progress → payoff). This stage decides **structure and slot
  roles**, not exact frames.
- **Stage 2 — shot/timing.** The EXISTING scoring loop fills each planned slot (keep pace/beat/quality/
  reuse/chronology machinery), now constrained to the slot's role and event rather than a global greedy
  fill.
- **Music.** A real transition model: choose the song-change at a musical phrase/energy boundary aligned
  to the reception entry, with a crossfade and an optional bridge shot.

how references become runtime-active:
- Build a **reference-edit corpus** from the actual edits: the 18 reference timelines (already downloaded)
  **plus the completed projects V7 / is edit / Elenora**, each stored as an ordered sequence of
  (category, scale, event, duration, energy, transition) — i.e. **sequence templates and transition
  statistics**, not just scalar aggregates. At plan time, **retrieve analogous event sequences** (by
  event type + available-footage profile) and condition Stage 1's templates and the music transition on
  them. This is the missing channel: the planner would *imitate how references sequence an event*, not
  just match their average shot length.

how finished projects become training/reference evidence:
- Ingest V7 / is edit / Elenora (and future accepted cuts) into the same corpus with an importer that
  reads their timeline_items into (event, role, duration, transition) sequences. Each accepted edit then
  **adds runtime-queryable grammar**, closing the loop the user expected: finished work teaches the next
  edit's structure, not only its statistics.

--------------------------------
## NEXT STEP
--------------------------------

**ONE milestone: build the reference-edit sequence corpus + retrieval, and a read-only Stage-1 story/
sequence planner that emits an EVENT/ROLE plan (shadow only, scored against V7/is-edit structure).** No
micro-fixes, no weight tuning, no intro/outro/music/first-dance patches. If Stage 1 demonstrably
reproduces reference sequence structure in shadow, only then wire Stage 2 to consume it.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518` unchanged). Resolve writes: 0. timeline changes: 0 (AI CUT V2 -
P6.20 CANDIDATE, V7, is edit, AI Rough Cut all untouched). No planner behaviour change (0-line planner
diff; audit adds a shadow tool, a fixture and tests only).
TESTS: full suite (below) + ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**B — References are runtime-active but their influence is too weak/local.** They change the plan
(ablation: 132 → 77 without them) yet only as **distributional pacing/share constants**; there is no
sequence-level, transition, intro/outro, causal or cross-project conditioning, and no channel to imitate
an individual reference edit. That missing **reference-conditioned story/sequence + transition layer** —
not weak constants — is why 18 references and 2 completed projects did not produce a V7-like edit.
Strengthen the architecture with the two-stage, retrieval-conditioned design above.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO** (P6.20 verdict withdrawn).
READY FOR GENERAL PRODUCTION: **NO.**

**DO NOT START IMPLEMENTATION.**
