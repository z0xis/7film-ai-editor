"""P6.20 -- build the current-planner TimelinePlan and export it via the PRODUCTION exporter.

Reuses the read-only, write-hardened P6.14 harness to build the exact production plan (no chronology
overlay), then writes FCPXML + OTIO + plan JSON with the production exporter (which already encodes
source trims, speed/retime and the music track). Destination is passed on argv. No DB/Resolve write.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def _harness():
    spec = importlib.util.spec_from_file_location("p6_14_shadow", ROOT / "tools/p6_14_shadow_planner.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    return h


def main(dest_dir: Path):
    h = _harness()
    from sevenfilm import api
    from sevenfilm.services import exporter, planner
    h._harden(api.DATABASE)
    plan, _f, segments = h._run_once(api, planner, seed=1)
    plan.music_segments = segments
    plan.name = "AI CUT V2 - P6.20 CANDIDATE"
    dest_dir.mkdir(parents=True, exist_ok=True)
    fcp = exporter.export_fcpxml(plan, dest_dir / "p6_20_candidate.fcpxml")
    otio = exporter.export_otio(plan, dest_dir / "p6_20_candidate.otio")
    pj = exporter.export_plan_json(plan, dest_dir / "p6_20_candidate_plan.json")
    print("items", len(plan.items), "dur_s", round(float(plan.duration), 2))
    print("fcpxml", fcp)
    print("otio", otio)
    print("plan_json", pj)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
