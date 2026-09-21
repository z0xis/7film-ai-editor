"""P6.28 read-only stability ablation over the frozen P6.20 manifest.

Reads local proxies, never source archives, and emits aggregate evidence without changing the
planner, database or Resolve.  The database hash is checked before and after the run.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from sevenfilm.services.stability import measure_camera_stability

DB = ROOT / "data" / "sevenfilm.sqlite3"
MANIFEST = ROOT / "tools" / "fixtures" / "p6_20_candidate_manifest.json"
OUT = ROOT / "tools" / "fixtures" / "p6_28_stability_shadow.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frames(path: str, start: int, duration: int) -> list:
    capture = cv2.VideoCapture(path)
    fps = capture.get(cv2.CAP_PROP_FPS)
    step = max(1, round(fps / 10))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames = []
    for offset in range(duration):
        ok, frame = capture.read()
        if not ok:
            break
        if offset % step == 0 or offset == duration - 1:
            frames.append(frame)
    capture.release()
    return frames


def run() -> dict:
    before = _hash(DB)
    manifest = json.loads(MANIFEST.read_text())
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    proxies = {row["id"]: row["proxy_path"] for row in connection.execute(
        "SELECT id, proxy_path FROM media_assets"
    )}
    connection.close()
    rows = []
    for item in manifest["items"]:
        result = measure_camera_stability(_frames(
            proxies[item["asset_id"]], item["src_start_frame"], item["src_dur_frames"]
        ))
        rows.append({
            "shot_id": item["shot_id"], "source_name": item["source_name"],
            "timeline_start_s": round(item["tl_start_frame"] / manifest["rate"], 2),
            "timeline_duration_s": round(item["tl_dur_frames"] / manifest["rate"], 2),
            "verdict": result.verdict.value, "confidence": result.confidence,
            "jitter": result.jitter, "rotation_jitter": result.rotation_jitter,
            "direction_reversal_rate": result.direction_reversal_rate,
            "reason": result.reason,
        })
    counts = Counter(row["verdict"] for row in rows)
    rejected = [row for row in rows if row["verdict"] == "unstable"]
    after = _hash(DB)
    result = {
        "method": "global affine RANSAC; trajectory acceleration + direction reversals",
        "sampling": "dense 10 fps within each selected source range",
        "p6_20_plan_hash": manifest["plan_hash"], "items": len(rows),
        "verdict_counts": dict(sorted(counts.items())),
        "hard_rejected": rejected,
        "shadow_duration_before_s": manifest["duration_s"],
        "shadow_duration_after_removal_s": round(
            manifest["duration_s"] - sum(row["timeline_duration_s"] for row in rejected), 2
        ),
        "replacement_required": len(rejected),
        "db_unchanged": before == after, "db_sha256": before,
        "resolve_calls": 0, "planner_calls": 0,
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    summary = run()
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2))
