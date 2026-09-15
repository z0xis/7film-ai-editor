"""P5.4: run Qwen3-VL-4B single-frame on ALL R4b candidates from the frozen 156-shot 15A shadow
sample, reusing P5.3's cache where the exact (path, start_frame) pair was already called.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shadow_qwen_cache import load_cache, make_key, save_cache, seed_from_p53

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
    return model, processor, device, time.perf_counter() - t0


def run_single_frame(model, processor, device, image_path: Path) -> dict:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(device)
    t0 = time.perf_counter()
    try:
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=200, do_sample=False)
        dt = time.perf_counter() - t0
        text = processor.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return {"raw": text, "latency_s": round(dt, 2), "exception": None}
    except Exception as e:  # noqa: BLE001
        return {"raw": None, "latency_s": round(time.perf_counter() - t0, 2), "exception": f"{type(e).__name__}: {e}"}


def parse_json_loose(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    router_data = json.loads(Path("tools/fixtures/p5_3_shadow_router_15agustos.json").read_text())
    p53_results = json.loads(Path("tools/fixtures/p5_3_qwen_shadow_results.json").read_text())

    cache = load_cache()
    seeded = seed_from_p53(cache, p53_results, router_data)
    print(f"seeded {seeded} entries from P5.3 into P5.4 cache")

    r4b = [e for e in router_data if e["router"]["r4b_conservative"]]
    print(f"{len(r4b)} R4b candidates total")

    to_run = []
    cache_hits = 0
    for e in r4b:
        key = make_key(e["path"], e["start_frame"])
        if key in cache:
            cache_hits += 1
        else:
            to_run.append(e)
    print(f"cache hits: {cache_hits}, fresh calls needed: {len(to_run)}")

    if to_run:
        print("loading Qwen3-VL-4B-Instruct...")
        model, processor, device, load_time = load_model()
        print(f"loaded in {load_time:.1f}s on {device}")
        for e in to_run:
            path = Path(e["frame_path"])
            r = run_single_frame(model, processor, device, path)
            parsed = parse_json_loose(r["raw"])
            key = make_key(e["path"], e["start_frame"])
            cache[key] = {
                "raw": r["raw"], "parsed": parsed, "parse_failed": parsed is None and r["exception"] is None,
                "exception": r["exception"], "latency_s": r["latency_s"], "source": "p5.4-fresh",
            }
            status = "EXCEPTION" if r["exception"] else (parsed.get("event_present") if parsed else "PARSE_FAILED")
            print(f"{e['frame_index']:03d} {e['clip_pred']['top1']:12s} -> {status}  ({r['latency_s']}s)")
            save_cache(cache)  # incremental save so partial progress survives an interrupt

    # Build final result set for all R4b candidates (cached + fresh)
    results = []
    for e in r4b:
        key = make_key(e["path"], e["start_frame"])
        c = cache[key]
        results.append({
            "shot_id": e["shot_id"], "frame_index": e["frame_index"], "frame_path": e["frame_path"],
            "path": e["path"], "start_frame": e["start_frame"], "clip_pred": e["clip_pred"],
            "router_reason": {k: v for k, v in e["router"].items() if v},
            "latency_s": c["latency_s"], "raw": c["raw"], "parsed": c["parsed"],
            "parse_failed": c["parse_failed"], "exception": c["exception"], "cache_source": c["source"],
        })

    Path("tools/fixtures/p5_4_qwen_r4b_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {len(results)} R4b results ({cache_hits} cached, {len(to_run)} fresh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
