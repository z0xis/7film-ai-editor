"""Export the two rich-reference timelines for read-only coordinate cross-checking."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
PROJECT = "15 Ağustos"
TIMELINES = {"IS EDIT - AI CUT V7": "v7", "is edit": "is_edit"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    arguments = parser.parse_args()
    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("RESOLVE_METADATA_CAPTURE_BLOCKED: Resolve unavailable")
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None or project.GetName() != PROJECT:
        actual = project.GetName() if project else None
        raise RuntimeError(f"RESOLVE_METADATA_CAPTURE_BLOCKED: expected {PROJECT!r}, got {actual!r}")
    found = {}
    for index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline.GetName() in TIMELINES:
            found[timeline.GetName()] = timeline
    missing = set(TIMELINES) - set(found)
    if missing:
        raise RuntimeError(f"RESOLVE_METADATA_CAPTURE_BLOCKED: missing {sorted(missing)}")

    arguments.out_dir = arguments.out_dir.resolve()
    arguments.out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, stem in TIMELINES.items():
        timeline = found[name]
        fcpxml = arguments.out_dir / f"{stem}.fcpxml"
        otio = arguments.out_dir / f"{stem}.otio"
        results[name] = {
            "fcpxml": timeline.Export(str(fcpxml), resolve.EXPORT_FCPXML_1_10),
            "otio": timeline.Export(str(otio), resolve.EXPORT_OTIO),
            "fcpxml_path": str(fcpxml),
            "otio_path": str(otio),
        }
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(row["fcpxml"] for row in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
