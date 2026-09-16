# P6.2 — Moment Population Reconciliation / Human Shortlist Audit

START HEAD: `32b6b52`
COMMIT: (this package's commit, see git log)

No production write, no reanalysis, no timeline generation, no Resolve mutation,
no prompt/threshold edit, no verifier-research reopening. Read-only SQL + local
ffmpeg frame extraction (cached under `/tmp/p62_*`, not committed) + human visual
review, exactly as scoped.

--------------------------------
## POPULATION RECONCILIATION
--------------------------------

- 15A total shots (`shots` joined to `media_assets` by `project_id`): **2638**
- 15A canonical planner/moments.py-eligible shots: **2638** (same set — every 15A
  shot has exactly one `shot_features` row, 1:1, 0 orphans)
- `shot_features` rows total (all 3 projects): **4043**
- `shot_features` rows with `embedding IS NOT NULL`: **1405** (Elenora only, unchanged)
- P6.1 Stage B encoded rows: **2638/2638** — exact match to 15A canonical set

**WHY 4893 vs 2638:** The DB holds **three** projects, not two:
`29cd1e06… "15 Ağustos"` (2638 shots), `df2a4a62… "elenora mustafa"` (1405 shots),
`e84045fa… "İS"` (850 shots). `2638 + 1405 + 850 = 4893`. My P6.1 safety-check
query ran `SELECT COUNT(*) FROM shots` with **no project filter**, so it silently
summed all three projects. This was **my own query-scoping error in P6.1's
reporting**, not a stale-row, duplicate-row, or data-integrity issue: 0 duplicate
shot ids anywhere in the table, every 15A shot has exactly one `shot_features`
row, a single `analysis_version` value ("4") across all 2638 15A rows, 362
distinct assets matching `media_assets` exactly.

**STALE/HISTORICAL ROWS?** NO.

**DOES PRODUCTION FILTER THEM CORRECTLY?** N/A — there was nothing to filter;
`moments.py`'s own queries (`WHERE media_assets.project_id = ? AND
shot_features.embedding IS NOT NULL`) are already project-scoped and shot-features
is 1:1 with shots, so production was never at risk of consuming the wrong
population. The ambiguity existed only in my prior report's phrasing.

**WAS P6.1 FULL POPULATION CLAIM VALID?** **YES.** The 2638-shot shadow matrix
is exactly the canonical 15A population `project_moments()` would consume once
embeddings exist. No re-run required.

**MOMENT_LIFT POPULATION VALIDITY: PASS.**

--------------------------------
## FROZEN MOMENT INVENTORY
--------------------------------

Unchanged from `tools/fixtures/p6_1_stage_b_moments_result.json` (prompts,
`MOMENT_LIFT=1.25`, `MOMENT_SHORTLIST=8` all unchanged). Full per-shot detail
with source asset/frame/similarity/human label is in
`tools/fixtures/p6_2_human_audit_manifest.json`.

- entrance: best 0.3363, median 0.2496, 8 shots, 6 episodes
- ring: best 0.3327, median 0.2032, 8 shots, 5 episodes
- kiss: best 0.3280, median 0.2439, 8 shots, 7 episodes
- cake: best 0.3599, median 0.2355, 8 shots, 1 episode
- cake_feed: best 0.3325, median 0.2410, 8 shots, 4 episodes
- first_dance: best 0.3534, median 0.2592, 8 shots, 4 episodes

--------------------------------
## FIRST DANCE
--------------------------------

shot-level: 1 TRUE_MATCH, 5 PLAUSIBLE_MATCH, 0 AMBIGUOUS, 2 FALSE_POSITIVE
episode-level: 4 episodes (DJI_0529 cluster ×5 shots, C7433 ×1, C7388 ×1, DJI_0528 ×1)

**CORRECTION to the P6.1 report:** P6.1 stated "0/8 match against any
previously-verified first-dance source." This was **wrong**. Shot
`f5e4fa8a-7392-5efb-80b7-739e5693ec0a` (DJI_0528, start_frame 3717) IS the exact
"drone_B" representative shot used as known-genuine first-dance evidence
throughout P5.3–P5.11. My P6.1 cross-reference check missed this match. Corrected
here: **1/8 known-source recall**, not 0/8.

**DJI_0529 (6/8 of the moment's members, 5 after episode-day filtering
considerations — see Planner Trace):** visually inspected all 5 distinct frames —
aerial view, bride in white dress and groom in suit standing close together on a
string-lit dance floor beside the wedding cake, gazing at each other. Not caught
mid-dance-embrace in any sampled frame; staged almost identically to the confirmed
DJI_0528 dance shot. Labeled PLAUSIBLE_MATCH (couple present, dance-floor
context, not literally shown dancing this frame).

**DJI_0528 vs DJI_0529:** `creation_time` metadata — DJI_0528 starts
2026-08-15T00:31:00Z, duration 705.7s (ends ≈00:42:46). DJI_0529 starts
2026-08-15T01:07:04Z, duration 139.6s. Gap ≈ 24 minutes. Same physical space
(same lit dance floor, same cake position, same lighting). Verdict: **LIKELY_SAME_EVENT**
(same reception dance-floor segment of the evening) — not definitively SAME_EVENT,
since the ~24-minute gap and DJI_0529's static-standing content could equally be a
separate moment (e.g., photos near the cake) rather than a continuation of the
dance itself.

known-source recall: 1/6 known first-dance-representative source clips
(C7450, C7252, C7261, drone_A, drone_B, drone... — only drone_B/DJI_0528 recovered)
known-event coverage: YES — the shortlist contains at least one shot
(`f5e4fa8a`) from the independently-verified genuine first-dance event, plus a
plausible same-event extension (DJI_0529).

**C7433:** FALSE_POSITIVE — solo person dancing outdoors, not the bride/groom
couple. Likely semantic reason: generic "person dancing" visual similarity
(clothing color, motion blur) without couple-specificity in the prompt's visual
cues.
**C7388:** FALSE_POSITIVE — general crowd dancing, several couples, not the bride
and groom specifically. Same likely reason: the prompt's embedding responds to
"two people close together, dance-like posture" broadly, not strictly to the two
named individuals (CLIP has no identity concept).

strict precision: 1/8 (0.125)
useful-candidate rate: 6/8 (0.75) — TRUE + PLAUSIBLE

**VALID FIRST-DANCE EPISODE: YES** — the known-genuine DJI_0528 shot is present in
the shortlist (confirmed via correction above), and DJI_0529 is a plausible
same-evening extension of it.

--------------------------------
## CAKE
--------------------------------

shots: 8, episodes: 1 (all C7309, start_frames 375–1750, contiguous)
precision: 8/8 TRUE_MATCH — every frame shows the couple actively cutting a
multi-tier cake with a knife.
verified episode? YES — this is the same source file (C7309) independently
verified genuine by Qwen in P5.4.
result: strongest positive control in the whole system, unchanged from P6.1.

--------------------------------
## CAKE FEED
--------------------------------

shots: 8, episodes: 4
- C7309 (4/8 shots, shared with the `cake` moment's episode): AMBIGUOUS — these
  frames show cutting, not feeding. Correct footage, wrong action for this
  specific prompt.
- C7411 (1/8): FALSE_POSITIVE — unrelated group toast/dance scene, no cake.
- C7281 (1/8): FALSE_POSITIVE — bride at party, no cake or feeding visible.
- **C7310 (2/8): TRUE_MATCH** — a previously-unaudited clip showing the groom
  feeding the bride by hand. This is a genuine, distinct cake_feed episode,
  separate from C7309's cutting episode.

strict precision: 2/8 (0.25)
useful-candidate rate: 2/8 (0.25) — the 4 C7309 shots are AMBIGUOUS, not PLAUSIBLE,
because they show the wrong action for this specific prompt.
**VALID EPISODE FOUND: YES** — C7310 is a genuine, newly-surfaced cake_feed episode.

--------------------------------
## KISS
--------------------------------

shots: 8, episodes: 7
- C7228 (2/8, same episode): TRUE_MATCH — both frames show the couple mid-kiss,
  faces together, eyes closed.
- C7248 (1/8): PLAUSIBLE_MATCH — forehead kiss visible.
- C7238 (1/8): PLAUSIBLE_MATCH — close affectionate faces, indoor.
- C7257 (1/8): PLAUSIBLE_MATCH — close embrace with crowd around, plausible kiss.
- C7348 (1/8): AMBIGUOUS — close dance embrace, no clear kiss visible.
- C7391 (1/8): AMBIGUOUS — cheek-to-cheek dance pose, not lips.
- C7235 (1/8): AMBIGUOUS — hand on neck, faces not shown together.

strict precision: 2/8 (0.25)
useful-candidate rate: 5/8 (0.625)
**VALID EPISODE FOUND: YES** — C7228 is a clean two-shot kiss episode.

--------------------------------
## RING
--------------------------------

shots: 8, episodes: 5
- C7161 (4/8, one continuous close-up-hands episode): PLAUSIBLE_MATCH — rings
  clearly visible in all 4 frames, but a static clasped-hands pose, not the
  "putting ring on finger" action the prompt specifies.
- C7221 (1/8): AMBIGUOUS — bouquet-holding shot, ring only incidentally visible.
- C7235 (1/8): AMBIGUOUS — hand on groom's chest/neck, not ring-focused.
- C7206 (1/8): FALSE_POSITIVE — hand-holding while walking, no ring focus.
- C7141 (1/8): FALSE_POSITIVE — bride seated using a phone during getting-ready,
  unrelated to rings; likely matched on "close-up of hands near white dress."

strict precision: 0/8 (0.0) — no frame shows the literal prompt action.
useful-candidate rate: 4/8 (0.5) — the C7161 episode is a real, useful ring
detail sequence even though it doesn't match the prompt's exact verb.
**VALID EPISODE FOUND: YES, but weakly** — C7161 gives a usable ring-detail
resource for editing, not a "ring exchange" moment as literally prompted.

--------------------------------
## ENTRANCE
--------------------------------

shots: 8, episodes: 6
- C7233, C7204 (×2 shots), C7205, C7183: PLAUSIBLE_MATCH — bride and groom
  walking together through decorated venue corridors/rooms. No guests or
  applause visible in any single sampled frame.
- C7176 (×2 shots), C7203: AMBIGUOUS — posed by decor rather than clearly
  walking/entering.

strict precision: 0/8 — no frame confirms the prompt's "guests applaud" element.
useful-candidate rate: 5/8 (0.625)

**15A entrance availability: PLAUSIBLE** (upgraded from P6.0's UNRESOLVED — the
moment system surfaces multiple real bride-and-groom walking/arrival episodes
across 6 distinct source clips, but none independently confirm the "guests
applaud" element the exact production prompt specifies; that would require
bounded temporal review beyond single middle-frames, not performed here to stay
within this package's scope).

--------------------------------
## ALL MOMENTS SCORECARD
--------------------------------

| Moment | Shots | Episodes | True | Plausible | Ambiguous | False | Strict precision | Useful-candidate rate | Valid episode found? |
|---|---|---|---|---|---|---|---|---|---|
| entrance | 8 | 6 | 0 | 5 | 3 | 0 | 0.0 | 0.625 | PLAUSIBLE |
| ring | 8 | 5 | 0 | 4 | 2 | 2 | 0.0 | 0.5 | YES (weak) |
| kiss | 8 | 7 | 2 | 3 | 3 | 0 | 0.25 | 0.625 | YES |
| cake | 8 | 1 | 8 | 0 | 0 | 0 | 1.0 | 1.0 | YES |
| cake_feed | 8 | 4 | 2 | 0 | 4 | 2 | 0.25 | 0.25 | YES |
| first_dance | 8 | 4 | 1 | 5 | 0 | 2 | 0.125 | 0.75 | YES |

**N is small (8 shots each) — none of these rates generalize to a broad
production-precision claim; they describe this specific shortlist only.**

--------------------------------
## FALSE POSITIVE TAXONOMY
--------------------------------

- ordinary/crowd dancing → first_dance (C7433, C7388): CLIP's dance-pose
  similarity is not couple-identity-specific.
- unrelated toast/dance scene → cake_feed (C7411): general "people close
  together, hand near face" visual similarity without cake context.
- party/veil scene with no cake → cake_feed (C7281): bride+veil visual
  similarity, cake not actually present.
- hand-holding walk → ring (C7206): "hands + white dress" visual similarity
  without a visible ring.
- phone-in-hand getting-ready shot → ring (C7141): "close hands + white dress"
  visual similarity, unrelated activity.
- posed decor shots → entrance (C7176, C7203): "bride+groom in a room" visual
  similarity without an actual walking/entering action.
- cutting footage → cake_feed (C7309, 4/8 slots): correct couple/cake context,
  wrong specific action (cutting vs. feeding) — the two `cake*` prompts are close
  enough in embedding space that one episode's footage leaks into both
  shortlists.

Not tuned in response to any of this, per the package's explicit instruction.

--------------------------------
## OPENING SIGNS
--------------------------------

candidate count: 27 (quantile 0.99), audited: top 6 (deterministic top-ranked
subset, inexpensive).
real useful opening resource? **NO.** All 6 audited frames are dance-floor /
cake-area scenes near a glowing decorative shell backdrop — none show an actual
welcome sign with the couple's names/date (the exact prompt semantics, per the
code comment describing how this worked on Elenora's shoot). Likely reason: the
glowing shell-shaped light installation visually resembles a bright signage-like
element to CLIP, without being one. **This is an honest negative finding**:
unlike `cake`/`kiss`/`first_dance`, semantic recovery does not appear to give the
intro system a real opening-sign resource for 15A — either the shoot has no such
sign, or it was never filmed distinctly enough for CLIP to separate it from the
dance-floor décor.

--------------------------------
## DISTRACTION / OBSTRUCTION SANITY
--------------------------------

Stratified sample (top / median / q99-edge) of the 494 flagged distractions:
top and edge-of-quantile picks are both genuine band/drummer performance shots
(C7372) — consistent with `DISTRACTION_PROMPTS`' band/musician semantics.
Median pick landed on a cake-cutting shot with onlookers in frame — a weak,
plausible match, not a clear contradiction. No further sampling performed
(bounded sanity check only, per scope).

--------------------------------
## PLANNER TRACE
--------------------------------

Traced `_score_candidate()` / `build_timeline()` (planner.py:1740-1880,
2025-2069) read-only, no timeline generated. The mechanism: `moment_of_shot`
maps each moment's day-clustered shots (`_moment_shots_of_the_day()`,
`MOMENT_DAY_SPREAD=0.05` of the day) to the moment's name; `_due_now()` returns
true once moments earlier in the day have been shown; `missing_moment =
shot.id in wanted_moment_shots`; `moment_bonus = MOMENT_BONUS (0.1)` when
`missing_moment` and `chronology_penalty == 0.0`. This is a real, working
mechanism (confirmed by code and its own inline measured-evidence comments,
e.g. "the first twenty-two seconds came out as the kiss, the entrance, the
cake, the ring and the first dance one after another" on a shoot where it
worked).

**Blocker to a full numeric trace:** `_moment_shots_of_the_day()` and
`_due_now()` both require `day_by_asset` — a day-position (0.0-1.0) for every
15A asset, derived from real per-asset chronology metadata elsewhere in the
planner. Computing this for all 362 15A assets is a materially separate piece
of work from moment/embedding recovery (it depends on the planner's own asset
day-position derivation, not touched or audited in P6.1/P6.2), and doing it here
would exceed this package's read-only/no-new-computation scope.

FIRST DANCE:
- moment valid? YES (per audit above)
- bonus? **UNKNOWN** — requires `day_by_asset` (not computed)
- due-now? **UNKNOWN** — same blocker
- would represent? **UNKNOWN — exact blocker: no `day_by_asset` chronology
  available in this shadow package to evaluate `_due_now()`/`moment_bonus`
  against the other 5 moments' day-positions.**

CAKE:
- moment valid? YES (strongest positive control)
- bonus? **UNKNOWN**, same blocker
- due-now? **UNKNOWN**, same blocker
- would represent? **UNKNOWN — same exact blocker as first_dance.**

INTRO:
- opening-sign candidate not validated (see above) — trace not applicable;
  no real opening resource was confirmed to trace.

--------------------------------
## CURRENT SYSTEM INTERPRETATION
--------------------------------

`moments.py` is **CANDIDATE DISCOVERY**, not a verifier. It surfaces
plausible/useful episodes at a real hit rate (useful-candidate rate 0.5-1.0
across 5/6 moments) but strict precision is low-to-zero for entrance/ring/cake_feed
because CLIP similarity does not encode the specific verb ("applaud", "putting
on", "feeding" vs. "cutting") as reliably as it encodes subject/setting
("bride+groom", "cake", "dance floor"). This matches the P5 verifier-research
finding (frozen, not reopened here) that CLIP is a discovery signal, not an
acceptance gate.

--------------------------------
## P6.0 ROOT CAUSE
--------------------------------

**CONFIRMED.** The moment system activates meaningfully once given embeddings,
and produces at least one valid episode for 5/6 moments (cake cleanly, kiss/
first_dance/cake_feed/ring more weakly). `entrance` is PLAUSIBLE but not
strictly confirmed. `opening_signs` is a genuine negative result — activation
does not guarantee a *useful* resource for every helper function.

--------------------------------
## READY FOR REAL 15A REANALYSIS
--------------------------------

**CONDITIONAL.** Evidence for authorization consideration only — reanalysis was
NOT performed. Conditions still open: (1) planner-trace blocker above (no
`day_by_asset` evaluated — moment activation without confirmed downstream
representation is not sufficient evidence alone), (2) entrance/ring/cake_feed
precision is low enough that a real reanalysis would need human review of which
specific shots enter the edit, not blind trust in the shortlist, (3) opening_signs
gives no real resource, so intro logic would need a different signal.

READY FOR PRODUCTION: **NO**

PROVEN:
- Population identity (2638 15A shots) is a single clean canonical set; P6.1's
  4893-figure was a reporting artifact, not a data problem.
- 5/6 moments produce at least one human-confirmed valid episode from real
  shadow-recovered embeddings.
- `cake` is a clean, high-precision positive control (8/8).
- `first_dance` does include a previously-verified genuine shot (correcting
  P6.1's error) plus a plausible new episode (DJI_0529).
- `cake_feed` surfaced a genuine new episode (C7310) distinct from `cake`'s.
- `opening_signs` does NOT give a real resource for 15A (honest negative).

NOT PROVEN:
- Whether any of these moments would actually receive `moment_bonus`/due-now
  priority in the real planner (blocked on missing day-position data).
- Whether entrance's "guests applaud" element is really present anywhere (would
  need bounded temporal review beyond single frames).
- Any broad precision claim beyond these specific 8-shot shortlists.

SAFETY: production DB unchanged (verified below), no writes, no tuning.

TESTS: `tests/test_p6_2_population_and_audit.py` (5 tests) +
`tests/test_shadow_moment_activation.py` (6 tests) — 11/11 passed. `ruff` clean.

--------------------------------
NEXT RECOMMENDED PACKAGE
--------------------------------

P6.3 — trace/compute `day_by_asset` chronology for 15A (read-only, no DB write)
specifically to close the moment_bonus/due-now blocker identified in this
package's Planner Trace section, so `cake` and `first_dance` can get a real
downstream-representation answer.

**DO NOT START.**

==================================================
GATES
==================================================

- GATE A (Population Integrity): **PASS** — fully explained, P6.1 used the correct population.
- GATE B (First-Dance Event Coverage): **PASS** — known-genuine shot recovered (corrected), plus a plausible extension.
- GATE C (Cake): **PASS** — clean useful episode.
- GATE D (Other Moment Precision): reported per-moment above, no forced aggregate.
- GATE E (Planner Activation): **CONDITIONAL** — mechanism traced and understood; numeric answer blocked on missing `day_by_asset`.
- GATE F (Intro Resource): **FAIL** — no real welcome-sign resource found.
- GATE G (Production Isolation): **PASS** — verified below.
- GATE H (Reanalysis Readiness): **CONDITIONAL** — see above.

==================================================
FINAL VERDICT
==================================================

**B — Moment discovery is useful but precision/vocabulary limitations require
one bounded shadow fix (day-position chronology for the planner trace) before
real reanalysis.**

READY FOR PRODUCTION REANALYSIS: **CONDITIONAL**
READY FOR PRODUCTION: **NO**

NEXT RECOMMENDED PACKAGE: P6.3 — 15A day-position chronology trace to close the
planner-activation blocker. **DO NOT START.**

==================================================
STOP CONDITION
==================================================

P6.2 tamamlandı. STOP — P6.3 başlatılmadı.
