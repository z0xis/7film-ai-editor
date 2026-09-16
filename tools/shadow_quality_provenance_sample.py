"""P6.5 Section 17-18: pre-registered small shadow sample. Calls the EXACT production
_shot_frame_groups()/measure_frames() functions (analysis.py/vision.py, unmodified, imported
directly) against a handful of frozen, pre-registered real 15A shots, read-only (opens video
files for reading only; never writes to the DB or any production artifact), to check whether
technical_quality=0.0-stored shots would produce a non-zero value if the exact current
production measurement ran on them today. Diagnostic only -- no backfill, no DB write, no
threshold judgment.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "apps/api")

from sevenfilm.services.analysis import _shot_frame_groups
from sevenfilm.services.vision import measure_frames
from sevenfilm.timebase import FrameRate, TimeRange

DB_PATH = "file:data/sevenfilm.sqlite3?mode=ro"

# Pre-registered BEFORE running: known zero-quality shots central to P6.1-P6.4's findings,
# plus two known non-zero controls to sanity-check the harness itself reproduces stored values.
SAMPLE = [
    {"case": "cake_C7309_zero", "shot_id": "b21ae921-9369-5413-b5a4-2c21c03ade3a", "expect": "zero"},
    {"case": "kiss_C7228_zero", "shot_id": "bd091ada-671e-5211-8577-44e7e82a588d", "expect": "zero"},
    {"case": "first_dance_DJI_0528_zero", "shot_id": "f5e4fa8a-7392-5efb-80b7-739e5693ec0a", "expect": "zero"},
    {"case": "first_dance_DJI_0529_zero", "shot_id": "cd10866a-83c4-5878-a7cc-0adf2a701557", "expect": "zero"},
    {"case": "ring_C7161_nonzero_control", "shot_id": "c83d488f-4372-5482-9369-5ecf951f537e", "expect": "nonzero"},
    {"case": "entrance_C7176_nonzero_control", "shot_id": "a979a3fd-b803-5a88-91bb-300a8d5e8641", "expect": "nonzero"},
]


def main() -> int:
    con = sqlite3.connect(DB_PATH, uri=True)
    con.row_factory = sqlite3.Row
    results = []
    for case in SAMPLE:
        row = con.execute(
            "SELECT s.id, a.path, s.start_frame, s.duration_frames, s.frame_rate, "
            "s.technical_quality FROM shots s JOIN media_assets a ON a.id = s.asset_id "
            "WHERE s.id = ?",
            (case["shot_id"],),
        ).fetchone()
        row = dict(row)

        class _AssetStub:
            path = row["path"]
            frame_rate = FrameRate.parse(row["frame_rate"])

        rate = FrameRate.parse(row["frame_rate"])
        source_range = TimeRange(int(row["start_frame"]), int(row["duration_frames"]), rate)
        frame_groups = _shot_frame_groups(_AssetStub(), [source_range])
        frames = frame_groups[0] if frame_groups else []
        metrics = measure_frames(frames)
        results.append(
            {
                "case": case["case"],
                "shot_id": case["shot_id"],
                "expect": case["expect"],
                "source_path": row["path"],
                "stored_technical_quality": row["technical_quality"],
                "frames_read_now": len(frames),
                "fresh_technical_quality": metrics.technical_quality,
                "delta": round(metrics.technical_quality - row["technical_quality"], 4),
            }
        )
        print(
            f"{case['case']:32s} stored={row['technical_quality']:.3f} "
            f"frames_read={len(frames)} fresh={metrics.technical_quality:.3f}"
        )

    Path("tools/fixtures/p6_5_shadow_quality_sample.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print("wrote tools/fixtures/p6_5_shadow_quality_sample.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
