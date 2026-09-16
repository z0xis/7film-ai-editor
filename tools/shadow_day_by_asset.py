"""P6.3: build a shadow day_by_asset map for 15 Agustos using the EXACT unchanged
production _day_position()/_timecode_seconds() functions (planner.py), sourced from a
read-only DB query instead of the live planner's normal asset-loading path. No DB write,
no production code modified or monkeypatched.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, "apps/api")

from sevenfilm.domain import MediaAsset
from sevenfilm.services.planner import _day_position, _timecode_seconds
from sevenfilm.timebase import FrameRate

PROJECT_ID = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
DB_PATH = "file:data/sevenfilm.sqlite3?mode=ro"


def load_assets() -> list[MediaAsset]:
    con = sqlite3.connect(DB_PATH, uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, project_id, path, file_name, duration_seconds, frame_rate, "
        "width, height, codec, timecode FROM media_assets WHERE project_id = ?",
        (PROJECT_ID,),
    ).fetchall()
    assets = []
    for row in rows:
        num, den = row["frame_rate"].split("/")
        assets.append(
            MediaAsset(
                id=row["id"],
                project_id=row["project_id"],
                path=Path(row["path"]),
                name=row["file_name"],
                duration=Fraction(row["duration_seconds"]),
                frame_rate=FrameRate(int(num), int(den)),
                width=row["width"],
                height=row["height"],
                codec=row["codec"],
                timecode=row["timecode"],
            )
        )
    return assets


def main() -> int:
    assets = load_assets()
    mapped = [a for a in assets if _timecode_seconds(a) is not None]
    unmapped = [a for a in assets if _timecode_seconds(a) is None]
    day_by_asset = _day_position(assets)

    print(f"total assets: {len(assets)}")
    print(f"with parseable timecode: {len(mapped)}")
    print(f"without timecode (excluded from day_by_asset input): {len(unmapped)}")
    print("unmapped file names:", sorted(a.name for a in unmapped))
    print(f"day_by_asset entries produced: {len(day_by_asset)}")

    out = {
        "total_assets": len(assets),
        "with_timecode": len(mapped),
        "without_timecode": len(unmapped),
        "unmapped_names": sorted(a.name for a in unmapped),
        "day_by_asset": {
            a.id: {
                "name": a.name,
                "raw_timecode": a.timecode,
                "day_position": day_by_asset.get(a.id),
            }
            for a in assets
        },
    }
    Path("tools/fixtures/p6_3_shadow_day_by_asset.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )
    print("wrote tools/fixtures/p6_3_shadow_day_by_asset.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
