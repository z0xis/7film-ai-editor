"""P6.1: shadow moment-activation test. Uses the EXACT production VisionClassifier (CLIP
ViT-B/32, apps/api/sevenfilm/services/vision.py) and the EXACT unchanged production
MOMENT_PROMPTS (apps/api/sevenfilm/services/moments.py) to encode already-extracted 15 Agustos
frames and reproduce moments.py's own median-lift logic -- entirely in-memory, no DB write, no
production code modified or monkeypatched (imported and called as-is).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "apps/api")

import cv2
import numpy as np
from sevenfilm.services.moments import MOMENT_LIFT, MOMENT_NAMES, MOMENT_PROMPTS
from sevenfilm.services.vision import VisionClassifier

# Stage A frozen regression set -- reused verbatim from P5.3-P5.9's already-extracted frames.
# All sourced from 15 Agustos (confirmed by path in prior packages), no new extraction.
STAGE_A_CASES = [
    {"case_id": "genuine_first_dance_C7450", "path": "/tmp/p53_shadow_frames/095.jpg", "human_label": "first_dance_TP"},
    {"case_id": "genuine_first_dance_drone_A", "path": "/tmp/p53_shadow_frames/111.jpg", "human_label": "first_dance_TP"},
    {"case_id": "genuine_first_dance_drone_B", "path": "/tmp/p53_shadow_frames/109.jpg", "human_label": "first_dance_TP"},
    {"case_id": "genuine_first_dance_C7252", "path": "/tmp/p53_shadow_frames/037.jpg", "human_label": "first_dance_TP"},
    {"case_id": "genuine_first_dance_C7261", "path": "/tmp/p54_stress_frames/052.jpg", "human_label": "first_dance_TP"},
    {"case_id": "genuine_cake_cutting_C7309", "path": "/tmp/p54_stress_frames/066.jpg", "human_label": "cake_TP"},
    {"case_id": "HARMFUL_solo_performer_C7349", "path": "/tmp/p54_stress_frames/083.jpg", "human_label": "solo_performer_FP_confusable"},
    {"case_id": "ordinary_dance_crowd_076", "path": "/tmp/p53_shadow_frames/076.jpg", "human_label": "ordinary_dance_confusable"},
    {"case_id": "ordinary_dance_couple_in_crowd_079", "path": "/tmp/p53_shadow_frames/079.jpg", "human_label": "ordinary_dance_confusable"},
    {"case_id": "cake_visible_only_050", "path": "/tmp/p53_shadow_frames/050.jpg", "human_label": "cake_visible_only_confusable"},
    {"case_id": "ceremony_halluc_C7343", "path": "/tmp/p53_shadow_frames/061.jpg", "human_label": "henna_confusable"},
    {"case_id": "ceremony_halluc_C7344", "path": "/tmp/p53_shadow_frames/062.jpg", "human_label": "henna_confusable"},
    {"case_id": "ceremony_borderline_C7342", "path": "/tmp/p54_stress_frames/078.jpg", "human_label": "henna_confusable"},
]

# Background population for a real median: P5.3's 156-frame deterministic systematic sample of
# the actual 15A project, already extracted, spans the full timeline/asset diversity -- used
# ONLY to give moments.py's population-relative MOMENT_LIFT threshold a realistic context,
# exactly as the unchanged production algorithm requires (it is not a per-case threshold).
BACKGROUND_DIR = Path("/tmp/p53_shadow_frames")


def main() -> int:
    classifier = VisionClassifier()
    if not classifier._load():
        print("STAGE A STOPPED: production CLIP encoder unavailable")
        return 1

    prompts = list(MOMENT_PROMPTS.values())
    names = list(MOMENT_PROMPTS)

    # Text prompt embeddings via the exact same classifier/model moments.py uses.
    import torch

    with torch.inference_mode():
        inputs = classifier._processor(text=prompts, return_tensors="pt", padding=True)
        features = classifier._model.get_text_features(
            **{k: v.to(classifier._device) for k, v in inputs.items()}
        )
        if hasattr(features, "pooler_output"):
            features = features.pooler_output
        text_vecs = features.cpu().numpy()
    text_vecs = text_vecs / (np.linalg.norm(text_vecs, axis=1, keepdims=True) + 1e-9)

    def encode_path(path: str) -> np.ndarray | None:
        img = cv2.imread(path)
        if img is None:
            return None
        t0 = time.perf_counter()
        vec = classifier.encode([img])
        dt = time.perf_counter() - t0
        if vec is None:
            return None
        v = vec[0]
        return v / (np.linalg.norm(v) + 1e-9), dt

    # Background population (real project sample) for median context.
    background_paths = sorted(BACKGROUND_DIR.glob("*.jpg"))
    background_vecs = []
    background_latencies = []
    for p in background_paths:
        result = encode_path(str(p))
        if result is not None:
            v, dt = result
            background_vecs.append(v)
            background_latencies.append(dt)
    background_matrix = np.stack(background_vecs) if background_vecs else np.zeros((0, 512))
    background_similarity = background_matrix @ text_vecs.T if len(background_vecs) else None

    results = []
    for case in STAGE_A_CASES:
        p = Path(case["path"])
        if not p.exists():
            print(f"MISSING {case['case_id']}: {case['path']}")
            continue
        v, dt = encode_path(str(p))
        sims = (v @ text_vecs.T).tolist()
        per_prompt = {}
        for i, name in enumerate(names):
            sim = sims[i]
            if background_similarity is not None:
                median = float(np.median(background_similarity[:, i]))
                threshold_pass = median > 0 and sim >= median * MOMENT_LIFT
            else:
                median = None
                threshold_pass = None
            per_prompt[name] = {"similarity": round(sim, 4), "background_median": round(median, 4) if median is not None else None,
                                 "threshold_pass": threshold_pass}
        ranked = sorted(names, key=lambda n: -per_prompt[n]["similarity"])
        results.append({**case, "moment_similarities": per_prompt, "rank_order": ranked, "latency_s": round(dt, 3)})
        top = ranked[0]
        print(f"{case['case_id']:38s} top={top:12s} sim={per_prompt[top]['similarity']:.3f} "
              f"pass={per_prompt[top]['threshold_pass']}")

    out = {
        "moment_prompts": MOMENT_PROMPTS, "moment_names": MOMENT_NAMES, "moment_lift": MOMENT_LIFT,
        "background_population_n": len(background_vecs),
        "background_median_latency_s": round(float(np.median(background_latencies)), 3) if background_latencies else None,
        "cases": results,
    }
    Path("tools/fixtures/p6_1_stage_a_moment_activation.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nbackground population: {len(background_vecs)} frames")
    print(f"wrote {len(results)} case results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
