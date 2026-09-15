"""P5.2 bake-off: run CLIP, SigLIP2-base and SigLIP2-SO400M on the corrected/expanded 42-sample
golden corpus, scored against tools/fixtures/p5_2_golden_corpus_expanded.json. Read-only against
extracted JPG frames (no source media mutation, no production database touched).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

CATEGORIES = {
    "bride_prep": "the bride getting ready, hair and makeup, putting on the wedding dress",
    "groom_prep": "the groom getting ready, putting on his suit, tie, cufflinks or watch",
    "bride": "a cinematic wedding shot focused on the bride",
    "groom": "a cinematic wedding shot focused on the groom",
    "couple": "a cinematic wedding shot of the bride and groom together",
    "family_group": "a wedding shot of family members or wedding guests",
    "venue": "a wide establishing shot of a wedding venue or landscape",
    "drone_exterior": "an aerial drone shot of a landscape or venue exterior",
    "detail": "a close detail shot of wedding rings flowers dress table or decoration",
    "ceremony": "a wedding ceremony ritual, vow aisle altar or ring exchange",
    "party": "a wedding reception performance, band or crowd celebration",
    "party_dance": "people dancing at a wedding reception dance floor",
}
NAMES = list(CATEGORIES)
PROMPTS = list(CATEGORIES.values())


def _feat(x):
    return x.pooler_output if hasattr(x, "pooler_output") else x


def run_clip(image_paths: list[Path]) -> dict:
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    t0 = time.perf_counter()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True).to(device).eval()
    load_time = time.perf_counter() - t0

    text_inputs = processor(text=PROMPTS, return_tensors="pt", padding=True)
    text_inputs = {k: v.to(device) for k, v in text_inputs.items()}
    with torch.inference_mode():
        text_features = _feat(model.get_text_features(**text_inputs))
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)

    results, infer_times = [], []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        t1 = time.perf_counter()
        with torch.inference_mode():
            image_features = _feat(model.get_image_features(**inputs))
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            logits = (image_features @ text_features.T * model.logit_scale.exp()).float().cpu()
            probs = logits.softmax(dim=1).numpy()[0]
        infer_times.append(time.perf_counter() - t1)
        order = probs.argsort()[::-1]
        results.append({
            "file": path.name,
            "top1": NAMES[order[0]], "top1_score": round(float(probs[order[0]]), 3),
            "top3": [(NAMES[i], round(float(probs[i]), 3)) for i in order[:3]],
        })
    return {"backend": "clip_vision", "model_id": "openai/clip-vit-base-patch32",
            "load_time": round(load_time, 2), "infer_times": infer_times, "results": results}


def run_siglip2(image_paths: list[Path], model_id: str, backend_name: str) -> dict:
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    t0 = time.perf_counter()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModel.from_pretrained(model_id, local_files_only=True).to(device).eval()
    load_time = time.perf_counter() - t0

    results, infer_times = [], []
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(images=[image], text=PROMPTS, return_tensors="pt", padding="max_length")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        t1 = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=-1).float().cpu().numpy()[0]
        infer_times.append(time.perf_counter() - t1)
        order = probs.argsort()[::-1]
        results.append({
            "file": path.name,
            "top1": NAMES[order[0]], "top1_score": round(float(probs[order[0]]), 3),
            "top3": [(NAMES[i], round(float(probs[i]), 3)) for i in order[:3]],
        })
    return {"backend": backend_name, "model_id": model_id, "load_time": round(load_time, 2),
            "infer_times": infer_times, "results": results}


def score(run: dict, manifest: list[dict]) -> dict:
    by_file = {s["frame_file"]: s for s in manifest}
    total = strict = 0
    top3_hits = 0
    per_cat = Counter()
    per_cat_total = Counter()
    hard_neg_total = hard_neg_correct = 0
    for r in run["results"]:
        sample = by_file.get(r["file"])
        if sample is None:
            continue
        gt = sample["broad_label"]
        total += 1
        per_cat_total[gt] += 1
        top3_names = [n for n, _ in r["top3"]]
        if r["top1"] == gt:
            strict += 1
            per_cat[gt] += 1
        if gt in top3_names:
            top3_hits += 1
        if sample.get("hard_negative_group"):
            hard_neg_total += 1
            if r["top1"] == gt:
                hard_neg_correct += 1
    macro_vals = [per_cat[c] / per_cat_total[c] for c in per_cat_total if per_cat_total[c] > 0]
    macro = sum(macro_vals) / len(macro_vals) if macro_vals else 0.0
    times = run["infer_times"]
    times_sorted = sorted(times)
    n = len(times_sorted)
    return {
        "strict_top1": f"{strict}/{total} ({100*strict/total:.0f}%)" if total else "n/a",
        "top3": f"{top3_hits}/{total} ({100*top3_hits/total:.0f}%)" if total else "n/a",
        "macro_balanced": f"{100*macro:.0f}%",
        "hard_negative": f"{hard_neg_correct}/{hard_neg_total} ({100*hard_neg_correct/hard_neg_total:.0f}%)" if hard_neg_total else "n/a",
        "per_category": {c: f"{per_cat[c]}/{per_cat_total[c]}" for c in sorted(per_cat_total)},
        "median_infer_s": round(times_sorted[n // 2], 4) if n else None,
        "p90_infer_s": round(times_sorted[int(n * 0.9)], 4) if n else None,
        "max_infer_s": round(max(times_sorted), 4) if n else None,
        "load_time_s": run["load_time"],
    }


def main() -> int:
    frame_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/p52_frames")
    manifest_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("tools/fixtures/p5_2_golden_corpus_expanded.json")
    manifest = json.loads(manifest_path.read_text())
    image_paths = sorted(frame_dir.glob("*.jpg"))
    print(f"{len(image_paths)} frames, {len(manifest)} manifest entries")

    out = {}
    for name, fn in [
        ("clip", lambda: run_clip(image_paths)),
        ("siglip2_base", lambda: run_siglip2(image_paths, "google/siglip2-base-patch16-256", "siglip2_base")),
        ("siglip2_so400m", lambda: run_siglip2(image_paths, "google/siglip2-so400m-patch14-384", "siglip2_so400m")),
    ]:
        print(f"--- running {name} ---")
        try:
            run = fn()
        except Exception as e:  # noqa: BLE001
            print(f"{name} FAILED: {type(e).__name__}: {e}")
            out[name] = {"error": f"{type(e).__name__}: {e}"}
            continue
        out[name] = {"raw": run, "scored": score(run, manifest)}
        print(json.dumps(out[name]["scored"], indent=2))

    Path("/tmp/p52_bakeoff.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
