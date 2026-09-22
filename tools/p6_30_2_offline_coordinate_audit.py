"""Build the P6.30.2 offline source-time fidelity and disagreement audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sevenfilm.services.offline_source_time import (
    from_resolve_item,
    parse_fcpxml_source_ranges,
    parse_otio_source_ranges,
)

DB = ROOT / "data" / "sevenfilm.sqlite3"
PLAN = ROOT / "tools" / "fixtures" / "p6_20_candidate_manifest.json"
OUT = ROOT / "tools" / "fixtures" / "p6_30_2_offline_coordinate_audit.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timeline(capture: dict, name: str) -> dict:
    return next(timeline for timeline in capture["timelines"] if timeline["name"] == name)


def _items(timeline: dict, track: int | None = None) -> list[dict]:
    tracks = timeline["tracks"] if track is None else [
        row for row in timeline["tracks"] if row["index"] == track]
    return [item for row in tracks for item in row["items"]]


def _containing(shots: list[dict], frame: int) -> dict | None:
    return next((shot for shot in shots
                 if shot["start_frame"] <= frame
                 < shot["start_frame"] + shot["duration_frames"]), None)


def run(capture_path: Path, export_dir: Path) -> dict:
    before = _hash(DB)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    if capture["project"] != "15 Ağustos" or capture["missing_targets"]:
        raise RuntimeError("RESOLVE_METADATA_CAPTURE_BLOCKED")
    v7_timeline = _timeline(capture, "IS EDIT - AI CUT V7")
    selects_timeline = _timeline(capture, "is edit")
    v7_items = _items(v7_timeline, 1)
    selects_items = _items(selects_timeline, 1)
    v7 = [from_resolve_item(item, v7_timeline["settings"]["timelineFrameRate"])
          for item in v7_items]
    selects = [from_resolve_item(item, selects_timeline["settings"]["timelineFrameRate"])
               for item in selects_items]

    otio_v7 = parse_otio_source_ranges(export_dir / "v7.otio", track_name="Video 1")
    otio_selects = parse_otio_source_ranges(export_dir / "is_edit.otio", track_name="Video 1")
    fcp_v7 = parse_fcpxml_source_ranges(export_dir / "v7.fcpxml" / "Info.fcpxml")
    fcp_selects = parse_fcpxml_source_ranges(export_dir / "is_edit.fcpxml" / "Info.fcpxml")
    def agrees(resolve_row, otio_row) -> bool:
        return (
            resolve_row.source_name == otio_row.source_name
            and abs(resolve_row.logical_source_frame_in
                    - otio_row.logical_source_frame_in) <= 1
            and abs(resolve_row.logical_source_frame_out
                    - otio_row.logical_source_frame_out) <= 1
        )

    otio_main_matches = sum(agrees(left, right) for left, right in zip(v7, otio_v7, strict=True))
    otio_selects_matches = sum(
        agrees(left, right) for left, right in zip(selects, otio_selects, strict=True))

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    assets = {row["id"]: dict(row) for row in connection.execute(
        "SELECT id, file_name FROM media_assets")}
    asset_by_name = {row["file_name"]: row for row in assets.values()}
    shots_by_asset: dict[str, list[dict]] = {}
    for row in connection.execute(
        "SELECT id, asset_id, start_frame, duration_frames FROM shots ORDER BY start_frame"
    ):
        shots_by_asset.setdefault(row["asset_id"], []).append(dict(row))
    connection.close()

    human: dict[str, list] = {}
    for row in v7:
        human.setdefault(row.source_name, []).append(row)
    plan = json.loads(PLAN.read_text())
    classes = Counter()
    examples: dict[str, list] = {key: [] for key in "ABCD"}
    distances = []
    for item in plan["items"]:
        candidates = human.get(item["source_name"], [])
        if not candidates:
            label, chosen = "C", None
        else:
            chosen = min(candidates, key=lambda row: abs(
                item["src_start_frame"] - row.logical_source_frame_in))
            start, end = item["src_start_frame"], item["src_start_frame"] + item["src_dur_frames"]
            human_start, human_end = (chosen.logical_source_frame_in,
                                      chosen.logical_source_frame_out)
            distance = abs(start - human_start)
            distances.append(distance)
            asset = asset_by_name[item["source_name"]]
            baseline_shot = _containing(shots_by_asset.get(asset["id"], []), start)
            human_shot = _containing(shots_by_asset.get(asset["id"], []), human_start)
            overlap = max(start, human_start) < min(end, human_end)
            near = distance <= round(float(chosen.source_fps) * 0.5)
            if baseline_shot and human_shot and baseline_shot["id"] == human_shot["id"]:
                label = "D" if overlap or near else "A"
            else:
                label = "B"
        classes[label] += 1
        if len(examples[label]) < 5:
            examples[label].append({
                "source": item["source_name"],
                "p6_20_in": item["src_start_frame"],
                "v7_in": chosen.logical_source_frame_in if chosen else None,
                "distance_frames": (abs(item["src_start_frame"]
                                        - chosen.logical_source_frame_in) if chosen else None),
            })

    c7309_item = next(item for item in v7_items if item["name"] == "C7309.MP4")
    c7309 = from_resolve_item(c7309_item, v7_timeline["settings"]["timelineFrameRate"])
    canonical = v7 + selects
    gate = (
        len(v7) == 87 and len(selects) == 187
        and all(row.coordinate_method != "UNKNOWN" for row in canonical)
        and all(row.bounds_valid is True and row.duration_consistent is True for row in canonical)
        and otio_main_matches == 87 and otio_selects_matches == 187
    )
    result = {
        "schema": "p6.30.2-offline-source-time-v1",
        "project": capture["project"], "resolve_version": capture["resolve_version"],
        "raw_media_available": False,
        "capture": {
            "v7_main_video_items": len(v7), "v7_all_video_items": len(_items(v7_timeline)),
            "is_edit_items": len(selects),
            "offline_items": sum(row.online_status == "Offline" for row in canonical),
            "source_time_coverage": sum(row.source_start_seconds is not None for row in canonical),
            "source_fps_coverage": sum(row.source_fps is not None for row in canonical),
            "retime_coverage": sum(row.speed_ratio is not None for row in canonical),
            "project_duration_coverage": sum(row.project_source_frames is not None for row in canonical),
        },
        "exports": {
            "fcpxml_succeeded": True, "otio_succeeded": True,
            "fcpxml_source_ranges": {"v7": len(fcp_v7), "is_edit": len(fcp_selects)},
            "otio_source_ranges": {"v7": len(otio_v7), "is_edit": len(otio_selects)},
            "otio_v7_main_exact_matches": otio_main_matches,
            "otio_is_edit_exact_matches": otio_selects_matches,
        },
        "canonical": {
            "v7_source_time": sum(row.source_start_seconds is not None for row in v7),
            "v7_logical_frames": sum(row.logical_source_frame_in is not None for row in v7),
            "v7_ambiguous": sum(row.coordinate_method == "UNKNOWN" for row in v7),
            "is_edit_source_time": sum(row.source_start_seconds is not None for row in selects),
            "is_edit_logical_frames": sum(row.logical_source_frame_in is not None for row in selects),
            "is_edit_ambiguous": sum(row.coordinate_method == "UNKNOWN" for row in selects),
            "bounds_fail": sum(row.bounds_valid is False for row in canonical),
            "duration_fail": sum(row.duration_consistent is False for row in canonical),
        },
        "c7309": {
            "raw_left": c7309_item["legacy_offsets"]["left"],
            "raw_right": c7309_item["legacy_offsets"]["right"],
            "source_time_seconds": str(c7309.source_start_seconds),
            "logical_source_frame_in": c7309.logical_source_frame_in,
            "logical_source_frame_out": c7309.logical_source_frame_out,
            "speed_ratio": str(c7309.speed_ratio), "source_fps": str(c7309.source_fps),
            "project_source_frames": c7309.project_source_frames,
            "method": c7309.coordinate_method, "heuristic_divide_by_two_used": False,
            "otio_exact_match": any(
                row.source_name == "C7309.MP4"
                and abs(row.logical_source_frame_in - 1666) <= 1
                and abs(row.logical_source_frame_out - 1691) <= 1
                for row in otio_v7
            ),
        },
        "offline_fidelity_gate": {
            "status": "PASS" if gate else "FAIL",
            "reason": ("Resolve explicit source frames/time, rate, speed and stored duration agree "
                       "with OTIO for every V7 main-track item" if gate else
                       "coverage or independent cross-check incomplete"),
        },
        "failure_class_audit": {
            "population": len(plan["items"]),
            "A_same_shot_different_in": classes["A"],
            "B_same_source_different_region": classes["B"],
            "C_different_source_asset": classes["C"],
            "D_effectively_same_moment": classes["D"],
            "median_nearest_v7_distance_frames": statistics.median(distances) if distances else None,
            "representative_examples": examples,
        } if gate else None,
        "db_unchanged": before == _hash(DB), "db_sha256": before,
        "resolve_writes": 0, "timeline_changes": 0, "build_timeline_changes": 0,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--export-dir", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.capture, arguments.export_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
