"""P5.5 E2: prompt-paraphrase stability check. Same semantic atomic question, differently worded,
re-run ONLY on the two cases where E1 disagreed with human ground truth (the harmful FP, correctly
caught, and C7261, a genuine TP that E1 wrongly contradicted) to see whether the disagreement is
stable across wording or an artifact of one specific phrasing. Not treated as independent evidence
-- same model family -- only a stability signal per P5.5 section 13/14.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

PARAPHRASE_PROMPT = """Examine this photograph carefully. Without guessing anyone's identity or role,
describe only what is physically observable. Respond with ONLY a JSON object:
{
  "how_many_people_are_clearly_the_main_focus": <integer>,
  "is_there_a_paired_couple_moving_together": <true/false>,
  "is_one_individual_performing_while_others_watch": <true/false>,
  "body_movement_suggests_dancing": <true/false>,
  "confidence_in_this_read": <0.0-1.0>
}"""

CASES = [
    ("HARMFUL_solo_performer_C7349", "/tmp/p54_stress_frames/083.jpg"),
    ("genuine_first_dance_C7261", "/tmp/p54_stress_frames/052.jpg"),
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


def run(model, processor, device, image_path: Path) -> dict:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": PARAPHRASE_PROMPT}]}]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
    ).to(device)
    t0 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=150, do_sample=False)
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
    print("loading Qwen3-VL-4B-Instruct...")
    model, processor, device = load_model()
    results = []
    for label, path in CASES:
        r = run(model, processor, device, Path(path))
        parsed = parse_json_loose(r["raw"])
        results.append({"label": label, "path": path, "raw": r["raw"], "parsed": parsed, "latency_s": r["latency_s"]})
        print(f"{label}: {parsed}")
    Path("tools/fixtures/p5_5_paraphrase_stability.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
