# P5.3 — Shadow Semantic Escalation Architecture

Design/audit notes accompanying `tools/shadow_semantic_escalation.py`. Shadow-only: nothing here
is wired into `apps/api/sevenfilm/services/vision.py`, `analysis.py`, `planner.py`, or the API.

## 1. Production pipeline audit (as of `b37d224`, unchanged by this package)

```
SOURCE FRAME
  -> VisionClassifier.encode()            [CLIP image embedding, MPS/CPU]
  -> VisionClassifier.classify_features() [cosine-sim vs CATEGORY_PROMPTS/SCALE_PROMPTS/AESTHETIC_PROMPTS,
                                            argmax -> category, shot_scale; softmax top1 -> confidence]
  -> shots.category, shots.shot_scale, shots.confidence, shots.labels_json (top-3 order + backend tag)
  -> planner.py reads shots.category / shot_scale / aesthetic_score / technical_quality / motion_score
     for band-share, sequence and quota scoring. confidence and the raw probability vector are
     NEVER read by planner.py today.
```

**Critical audit finding:** 15 Ağustos has **zero real CLIP inference in the database**. Every
one of its 2638 shots carries `backend=opencv_fallback`, `confidence=0.25` (the fallback's fixed
constant, not a model score), and `shot_features.embedding IS NULL` for all rows. There is no
existing CLIP signal to read for a production router — any router evaluation against real 15
Ağustos data requires running CLIP fresh, read-only, outside the DB (exactly what this package's
shadow tooling does). This is not a regression; it is the pre-existing DEGRADED state P5 already
documented, restated here because it directly shapes what "shadow architecture" can mean for this
project until a real semantic pass is run.

**Where shadow attaches:** conceptually after `classify_features()`'s per-frame result, before it
is written to `shots`. The shadow harness in this package reproduces the same CLIP call
(same `CATEGORY_PROMPTS`, same cosine-sim math) independently, rather than monkeypatching
production code, specifically so this package cannot accidentally change production behavior.

## 2. Router signals — availability audit

| Signal | Exists in production today? | Used by shadow router |
|---|---|---|
| CLIP top1 confidence | Computed per-call, but not persisted meaningfully for 15A (fallback 0.25 for all rows) | Yes (R1) |
| top1-top2 margin | Not persisted anywhere (labels_json stores only ordered names, not scores) | Yes (R2) |
| Semantic entropy / top-k disagreement | Same as margin — derivable only from a fresh call | Not used (redundant with margin at this N) |
| Predicted-category family (story-critical vs container) | Derivable from the category name alone, no extra data needed | Yes (R3, R4, R4b) |
| Shot/source metadata (motion_score, face count, technical_quality) | Exists (`shot_features.metrics_json`) | Not used — no measured correlation established this package |
| Sequence/project-level uncertainty context | Would require aggregating across shots; not attempted | Not used |

Event ground truth, filenames, and golden-corpus labels are excluded from every router input by
construction — `FastPrediction` only carries `(category, top1_score, top2_category, top2_score)`.

## 3. Object/scene vs. event/action vocabulary

**CLIP's `CATEGORY_PROMPTS`** (couple, bride_prep, groom_prep, bride, groom, family, venue,
detail, ceremony, party) are **object/scene-level** — "what kind of shot is this broadly." None
of them describe an action in progress. `ceremony` and `party` are the closest to event-adjacent,
but P5.2 showed CLIP scores 0/4 on ceremony and this package's real-data run below shows the same
weakness persists on real 15A footage.

**Qwen's role is event/action-level**: first_dance vs. ordinary dancing, cake_cutting vs.
cake-visible, entrance vs. ordinary walking — distinctions CLIP's single-frame cosine-similarity
architecture cannot represent no matter how the prompt vocabulary is worded, because they depend
on distinguishing actions with near-identical visual composition (a couple standing close together
either dancing or embracing).

**This asymmetry is why escalation is architecturally motivated at all** — it is not "run a
bigger model," it is "run a model of a different architectural family for a different level of
the semantic hierarchy."

## 4. Provenance / cache design (not implemented, design-only)

```
backend: str                       # "clip_vision" | "opencv_fallback" | "qwen3_vl_shadow"
model_id: str
model_revision: str | None
prompt_vocabulary_version: str
analysis_algorithm_version: str
router_version: str                # e.g. "p5.3-r3-story-critical-v1"
deep_model_id: str | None
deep_model_revision: str | None
deep_prompt_version: str | None
```

Cache key = `source_fingerprint + source_frame_time + model_id + model_revision + prompt_version
+ algorithm_version` (see `shadow_semantic_escalation.cache_key`). This closes the exact gap P5.2
flagged: a bare `"clip_vision"` tag cannot today distinguish "analyzed with the production CLIP
prompt set v1" from "analyzed with a different prompt vocabulary" or "escalated and DEEP_ACCEPTed"
from "fast-tier only." None of this is wired to the real `shots` table in this package.

## 5. Retired methods — explicitly not reused here

Background-face penalty, continuous sharpness ranker, negative-only score, SmolVLM temporal
validator, optical-flow/RANSAC hard router, Candidate-0 RANSAC vote, global motion hard veto —
none of these appear in `shadow_semantic_escalation.py`. The router signals are limited to
CLIP category/score only, as specified.
