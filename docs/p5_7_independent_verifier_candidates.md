# P5.7 — Independent Verifier Model Selection

Audit + candidate comparison + controlled bake-off PLAN. **No model was downloaded in this
package.** Scope: select a genuinely different-architecture, lightweight local verifier for the
narrow physical-evidence questions P5.5/P5.6 could not answer independently of Qwen itself —
not a general VLM re-run, not an event classifier.

## 1. Local environment audit

```
Machine: Apple M1 Pro, 16 GB unified memory
Disk free: 34 GB
torch: 2.14.0 (MPS available)
torchvision: 0.29.0 (already installed -- includes torchvision.models.detection)
transformers: 5.16.1
opencv-python: 5.0.0.93 (already used for YuNet face detector, P5.5/P5.6)
```

No object/pose detector weights are cached yet (`~/.cache/torch/hub/checkpoints/` does not
exist). No `ultralytics`, `mediapipe`, `timm`, or other detection-specific package is installed.
CLIP and SigLIP2 (encoder-only, not detectors) and Qwen3-VL-4B are already cached from P5.1-P5.6
but none of them is a genuinely different architecture from the classifier/verifier already in
use -- they don't qualify as an independent signal for this package's purpose.

## 2. What the narrow task actually needs

Not an event classifier. Four physical-evidence questions, answerable by classic object/person
detection rather than a second VLM:

1. **Person count and rough position** -- solo performer vs. two co-located primary people.
2. **Proximity/pairing** -- are two person boxes close together (candidate "interacting pair")
   vs. scattered across a crowd.
3. **Object presence** -- is a cake actually in frame (COCO class 55, "cake").
4. **Coarse interaction** -- a hand/person bounding box overlapping the cake box, as a weak proxy
   for "touching/cutting" vs. "merely visible," without claiming to detect the cutting motion
   itself (a detector gives boxes per frame, not the temporal action).

This is deliberately coarser than what Qwen reports -- the point is a hard, non-language-model
count/box signal to catch exactly the failure P5.5/P5.6 found: Qwen's own claim of "two people
interacting" cannot be trusted to mean two people are actually both present.

## 3. Candidates compared

| Candidate | Params / weights size | Architecture | License | MPS / Apple Silicon | Est. latency (single frame) | Est. peak memory | Fit for this task |
|---|---|---|---|---|---|---|---|
| **torchvision `ssdlite320_mobilenet_v3_large`** (COCO) | ~13.4M params, ~13 MB weights | CNN, single-stage SSD on MobileNetV3 backbone | **BSD-3-Clause** (torchvision itself) | Runs on CPU reliably; MPS support for standard conv/NMS ops in torch 2.x is generally functional but not exhaustively verified on this exact model -- real risk, not assumed | ~15-40ms CPU, likely <20ms MPS if ops are supported | Low (~200-400MB resident) | **Best first candidate** -- has "person" and "cake" as native COCO classes, already-installed package, permissive license, minimal download |
| torchvision `fasterrcnn_mobilenet_v3_large_320_fpn` | ~19M params, ~74 MB | CNN, two-stage Faster R-CNN, MobileNetV3-FPN backbone | BSD-3-Clause | Same MPS caveat as above | ~40-100ms CPU | Moderate (~400-700MB) | Fallback if SSDLite's box quality is too coarse -- meaningfully more accurate, still light |
| torchvision `fasterrcnn_resnet50_fpn_v2` | ~43M params, ~167 MB | CNN, two-stage Faster R-CNN, ResNet50-FPN backbone | BSD-3-Clause | Same caveat | ~100-300ms CPU, better on MPS | Higher (~1-1.5GB) | Only worth it if the two lighter models both underperform -- disproportionate cost for a coarse task |
| Ultralytics YOLOv8n (COCO) | ~3.2M params, ~6 MB | CNN, single-stage YOLO | **AGPL-3.0** (Ultralytics package) | Excellent, first-class MPS/CoreML export support | ~5-15ms | Low | Fastest and smallest, but the AGPL-3.0 license is a real constraint for a commercial product if the linked code is ever distributed as a network service -- flagged, not silently ignored |
| MediaPipe (Google, pose/hand landmarks) | Small (~5-30 MB per task model) | CNN + landmark regression, mobile-optimized | Apache 2.0 | Good on Apple Silicon (CPU delegate; GPU delegate is Android/iOS-native, not guaranteed on macOS Python bindings) | ~10-30ms | Low | Requires a **new pip package** (`mediapipe` is not installed) -- more setup than the torchvision options for a task that doesn't need pose landmarks, just boxes/counts |
| Existing YuNet face detector (already in use, P5.5/P5.6) | ~1MB ONNX | CNN face detector | Apache-2.0-family (OpenCV Zoo) | Already working via OpenCV DNN | ~5-10ms | Negligible | **Already audited as insufficient alone** -- misses profiles, backs-turned, and drone-altitude subjects (P5.5/P5.6 findings); still useful as one signal among several, not a standalone verifier |

## 4. Why torchvision SSDLite is the recommended first candidate

- **Zero new dependency** -- `torchvision` is already in `.venv`, so nothing new to install beyond the ~13MB weight file itself.
- **Permissive license** -- BSD-3-Clause, no AGPL exposure (unlike Ultralytics YOLOv8).
- **Genuinely different architecture family** -- a CNN object detector shares no failure modes with a VLM's language-conditioned visual reasoning; a hallucinated "second person" or "cutting action" from Qwen has no mechanism to also fool a box-regression detector the same way.
- **Native classes for both open questions** -- COCO includes both "person" (class 1) and "cake" (class 55) out of the box; no fine-tuning needed for a first pass.
- **Small enough to trial cheaply** -- if the bake-off shows SSDLite's boxes are too coarse (missed persons, no cake detections on our actual wedding footage lighting/angles), the fallback to Faster R-CNN MobileNetV3 is a ~74MB step up, not a new architecture family.

## 5. Known limitations to test for, not assume away

- COCO's "person" class is trained on ordinary photography; drone-altitude, back-turned, or motion-blurred wedding dancers (the exact case that matters for the drone first-dance episode) may be missed or under-detected, mirroring YuNet's known gap -- **must be explicitly tested on the drone case before trusting any output**.
- COCO's "cake" class was trained on ordinary photographed cakes, not necessarily large tiered wedding cakes at night under string lights -- detection reliability on our actual footage is unverified until tested.
- Bounding-box proximity is not the same as physical touching or a cutting motion -- a coarse detector can only ever be a *contradiction* signal (no plausible person nearby a cake at all) or a *count* signal (one dominant person vs. two), never proof an event genuinely happened. This must not be oversold as more capable than it is.
- MPS operator coverage for the detection post-processing ops (NMS, RoI-Align) has historically had gaps in older PyTorch/torchvision releases -- with torch 2.14 this is likely resolved but was not verified this package (no model was run).

## 6. Controlled bake-off PLAN (not executed this package)

1. Download **only** `SSDLite320_MobileNet_V3_Large_Weights.COCO_V1` (~13MB) via `torchvision.models.detection.ssdlite320_mobilenet_v3_large(weights=...)`.
2. Run it, read-only, against the same frozen P5.5/P5.6 17-case set (already-extracted JPGs, no new frame extraction) -- zero new video/DB access needed.
3. For each case, extract: person-box count, largest-two-box proximity (candidate "pair" heuristic), cake-box presence, person-box/cake-box overlap.
4. Compare directly against the same cases' known human verdicts and Qwen's atomic claims -- specifically:
   - Does it correctly show **1 dominant person box** for `HARMFUL_solo_performer_C7349` (the known hallucination case)?
   - Does it correctly show **2 person boxes** for the drone first-dance frames, despite altitude/back-turned framing (the known hard case)?
   - Does it detect the cake box for `genuine_cake_cutting_C7309` and `cake_visible_only_050`?
5. Report detection rate, false-negative rate on the drone case specifically, and whether MPS ran cleanly or fell back to CPU.
6. Only if this first pass looks promising, consider the Faster R-CNN MobileNetV3 fallback on the same set.

This plan is deliberately small: one ~13MB download, no new pip package, evaluated against
frames that already exist locally, explicitly checked against the exact failure cases already
known from P5.5/P5.6 rather than a fresh, larger evaluation corpus.
