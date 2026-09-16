"""P5.9: Faster R-CNN MobileNetV3-320-FPN fallback bake-off, head-to-head against P5.8's SSDLite
result on the exact same frozen 17-case set, same pre-registered thresholds/ratios, same
evaluation logic. See tools/shadow_ssdlite_verifier.py for the SSDLite baseline this compares
against.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CONFIDENCE_THRESHOLDS = [0.20, 0.35, 0.50, 0.70]
DOMINANT_RATIOS = [0.25, 0.40, 0.60]

PERSON_LABEL = 1
CAKE_LABEL = 61

# Exact same frozen case set as P5.6/P5.8 -- no substitutions.
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
    from torchvision.models.detection import (
        FasterRCNN_MobileNet_V3_Large_320_FPN_Weights,
        fasterrcnn_mobilenet_v3_large_320_fpn,
    )

    weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT
    model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights)
    model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    try:
        model = model.to(device)
    except Exception:  # noqa: BLE001
        device = "cpu"
        model = model.to(device)
    return model, weights.transforms(), device


def run_detection(model, transform, device: str, image_path: Path) -> dict:
    import torch
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    x = transform(img).to(device)
    t0 = time.perf_counter()
    try:
        with torch.no_grad():
            out = model([x])[0]
        dt = time.perf_counter() - t0
        boxes = out["boxes"].cpu().numpy().tolist()
        labels = out["labels"].cpu().numpy().tolist()
        scores = out["scores"].cpu().numpy().tolist()
        w, h = img.size
        return {"boxes": boxes, "labels": labels, "scores": scores,
                "frame_w": w, "frame_h": h, "latency_s": round(dt, 4), "exception": None, "device": device}
    except Exception as e:  # noqa: BLE001
        return {"boxes": [], "labels": [], "scores": [], "frame_w": 0, "frame_h": 0,
                "latency_s": round(time.perf_counter() - t0, 4), "exception": f"{type(e).__name__}: {e}", "device": device}


def summarize(detection: dict) -> dict:
    boxes, labels, scores = detection["boxes"], detection["labels"], detection["scores"]
    frame_area = max(1.0, detection["frame_w"] * detection["frame_h"])

    by_threshold = {}
    for t in CONFIDENCE_THRESHOLDS:
        person_boxes = [b for b, lbl, s in zip(boxes, labels, scores) if lbl == PERSON_LABEL and s >= t]
        cake_boxes = [b for b, lbl, s in zip(boxes, labels, scores) if lbl == CAKE_LABEL and s >= t]
        areas = sorted(((b[2] - b[0]) * (b[3] - b[1]) for b in person_boxes), reverse=True)
        largest = areas[0] if areas else 0.0
        second = areas[1] if len(areas) > 1 else 0.0
        dominant_counts = {}
        for ratio in DOMINANT_RATIOS:
            dominant_counts[f"dominant_ratio_{ratio}"] = sum(1 for a in areas if largest > 0 and a >= ratio * largest)
        by_threshold[str(t)] = {
            "total_person_count": len(person_boxes),
            "cake_count": len(cake_boxes),
            "largest_person_area_ratio_to_frame": round(largest / frame_area, 4),
            "second_largest_person_area_ratio_to_frame": round(second / frame_area, 4),
            "largest_to_second_box_ratio": round(largest / second, 3) if second > 0 else None,
            **dominant_counts,
        }
    return by_threshold


def main() -> int:
    print("loading Faster R-CNN MobileNetV3-320-FPN...")
    t0 = time.perf_counter()
    model, transform, device = load_model()
    load_time = time.perf_counter() - t0
    print(f"loaded on {device} in {load_time:.2f}s")

    results = []
    for case in CASES:
        p = Path(case["path"])
        if not p.exists():
            print(f"MISSING {case['case_id']}: {case['path']}")
            continue
        det = run_detection(model, transform, device, p)
        summary = summarize(det)
        results.append({**case, "raw_detection": det, "threshold_summary": summary})
        person_t35 = summary["0.35"]["total_person_count"]
        print(f"{case['case_id']:38s} persons@0.35={person_t35}  latency={det['latency_s']}s")

    Path("tools/fixtures/p5_9_frcnn_results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {len(results)} case results, device={device}, load_time={load_time:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
