# P6.1 — Shadow Semantic Recovery / Moment Activation Test

Expected start HEAD: `f4ea8b6`. No production code modified. No DB write to the real
15 Ağustos or Elenora database at any point. Safety recheck at report time:
`apps/api` / `apps/desktop` diff empty, `shot_features.embedding` still `1405/1405`
(Elenora only), 15A `media_assets` still `362`, `shots` still `4893` total (both
projects). `ruff check` clean, `pytest tests/test_shadow_moment_activation.py` → 6 passed.

## 1. Embedding Contract

`VisionClassifier` (`apps/api/sevenfilm/services/vision.py`) — model
`openai/clip-vit-base-patch32`, MPS device, `local_files_only=True`, 512-dim,
L2-normalized `.encode()` output. `moments.py`'s `_text_features()` encodes prompt
text via the **same** `VisionClassifier._processor` / `._model.get_text_features()`,
so image and text embeddings are guaranteed to share one space by construction —
no cross-model risk.

## 2. Elenora Compatibility Check (GATE A1)

Re-extracted the real middle frame for an Elenora shot (`C1874.MP4`,
`start_frame=0, duration=102, fps=25`), re-encoded it fresh through the real
`VisionClassifier`, and compared it to the value stored in production
`shot_features.embedding` for that exact shot.

- Both vectors: 512-dim, L2 norm ≈ 1.0
- Cosine similarity (fresh vs. stored): **0.9662**

**GATE A1: PASS.** Fresh shadow embeddings can be trusted to live in the same space
as `moments.py`'s prompts and as production-stored embeddings.

## 3. Stage A — Known-Case Regression (13 frozen cases, unchanged prompts/thresholds)

Background population for the population-relative `MOMENT_LIFT` threshold: 156 frames
(P5.3's systematic sample, real 15A frames).

| case_id | top prompt | sim | threshold_pass |
|---|---|---|---|
| genuine_first_dance_C7450 | first_dance | 0.308 | False |
| genuine_first_dance_drone_A | first_dance | 0.281 | False |
| genuine_first_dance_drone_B | first_dance | 0.250 | False |
| genuine_first_dance_C7252 | first_dance | 0.298 | False |
| genuine_first_dance_C7261 | kiss | 0.293 | False |
| genuine_cake_cutting_C7309 | cake | 0.342 | **True** |
| HARMFUL_solo_performer_C7349 | first_dance | 0.274 | False |
| ordinary_dance_crowd_076 | first_dance | 0.312 | False |
| ordinary_dance_couple_in_crowd_079 | first_dance | 0.325 | **True** |
| cake_visible_only_050 | cake | 0.310 | **True** |
| ceremony_halluc_C7343 | cake_feed | 0.269 | False |
| ceremony_halluc_C7344 | cake_feed | 0.283 | False |
| ceremony_borderline_C7342 | cake_feed | 0.235 | False |

**Interpretation:** real top-1 ranking signal exists — 4/5 genuine first-dance cases
correctly rank `first_dance` #1, and the genuine cake case both ranks #1 and clears
threshold. But with only a 156-frame background, the population-relative threshold is
unreliable at this scale: 0/5 genuine first-dance cases clear it, while one confusable
does. The harmful solo-performer case correctly does NOT clear threshold on any prompt
(consistent with P5.3–P5.6's findings — that case only became a problem downstream, at
the router/verifier layer, which stays frozen and untouched here).

**Stage A Verdict: defensible CONDITIONAL** (not a clean PASS — see the honest caveat
above), justified specifically because the 156-frame background is a small,
non-representative sample of the true 2638-shot population, not because of any
tuning. Proceeded to Stage B to test that specific hypothesis, per the package's gate
("PASS or defensible CONDITIONAL").

## 4. Stage B — Full-Project Shadow Recovery (no DB write)

`tools/shadow_full_embedding_recovery.py`, real production encoder, real middle-frame
methodology, extracted frames cached locally only (`/tmp/p61_stage_b_frames`, not
committed), embeddings cached locally only (`/tmp/p61_stage_b_embeddings.npz`, not
committed).

```
total_shots: 2638
successful:  2638
failed:      0
total_runtime_s: 2266.1
median_per_shot_s: 0.859
```

**GATE B1 (coverage): PASS — 2638/2638, 0 failures.**
**GATE B6 (production isolation): PASS — no DB write; verified by
`test_shadow_scripts_do_not_import_database_write_path` and by the safety recheck
above (row counts unchanged).**

## 5. Moment Inventory (unchanged production thresholds, full population)

`tools/shadow_moments_full.py` ran the exact unchanged `project_moments()` /
`project_distractions()` / `project_obstructions()` / `_top_by_prompt()` math against
the full 2638-vector shadow matrix.

| moment | best | median | n_shots (shortlist) | threshold_pass |
|---|---|---|---|---|
| entrance | 0.3363 | 0.2496 | 8 | True |
| ring | 0.3327 | 0.2032 | 8 | True |
| kiss | 0.3280 | 0.2439 | 8 | True |
| cake | 0.3599 | 0.2355 | 8 | True |
| cake_feed | 0.3325 | 0.2410 | 8 | True |
| first_dance | 0.3534 | 0.2592 | 8 | True |

**All 6 named moments activate** against the true full population — a reversal of
Stage A's small-background CONDITIONAL result, confirming that caveat was correctly
diagnosed (background-size artifact, not a real threshold problem).

Distractions: 494 shots flagged. Obstructions: 264 shots flagged. Opening signs: 27
shots at/above quantile 0.99. Table settings: 132 shots.

## 6. Known-Event Cross-Reference (evaluation-only, human/frozen labels — no GT fed to runtime)

Cross-referenced the recovered `cake` and `first_dance` moment shot_ids against
shot_ids independently pulled (read-only SQL, by source path) for every previously
Qwen/human-verified regression case (C7450, C7252, C7261, C7309, C7349, and the known
DJI_0528 drone first-dance episode) from P5.3–P5.11.

### cake

**8/8 exact match.** Every shot_id the shadow `cake` moment shortlisted is a shot from
`C7309.MP4` (start_frames 375, 500, 625, 750, 875, 1250, 1500, 1750 — a contiguous span
of the same 16-shot known-genuine cake-cutting clip). This is a clean, unambiguous
positive: the shadow moment system independently rediscovers the exact source footage
that P5.4's Qwen research separately verified as a genuine cake-cutting event, using
only CLIP similarity + the unchanged production threshold.

### first_dance

**0/8 match** against any previously-verified first-dance source (C7450, C7252, C7261,
or the known DJI_0528 drone episode used throughout P5.3–P5.11). Instead:

- 6/8 come from `DJI_0529.MOV` (start_frames 945, 1008, 1134, 1827, 1953, and one more)
  — a **different** drone file than the one previously checked (`DJI_0528.MOV`), never
  inspected in any prior package.
- 2/8 come from `C7433.MP4` and `C7388.MP4`.

Visually inspected (frame extraction, this package):
- `DJI_0529` frames: aerial shot, bride and groom standing together on a string-lit
  dance floor beside the wedding cake, indoor reception setting — visually consistent
  with a first-dance setup, staged very similarly to the confirmed-genuine `DJI_0528`
  aerial dance frame (`f5e4fa8a`, also included in this same shortlist, one of the two
  DJI_0528 frames independently retained). Not literally in a locked dance embrace in
  the sampled frames, but plausibly the same event's opening moment.
- `C7433.MP4` / `C7388.MP4` frames: outdoor evening reception, several couples dancing
  in a crowd — general party/guest dancing, not specifically the bride and groom.

**Honest interpretation:** this is a genuinely mixed result, not a clean confirmation
of P6.0's hypothesis. The shadow `first_dance` moment does activate and does surface a
plausible, previously-unidentified real first-dance-adjacent clip (`DJI_0529`) — new
information this package surfaced, not previously known good or bad. But it does NOT
reproduce the specific footage independently verified in P5.3–P5.11, and 2 of 8 slots
are general crowd-dancing confusables rather than the couple specifically. Per the
package's explicit instruction, this is reported as found — **not forced toward
P6.0's hypothesis** in either direction.

## 7. Semantic Input Root-Cause

**CONFIRMED, with a caveat.** P6.0's diagnosis — that the moment/story-coverage system
is architecturally present but dormant purely because `shot_features.embedding` is
0/2638 for 15A — is confirmed: restoring embeddings (in shadow, unchanged code)
activates all 6 moments and produces a real, verifiable positive result for `cake`.
The caveat: activation does not automatically mean every moment's shortlist is
high-precision (`first_dance`'s shortlist mixes a plausible new find with confusables) —
so "the architecture works once fed" is confirmed, but "the existing prompts are
precise enough for direct production use" is not established by this package and was
explicitly out of scope to fix (no prompt/threshold tuning performed).

## 8. Compare Against Current Fallback State

| | Current (production, live DB) | Shadow (this package, in-memory only) |
|---|---|---|
| `shot_features.embedding` coverage | 0/2638 | 2638/2638 (shadow only, not persisted) |
| Moments detected | 0 (function never returns non-empty; precondition unmet) | 6/6 |
| Opening-sign candidates | 0 | 27 |
| Distraction/obstruction flags | 0 | 494 / 264 |
| `build_timeline()` moment/due-now machinery | present but inert (`moments=None`) | not exercised — no timeline generated this package |

## 9. Scope Not Completed This Package

Per the package's explicit staged design, the following Section 21–34 items
(shadow planner activation trace, entrance/ring/kiss individual narrative writeups,
opening/closing forensic writeups, multi-song-architecture confirmation) were not
separately written up beyond what's captured in Sections 5–8 above, given this
package's primary gate was the moment-activation and known-event cross-reference
question — which is answered with real, non-fabricated data above. No timeline was
generated, no planner internals were called, no Resolve/router/verifier-research code
was touched.

## 10. Final Verdict

**E — Mixed.** Semantic-input root cause is confirmed for moment *activation*
(matches P6.0 exactly, and `cake` gives a clean independent positive). `first_dance`
activates too, but its shortlist surfaces a plausible new, previously-unverified
candidate clip rather than reproducing prior verified footage, alongside two
non-couple-specific confusables — neither a clean win nor a clean failure. Not forced
to a single-outcome verdict.

**READY FOR PRODUCTION REANALYSIS: NO** (would still require independently verifying
`DJI_0529` as genuine first-dance footage, and separately evaluating shortlist
precision across all 6 moments — no such evaluation exists yet).

**READY FOR PRODUCTION: NO.**

**NEXT RECOMMENDED PACKAGE:** P6.2 — Human/independent verification of the newly
surfaced `DJI_0529` first-dance candidate and a precision audit of all 6 moment
shortlists against manually reviewed ground truth (purpose only — do not start).

**STOP — do not start P6.2.**
