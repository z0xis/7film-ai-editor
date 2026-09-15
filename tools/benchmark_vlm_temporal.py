"""P5.2 VLM temporal closure: Qwen3-VL-4B-Instruct with BEFORE/CURRENT/AFTER temporal context on
the same 13-sample event subset as the single-frame baseline (7901d30). Same structured schema as
the single-frame run for direct comparability. Deterministic decoding, no ground-truth leakage,
no per-case prompt tuning. Read-only against extracted frames.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

TEMPORAL_PROMPT = """You are analyzing THREE frames extracted in chronological order from the same real wedding video clip: BEFORE (an earlier moment), CURRENT (the moment being evaluated), AFTER (a later moment). Use the sequence to understand motion and context, but judge the event for the CURRENT moment specifically. Respond with ONLY a JSON object, no other text:
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


def run_temporal(model, processor, device, before_path: Path, current_path: Path, after_path: Path) -> dict:
    import torch
    from PIL import Image

    before_img = Image.open(before_path).convert("RGB")
    current_img = Image.open(current_path).convert("RGB")
    after_img = Image.open(after_path).convert("RGB")
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "BEFORE:"},
            {"type": "image", "image": before_img},
            {"type": "text", "text": "CURRENT:"},
            {"type": "image", "image": current_img},
            {"type": "text", "text": "AFTER:"},
            {"type": "image", "image": after_img},
            {"type": "text", "text": TEMPORAL_PROMPT},
        ],
    }]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(device)
    t0 = time.perf_counter()
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
    manifest = json.loads(Path("tools/fixtures/p5_2_temporal_manifest.json").read_text())
    print("loading Qwen3-VL-4B-Instruct...")
    model, processor, device, load_time = load_model()
    print(f"loaded in {load_time:.1f}s on {device}")

    results = []
    for entry in manifest:
        before_p = Path(entry["before_frame_path"])
        current_p = Path(entry["current_frame_path"])
        after_p = Path(entry["after_frame_path"])
        r = run_temporal(model, processor, device, before_p, current_p, after_p)
        parsed = parse_json_loose(r["raw"])
        parse_failed = parsed is None
        results.append({
            "file": entry["frame_file"], "latency_s": r["latency_s"], "raw": r["raw"],
            "parsed": parsed, "parse_failed": parse_failed,
        })
        print(entry["frame_file"], r["latency_s"], "s ->", parsed if parsed else f"PARSE_FAILED: {r['raw'][:200]}")

    Path("/tmp/p52_vlm_temporal.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
