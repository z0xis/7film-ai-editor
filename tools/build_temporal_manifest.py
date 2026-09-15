"""P5.2 VLM temporal closure: build the BEFORE/CURRENT/AFTER manifest for the 13-sample event
subset, using a fixed +/-2.0s source-time offset (no per-case tuning), clamped to [0, file
duration]. Extracts BEFORE/AFTER frames via ffmpeg; CURRENT frame is the existing p5.2 frame
(reused as-is for fairness -- not re-extracted). Read-only against source media.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

OFFSET_S = 2.0

# (frame_file, source_path, current_time_s, source_duration_s)
CASES = [
    ("23_ceremony_henna_entrance.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7261.MP4", 1.24, 20.640000),
    ("34_bride_walking_entrance.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7411.MP4", 1.24, 10.080000),
    ("41_ceremony_entrance_walk.jpg", "/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP/C1996.MP4", 13.58, 20.640000),
    ("33_couple_cake_feeding.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7391.MP4", 1.24, 17.280000),
    ("39_ceremony_cake_cutting.jpg", "/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP/C2075.MP4", 36.28, 121.440000),
    ("22_couple_chandelier.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7251.MP4", 1.24, 16.320000),
    ("29_couple_embrace_henna.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7331.MP4", 1.24, 7.680000),
    ("40_party_first_dance.jpg", "/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP/C2121.MP4", 15.60, 22.560000),
    ("24_party_dance_groom.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7271.MP4", 1.24, 3.360000),
    ("26_party_dance_group.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7291.MP4", 1.24, 11.040000),
    ("32_party_dance_guests.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7381.MP4", 1.24, 10.080000),
    ("36_bride_dancing_party.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7431.MP4", 1.24, 8.160000),
    ("30_ceremony_henna_seated.jpg", "/Volumes/T7 2TB-1/15 AĞUSTOS/CLIP hikaye /C7341.MP4", 1.24, 12.000000),
]

OUT_DIR = Path("/tmp/p52_temporal_frames")
OUT_DIR.mkdir(exist_ok=True)


def extract(path: str, t: float, out: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=480:-1", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if not out.exists():
        raise RuntimeError(f"ffmpeg failed for {path}@{t}: {r.stderr[-500:]}")


def main() -> int:
    manifest = []
    for frame_file, source_path, current_t, duration in CASES:
        before_t_raw = current_t - OFFSET_S
        after_t_raw = current_t + OFFSET_S
        before_t = max(0.0, before_t_raw)
        after_t = min(duration, after_t_raw)
        before_clamped = before_t != before_t_raw
        after_clamped = after_t != after_t_raw

        stem = frame_file.rsplit(".", 1)[0]
        before_out = OUT_DIR / f"{stem}__before.jpg"
        after_out = OUT_DIR / f"{stem}__after.jpg"
        extract(source_path, before_t, before_out)
        extract(source_path, after_t, after_out)

        entry = {
            "frame_file": frame_file,
            "source_path": source_path,
            "source_duration_s": duration,
            "current_time_s": round(current_t, 3),
            "before_time_s": round(before_t, 3),
            "after_time_s": round(after_t, 3),
            "before_current_delta_s": round(current_t - before_t, 3),
            "current_after_delta_s": round(after_t - current_t, 3),
            "before_clamped": before_clamped,
            "after_clamped": after_clamped,
            "before_frame_path": str(before_out),
            "after_frame_path": str(after_out),
            "current_frame_path": str(Path("/tmp/p52_frames") / frame_file),
        }
        manifest.append(entry)
        print(frame_file, "before=", entry["before_time_s"], "current=", entry["current_time_s"],
              "after=", entry["after_time_s"], "clamped=", before_clamped, after_clamped)

    Path("tools/fixtures/p5_2_temporal_manifest.json").write_text(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
