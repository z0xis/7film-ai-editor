"""P5.3: run Qwen3-VL-4B-Instruct single-frame on the real escalation candidates selected by the
shadow router (tools/shadow_router_15agustos.py output, R3 signal). No temporal input (P5.2
showed no incremental value). No DB writes, no reanalysis, no production code touched.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

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
    router_field = sys.argv[1] if len(sys.argv) > 1 else "r3_not_story_critical"
    shadow = json.loads(Path("tools/fixtures/p5_3_shadow_router_15agustos.json").read_text())
    escalated = [e for e in shadow if e["router"][router_field]]
    print(f"{len(escalated)} escalated candidates for router={router_field}")

    print("loading Qwen3-VL-4B-Instruct...")
    model, processor, device, load_time = load_model()
    print(f"loaded in {load_time:.1f}s on {device}")

    results = []
    for e in escalated:
        path = Path(e["frame_path"])
        r = run_single_frame(model, processor, device, path)
        parsed = parse_json_loose(r["raw"])
        parse_failed = parsed is None and r["exception"] is None
        entry = {
            "shot_id": e["shot_id"], "frame_index": e["frame_index"], "frame_path": e["frame_path"],
            "path": e["path"], "start_frame": e["start_frame"],
            "clip_pred": e["clip_pred"], "router_reason": {k: v for k, v in e["router"].items() if v},
            "latency_s": r["latency_s"], "raw": r["raw"], "parsed": parsed,
            "parse_failed": parse_failed, "exception": r["exception"],
        }
        results.append(entry)
        status = "EXCEPTION" if r["exception"] else ("PARSE_FAILED" if parse_failed else parsed.get("event_present"))
        print(f"{e['frame_index']:03d} {e['clip_pred']['top1']:12s} -> {status}  ({r['latency_s']}s)")

    Path("/tmp/p53_qwen_shadow_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {len(results)} results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
