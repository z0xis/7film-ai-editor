# P5.10 — Relationship/Action-Aware Independent Verifier Scoping

Scoping only. No model downloaded. No code executed against real frames this package.

## 1. Frozen P5.9 conclusion (what object detection fundamentally lacked)

Faster R-CNN saw MORE people than SSDLite in every case (including drone) and still could not
separate `HARMFUL_solo_performer_C7349` (solo + incidental bystander) from
`genuine_first_dance_C7261` (real pair, partner partially cropped) at any of the 12 pre-registered
threshold/ratio cells. The missing information is not *how many people are in frame* — both
detectors already answer that adequately. What is missing is **relationship**: whether two
detected people are behaving as a pair (mutually oriented, coordinated, spatially paired as an
event-relevant unit) versus two people who merely happen to both be in frame (a performer and a
bystander, or a couple and a nearby waiter). Box-level features (count, area, area ratio,
proximity) carry no representation of orientation, pose, or coordinated motion — they cannot
carry this signal by construction, regardless of detector accuracy.

## 2. Task requirement (defined before candidate research)

**FIRST_DANCE** plausibly requires evidence from:
- **Person structure**: solo dominant subject vs. two co-present subjects.
- **Pair relationship**: mutual orientation (facing each other), spatial pairing distinct from
  background, plausibly coordinated movement.
- **Scene structure**: one visually/event-dominant pair vs. everyone else being background/audience.
- **Action**: dance-like body movement.
- **Temporal** (possibly): does the paired relationship persist across nearby frames, or is it a
  one-frame coincidence of two overlapping boxes?

**CAKE_CUTTING** plausibly requires:
- **Object**: cake present.
- **Human-object relation**: a hand/tool actually contacting the cake, not just proximity.
- **Action**: a cutting/manipulation motion, distinguishable from standing beside it.

## 3. Single-frame vs. temporal

P5.2 found Qwen's own temporal (before/current/after) prompting added zero measured value —
but that tested one specific model's text-conditioned reasoning over three static frames, not
whether motion/coordination information helps a *pose- or motion-based* signal. A pose-pair
orientation feature is answerable from a single frame (are the skeletons facing each other right
now); a *coordinated movement* feature structurally requires at least a short window. This
package classifies candidates by which they need, without committing to an exact window size.

## 4. Local environment audit

```
Already installed / zero new dependency:
  torchvision 0.29.0 -- includes KeypointRCNN (torchvision.models.detection.keypointrcnn_resnet50_fpn),
    a multi-person, multi-keypoint (COCO 17-point) pose estimator. Weights NOT yet cached
    (would need a ~226MB download to actually run -- see docs below, not downloaded this package).
  opencv-python 5.0.0.93 -- has NO pose-estimation module (only geometric pose/PnP utilities,
    unrelated to human pose). YuNet face detector already in use (P5.5-P5.9), insufficient alone.
  av (PyAV) 18.1.0 -- video frame I/O, not a model. Useful infrastructure if a temporal candidate
    is eventually chosen, not itself a verifier.

NOT installed (would require a new pip package before any weight download):
  mediapipe, ultralytics (YOLO-pose), mmpose/rtmlib, pytorchvideo, transformers video-model
    extras (VideoMAE etc. would load via the already-installed `transformers`, but no such
    checkpoint is cached).

No pose/action/HOI model weights are cached in ~/.cache/torch or ~/.cache/huggingface beyond
what P5.1-P5.9 already downloaded (CLIP, SigLIP2, Qwen3-VL-4B, SSDLite, Faster R-CNN -- none of
which are pose/action/relation models).
```

## 5. Hardware constraint

Apple M1 Pro, 16GB unified memory, MPS available (confirmed working for SSDLite and Faster R-CNN
in P5.8/P5.9). Every candidate considered below is a "lightweight" or "real-time" model class by
design (tens of MB to low hundreds of MB) -- nothing in this comparison approaches a size where
16GB is a real constraint. Rejected on hardware grounds: any full video transformer in the
hundreds-of-millions-to-billions-of-parameters range (e.g. large VideoMAE variants), and any
second full VLM.

## 6. Candidate families

### Family A — Human Pose Estimation (single/multi-person keypoints)

| Candidate | Available? | Size | License | MPS | Latency est. |
|---|---|---|---|---|---|
| **torchvision KeypointRCNN (ResNet50-FPN)** | API already installed, weights need ~226MB download | ~226MB | BSD-3-Clause | Should work (same family as SSDLite/Faster R-CNN, both confirmed working) | ~50-150ms/frame CPU, faster MPS |
| MediaPipe Pose (BlazePose) | Needs new `mediapipe` pip package | 3-13MB (lite/full/heavy variants) | Apache 2.0 | CPU delegate reliable on macOS; GPU delegate not guaranteed for Python bindings | ~10-30ms/frame |
| RTMPose (via `rtmlib`) | Needs new `rtmlib` pip package | Small (s/m variants, ONNX) | Apache 2.0 | ONNXRuntime CPU proven fast (90+ FPS reported on desktop CPU); MPS via ONNXRuntime CoreML EP plausible, unverified | Likely <20ms/frame |

**Strength**: gives per-person orientation and limb geometry, not just a box — this is the
minimum representation that could distinguish "facing each other, arms engaged" from "standing
near each other." **Weakness**: pose alone is still not relationship — two independently-posed
skeletons that happen to be near each other say nothing about whether they're a couple.
torchvision's KeypointRCNN is natively multi-person (detects all people and all their keypoints
in one pass), which MediaPipe's default pose landmarker is not (single-person by default, needs
pairing with a person detector for multi-person scenes) — a meaningful practical difference for
crowded wedding footage.

### Family B — Multi-person pose + generic pair features (not a model, a feature layer on top of A)

Not a downloadable candidate — this is classical geometry computed from Family A's keypoint
output: inter-person distance normalized by body scale, mutual body/shoulder orientation, relative
limb position, and (if temporal) frame-to-frame movement correlation between two tracked
skeletons. This is the layer that could plausibly encode "these two are a pair" beyond raw
co-presence, without inventing a wedding-specific rule maze — the features themselves (orientation,
normalized distance, movement correlation) are generic, not "if closer than X pixels."

### Family C — Human-Object Interaction (HOI) / Relationship Detection

Research landscape as of 2026: mostly academic/research-grade, several recent papers (e.g.
"Streamlined Open-Vocabulary HOI Detection", arXiv 2026) explicitly build on large foundation
backbones (DINOv3-scale) rather than offering a small, turnkey, pip-installable lightweight
detector. No evidence found of a widely-adopted, small, permissively-licensed, off-the-shelf HOI
model comparable in maturity/size to the pose or object-detection families. **This family is
currently immature for our hardware/deployment constraint** — not rejected on principle, but
nothing concrete and small enough was found.

### Family D — Action/Video Recognition

Well-known families: X3D, SlowFast, R(2+1)D (Meta/Facebook Research, BSD-3 via PyTorchVideo),
VideoMAE (available via `transformers`, Apache-2.0-family). All are pretrained on generic action
datasets (Kinetics-400/600/700) whose vocabulary includes classes like "dancing" but has **no
"first dance" class** and no notion of wedding-specific event structure — confirmed limitation,
not assumed away. Even the smallest variants (X3D-XS) are meaningfully larger and heavier than
the pose candidates for a task that doesn't obviously need full spatiotemporal video
understanding. **Directly relevant weakness for our exact problem**: a generic action classifier
would very plausibly label both C7349 and C7261 "dancing" — the same non-discriminating signal
object detection already gave us, just from a different architecture.

### Family E — Motion/Optical-Flow-Assisted Features

Explicitly de-prioritized: prior Source Moment research (P3.5, referenced in this package's own
retired-methods list) already found optical flow insufficient as a standalone discriminator on
this footage. Only worth revisiting *combined with* pose tracks (Family B) to measure coordinated
movement between two already-identified skeletons — not as a standalone candidate.

### Family F — Small Independent Vision-Language Model

Rejected as a primary candidate. Any second VLM (even a small one) shares Qwen's fundamental risk
profile: language-conditioned visual reasoning that can produce fluent, confident, wrong claims
(exactly what P5.3-P5.6 found and P5.6 formally falsified for same-model voting). A *different*
VLM family would be less correlated than same-model voting, but P5.10's brief explicitly asks for
independence from Qwen's reasoning style, and a second VLM's failure mode (hallucinated
relationships stated in fluent language) is architecturally the same *class* of risk, not a
different one. Not pursued further this package.

## 7. Task-capability matrix

| Family / Candidate | Different architecture from Qwen? | Solo-vs-pair | Partner-vs-bystander | Ordinary-vs-first-dance | Drone | Cake action | Frame type | Local availability | Download | Deps | MPS | License | Latency est. | Main weakness |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KeypointRCNN (torchvision) | Yes (CNN+keypoint head) | STRONG FIT | PROMISING (via pose geometry) | LIMITED alone | UNKNOWN (small-scale keypoints degrade) | POOR FIT (no object semantics) | single-frame | API installed, weights not cached | ~226MB | none new | Likely yes | BSD-3 | ~50-150ms | Pose ≠ relationship by itself; needs Family B logic on top |
| MediaPipe Pose | Yes | STRONG FIT (single-person) / LIMITED (multi-person needs extra pairing) | PROMISING | LIMITED alone | UNKNOWN | POOR FIT | single-frame | not installed | new pkg + small weights | `mediapipe` | CPU reliable, GPU unverified | Apache 2.0 | ~10-30ms | Default landmarker is single-person; crowded scenes need a person detector in front of it |
| RTMPose (rtmlib) | Yes | STRONG FIT | PROMISING | LIMITED alone | UNKNOWN | POOR FIT | single-frame | not installed | new pkg + small ONNX weights | `rtmlib`, `onnxruntime` | Plausible via ONNXRuntime CoreML EP, unverified | Apache 2.0 | <20ms (CPU-proven) | Newest/least locally battle-tested of the three pose options |
| HOI/relation detectors | Yes | PROMISING in principle | PROMISING in principle | PROMISING in principle | UNKNOWN | PROMISING in principle | single-frame | not found as a small off-the-shelf option | large/unclear | unclear | unclear | unclear/research-grade | unclear | Immature ecosystem for this size/deployment target |
| X3D/SlowFast/VideoMAE | Yes | LIMITED (person-level, not object-level) | POOR FIT | POOR FIT (vocabulary has no "first dance") | UNKNOWN | LIMITED | temporal (clip) | not installed | new pkg + weights (larger) | `pytorchvideo` or `transformers` extras | plausible | BSD/Apache family | Higher (clip-based) | Generic action vocabulary can't express our specific event distinction |
| Second VLM | No (same risk class) | — | — | — | — | — | either | rejected | — | — | — | — | — | Same hallucination risk class as Qwen, not truly independent |

## 8. C7349 vs. C7261 — which family has a plausible discriminating signal?

**Family A+B (pose + pair geometry) is the only family in this audit with a feature that
structurally could separate these two cases**: mutual body/shoulder orientation and normalized
inter-person distance are computable *because* keypoints exist, unlike a bounding box which has
no notion of "facing." Whether it *actually* separates them is untested and must not be assumed
— this is exactly why P5.11 would need to be a real bake-off, not a decision made here. Object
detection (closed, P5.8/P5.9) and generic action recognition (Family D, "dancing" vocabulary)
structurally cannot carry this distinction regardless of accuracy.

## 9. Ordinary dance vs. first dance

Same reasoning: pose-pair persistence/dominance (is this specific pair the only or clearly
dominant coordinated pair in frame, versus one of several similarly-postured pairs in a crowd)
is a feature only Family A+B can represent. Family D's generic "dancing" label cannot, by
vocabulary, express this distinction — confirmed limitation, not assumed.

## 10. Drone

Explicit risk, not assumed away: pose keypoint detectors generally need more resolved subjects
than a coarse box detector (harder to resolve 17 keypoints on a tiny, distant figure than to draw
one bounding box around it) — plausible that a drone frame yields 0 usable poses even where
Faster R-CNN found boxes. Required architecture, carried into any future bake-off: no usable
keypoints → UNKNOWN, never CONTRADICTED, exactly the rule already enforced for the object
detectors in P5.8/P5.9.

## 11. Cake cutting

No candidate family audited here offers strong native cake-action semantics. Pose estimation
could in principle contribute a "hand near a fixed object region" signal if combined with
Family C-style object/hand relation logic, but this is speculative and not evidenced. **Cake
remains the weaker half of this package's scope** regardless of which family is chosen next; no
family reviewed changes the P5.9 cake verdict (presence-only, no cutting-action evidence).

## 12. Elimination

- Generic object detection (Family, already closed in P5.8/P5.9): closed, not reopened.
- Family D (action/video): eliminated as primary — vocabulary structurally cannot express the
  needed distinction; heavier than pose candidates for no compensating advantage on this specific
  problem.
- Family E (optical flow): eliminated as standalone, already found insufficient in prior Source
  Moment research; only relevant combined with pose tracking, not on its own.
- Family F (second VLM): eliminated — same risk class as the thing being verified.
- Family C (HOI): not eliminated on principle, but no small off-the-shelf candidate was found
  mature enough to name concretely; parked as a longer-shot future option, not recommended for
  the immediate next test.

**Remaining: Family A/B (pose + pair geometry).** Within that family, three concrete candidates
(KeypointRCNN, MediaPipe Pose, RTMPose) all plausibly fit; the audit does not yet pick a winner
among them — that comparison is exactly what P5.11's bake-off should measure empirically rather
than guess at here.

## 13. Two-stage verifier concept

Consistent with the audit above: **Stage A** = multi-person pose detection (candidate TBD in
P5.11), **Stage B** = generic pair-relationship features computed on Stage A's output (mutual
orientation, normalized distance, and — if a temporal window is used — movement correlation
between the two tracked skeletons). Not implemented this package; the audit supports it as the
most promising *shape* of solution, not a guaranteed one.
