"""P5.6: run all 4 pre-registered prompts (V1-V4) on the frozen 17-case set. Cache key includes
prompt hash so a wording edit invalidates prior entries. Ground truth (human_verdict, event
labels) lives ONLY in this manifest for post-hoc scoring -- it is never passed to the model or
to the normalization/decision functions, which take only (parsed_json, prompt_version).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shadow_prompt_family import PROMPTS, prompt_hash

CACHE_PATH = Path("tools/fixtures/p5_6_prompt_cache.json")

# Frozen case set -- selected and captioned with human labels established from THIS SESSION's
# earlier direct visual inspection (P5.3/P5.4/P5.5), before any V2-V4 prompt was run. No new
# candidate discovery was performed to build this set -- reused verified frames only.
CASES = [
    {"case_id": "genuine_first_dance_C7450", "path": "/tmp/p53_shadow_frames/095.jpg", "event": "first_dance", "human_verdict": "TP", "episode": "C7450"},
    {"case_id": "genuine_first_dance_drone_A", "path": "/tmp/p53_shadow_frames/111.jpg", "event": "first_dance", "human_verdict": "TP", "episode": "drone_DJI_0528"},
    {"case_id": "genuine_first_dance_drone_B", "path": "/tmp/p53_shadow_frames/109.jpg", "event": "first_dance", "human_verdict": "TP", "episode": "drone_DJI_0528"},
    {"case_id": "genuine_first_dance_C7252", "path": "/tmp/p53_shadow_frames/037.jpg", "event": "first_dance", "human_verdict": "TP", "episode": "C7252"},
    {"case_id": "genuine_first_dance_C7261", "path": "/tmp/p54_stress_frames/052.jpg", "event": "first_dance", "human_verdict": "TP", "episode": "C7261"},
    {"case_id": "genuine_cake_cutting_C7309", "path": "/tmp/p54_stress_frames/066.jpg", "event": "cake_cutting", "human_verdict": "TP", "episode": "C7309"},
    {"case_id": "HARMFUL_solo_performer_C7349", "path": "/tmp/p54_stress_frames/083.jpg", "event": "first_dance", "human_verdict": "FP", "episode": "C7349"},
    {"case_id": "ceremony_halluc_C7343", "path": "/tmp/p53_shadow_frames/061.jpg", "event": "ceremony_action", "human_verdict": "FP", "episode": "C7343"},
    {"case_id": "ceremony_halluc_C7344", "path": "/tmp/p53_shadow_frames/062.jpg", "event": "ceremony_action", "human_verdict": "FP", "episode": "C7344"},
    {"case_id": "ceremony_borderline_C7342", "path": "/tmp/p54_stress_frames/078.jpg", "event": "ceremony_action", "human_verdict": "FP", "episode": "C7342"},
    {"case_id": "ordinary_dance_crowd_076", "path": "/tmp/p53_shadow_frames/076.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_076"},
    {"case_id": "ordinary_dance_couple_in_crowd_079", "path": "/tmp/p53_shadow_frames/079.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_079"},
    {"case_id": "cake_visible_only_050", "path": "/tmp/p53_shadow_frames/050.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_050"},
    {"case_id": "ambiguous_napkin_090", "path": "/tmp/p53_shadow_frames/090.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_090"},
    {"case_id": "gift_table_detail_012", "path": "/tmp/p53_shadow_frames/012.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_012"},
    {"case_id": "bride_mirror_019", "path": "/tmp/p53_shadow_frames/019.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_019"},
    {"case_id": "wide_reception_dancing_155", "path": "/tmp/p53_shadow_frames/155.jpg", "event": "none", "human_verdict": "TN", "episode": "shot_155"},
]


def load_model():
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    model_id = "Qwen/Qwen3-VL-4B-Instruct"
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, dtype=torch.bfloat16, local_files_only=True
    ).to(device).eval()
    return model, processor, device


def run_prompt(model, processor, device, image_path: Path, prompt_text: str) -> dict:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt_text}]}]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(device)
    t0 = time.perf_counter()
    try:
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=220, do_sample=False)
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


def cache_key(path: str, version: str) -> str:
    return f"{path}::{version}::{prompt_hash(version)}::Qwen/Qwen3-VL-4B-Instruct::p5.6-shadow-v1"


def main() -> int:
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}

    to_run = []
    for case in CASES:
        if not Path(case["path"]).exists():
            print(f"MISSING {case['case_id']}: {case['path']}")
            continue
        for version in PROMPTS:
            key = cache_key(case["path"], version)
            if key not in cache:
                to_run.append((case, version, key))

    print(f"{len(CASES)} cases x {len(PROMPTS)} prompts = {len(CASES) * len(PROMPTS)} total combos, "
          f"{len(to_run)} need a fresh call")

    if to_run:
        print("loading Qwen3-VL-4B-Instruct...")
        model, processor, device = load_model()
        for case, version, key in to_run:
            r = run_prompt(model, processor, device, Path(case["path"]), PROMPTS[version])
            parsed = parse_json_loose(r["raw"])
            cache[key] = {
                "raw": r["raw"], "parsed": parsed, "parse_failed": parsed is None and r["exception"] is None,
                "exception": r["exception"], "latency_s": r["latency_s"],
            }
            status = "EXCEPTION" if r["exception"] else (parsed if parsed else "PARSE_FAILED")
            print(f"{case['case_id']:38s} {version:28s} -> {status}")
            CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))

    results = []
    for case in CASES:
        if not Path(case["path"]).exists():
            continue
        per_prompt = {}
        for version in PROMPTS:
            key = cache_key(case["path"], version)
            per_prompt[version] = cache[key]
        results.append({**case, "prompt_results": per_prompt})

    Path("tools/fixtures/p5_6_prompt_robustness_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {len(results)} case results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
