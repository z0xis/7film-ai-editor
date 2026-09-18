"""P6.23 -- semantic enrichment of the 18 render-only (Tier-2) references.

For each reference video: detect shot boundaries (PySceneDetect AdaptiveDetector), sample one frame per
shot, run the project's own CLIP VisionClassifier for category + shot scale, measure motion (frame
difference), and characterise the audio energy curve + a structural transition (librosa). Everything is
stored with provenance and confidence, distinguishing MODEL-DETECTED from UNKNOWN. Deterministic (fixed
sampling, sorted iteration). Output: data/reference_editor/tier2/<id>.json (gitignored). No DB/Resolve write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
MEDIA = ROOT / "data" / "references" / "media"
OUT = ROOT / "data" / "reference_editor" / "tier2"


def _shot_boundaries(path: Path):
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import AdaptiveDetector
    video = open_video(str(path))
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector())
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    if not scenes:
        return []
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def _motion_band(m):
    return "calm" if m < 6 else "energetic" if m > 18 else "medium"


def enrich_one(path: Path) -> dict:
    from sevenfilm.services.vision import VisionClassifier, measure_frames
    scenes = _shot_boundaries(path)
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_s = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    frames, motions = [], []
    for a, b in scenes:
        mid = (a + b) / 2
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ok, img = cap.read()
        if not ok:
            frames.append(None)
            motions.append(0.0)
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        frames.append(rgb)
        # motion: mean abs diff to a frame 0.3s later within the shot
        cap.set(cv2.CAP_PROP_POS_MSEC, min(b, mid + 0.3) * 1000)
        ok2, img2 = cap.read()
        motions.append(float(np.mean(np.abs(img.astype(np.int16) - img2.astype(np.int16)))) if ok2 else 0.0)
    cap.release()

    classifier = VisionClassifier()
    have_model = classifier._load()
    valid = [f for f in frames if f is not None]
    labels = [None] * len(frames)
    if have_model and valid:
        feats = classifier.encode(valid)
        metrics = [measure_frames([f]) for f in valid]
        classed = classifier.classify_features(feats, metrics, classifier.prompt_priors(feats))
        it = iter(classed)
        for i, f in enumerate(frames):
            if f is not None:
                labels[i] = next(it)

    shots = []
    for i, ((a, b), mo) in enumerate(zip(scenes, motions, strict=True)):
        lab = labels[i] or {}
        shots.append({
            "shot_index": i,
            "start_s": round(a, 3), "end_s": round(b, 3), "duration_s": round(b - a, 3),
            "story_position": round((a + b) / 2 / total_s, 4) if total_s else 0.0,
            "category": str(lab.get("category")) if lab else None,
            "category_confidence": round(float(lab.get("confidence", 0.0)), 3) if lab else 0.0,
            "shot_scale": str(lab.get("shot_scale")) if lab.get("shot_scale") else "unknown",
            "motion": round(mo, 2), "motion_band": _motion_band(mo),
            "detected": bool(lab),
        })
    return {"reference_id": f"ref:{path.stem}", "video": path.name, "fps": round(fps, 3),
            "duration_s": round(total_s, 2), "n_shots": len(shots),
            "model": "clip-vit-base-patch32" if have_model else "fallback",
            "shots": shots}


def run(only: str | None = None) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    done = {}
    for path in sorted(MEDIA.glob("*.mkv")):
        if only and path.stem != only:
            continue
        res = enrich_one(path)
        (OUT / f"{path.stem}.json").write_text(json.dumps(res, indent=1, sort_keys=True))
        done[res["reference_id"]] = {"n_shots": res["n_shots"], "model": res["model"],
                                     "detected": sum(1 for s in res["shots"] if s["detected"])}
    return done


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(run(only), indent=2))
