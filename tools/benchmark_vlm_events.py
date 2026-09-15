"""P5.2.15-19 VLM event/action test: Qwen3-VL-4B-Instruct on the event/action subset of the
golden corpus, single-frame vs before/current/after temporal context. Structured JSON output,
deterministic decoding. Read-only, no production code touched.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

EVENT_SUBSET_FILES = [
    "23_ceremony_henna_entrance.jpg", "34_bride_walking_entrance.jpg", "41_ceremony_entrance_walk.jpg",
    "33_couple_cake_feeding.jpg", "39_ceremony_cake_cutting.jpg",
    "22_couple_chandelier.jpg", "29_couple_embrace_henna.jpg", "40_party_first_dance.jpg",
    "24_party_dance_groom.jpg", "26_party_dance_group.jpg", "32_party_dance_guests.jpg", "36_bride_dancing_party.jpg",
    "30_ceremony_henna_seated.jpg",
]

PROMPT = """You are analyzing a single frame from real wedding video footage. Respond with ONLY a JSON object, no other text:
{"broad_scene": "<short phrase>", "subjects": ["..."], "action": "<short phrase describing what is happening>", "event_present": "<one of: first_dance, entrance, cake_cutting, ceremony_action, none>", "confidence": <0.0-1.0>}"""


def load_model():
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    model_id = "Qwen/Qwen3-VL-4B-Instruct"
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, dtype=torch.bfloat16, local_files_only=True
    ).to(device).eval()
    load_time = time.perf_counter() - t0
    return model, processor, device, load_time


def run_single_frame(model, processor, device, image_path: Path) -> dict:
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(device)
    t0 = time.perf_counter()
    import torch
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
    dt = time.perf_counter() - t0
    text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    return {"raw": text, "latency_s": round(dt, 2)}


def parse_json_loose(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    frame_dir = Path("/tmp/p52_frames")
    print("loading Qwen3-VL-4B-Instruct...")
    model, processor, device, load_time = load_model()
    print(f"loaded in {load_time:.1f}s on {device}")

    results = []
    for fname in EVENT_SUBSET_FILES:
        path = frame_dir / fname
        if not path.exists():
            print(f"MISSING {fname}")
            continue
        r = run_single_frame(model, processor, device, path)
        parsed = parse_json_loose(r["raw"])
        results.append({"file": fname, "latency_s": r["latency_s"], "raw": r["raw"], "parsed": parsed})
        print(fname, r["latency_s"], "s ->", parsed if parsed else r["raw"][:200])

    Path("/tmp/p52_vlm_single_frame.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
