"""P5.5: shadow-only evidence-consistency verifier for the P5.4 accept policy.

E1 -- same-Qwen atomic recheck: re-asks Qwen for directly-visible physical facts only (person
count, interaction, dance-like movement, cake, cutting action), explicitly NOT the event label
and NOT role identities (bride/groom). This is the SAME model family as the classifier call, so
it is at best a correlated signal, never treated as independent -- see INDEPENDENCE ASSESSMENT
in the P5.5 report.

E3 -- existing lightweight signal: reuses the production YuNet face detector
(apps/api/sevenfilm/services/models/face_detection_yunet_2023mar.onnx) already shipped for
FrameMetrics.face_count. Used only as a CONTRADICTION check (does the frame show enough visible
faces to be plausible for a "two people interacting" claim), never a hard veto, since a
back-turned or profile pair (esp. drone footage) can have face_count=0 and still be a genuine
couple.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

ATOMIC_PROMPT = """Look at this single photo. Report ONLY directly visible physical facts about
what is in the frame -- do not guess who anyone is, do not name roles like "bride" or "groom",
do not infer an event name. Answer strictly from what is visually present. Respond with ONLY a
JSON object, no other text:
{
  "primary_person_count": <integer, count of people who are clearly a main subject of the frame, not background/crowd>,
  "two_people_interacting": <true/false, are exactly two primary people visibly engaged with each other (touching, facing, holding)>,
  "dance_like_movement_visible": <true/false, is there visible dance-like body movement/posture>,
  "solo_performer_pattern": <true/false, is there ONE person clearly dominant/performing while others are audience/background>,
  "cake_visible": <true/false>,
  "cake_cutting_action_visible": <true/false, hands + implement actively cutting the cake, not just standing near it>,
  "confidence_in_this_read": <0.0-1.0>
}"""


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


def run_atomic(model, processor, device, image_path: Path) -> dict:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": ATOMIC_PROMPT}]}]
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


def run_yunet_face_count(image_path: Path) -> dict:
    """E3: production's own YuNet detector, run standalone (shadow tool, not the production
    module) against a single extracted JPG frame."""
    import cv2  # type: ignore[import-not-found]

    model_path = (
        Path(__file__).resolve().parents[1]
        / "apps" / "api" / "sevenfilm" / "models" / "face_detection_yunet_2023mar.onnx"
    )
    if not model_path.exists():
        return {"available": False, "face_count": None}
    img = cv2.imread(str(image_path))
    if img is None:
        return {"available": False, "face_count": None}
    h, w = img.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(model_path), "", (w, h), score_threshold=0.6, nms_threshold=0.3)
    _success, faces = detector.detect(img)
    face_count = len(faces) if faces is not None else 0
    return {"available": True, "face_count": face_count}


# Frozen P5.4 case set: (label, path_hint, frame_file). Not committed images -- paths reference
# the same /tmp extraction the P5.3/P5.4 harnesses already produced this session.
CASES = [
    ("genuine_first_dance_C7450", "/tmp/p53_shadow_frames/095.jpg", "first_dance", "TP"),
    ("genuine_first_dance_drone_A", "/tmp/p53_shadow_frames/111.jpg", "first_dance", "TP"),
    ("genuine_first_dance_drone_B", "/tmp/p53_shadow_frames/109.jpg", "first_dance", "TP"),
    ("genuine_first_dance_C7252", "/tmp/p53_shadow_frames/037.jpg", "first_dance", "TP"),
    ("genuine_first_dance_C7261", "/tmp/p54_stress_frames/052.jpg", "first_dance", "TP"),
    ("genuine_cake_cutting_C7309", "/tmp/p54_stress_frames/066.jpg", "cake_cutting", "TP"),
    ("HARMFUL_solo_performer_C7349", "/tmp/p54_stress_frames/083.jpg", "first_dance", "FP"),
    ("ceremony_halluc_C7343", "/tmp/p53_shadow_frames/061.jpg", "ceremony_action", "FP"),
    ("ceremony_halluc_C7344", "/tmp/p53_shadow_frames/062.jpg", "ceremony_action", "FP"),
    ("ceremony_borderline_C7342", "/tmp/p54_stress_frames/078.jpg", "ceremony_action", "FP"),
]


def main() -> int:
    print("loading Qwen3-VL-4B-Instruct...")
    model, processor, device, load_time = load_model()
    print(f"loaded in {load_time:.1f}s on {device}")

    results = []
    for label, path, event, verdict in CASES:
        p = Path(path)
        if not p.exists():
            print(f"MISSING {label}: {path}")
            continue
        r = run_atomic(model, processor, device, p)
        parsed = parse_json_loose(r["raw"])
        face = run_yunet_face_count(p)
        entry = {
            "label": label, "path": path, "event_claimed": event, "human_verdict": verdict,
            "atomic_raw": r["raw"], "atomic_parsed": parsed, "atomic_latency_s": r["latency_s"],
            "atomic_exception": r["exception"], "yunet": face,
        }
        results.append(entry)
        print(f"{label:35s} event={event:15s} verdict={verdict}  atomic={parsed}  yunet_faces={face['face_count']}")

    Path("tools/fixtures/p5_5_evidence_verification.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"wrote {len(results)} results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
