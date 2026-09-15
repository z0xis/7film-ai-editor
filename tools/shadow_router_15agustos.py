"""P5.3 shadow router simulation on real 15 Agustos shots. Extracts a mid-shot frame for each
sampled shot (read-only against source media, no DB writes, no reanalysis), runs CLIP shadow
classification (same category vocabulary/prompts as production vision.py), and applies router
signals to determine escalation candidates. Does not call Qwen -- that is a separate step over
the selected escalation subset.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

# Same vocabulary as production CATEGORY_PROMPTS in apps/api/sevenfilm/services/vision.py
CATEGORY_PROMPTS = {
    "couple": "a cinematic wedding shot of the bride and groom together",
    "bride_prep": "the bride getting ready, hair and makeup, putting on the wedding dress",
    "groom_prep": "the groom getting ready, putting on his suit, tie, cufflinks or watch",
    "bride": "a cinematic wedding shot focused on the bride",
    "groom": "a cinematic wedding shot focused on the groom",
    "family": "a wedding shot of family members or wedding guests",
    "venue": "a wide establishing shot of a wedding venue or landscape",
    "detail": "a close detail shot of wedding rings flowers dress table or decoration",
    "ceremony": "a wedding ceremony vow aisle altar or ring exchange",
    "party": "a lively wedding reception dance floor celebration or party",
}
NAMES = list(CATEGORY_PROMPTS)
STORY_CRITICAL = {"ceremony", "party", "couple", "bride_prep", "groom_prep"}

FRAME_DIR = Path("/tmp/p53_shadow_frames")
FRAME_DIR.mkdir(exist_ok=True)


def extract_frame(path: str, start_frame: int, duration_frames: int, frame_rate: str, out: Path) -> bool:
    num, den = frame_rate.split("/")
    fps = float(num) / float(den)
    mid_frame = start_frame + duration_frames // 2
    t = mid_frame / fps
    cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=480:-1", str(out)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    return out.exists()


def _feat(x):
    return x.pooler_output if hasattr(x, "pooler_output") else x


def load_clip():
    import torch
    from transformers import CLIPModel, CLIPProcessor

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32", local_files_only=True).to(device).eval()
    prompts = list(CATEGORY_PROMPTS.values())
    text_inputs = processor(text=prompts, return_tensors="pt", padding=True)
    text_inputs = {k: v.to(device) for k, v in text_inputs.items()}
    with torch.inference_mode():
        text_features = _feat(model.get_text_features(**text_inputs))
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
    return model, processor, device, text_features


def classify(model, processor, device, text_features, image_path: Path) -> dict:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=[image], return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.inference_mode():
        image_features = _feat(model.get_image_features(**inputs))
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        logits = (image_features @ text_features.T * model.logit_scale.exp()).float().cpu()
        probs = logits.softmax(dim=1).numpy()[0]
    order = probs.argsort()[::-1]
    top1, top2 = NAMES[order[0]], NAMES[order[1]]
    return {
        "top1": top1, "top1_score": round(float(probs[order[0]]), 3),
        "top2": top2, "top2_score": round(float(probs[order[1]]), 3),
        "margin": round(float(probs[order[0]] - probs[order[1]]), 3),
    }


def router_decision(pred: dict) -> dict:
    conf = pred["top1_score"]
    margin = pred["margin"]
    not_story_crit = pred["top1"] not in STORY_CRITICAL
    return {
        "r1_low_confidence": conf < 0.6,
        "r2_low_margin": margin < 0.15,
        "r3_not_story_critical": not_story_crit,
        "r4_union": not_story_crit or margin < 0.15,
        "r4b_conservative": not_story_crit and margin < 0.3,
    }


def main() -> int:
    candidates = []
    with open("/tmp/p53_shadow_candidates.txt") as f:
        for line in f:
            sid, path, sf, dur, fr, cat = line.rstrip("\n").split("|")
            candidates.append({"shot_id": sid, "path": path, "start_frame": int(sf),
                                "duration_frames": int(dur), "frame_rate": fr, "fallback_category": cat})

    print("loading CLIP...")
    model, processor, device, text_features = load_clip()
    print(f"loaded on {device}")

    results = []
    for i, c in enumerate(candidates):
        out = FRAME_DIR / f"{i:03d}.jpg"
        if not out.exists():
            ok = extract_frame(c["path"], c["start_frame"], c["duration_frames"], c["frame_rate"], out)
            if not ok:
                print(f"SKIP {i}: extraction failed for {c['path']}")
                continue
        t0 = time.perf_counter()
        pred = classify(model, processor, device, text_features, out)
        dt = time.perf_counter() - t0
        decisions = router_decision(pred)
        entry = {**c, "frame_index": i, "frame_path": str(out), "clip_pred": pred,
                 "router": decisions, "clip_latency_s": round(dt, 4)}
        results.append(entry)
        if i % 20 == 0:
            print(f"{i}/{len(candidates)} done")

    Path("tools/fixtures/p5_3_shadow_router_15agustos.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {len(results)} results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
