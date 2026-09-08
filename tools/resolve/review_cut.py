"""Pull frames from the riskiest cuts in an edit, so they can be looked at before the editor
has to.

Two automatic routes were tried for this and measured on the shots the editor had rejected
against the ones they kept:

  * geometry — where the subject sits in the frame and how empty the top third is. Separation
    0.02 on subject position, 0.015 on the detail ratio.
  * CLIP asked to judge — "a well composed wedding photograph" against "a badly framed
    snapshot". Separation 0.014.

All three are noise. What those shots have in common is not measurable in the picture: they
are sharp, steady and well exposed, and what is wrong is that they are not about anything.

So this does not decide. It ranks the cuts by the things that *are* measured — a low score, no
movement, no face where there should be one — and writes out a frame for each, so the ones
worth a second look are a short list rather than the whole film.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

import numpy as np
from sevenfilm.db import Database
from sevenfilm.services.planner import STILL_CATEGORIES, get_timeline
from sevenfilm.services.windows import project_windows

FFMPEG = ".runtime/mamba-root/envs/sevenfilm/bin/ffmpeg"


def risk_of(item, windows) -> float:
    """How much this cut is worth looking at. Not a verdict — an ordering."""
    measured = windows.get(item.shot.id) or ()
    faces = float(np.mean([window.face_count for window in measured])) if measured else 0.0
    return (
        (1 - item.score) * 2
        + (0.5 if item.shot.motion_score < 0.18 else 0.0)
        + (0.5 if faces < 0.5 and item.shot.category not in STILL_CATEGORIES else 0.0)
        + (0.3 if item.shot.face_ratio == 0 else 0.0)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project", default="df2a4a62-e821-40f7-86fc-b6a9259e9ee9")
    parser.add_argument("--count", type=int, default=12)
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    for old in arguments.out.glob("*.jpg"):
        old.unlink()

    database = Database(Path("data/sevenfilm.sqlite3"))
    timeline_id = database.fetch_one(
        "SELECT id FROM timeline_versions ORDER BY created_at DESC LIMIT 1")["id"]
    plan = get_timeline(database, timeline_id)
    windows = project_windows(database, arguments.project)

    ranked = sorted(
        ((risk_of(item, windows), index, item) for index, item in enumerate(plan.items)),
        reverse=True,
    )
    print(f"{'kesim':>6} {'klip':10}{'kategori':11}{'skor':>7}{'hareket':>8}{'risk':>7}")
    for rank, (risk, index, item) in enumerate(ranked[:arguments.count]):
        middle = float(
            item.source_range.start_seconds + item.source_range.duration_seconds / 2)
        name = item.asset.name.rsplit(".", 1)[0]
        subprocess.run(
            [FFMPEG, "-v", "quiet", "-ss", str(middle), "-i", str(item.asset.path),
             "-frames:v", "1", "-vf", "scale=320:-1", "-update", "1", "-y",
             str(arguments.out / f"{rank:02}_{name}.jpg")], check=True)
        print(f"{index:6} {name:10}{item.shot.category:11}{item.score:7.3f}"
              f"{item.shot.motion_score:8.2f}{risk:7.2f}")
    print(f"\nkareler: {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
