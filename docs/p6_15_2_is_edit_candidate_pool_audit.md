# PACKAGE 06.15.2 — IS EDIT VISUAL CANDIDATE-POOL / SHOT-SELECTION AUDIT

START HEAD: `cb22a2d`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Compared the editor's source-assembly selects (`is edit`) against the accepted edit (V7),
structurally and with a bounded read-only visual audit, to learn the editor's shot-/moment-/
sequence-selection grammar before P6.16. No Resolve/timeline/DB/planner change. Fixture:
`tools/fixtures/p6_15_2_is_edit_pool_audit.json`; tests: `tests/test_p6_15_2_is_edit_pool_audit.py`.

--------------------------------
## IS EDIT STRUCTURE
--------------------------------

items 187 · duration 365.6 s · 50 fps · **140 unique sources** · median cut 1.86 s · repeated
sources incl. C7404 ×7, DJI_0530 ×6, C7351 ×4, C7161/C7151/C7193/C7196 ×3.
candidate-pool type: **manually-trimmed curated SELECTS** — each item is trimmed around a useful
moment; unusable material is largely pre-excluded. already curated: **YES.** So it is a strong
sequence/story-grammar reference and a moderate good-vs-bad shot reference (the bad-clip contrast is
limited because is-edit already filtered).

--------------------------------
## V7 MAPPING
--------------------------------

V7 track-1 items 87 (75 sources). mapped: **43 DIRECT_MATCH**, **44 SAME_SOURCE_DIFFERENT_MOMENT**,
**0 SOURCE_NOT_IN_IS_EDIT**. So **V7 draws 100 % from the is-edit pool**, and on tightening it
**refines to a different moment of the same source about half the time**. is-edit sources dropped
from V7: **65 / 140**; reception-region selects left out: **39**.

--------------------------------
## VISUAL POOL SUMMARY
--------------------------------

is-edit is pre-curated, so nearly all items are USABLE+; the meaningful contrast is at the moment/
sequence level. A bounded visual sample of the **left-out reception selects** — C7377 (groom
dancing, night), C7395 (couple at party), C7401 (guest singing), C7429 (groom celebrated), C7447
(crowd hands-up), C7413 (groom dancing) — are all **genuinely good, energetic reception shots**.

--------------------------------
## SELECTED VS UNSELECTED
--------------------------------

The differentiator among already-usable shots is **content/action/sequence**, not raw technical
quality. V7 keeps forward-progressing event moments and drops individually-fine but redundant
alternatives; it does NOT use every good shot (65 sources / 39 reception selects dropped).

--------------------------------
## SOURCE-MOMENT GRAMMAR
--------------------------------

**Prefers the action phase over the setup.** cake C7309: is-edit's early moment (src 110) is a
**static setup pose by the cake**; V7 chose src 3332, the **actual cake-cut action**. This pattern
(action peak over setup/aftermath) is the likely driver of the 44 same-source-different-moment
refinements.

--------------------------------
## FIRST DANCE
--------------------------------

is-edit candidates: DJI_0528 src 1202 (isolated couple wide) and src 10501 (guests join). **DJI_0529
is in NEITHER is-edit nor V7** — the human editor built the first dance **only from DJI_0528 forward
reuse** (isolated establishing → guests join), and did not use DJI_0529 at all (even though the
semantic planner surfaced DJI_0529 in its first-dance shortlist). selection logic: **forward reuse
of one drone source to show the event's phases.**

--------------------------------
## CAKE
--------------------------------

is-edit: C7308, C7309 (×2: src 110 setup, src 1666), C7310 (×2). V7: C7308, **C7309 src 3332
(action)**, C7310. Grammar: prefers the action phase; tightens to the cut moment.

--------------------------------
## ENTRANCE / CEREMONY / RING / KISS
--------------------------------

is-edit's head is camera prep/detail shots (C7110/C7114/C7118…), not establishing; V7 opens on the
DJI_0524 aerial instead. Ceremony/ring/kiss coverage is thin in the pool itself — V7's low coverage
of these is **partly a footage limitation, not only a planner choice** (important context before
blaming the planner).

--------------------------------
## PARTY / KINA / NIGHT
--------------------------------

The pool is rich in reception/party material (39 reception selects beyond what V7 used). V7 prefers
readable couple/groom-focused and crowd-energy peaks; a large, genuinely good party pool remains
unused (tightening, not absence).

--------------------------------
## DRONE
--------------------------------

is-edit drone pool: DJI_0524 ×2, DJI_0525 ×2, DJI_0527, DJI_0528 ×2, DJI_0530 ×6, DJI_0531. V7 uses
drone as narrative punctuation (establishing/transition/first-dance/party/outro bookend); the pool
contains more aerials than V7 uses (drone is not spammed).

--------------------------------
## BOUQUET
--------------------------------

is-edit event phases: C7450 ×2 (src 461, 878) and C7451 ×3 (src 82 setup, 5532, 8913). V7 orders
C7451 setup (bride holds) → throw — **causally correct**. Dangerous alternative: is-edit contains
multiple C7451 moments; an independent (non-sequence) scorer could pick throw-before-setup, but the
human sequences them causally. This is direct evidence for sequence-level causality.

--------------------------------
## PAPYON / FAILED ACTION
--------------------------------

**NOT specifically identified** in the audited sample; not asserted (would require a targeted search
of the full pool).

--------------------------------
## FORWARD SAME-SOURCE REUSE
--------------------------------

**C7404 ×7** is one continuous **bride-sparkler/flare celebration** sampled across its progression
(sparkler lights → smoke builds → celebration) — a textbook FORWARD_SEQUENCE / EVENT_PHASE_SELECTION.
DJI_0530 ×6 and C7351 ×4 likewise sample one reception event forward. The editor deliberately reuses
a source to show an event's phases, in forward source order.

--------------------------------
## STRONG UNSELECTED SHOTS
--------------------------------

39 reception-region selects (e.g. C7377, C7395, C7401, C7413, C7429, C7447) plus extra C7404/DJI_0530
moments. Likely omitted for **redundancy / tightening** (V7 keeps a subset for pace), not because
they are weak. Lesson: do NOT teach the planner "use every good shot."

--------------------------------
## SEQUENCE FIT
--------------------------------

V7 keeps forward-progressing same-source moments (sparkler, first dance, bouquet) and drops
individually-fine but redundant alternatives to preserve sequence pace and causality — direct
evidence that **best-isolated-shot ≠ best-sequence-shot**.

--------------------------------
## VISUAL FILTER VS RANKING
--------------------------------

filter signals: technical usability (is-edit already applied it). ranking signals: action phase,
event importance, sequence/causal fit, forward source progression, non-redundancy, music-energy fit.
Conclusion: **quality behaves as a FILTER, not a strong RANKER** — confirmed by the pool.

--------------------------------
## SHOT-SELECTION GRAMMAR (evidence-backed)
--------------------------------

- VISUAL FILTER: exclude unusable (blur/blown/obstructed) — is-edit already encodes this.
- SOURCE MOMENT: pick the action peak / settled readable moment, not setup or aftermath.
- EVENT IMPORTANCE: cake, first dance, bouquet, entrance, reception survive; generic filler drops.
- SEQUENCE FIT: keep shots that build a mini-sequence; drop redundant alternatives.
- SOURCE REUSE: reuse one source across forward-progressing moments to show an event's phases.
- MUSIC FIT: faster cuts on higher-energy reception (song 2), calmer/longer on day (song 1).
- CAUSALITY: order action phases correctly (setup → action → reaction).

--------------------------------
## CURRENT PLANNER COVERAGE
--------------------------------

| grammar | evidence | modeled? |
|---|---|---|
| forward same-source progression | C7404/DJI_0528 phase reuse | **PARTIAL** (reuse only until source consumed, not for event phases) |
| action-phase moment choice | cake setup vs cut | **NO** (windows pick technically-good, not action peaks) |
| event importance / moment bonus | cake/first dance survive | **PARTIAL** (bonus exists, truncation blocks reception) |
| sequence fit / redundancy | 39 dropped selects | **PARTIAL** |
| music energy → cut length | song1 1.5 s vs song2 0.75 s | **YES** |
| causal ordering | bouquet setup→throw | **NO** |
| continue into reception while strong candidates remain | 39 unused reception selects | **NO** (early-exit stops in day story) |

--------------------------------
## FALSE EARLY STOP
--------------------------------

good unused late-story candidates present? **YES.** At the ~96 s planner stop, the editor's own
selects contain a large pool of genuinely good, coherent reception/party/first-dance/cake candidates
(C7377/C7395/C7429/C7447/C7413 party, the whole C7404 sparkler sequence, DJI_0530 ×6 aerials, plus
the first-dance/cake region V7 built) — not merely technically-valid shots. **FALSE-EARLY-STOP is now
very strongly supported.**

--------------------------------
## UPDATED P6.16 REQUIREMENTS
--------------------------------

1. Continue while coherent **high-value** story candidates remain (reception/first-dance/cake/
   bouquet), not merely any usable clip.
2. Relax the cut-run / 50 %-deliverable early-exit that stops in the day story.
3. Transition into the second-song reception.
4. Allow deliberate **forward same-source reuse** to build event phase-sequences.
5. Prefer **action-phase** moments over static setups within a source.
6. Preserve event causality (setup → action → reaction).
7. Do NOT require using every good shot — keep a tightened, non-redundant subset.
8. Reframe duration around a coherent-story endpoint (~123 s like V7), not a fixed 180 s.

--------------------------------
## SAFETY
--------------------------------

Resolve writes: **0** (read-only GetTimeline/GetItemList; frames from proxies). DB writes: **0**
(checksum `e8798470…` and mtime `2026-09-18 21:07:36` unchanged). timeline changes: **0** (is edit,
V7, 129-cut all unchanged). features 2638 · embeddings 2638 · jobs 0 · Elenora 1405 · contamination
0. Extracted frames deleted; none committed. Full suite 1108 passed, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**A** — `is edit` confirms V7 selected from a rich, pre-curated pool using an identifiable
source-moment/sequence grammar (action-phase choice, forward event-phase reuse, causal ordering,
non-redundant tightening); and a large pool of strong **unused reception candidates** proves the
planner false-early-stop and yields concrete P6.16 constraints. A secondary **B** caveat applies:
because is-edit is already curated, its evidence is strongest for story/sequence grammar and only
moderate for low-level good-vs-bad shot ranking — but the decisive finding (rich unused coherent
late-story material + a clear selection grammar) makes this **verdict A**.

READY FOR CONTROLLED CANDIDATE ROUGH CUT: **NO** (P6.16 fix first).
READY FOR GENERAL PRODUCTION: **NO.**

NEXT RECOMMENDED PACKAGE:
**P6.16 — BOUNDED PLANNER EARLY-STOP / RECEPTION-COVERAGE FIX (SHADOW VALIDATION FIRST)** — relax
the cut-run / 50 %-deliverable early-exit so the planner continues into the second-song reception
while coherent high-value candidates remain, with deliberate forward same-source reuse and
action-phase moment preference, reframing duration around a coherent-story endpoint (~123 s); all
validated in shadow against V7 before any candidate rough cut. The updated requirements above are the
acceptance criteria.

**DO NOT START.**
