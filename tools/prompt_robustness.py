"""P5.2.13 prompt robustness: run CLIP and SigLIP2-SO400M with 3 controlled prompt styles over
the same 42-sample corpus and compare ranking/accuracy stability. Read-only, no production code.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CONCEPTS = {
    "bride_prep": "the bride getting ready",
    "groom_prep": "the groom getting ready",
    "bride": "the bride",
    "groom": "the groom",
    "couple": "the bride and groom together",
    "family_group": "family members or wedding guests",
    "venue": "a wedding venue or landscape",
    "drone_exterior": "an aerial drone view of a landscape or venue",
    "detail": "a close detail of rings, flowers, dress, table or decoration",
    "ceremony": "a wedding ceremony ritual or ring exchange",
    "party": "a wedding reception performance or celebration",
    "party_dance": "people dancing at a wedding reception",
}
NAMES = list(CONCEPTS)

STYLES = {
    "style1_bare": {k: v for k, v in CONCEPTS.items()},
    "style2_sentence": {k: f"a photo of {v}" for k, v in CONCEPTS.items()},
    "style3_cinematic": {k: f"a cinematic wedding photograph of {v}" for k, v in CONCEPTS.items()},
}


def _feat(x):
    return x.pooler_output if hasattr(x, "pooler_output") else x


def run_clip_style(image_paths, prompts):
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True).to(device).eval()
    text_inputs = processor(text=prompts, return_tensors="pt", padding=True)
    text_inputs = {k: v.to(device) for k, v in text_inputs.items()}
    with torch.inference_mode():
        text_features = _feat(model.get_text_features(**text_inputs))
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
    results = []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.inference_mode():
            image_features = _feat(model.get_image_features(**inputs))
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ text_features.T * model.logit_scale.exp()).float().cpu()
            probs = logits.softmax(dim=1).numpy()[0]
        order = probs.argsort()[::-1]
        results.append({"file": path.name, "top1": NAMES[order[0]], "margin": round(float(probs[order[0]] - probs[order[1]]), 3)})
    return results


def run_siglip2_style(image_paths, prompts):
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    model_id = "google/siglip2-so400m-patch14-384"
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModel.from_pretrained(model_id, local_files_only=True).to(device).eval()
    results = []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], text=prompts, return_tensors="pt", padding="max_length")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.inference_mode():
            outputs = model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=-1).float().cpu().numpy()[0]
        order = probs.argsort()[::-1]
        results.append({"file": path.name, "top1": NAMES[order[0]], "margin": round(float(probs[order[0]] - probs[order[1]]), 3)})
    return results


def score(results, manifest_by_file):
    correct = sum(1 for r in results if manifest_by_file.get(r["file"], {}).get("broad_label") == r["top1"])
    return correct, len(results)


def main() -> int:
    frame_dir = Path("/tmp/p52_frames")
    manifest = json.loads(Path("tools/fixtures/p5_2_golden_corpus_expanded.json").read_text())
    by_file = {s["frame_file"]: s for s in manifest}
    image_paths = sorted(frame_dir.glob("*.jpg"))

    out = {"clip": {}, "siglip2_so400m": {}}
    for style_name, concept_map in STYLES.items():
        prompts = [concept_map[n] for n in NAMES]
        t0 = time.perf_counter()
        clip_results = run_clip_style(image_paths, prompts)
        clip_dt = time.perf_counter() - t0
        c, n = score(clip_results, by_file)
        out["clip"][style_name] = {"accuracy": f"{c}/{n} ({100*c/n:.0f}%)", "prompts_sample": prompts[:2], "wall_s": round(clip_dt, 1)}
        print("clip", style_name, out["clip"][style_name])

    for style_name, concept_map in STYLES.items():
        prompts = [concept_map[n] for n in NAMES]
        t0 = time.perf_counter()
        sig_results = run_siglip2_style(image_paths, prompts)
        sig_dt = time.perf_counter() - t0
        c, n = score(sig_results, by_file)
        out["siglip2_so400m"][style_name] = {"accuracy": f"{c}/{n} ({100*c/n:.0f}%)", "prompts_sample": prompts[:2], "wall_s": round(sig_dt, 1)}
        print("siglip2_so400m", style_name, out["siglip2_so400m"][style_name])

    Path("/tmp/p52_prompt_robustness.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
