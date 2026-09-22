"""Read canonical source-coordinate evidence from existing Resolve timelines.

This probe is deliberately read-only: it never changes the current timeline, calls a
setter, exports a timeline, or writes to the project database.  Its JSON output is a
local analysis artifact supplied by ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
TARGETS = {"IS EDIT - AI CUT V7", "is edit"}


def _call(obj: Any, method: str, *args: Any) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception as error:  # noqa: BLE001 - remote API raises opaque bridge exceptions
        return {"error": f"{type(error).__name__}: {error}"}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return repr(value)


def inspect_item(item: Any, track: int, index: int) -> dict[str, Any]:
    media = _call(item, "GetMediaPoolItem")
    media_properties = (
        _call(media, "GetClipProperty") if media and not isinstance(media, dict) else {}
    )
    return {
        "track": track,
        "index": index,
        "name": _call(item, "GetName"),
        "timeline": {
            "start": _call(item, "GetStart"),
            "end": _call(item, "GetEnd"),
            "duration": _call(item, "GetDuration"),
        },
        "legacy_offsets": {
            "left": _call(item, "GetLeftOffset"),
            "right": _call(item, "GetRightOffset"),
        },
        "canonical_api": {
            "source_start_frame": _call(item, "GetSourceStartFrame"),
            "source_end_frame": _call(item, "GetSourceEndFrame"),
            "source_start_time": _call(item, "GetSourceStartTime"),
            "source_end_time": _call(item, "GetSourceEndTime"),
        },
        "speed": _call(item, "GetSpeed"),
        "properties": _call(item, "GetProperty"),
        "media": {
            "name": _call(media, "GetName") if media and not isinstance(media, dict) else None,
            "id": _call(media, "GetMediaId") if media and not isinstance(media, dict) else None,
            "properties": media_properties,
        },
    }


def collect() -> dict[str, Any]:
    sys.path.insert(0, MODULES)
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Resolve'a bağlanılamadı")
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("Açık Resolve projesi yok")

    timelines = []
    seen = set()
    for timeline_index in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(timeline_index)
        name = _call(timeline, "GetName")
        if name not in TARGETS:
            continue
        seen.add(name)
        tracks = []
        track_count = _call(timeline, "GetTrackCount", "video")
        if not isinstance(track_count, int):
            track_count = 0
        for track in range(1, track_count + 1):
            items = _call(timeline, "GetItemListInTrack", "video", track)
            if not isinstance(items, list):
                items = []
            tracks.append({
                "index": track,
                "items": [inspect_item(item, track, index) for index, item in enumerate(items, 1)],
            })
        timelines.append({
            "index": timeline_index,
            "name": name,
            "settings": _call(timeline, "GetSettings"),
            "start_frame": _call(timeline, "GetStartFrame"),
            "end_frame": _call(timeline, "GetEndFrame"),
            "tracks": tracks,
        })

    return {
        "schema": "p6.30.1-resolve-coordinate-probe-v1",
        # Resolve bundles Python 3.9, where datetime.UTC does not exist.
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "resolve_version": _call(resolve, "GetVersionString"),
        "project": _call(project, "GetName"),
        "project_settings": _call(project, "GetSettings"),
        "targets": sorted(TARGETS),
        "missing_targets": sorted(TARGETS - seen),
        "timelines": timelines,
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args()
    report = _json_safe(collect())
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    counts = {
        timeline["name"]: sum(len(track["items"]) for track in timeline["tracks"])
        for timeline in report["timelines"]
    }
    print(json.dumps({"project": report["project"], "items": counts,
                      "missing": report["missing_targets"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
