# PACKAGE 06.20 — CONTROLLED CANDIDATE ROUGH CUT V2

START HEAD: `27ecb9f`
END HEAD: (this commit)
COMMIT: (this commit — recorded in the ledger follow-up)

Built ONE new isolated Resolve timeline from the current production planner (post-P6.19), exported
through the production exporter (FCPXML, which already encodes source trims / speed / music) and
imported as a new timeline. No planner tuning, no chronology overlay, no hand edits. Visually reviewed
the whole edit from extracted frames. Tools: `tools/p6_20_candidate_manifest.py`, `tools/p6_20_export.py`;
fixtures: `tools/fixtures/p6_20_{candidate_manifest,build_verification}.json`; tests:
`tests/test_p6_20_candidate_build.py`.

--------------------------------
## NEW TIMELINE
--------------------------------

name: **AI CUT V2 - P6.20 CANDIDATE**
project: 15 Ağustos · fps: 50 · resolution: 3840×2160 · start tc: 00:00:00:00
duration: 162.94 s (8147 frames)
video items: 132 · audio items: 2 (two songs)

--------------------------------
## PLAN
--------------------------------

plan hash: `49991347e0d406ea` · deterministic: yes (two runs identical)
planned items: 132 · actual items: 132
chronology path: **plain production (no overlay)** — P6.18 was NOT injected
manifest match: source name 0 mismatches · timeline start 0 · timeline duration 0
retimed items: 26 (24×0.5, 1×0.25, 1×0.507 — slow-motion, mostly drone). 20/26 source in-points
confirmed via read-back; the other 6 are time-remapped clips where Resolve reports `GetLeftOffset=0`
(the in-point is encoded in the FCPXML `start`+timeMap, verified distinct per clip) — a reporting
quirk, not a placement error. Matches the accepted P6.16/P6.19 plan shot-for-shot.

--------------------------------
## PROTECTED TIMELINES
--------------------------------

V7 (`IS EDIT - AI CUT V7`): **unchanged** (hash `689d0c574319a091` before == after)
is edit: **unchanged** (`efe59c58e9236478`)
old AI cut (`AI Rough Cut`, 129): **unchanged** (`056645bd0f954826`)
timeline count 11 → 12 (only the new candidate added)

--------------------------------
## INTRO (tl 0–18 s)
--------------------------------

result: **PARTLY_COHERENT**
visual evidence: couple portrait in the hall (day) → aerial dusk valley (DJI_0523) → two top-down
drone shots of the couple on the fairy-lit dance floor (DJI_0528, night) → night aerial of the
reception tables (DJI_0529). A striking montage opener, but chronologically mixed (day → night → night)
and it **spends the isolated first-dance drone material here decoratively**, so it is unavailable as a
real first-dance beat later.

--------------------------------
## DAY / PREPARATION (tl 18–50 s)
--------------------------------

result: **COHERENT.** bride makeup (C7151) → bride hair/veil (C7139) → couple portrait with bouquet
(C7174) → bride at window (C7194) → groom walking in (C7200). Standard, readable preparation grammar;
no obvious filler or abrupt jumps in the sampled span.

--------------------------------
## ENTRANCE
--------------------------------

No distinct isolated entrance sequence surfaced in the sampled positions; entrance reads as
USEFUL_CONTEXT folded into the couple/portrait material rather than a marked TRUE_ENTRANCE beat.
Overall: **PARTLY_COHERENT** — consistent with V7, which also had thin entrance marking.

--------------------------------
## CEREMONY / RING / KISS
--------------------------------

ceremony: thin — no marked ceremony sequence in the sample (camera ceremony coverage is limited in the
source, as in V7). ring: not visually isolated. kiss: not surfaced as a distinct beat (the kiss-angle
DJI_0528 appears only as brief aerials). Consistent with V7's own thin ceremony/kiss coverage; no
artificial quota demanded.

--------------------------------
## CAKE (tl 59–77 s)
--------------------------------

selected phase: **STATIC_SETUP → ACTION** (C7309 twice: couple by the tall cake at 59 s, then a closer
cake-action phase at 77 s with the red sash). result: **PARTLY_COHERENT** — good forward progression
within the cake event (setup → action, distinct C7309 phases), but a bride getaway-van shot (C7215) is
inserted **between** the two cake shots, interrupting the cake mini-sequence, and the whole cake event
sits inside song1 (~59–77 s) rather than the reception half (a chronology-placement effect).

--------------------------------
## FIRST DANCE (tl ~128–136 s)
--------------------------------

shots: C7388 / C7389 / C7405 (timecoded cameras) + brief DJI_0528 aerials.
visible roles: **GENERIC_RECEDING_DANCE / GUESTS_JOIN** — couple dancing amid guests, crowd party
dancing; no isolated couple-alone first-dance beat.
result: **GENERIC_DANCE_ONLY** (the known, documented limitation). The isolated first-dance drone was
spent in the intro; the reception first-dance slot is generic crowd dance. As instructed, NOT forced.

--------------------------------
## RECEPTION / KINA / PARTY (tl ~89–160 s)
--------------------------------

result: **COHERENT.** A real, energetic second half: reception couple → energetic dancing → kına
(henna) crowd in traditional dress → groom seated in the green kına robe → couple dancing → sparkler
celebration. Reads clearly as the reception/kına, with night atmosphere, crowd energy and drone
context. This confirms the P6.16 shadow reception coherence in the real Resolve timeline.

--------------------------------
## DRONE
--------------------------------

roles: ESTABLISHING (dusk valley DJI_0523, night venue DJI_0529), FIRST_DANCE-as-decoration
(DJI_0528 top-down floor in intro), PARTY_CONTEXT (brief DJI_0528/0529 reception cuts).
result: **mostly PURPOSEFUL** — establishing and context drones help; the main weakness is that the
best first-dance drone is used as intro decoration rather than at the first-dance beat.

--------------------------------
## SAME-SOURCE REUSE
--------------------------------

good forward: cake C7309 (setup → action), distinct C7450 reception phases.
useful distinct: DJI_0528 distinct aerials (intro long take vs brief reception cuts).
redundant: DJI_0528 top-down floor motif repeats (intro ×2 + brief reception cuts); C7404 sparkler
bride bookends the outro twice (144 s & 160 s) — mild.
backward: none obvious. Overall low visible redundancy for a 132-cut edit.

--------------------------------
## CAUSALITY
--------------------------------

bouquet: no distinct SETUP→THROW→REACTION bouquet sequence surfaced in the sample (bouquet camera
C7451 appears in the outro crowd walk, not as an isolated throw). papyon/bow-tie: not present in the
sampled candidate. other: no obvious result-before-action or reaction-before-cause errors seen; the
one ordering wrinkle is the van shot splitting the cake setup/action.

--------------------------------
## MUSIC TRANSITION (tl ~108 s)
--------------------------------

result: **PARTLY_COHERENT.** song1 (Alex Warren – Ordinary) 0→108 s; song2 (Wella Kole) 108→162.94 s
(the exporter trims song2 to the video end). At the 108 s cut the visuals move from energetic party
dancing (~96–101 s) to a calmer bride pearl-detail (108 s) then couple in kına attire — a reasonable
energy handoff, and it does NOT reproduce the old complaint (song2 entering under energetic visuals at
a weak musical point). Not perfectly punched to a musical drop, but coherent.

--------------------------------
## MUSIC-FIRST PACING
--------------------------------

result: **BALANCED-to-slightly-rigid.** song1 (calmer) carries longer establishing/prep takes; song2
(reception) is shorter, higher-motion party cuts (~0.5 s cuts in the reception body). beat rigidity:
**tends TOO_BEAT_RIGID** (prior planner evidence ~91% within 120 ms, more rigid than the manual
reference) — visible as very even ~0.5 s reception cutting.

--------------------------------
## OUTRO (tl 144–162.9 s)
--------------------------------

result: **COHERENT** (mild repetition). bride sparkler (C7404) → couple walking through a cheering
crowd (C7451) → bride sparkler again (C7404) → final group shot (C7452). An intentional, energetic
sparkler send-off ending; the only blemish is C7404 sparkler used twice as a bookend.

--------------------------------
## V7 VS CANDIDATE
--------------------------------

| dimension | V7 (accepted ref) | P6.20 candidate |
|---|---|---|
| duration | 122.8 s | 162.94 s |
| story progression | prep → events → reception | prep → cake/events → reception/kına (coherent) |
| intro | isolated build | montage (day+night mixed), first-dance drone spent here |
| entrance | thin | thin (context only) |
| ceremony/kiss | thin | thin (matches source) |
| cake | action-led | setup→action, but van split |
| first dance | isolated drone sequence | GENERIC dance only (known gap) |
| reception/kına | full | full, coherent, energetic |
| drone | purposeful bookend | purposeful establishing, first-dance drone misplaced to intro |
| music transition | punched ~78–80 s | 108 s, calmer handoff, coherent (not punched) |
| same-source progression | forward | mostly forward, low redundancy |
| causality | ordered | no gross errors; van-in-cake wrinkle |
| outro | bouquet+drone bookend | sparkler send-off (C7404 doubled) |

The behaviours that still separate the AI candidate from a V7-like edit: (1) first-dance drone spent
in the intro instead of at the first-dance beat; (2) beat-rigid reception cutting; (3) event
mini-sequences occasionally interrupted (van-in-cake).

--------------------------------
## TOP 5 ACTUAL DEFECTS
--------------------------------

1. **First-dance drone misplaced to the intro** (layer: CHRONOLOGY / SEQUENCE). The isolated
   couple-alone DJI_0528 first-dance aerials play at 6–8 s as decoration; the real first-dance slot is
   generic crowd dance. Symptom: no true first-dance beat. Manual fix: expensive (needs the drone
   chronology anchor from P6.18, not persisted) — or cheap-ish manual re-placement in Resolve.
2. **Beat-rigid reception cutting** (layer: MUSIC / PACING). Reception body cuts are very even ~0.5 s,
   more metronomic than the manual reference. Symptom: mechanical feel in song2. Manual fix: moderate
   (loosen a subset of cuts).
3. **Cake mini-sequence interrupted** (layer: SEQUENCE / SOURCE_MOMENT). A getaway-van shot splits the
   cake setup and cake action. Symptom: small continuity hiccup. Manual fix: cheap (move one clip).
4. **Cake event chronology** (layer: CHRONOLOGY). The night cake sits inside song1 (~59–77 s) rather
   than the reception half. Symptom: event-time ordering feels early. Manual fix: moderate.
5. **Mild outro/drone repetition** (layer: REDUNDANCY). C7404 sparkler bookends the outro twice; the
   DJI_0528 top-down floor motif recurs. Symptom: minor déjà-vu. Manual fix: cheap.

None are BLOCKING.

--------------------------------
## PRACTICAL EDIT QUALITY
--------------------------------

story structure: ACCEPTABLE · shot selection: GOOD · source moments: ACCEPTABLE ·
sequence continuity: ACCEPTABLE · music pacing: ACCEPTABLE · music transition: ACCEPTABLE ·
first dance: NEEDS_WORK · reception: GOOD · redundancy: GOOD · intro: ACCEPTABLE · outro: ACCEPTABLE.

--------------------------------
## MANUAL WORK ESTIMATE
--------------------------------

Needs real editing work: re-placing the first-dance drone at the first-dance beat; loosening the
beat-rigid reception cutting; un-splitting the cake sequence. A skilled editor: roughly 30–60 minutes
of targeted polish, not a rebuild.

Already usable: prep progression, reception/kına energy, drone establishing, outro send-off, overall
structure, low redundancy, correct 50 fps / UHD build with both songs and slow-motion intact.

--------------------------------
## NEXT ACTION
--------------------------------

**A — Candidate is good enough as an AI first pass.** It is a coherent, watchable 162.9 s highlight
with a real reception second half, correct build, and only bounded, known imperfections (first-dance
placement chief among them). Next work should be **bounded polish of this actual candidate**, not a new
research branch. NO broad research plan.

--------------------------------
## SAFETY
--------------------------------

DB writes: 0 (checksum `e8798470c518`, mtime 2026-09-18 21:07:36 unchanged; shots/features/embeddings
2638/2638/2638).
protected timeline changes: 0 (V7 / is edit / AI Rough Cut hashes unchanged).
new timeline writes: 1 (AI CUT V2 - P6.20 CANDIDATE; count 11→12).
chronology persisted: none. source media modified: none. candidate NOT hand-edited after build.
TESTS: full suite **1144 passed**, ruff clean.

--------------------------------
## FINAL VERDICT
--------------------------------

**A — Good/acceptable AI first pass.** Stop planner research; polish this candidate. The candidate
timeline remains in Resolve as a clean evaluation artifact. First dance is the one dimension that
would benefit from a bounded correction (option B territory), but nothing is blocking and no broad
research is warranted.
