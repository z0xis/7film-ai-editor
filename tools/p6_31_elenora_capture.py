"""Read-only capture/export of the Elenora human reference timeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
PROJECT = "EM WD"
TIMELINE = "Elenora Mustafa Wedding Day"
RAW_ROOT = "/Users/ibrahimsoylu/Desktop/ELENORA MUSTAFA/KLIP/CLIP/"


def call(obj: Any, method: str, *args: Any) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception as error:  # noqa: BLE001 - Resolve bridge exceptions are opaque
        return {"error": f"{type(error).__name__}: {error}"}


def item_row(item: Any, track_type: str, track: int, index: int) -> dict[str, Any]:
    media = call(item, "GetMediaPoolItem")
    media_properties = call(media, "GetClipProperty") if media and not isinstance(media, dict) else {}
    row = {
        "track_type": track_type, "track": track, "index": index,
        "name": call(item, "GetName"),
        "timeline": {"start": call(item, "GetStart"), "end": call(item, "GetEnd"),
                     "duration": call(item, "GetDuration")},
        "legacy_offsets": {"left": call(item, "GetLeftOffset"),
                           "right": call(item, "GetRightOffset")},
        "canonical_api": {
            "source_start_frame": call(item, "GetSourceStartFrame"),
            "source_end_frame": call(item, "GetSourceEndFrame"),
            "source_start_time": call(item, "GetSourceStartTime"),
            "source_end_time": call(item, "GetSourceEndTime"),
        },
        "speed": call(item, "GetSpeed"), "properties": call(item, "GetProperty"),
        "media": {"name": call(media, "GetName") if media and not isinstance(media, dict) else None,
                  "id": call(media, "GetMediaId") if media and not isinstance(media, dict) else None,
                  "properties": media_properties},
    }
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--export-dir", required=True, type=Path)
    arguments = parser.parse_args()
    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    if project is None or project.GetName() != PROJECT:
        actual = project.GetName() if project else None
        raise RuntimeError(f"expected project {PROJECT!r}, got {actual!r}")
    timeline = next((project.GetTimelineByIndex(index)
                     for index in range(1, project.GetTimelineCount() + 1)
                     if project.GetTimelineByIndex(index).GetName() == TIMELINE), None)
    if timeline is None:
        raise RuntimeError(f"missing timeline {TIMELINE!r}")
    tracks = []
    for track_type in ("video", "audio"):
        for track in range(1, timeline.GetTrackCount(track_type) + 1):
            items = timeline.GetItemListInTrack(track_type, track) or []
            tracks.append({"type": track_type, "index": track,
                           "items": [item_row(item, track_type, track, index)
                                     for index, item in enumerate(items, 1)]})
    out_dir = arguments.export_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fcpxml, otio = out_dir / "elenora.fcpxml", out_dir / "elenora.otio"
    report = {
        "schema": "p6.31-elenora-resolve-capture-v1",
        "resolve_version": resolve.GetVersionString(), "project": project.GetName(),
        "timeline": timeline.GetName(), "settings": call(timeline, "GetSettings"),
        "start_frame": call(timeline, "GetStartFrame"), "end_frame": call(timeline, "GetEndFrame"),
        "raw_root_expected": RAW_ROOT, "tracks": tracks,
        "exports": {
            "fcpxml": timeline.Export(str(fcpxml), resolve.EXPORT_FCPXML_1_10),
            "otio": timeline.Export(str(otio), resolve.EXPORT_OTIO),
            "fcpxml_path": str(fcpxml), "otio_path": str(otio),
        },
        "read_only_project_state": True,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    summary = {"project": report["project"], "timeline": report["timeline"],
               "tracks": [(row["type"], row["index"], len(row["items"])) for row in tracks],
               "exports": report["exports"]}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
