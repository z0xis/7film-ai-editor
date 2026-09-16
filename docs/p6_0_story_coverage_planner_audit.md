# P6.0 — Story Coverage / Episode Planner Architecture Audit

Read-only forensic audit. No planner change, no DB mutation, no reanalysis, no timeline mutation.

## Headline finding

**An episode/story-coverage layer already exists in production** (`apps/api/sevenfilm/services/moments.py`,
the `Moment` dataclass + `project_moments()`), well-designed, with real prior editorial research
baked into six hard-won CLIP prompts (entrance, ring, kiss, cake, cake_feed, first_dance) and a
genuine day-position episode-clustering mechanism (`_moment_shots_of_the_day`) plus a
coverage/sequencing mechanism in `build_timeline` (a moment becomes "due" once earlier moments in
the day are shown; `moment_bonus` rewards satisfying it). **This entire system is dormant for 15
Ağustos** because every function in `moments.py` requires `shot_features.embedding IS NOT NULL`,
and **15 Ağustos has 0 of 2638 rows with a populated embedding** (confirmed live, read-only, this
package) — vs. Elenora's 1405/1405. This is not a planner architecture gap. It is a semantic
input gap, exactly the distinction Section 31 of this package's brief asked to keep separate.

## Current planner inputs (verified against `planner.py` at HEAD `64ecc54`)

Read: `shot.category`, `shot.confidence` (via `semantic_trust = max(0.4, min(1.0, confidence*2))`
— **this corrects the earlier P5.3-era assumption that confidence is unused**; it is read, but
for 15A confidence is a constant 0.25, so `semantic_trust` is a constant 0.5 for every shot — a
real input that carries zero information for this project specifically), `shot.aesthetic_score`,
`shot.motion_score`, `shot.shot_scale`, `shot.technical_quality`, `shot.face_edge`,
`shot.face_ratio`, source asset timecodes (`_day_position`), music section/energy/BPM
(`BeatGrid`), a `moments: Sequence[Moment] | None` parameter, `project_distractions()`,
`project_obstructions()`, `project_opening_signs()`, `project_table_settings()` (all also
embedding-gated, also dormant for 15A), sequence/run state, perceptual-hash duplicate detection,
reuse counts, and a `style_profile` derived from reference edits.

Not read: raw CLIP probability vectors, `labels_json`'s full ranked list (only the single
`shot.category` argmax reaches the planner), any Qwen/verifier output (no code path connects
P5's research to `planner.py` — confirmed, none of P5.1-P5.12's work is wired in, consistent with
every package's explicit "no production integration" instruction).

## Category balancing vs. story coverage — confirmed as two different, both-present mechanisms

1. **`_story_coverage_warning`** (planner.py:2727): counts `shot.category` shares against
   `_preferred_categories` at fixed story-progress points, warns when a wanted category is
   "thin." This is genuine **category balancing**, not story coverage — it has no concept of
   "first dance" or "entrance," only of category-share arithmetic. **Active for 15A** (does not
   need embeddings), but operates purely on the 4-category opencv_fallback vocabulary
   (bride/couple/venue/family), so it cannot distinguish a generic couple portrait from the
   couple's first dance.
2. **`moments.py`'s `Moment` system**: genuine event-aware coverage (`_due_now`, `moment_bonus`,
   day-position clustering). **This is the real story-coverage layer** — and it is the one that
   is dormant for 15A.

## 15A story availability (from frozen P5 research evidence + live read-only DB, not guessed)

| Story beat | Footage exists? | Evidence |
|---|---|---|
| First dance | **YES, confirmed** | P5.3-P5.9: real first-dance episode found on `DJI_0528.MOV` (drone) + additional episodes on `C7450`, `C7252`, `C7261` — visually verified, not model-claimed |
| Cake cutting | **YES, confirmed** | Real genuine cake_cutting TP found on `C7309.MP4` during P5.4 stress sampling |
| Drone/aerial footage | **YES, confirmed** | 10 source DJI clips, ~941 shots (P5.3) |
| Entrance | **UNRESOLVED** | P5.2-P5.6: Qwen's entrance detection showed 2/2 false negatives in every configuration tested; never resolved, not claimed absent |
| Ceremony (vow/ring exchange) | **UNRESOLVED** | Every "ceremony_action" candidate found in P5.3-P5.9 was actually a henna-night ritual scene, not a vow ceremony; whether real ceremony footage exists was never established either way |
| Night/party | **YES, confirmed (partial)** | Real party/dance footage repeatedly found and visually confirmed throughout P5.3-P5.9 (e.g. `076`, `079`, drone party frames) |

## Coverage matrix

| Story Beat | Evidence available? | Candidate evidence | Episode evidence | Present in rough cut? | Failure layer |
|---|---|---|---|---|---|
| First dance | YES | P5 real verified (multiple episodes) | Would be, if `moments.py` ran (day-position clustering exists) | **NO** | **A** (discovery never reaches production — `project_moments()` returns `()` for 15A) |
| Cake cutting | YES | P5 real verified (1 episode) | Same mechanism, same block | **NO** | **A** |
| Drone/aerial | YES | 941 shots confirmed | No episode concept for "drone" specifically (not one of the 6 named moments) | **NO (0 drone assets used)** | **A+C** — discovery blocked (embeddings) AND no coverage concept even exists for "drone/establishing" as a beat (moments.py's 6 prompts don't include it) |
| Entrance | UNRESOLVED | Unresolved | N/A | NO | **G** (insufficient evidence to attribute — genuinely unknown, not "discovery failure") |
| Ceremony | UNRESOLVED | Unresolved | N/A | Weak (category-share only) | **G** |
| Night/party | YES (partial) | Real footage confirmed | Not a named moment either | Present via category share only, not as a recognized "party" beat | **A+C** (same as drone) |

## First-dance forensic (exact boundary traced)

1. Source footage: real (confirmed, P5.3-P5.9).
2. Shot segmentation: exists (2638 shots in DB).
3. Current DB label: `opencv_fallback`, category ∈ {bride, couple, venue, family} — the actual
   first-dance frames are almost certainly mislabeled `venue` (P5.3's forensic audit found the
   fallback's face-detector-based heuristic defaults to `venue` when no face is detected, which
   is exactly what happens at drone altitude).
4. `shot_features.embedding`: **NULL for every 15A row** — this is the actual break point.
5. `project_moments()`: returns `()` because its query requires non-null embeddings.
6. Planner eligibility: since `moments=()`, the `moment_of_shot`/`unshown`/`_due_now`/
   `moment_bonus` machinery in `build_timeline` never activates for a single 15A shot.
7. Rough cut: 0 first-dance representation, consistent with #6.

**Exact failure layer: A (discovery) — not B, C, or D.** The episode-construction mechanism
(Layer B) and the coverage/sequencing mechanism (Layer C) both already exist in code and are
architecturally sound for this exact beat; they simply never receive input for this project.

## Drone forensic

Drone shots carry the same `opencv_fallback` label problem as everything else in 15A, landing
almost entirely in the `venue` bucket. Two things must be true for drone to plausibly appear in
a cut: (a) it must be selected over ~2500 other venue-labeled shots by category-share/quality
scoring alone (no drone-specific mechanism exists to prefer it), and (b) there is no "drone" or
"establishing aerial" entry in `MOMENT_PROMPTS` even if embeddings did exist — this specific beat
was never designed into `moments.py` at all (it was built from Elenora's manual-edit research,
which evidently didn't surface a drone gap the same way). **Failure layer: A (blocked by the
same embedding gap) + C (no coverage concept for this beat exists yet, independent of the
embedding fix).**

## Intro forensic

`_story_coverage_warning`'s thin-category detection and `moments.py`'s `project_opening_signs()`
(explicitly designed, with real prior editorial research, to find a wedding's welcome/name sign
for the opening) both exist. `project_opening_signs()` is embedding-gated — dormant for 15A. With
it dormant, the opening falls back to generic category+quality scoring with no notion of "this is
what a wedding film should open on," landing on whatever combination of bride/venue/couple shots
scores highest under generic rhythm/quality rules — exactly the "random" quality the user
described. The code's own comments (`# and a four second hold landing inside the opening. "klibin
intro ve outrosu kötü hatta yok"`, `planner.py:379`) show this exact failure mode was already
observed and partially addressed via `_closing_ramp_seconds` (for the outro side) on a *different*
prior edit — but the opening-sign detection fix specifically needs embeddings 15A doesn't have.

## Outro forensic

A `_closing_ramp_seconds` mechanism exists and is genuinely invoked in `build_timeline`
(planner.py:2133) — this is real, working closing-shape logic, not absent. What's missing for
15A is *what* fills that shape: without moment/opening-sign detection, the closing ramp still
lands on generic category-scored material, not a recognized "closing resource." **Failure layer:
D (representative selection within an existing but semantically blind mechanism), not a missing
architecture layer.**

## Multi-song transition forensic

Not deeply traced this package (would require reading the music/BeatGrid section-boundary logic
in more depth than the time budget for this audit supports) — flagged honestly as **NOT AUDITED**,
not assumed solved or broken. `_section_at`/`_pacing_scale`/`_band_preferences` exist and clearly
vary category preference and pacing by section, but whether they encode a genuine "Song A arc →
transition → Song B arc" structure versus filling a combined beat grid was not verified this
package.

## Elenora structural lessons already encoded

Confirmed directly in code (not inferred): music-first pacing (`_beats_per_cut`, `_pacing_scale`),
mini-sequence/forward-progression logic (`take_bonus`/`backward_penalty`/`staying`, with a comment
citing "17 runs from a single clip... every one of them advances"), section/subject-aware category
preference (`_preferred_categories` by `STORY_PROGRESS_POINTS`), and soft chronology
(`chronology_penalty` with `CHRONOLOGY_SLACK`, explicitly not hard sorting — a `moment_bonus`
deliberately overrides strict chronology when a moment is "owed"). **All of these were already
built from real editorial research; none of them are missing architecture.**

## Current pipeline (as it actually runs today)

```
shots (category/confidence/aesthetic/motion/scale, from opencv_fallback for 15A)
  + shot_features.embedding (NULL for 15A, populated for Elenora)
  → project_moments() / project_distractions() / project_obstructions() / project_opening_signs()
    [ALL return empty for 15A -- embedding-gated]
  → build_timeline(): category-share preference + quality/rhythm/chronology scoring
    + (for Elenora only) moment-aware coverage/sequencing + distraction/obstruction avoidance
    + opening-sign-aware intro
  → TimelinePlan
```

## Desired minimal flow (what would change, conceptually — not implemented)

```
shots + REAL semantic embeddings (any backend -- CLIP is already what moments.py expects)
  → project_moments() actually returns real first_dance/cake/entrance/ring/kiss candidates
  → existing Layer B (day-position clustering) and Layer C (due-now coverage) already handle
    the rest, unchanged
  → optionally: extend MOMENT_PROMPTS with project-agnostic beats not yet covered (e.g. a
    generic "aerial/establishing" prompt) if drone-as-a-beat is judged worth adding
```

## Architecture gap

**Primarily none at the episode/coverage layer** — that layer already exists, is well-designed,
and (per Elenora, where embeddings are populated) presumably already functions as intended, since
this whole module was built from real editorial complaints and validated against a real manual
edit. The gap is almost entirely a **semantic input gap**: 15 Ağustos was never analyzed with a
real embedding-producing backend. This directly matches every finding from P5.1 onward — 15A has
been DEGRADED/opencv_fallback since before this research arc began, and no package in P5.1-P5.12
ever ran a real reanalysis, by explicit, repeated instruction.

A secondary, smaller gap: `MOMENT_PROMPTS` covers 6 beats derived from one prior edit's specific
complaints; it does not include drone/aerial/establishing or night/party as named beats, so even
with real embeddings, those two would still only be reached via generic category-share balancing,
not true coverage. This is a real, bounded gap in the *content* of the moment list, not in the
mechanism itself.

## Minimum required addition: **A — Current planner mostly adequate; semantic input is main blocker**

Not B, C, or D — because B (episode construction) and C (story coverage) are not missing; they
are unexercised. The one genuinely-missing piece of content (drone/party as named beats) is a
small, bounded addition to an existing list (`MOMENT_PROMPTS`), not a new architectural layer.

## Insertion point

None required for the primary finding — the correct "insertion point" is upstream, in whatever
produces `shot_features.embedding` for a project (i.e., real semantic analysis, not this
planner). If the smaller MOMENT_PROMPTS gap is ever addressed, the insertion point is
`apps/api/sevenfilm/services/moments.py`'s `MOMENT_PROMPTS`/`MOMENT_NAMES` dictionaries — additive,
bounded, no restructuring.

## Semantic input blockers

15 Ağustos `shot_features.embedding`: 0/2638 populated. This has been true and unchanged since
before P5.1 and remains explicitly out of scope for every package in this research arc
(reanalysis was never authorized). This is the actual, sole, verified blocker for Layers A-D on
this specific project.

## Planner blockers

None identified that block story coverage specifically. `_story_coverage_warning`'s
category-only definition of "coverage" could be seen as a documentation/framing issue (it is
correctly NOT the same thing as story coverage, and this package's evidence confirms the two
should not be conflated) but it is not itself broken — it does what its narrower job describes.

## What can be fixed without reanalysis

- Nothing that restores real first-dance/cake/entrance/ceremony coverage for 15A specifically —
  that mechanism requires embeddings, which requires (some form of) real semantic analysis.
- The MOMENT_PROMPTS content gap (drone/party as named beats) could be addressed for *future*
  fully-analyzed projects without touching 15A at all.

## What requires better semantic input

Everything in the coverage matrix marked failure layer A: first dance, cake cutting, drone,
night/party representation as *recognized beats* (not just generic category material) — all
require `shot_features.embedding` to be populated by a real analysis pass, which is explicitly
not performed in this package.

## Proven
- The episode/coverage architecture (`Moment`, day-position clustering, due-now sequencing,
  moment_bonus) already exists in production, is well-designed, and is evidenced as built from
  real prior editorial research (quoted Turkish editor feedback, measured numbers in code
  comments).
- This entire mechanism is provably dormant for 15 Ağustos: `shot_features.embedding` is 0/2638
  populated (verified live, read-only, this package), vs. 1405/1405 for Elenora.
- The rough cut's actual composition (129 items, 4 categories: bride/venue/couple/family, 0 drone
  assets) is exactly consistent with category-share-only scoring and zero moment awareness — an
  independent confirmation of the code-level finding, not just a theoretical implication.
- `shot.confidence` is in fact read by the planner (correcting an earlier assumption from P5.3),
  but for 15A it is a constant, uninformative value (opencv_fallback's fixed 0.25).

## Not proven
- Whether the multi-song transition problem is a planner defect or a music/section-modeling gap
  — not audited to sufficient depth this package.
- Whether entrance or real-ceremony footage exists in 15A's 362 assets at all — genuinely
  unresolved by prior research, not assumed either way.
- Whether adding drone/party to `MOMENT_PROMPTS` would actually work well without real evaluation
  — plausible, not tested.

## Safety
```
PRODUCTION CHANGED: NO
DB CHANGED: NO (362 assets / 2638 shots / Elenora 345 unchanged; all reads were read-only SELECTs)
REANALYZED: NO
RESOLVE: unchanged
TIMELINE: 129 items unchanged
SOURCE MOMENT: unchanged
ROUTER: frozen R4b, unchanged
VERIFIER RESEARCH: frozen, not reopened
NEW MODEL DOWNLOADED: NO
CONTAMINATION: 0
```

## Tests
No code added — pure read-only audit + documentation. Full suite expected unchanged at 963/963.
