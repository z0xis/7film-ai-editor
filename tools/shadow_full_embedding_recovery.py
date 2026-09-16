"""P6.1 Stage B: full-project SHADOW embedding recovery for 15 Agustos. Uses the exact production
VisionClassifier/CLIP encoder and the exact middle-frame-per-shot methodology _encode_asset()
uses, entirely in-memory -- NEVER writes to the real database. Output is a local JSON cache of
(shot_id -> embedding) for shadow moment/planner analysis only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "apps/api")

import cv2
import numpy as np
from sevenfilm.services.vision import VisionClassifier

FRAME_CACHE = Path("/tmp/p61_stage_b_frames")
FRAME_CACHE.mkdir(exist_ok=True)
OUT_PATH = Path("/tmp/p61_stage_b_embeddings.npz")
PROGRESS_PATH = Path("/tmp/p61_stage_b_progress.json")


def extract_middle_frame(path: str, start_frame: int, duration_frames: int, frame_rate: str, out: Path) -> bool:
    import subprocess

    num, den = frame_rate.split("/")
    fps = float(num) / float(den)
    mid_frame = start_frame + duration_frames // 2
    t = mid_frame / fps
    cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=480:-1", str(out)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    return out.exists()


def main() -> int:
    shots = []
    with open("/tmp/p61_all_15a_shots.txt") as f:
        for line in f:
            sid, path, sf, dur, fr = line.rstrip("\n").split("|")
            shots.append({"shot_id": sid, "path": path, "start_frame": int(sf),
                          "duration_frames": int(dur), "frame_rate": fr})

    classifier = VisionClassifier()
    if not classifier._load():
        print("STAGE B STOPPED: production CLIP encoder unavailable")
        Path("/tmp/p61_stage_b_STOPPED").write_text("encoder unavailable")
        return 1

    shot_ids = []
    vectors = []
    failures = []
    t_start = time.perf_counter()
    for i, shot in enumerate(shots):
        out = FRAME_CACHE / f"{i:05d}.jpg"
        if not out.exists():
            ok = extract_middle_frame(shot["path"], shot["start_frame"], shot["duration_frames"], shot["frame_rate"], out)
            if not ok:
                failures.append({"shot_id": shot["shot_id"], "reason": "extraction_failed"})
                continue
        img = cv2.imread(str(out))
        if img is None:
            failures.append({"shot_id": shot["shot_id"], "reason": "read_failed"})
            continue
        vec = classifier.encode([img])
        if vec is None:
            failures.append({"shot_id": shot["shot_id"], "reason": "encode_failed"})
            continue
        v = vec[0]
        v = v / (np.linalg.norm(v) + 1e-9)
        shot_ids.append(shot["shot_id"])
        vectors.append(v)
        if i % 100 == 0:
            elapsed = time.perf_counter() - t_start
            PROGRESS_PATH.write_text(json.dumps({"done": i, "total": len(shots), "elapsed_s": elapsed,
                                                  "successes": len(shot_ids), "failures": len(failures)}))
            print(f"{i}/{len(shots)} done, {len(shot_ids)} ok, {len(failures)} failed, {elapsed:.0f}s elapsed")

    matrix = np.stack(vectors) if vectors else np.zeros((0, 512))
    np.savez(OUT_PATH, shot_ids=np.array(shot_ids), vectors=matrix)
    total_time = time.perf_counter() - t_start
    result = {"total_shots": len(shots), "successful": len(shot_ids), "failed": len(failures),
              "failures_sample": failures[:20], "total_runtime_s": round(total_time, 1),
              "median_per_shot_s": round(total_time / max(1, len(shots)), 3)}
    Path("tools/fixtures/p6_1_stage_b_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2))
    Path("/tmp/p61_stage_b_DONE").write_text("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
