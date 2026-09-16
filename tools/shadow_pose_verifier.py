"""P5.11: multi-person pose (torchvision Keypoint R-CNN) + generic pair-geometry feature
extraction, frozen BEFORE any case result was inspected. Phase 1 (recall) is reported completely
separately from Phase 2 (geometry) -- the two must never be conflated (P5.10's explicit
falsification-first design).

Keypoint layout (COCO-17): 0 nose, 1 L-eye, 2 R-eye, 3 L-ear, 4 R-ear, 5 L-shoulder,
6 R-shoulder, 7 L-elbow, 8 R-elbow, 9 L-wrist, 10 R-wrist, 11 L-hip, 12 R-hip, 13 L-knee,
14 R-knee, 15 L-ankle, 16 R-ankle.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

# Pre-registered BEFORE inspecting any case result.
KEYPOINT_SCORE_THRESHOLDS = [0.20, 0.35, 0.50]  # K20 / K35 / K50
MIN_USABLE_KEYPOINTS = [4, 6, 8]  # U4 / U6 / U8
PERSON_SCORE_THRESHOLD = 0.50  # instance-level detection confidence to consider a skeleton at all
ORIENTATION_COMPATIBLE_DEG = 30.0  # coarse, frozen tolerance for "mutual facing" descriptive flag

L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

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
        KeypointRCNN_ResNet50_FPN_Weights,
        keypointrcnn_resnet50_fpn,
    )

    weights = KeypointRCNN_ResNet50_FPN_Weights.DEFAULT
    model = keypointrcnn_resnet50_fpn(weights=weights)
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
        return {
            "boxes": out["boxes"].cpu().numpy().tolist(),
            "scores": out["scores"].cpu().numpy().tolist(),
            "keypoints": out["keypoints"].cpu().numpy().tolist(),  # [N,17,3] (x,y,score)
            "frame_w": img.size[0], "frame_h": img.size[1],
            "latency_s": round(dt, 4), "exception": None, "device": device,
        }
    except Exception as e:  # noqa: BLE001
        return {"boxes": [], "scores": [], "keypoints": [], "frame_w": 0, "frame_h": 0,
                "latency_s": round(time.perf_counter() - t0, 4), "exception": f"{type(e).__name__}: {e}", "device": device}


def usable_keypoint_count(keypoints_person: list, kp_threshold: float) -> int:
    return sum(1 for kp in keypoints_person if kp[2] >= kp_threshold)


def phase1_recall(detection: dict) -> dict:
    """Pose recall characterization ONLY -- no geometry, no orientation, no pair logic."""
    instances = []
    for box, score, kps in zip(detection["boxes"], detection["scores"], detection["keypoints"]):
        if score < PERSON_SCORE_THRESHOLD:
            continue
        per_threshold = {}
        for kt in KEYPOINT_SCORE_THRESHOLDS:
            n_usable = usable_keypoint_count(kps, kt)
            per_threshold[str(kt)] = {
                "usable_keypoints": n_usable,
                "usable_at_U4": n_usable >= 4,
                "usable_at_U6": n_usable >= 6,
                "usable_at_U8": n_usable >= 8,
            }
        box_area = (box[2] - box[0]) * (box[3] - box[1])
        instances.append({"person_score": round(score, 3), "box_area": round(box_area, 1),
                           "keypoint_summary": per_threshold})
    return {"total_person_instances": len(instances), "instances": instances}


def _kp(kps: list, idx: int) -> tuple[float, float, float]:
    return kps[idx][0], kps[idx][1], kps[idx][2]


def torso_orientation_deg(kps: list, kp_threshold: float) -> float | None:
    """Angle (degrees, 0-180) of the shoulder-line vector. UNKNOWN (None) if either shoulder
    keypoint is below the confidence threshold -- never guessed."""
    lx, ly, ls = _kp(kps, L_SHOULDER)
    rx, ry, rs = _kp(kps, R_SHOULDER)
    if ls < kp_threshold or rs < kp_threshold:
        return None
    angle = math.degrees(math.atan2(ry - ly, rx - lx))
    return angle % 180.0


def body_scale(kps: list, kp_threshold: float) -> float | None:
    """Shoulder width as a generic body-scale normalizer. UNKNOWN if shoulders unavailable."""
    lx, ly, ls = _kp(kps, L_SHOULDER)
    rx, ry, rs = _kp(kps, R_SHOULDER)
    if ls < kp_threshold or rs < kp_threshold:
        return None
    return math.hypot(rx - lx, ry - ly)


def torso_center(kps: list, kp_threshold: float) -> tuple[float, float] | None:
    """Midpoint of shoulders+hips (whichever are usable). UNKNOWN if nothing usable."""
    pts = []
    for idx in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP):
        x, y, s = _kp(kps, idx)
        if s >= kp_threshold:
            pts.append((x, y))
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def phase2_geometry(detection: dict, kp_threshold: float) -> dict:
    """Pair-geometry features (F1-F5) for the two highest-scoring person instances. This is
    descriptive only -- selecting the top-2 by detection score is the most generic, non-tuned
    way to pick "candidate pair" without hand-crafting a wedding-specific rule."""
    instances = [
        (score, box, kps) for box, score, kps in zip(detection["boxes"], detection["scores"], detection["keypoints"])
        if score >= PERSON_SCORE_THRESHOLD
    ]
    instances.sort(key=lambda t: -t[0])

    f1_usable_skeleton_count = sum(
        1 for _s, _b, kps in instances if usable_keypoint_count(kps, kp_threshold) >= 4
    )

    if len(instances) < 2:
        return {"F1_usable_skeleton_count": f1_usable_skeleton_count, "recall_status": "RECALL_INSUFFICIENT",
                "F2_orientation_a": None, "F2_orientation_b": None,
                "F3_normalized_pair_distance": None, "F4_mutual_facing_evidence": "UNKNOWN",
                "F5_pair_dominance": None}

    (score_a, _box_a, kps_a), (score_b, _box_b, kps_b) = instances[0], instances[1]

    orient_a = torso_orientation_deg(kps_a, kp_threshold)
    orient_b = torso_orientation_deg(kps_b, kp_threshold)
    scale_a = body_scale(kps_a, kp_threshold)
    scale_b = body_scale(kps_b, kp_threshold)
    center_a = torso_center(kps_a, kp_threshold)
    center_b = torso_center(kps_b, kp_threshold)

    normalized_distance = None
    if center_a and center_b and scale_a and scale_b:
        raw_dist = math.hypot(center_a[0] - center_b[0], center_a[1] - center_b[1])
        avg_scale = (scale_a + scale_b) / 2.0
        normalized_distance = round(raw_dist / avg_scale, 3) if avg_scale > 0 else None

    mutual_facing = "UNKNOWN"
    if orient_a is not None and orient_b is not None:
        diff = abs(orient_a - orient_b)
        diff = min(diff, 180.0 - diff)
        mutual_facing = "SUPPORTED" if diff <= ORIENTATION_COMPATIBLE_DEG else "CONTRADICTED"

    pair_dominance = None
    other_scales = []
    for score_o, _box_o, kps_o in instances[2:]:
        s = body_scale(kps_o, kp_threshold)
        if s:
            other_scales.append(s)
    if scale_a and scale_b:
        pair_avg_scale = (scale_a + scale_b) / 2.0
        if other_scales:
            pair_dominance = round(pair_avg_scale / max(other_scales), 3)
        else:
            pair_dominance = "no_other_skeletons"

    recall_status = "RECALL_SUFFICIENT" if (
        usable_keypoint_count(kps_a, kp_threshold) >= 4 and usable_keypoint_count(kps_b, kp_threshold) >= 4
    ) else "RECALL_INSUFFICIENT"

    return {
        "F1_usable_skeleton_count": f1_usable_skeleton_count,
        "recall_status": recall_status,
        "candidate_a_score": round(score_a, 3), "candidate_b_score": round(score_b, 3),
        "F2_orientation_a": round(orient_a, 1) if orient_a is not None else None,
        "F2_orientation_b": round(orient_b, 1) if orient_b is not None else None,
        "F3_normalized_pair_distance": normalized_distance,
        "F4_mutual_facing_evidence": mutual_facing,
        "F5_pair_dominance": pair_dominance,
    }


def main() -> int:
    print("loading Keypoint R-CNN ResNet50-FPN...")
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
        recall = phase1_recall(det)
        geometry_by_threshold = {str(kt): phase2_geometry(det, kt) for kt in KEYPOINT_SCORE_THRESHOLDS}
        results.append({**case, "raw_detection": {k: v for k, v in det.items() if k != "keypoints"},
                         "phase1_recall": recall, "phase2_geometry": geometry_by_threshold})
        print(f"{case['case_id']:38s} instances={recall['total_person_instances']}  "
              f"recall@0.35={geometry_by_threshold['0.35']['recall_status']}  latency={det['latency_s']}s")

    Path("tools/fixtures/p5_11_pose_results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {len(results)} case results, device={device}, load_time={load_time:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
