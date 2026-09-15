"""P5.1 bake-off: run CLIP and SigLIP2 on the same real, visually-verified frame corpus with
a shared broad-category prompt set. Read-only against extracted JPG frames (no source media
mutation). No production database touched.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

CATEGORIES = {
    "bride_prep": "the bride getting ready, hair and makeup, putting on the wedding dress",
    "groom_prep": "the groom getting ready, putting on his suit, tie, cufflinks or watch",
    "bride": "a cinematic wedding shot focused on the bride",
    "groom": "a cinematic wedding shot focused on the groom",
    "couple": "a cinematic wedding shot of the bride and groom together",
    "family": "a wedding shot of family members or wedding guests",
    "venue": "a wide establishing shot of a wedding venue or landscape",
    "detail": "a close detail shot of wedding rings flowers dress table or decoration",
    "ceremony": "a wedding ceremony vow aisle altar or ring exchange",
    "party": "a lively wedding reception dance floor celebration or party",
}


def run_clip(image_paths: list[Path]) -> dict:
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    t0 = time.perf_counter()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True).to(device).eval()
    load_time = time.perf_counter() - t0

    names = list(CATEGORIES)
    prompts = list(CATEGORIES.values())
    text_inputs = processor(text=prompts, return_tensors="pt", padding=True)
    text_inputs = {k: v.to(device) for k, v in text_inputs.items()}
    with torch.inference_mode():
        text_features = model.get_text_features(**text_inputs)
        if hasattr(text_features, "pooler_output"):
            text_features = text_features.pooler_output
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    results = []
    infer_times = []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        t1 = time.perf_counter()
        with torch.inference_mode():
            image_features = model.get_image_features(**inputs)
            if hasattr(image_features, "pooler_output"):
                image_features = image_features.pooler_output
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ text_features.T * model.logit_scale.exp()).float().cpu()
            probs = logits.softmax(dim=1).numpy()[0]
        infer_times.append(time.perf_counter() - t1)
        order = probs.argsort()[::-1]
        results.append({
            "file": path.name,
            "top1": names[order[0]], "top1_score": round(float(probs[order[0]]), 3),
            "top3": [(names[i], round(float(probs[i]), 3)) for i in order[:3]],
        })
    return {"backend": "clip_vision", "load_time": round(load_time, 2),
            "infer_times": infer_times, "results": results}


def run_siglip2(image_paths: list[Path]) -> dict:
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    model_id = "google/siglip2-so400m-patch14-384"
    t0 = time.perf_counter()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModel.from_pretrained(model_id, local_files_only=True).to(device).eval()
    load_time = time.perf_counter() - t0

    names = list(CATEGORIES)
    prompts = list(CATEGORIES.values())

    results = []
    infer_times = []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], text=prompts, return_tensors="pt", padding="max_length")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        t1 = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=-1).float().cpu().numpy()[0]
        infer_times.append(time.perf_counter() - t1)
        order = probs.argsort()[::-1]
        results.append({
            "file": path.name,
            "top1": names[order[0]], "top1_score": round(float(probs[order[0]]), 3),
            "top3": [(names[i], round(float(probs[i]), 3)) for i in order[:3]],
        })
    return {"backend": "siglip2_so400m", "load_time": round(load_time, 2),
            "infer_times": infer_times, "results": results}


def main() -> int:
    frame_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/p51_frames")
    image_paths = sorted(frame_dir.glob("*.jpg"))
    print(f"{len(image_paths)} frames")

    clip_result = run_clip(image_paths)
    siglip_result = run_siglip2(image_paths)

    out = {"clip": clip_result, "siglip2": siglip_result}
    Path("/tmp/p51_bakeoff.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
