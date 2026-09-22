"""Audit rich-reference coordinate fidelity without guessing legacy offset units."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sevenfilm.sqlite3"
PROJECT = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
OUT = ROOT / "tools" / "fixtures" / "p6_30_1_coordinate_fidelity.json"
TRACES = {
    "V7": ROOT / "data" / "reference_editor" / "raw" / "v7_trace.json",
    "is_edit": ROOT / "data" / "reference_editor" / "raw" / "is_edit_trace.json",
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frames(seconds: str | float, fps: str | float) -> int:
    return round(float(Fraction(str(seconds)) * Fraction(str(fps))))


def run() -> dict:
    before = _hash(DB)
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    assets = {row["file_name"]: dict(row) for row in connection.execute(
        "SELECT id, file_name, duration_seconds, frame_rate FROM media_assets WHERE project_id=?",
        (PROJECT,),
    )}
    connection.close()

    reports = {}
    for label, path in TRACES.items():
        trace = json.loads(path.read_text())
        mapped = []
        for source_name, timeline_start, timeline_duration, raw_left in trace["items"]:
            asset = assets.get(source_name)
            if not asset:
                continue
            physical_frames = _frames(asset["duration_seconds"], asset["frame_rate"])
            mapped.append({
                "source": source_name,
                "raw_timeline_start": timeline_start,
                "raw_timeline_duration": timeline_duration,
                "raw_resolve_left_offset": raw_left,
                "physical_asset_frames": physical_frames,
                "raw_in_physical_bounds": 0 <= raw_left < physical_frames,
            })
        reports[label] = {
            "video_items": len(trace["items"]),
            "mapped_assets": len(mapped),
            "canonicalized": 0,
            "ambiguous": len(mapped),
            "unmapped_assets": len(trace["items"]) - len(mapped),
            "raw_bounds_violations": sum(not row["raw_in_physical_bounds"] for row in mapped),
            "canonical_bounds_violations": 0,
            "canonical_bounds_note": "no guessed canonical coordinates were emitted",
            "timeline_fps_trace_level": str(trace.get("fps")),
            "per_item_source_fps": False,
            "per_item_speed_or_retime": False,
            "per_item_source_out": False,
        }

    c7309 = assets["C7309.MP4"]
    c7309_raw = next(
        item[3] for item in json.loads(TRACES["V7"].read_text())["items"]
        if item[0] == "C7309.MP4"
    )
    after = _hash(DB)
    result = {
        "coordinate_schema_version": "p6.30.1-canonical-source-v1",
        "canonical_domain": "physical_decoded_source_frames_at_native_source_timebase",
        "legacy_offset_policy": "forensic_only_never_automatically_canonical",
        "metadata_inventory": {
            "trace_fields": ["source_name", "timeline_start", "timeline_duration", "raw_left"],
            "trace_timeline_fps": True,
            "source_native_fps_per_item": False,
            "speed_or_retime_per_item": False,
            "authoritative_source_in_out": False,
            "resolve_live_probe": "UNAVAILABLE",
            "matching_fcpxml_or_otio": False,
        },
        "timelines": reports,
        "c7309_regression": {
            "raw_resolve_left_offset": c7309_raw,
            "trace_timeline_fps": "50",
            "source_fps": str(c7309["frame_rate"]),
            "retime_or_speed": None,
            "physical_asset_frames": _frames(c7309["duration_seconds"], c7309["frame_rate"]),
            "canonical_source_in": None,
            "canonical_source_out": None,
            "coordinate_confidence": "UNKNOWN_COORDINATE",
            "reason": "authoritative per-item retime and source coordinates unavailable",
            "old_divide_by_two_value": 1666,
            "old_divide_by_two_is_canonical": False,
        },
        "fidelity_gate": {
            "status": "FAIL",
            "coverage_pass": False,
            "bounds_pass": None,
            "duration_consistency_pass": None,
            "normal_speed_controls_pass": None,
            "retimed_controls_pass": None,
            "same_source_reuse_pass": None,
            "c7309_pass": False,
            "reason": "authoritative source in/out and per-item retime metadata unavailable",
        },
        "benchmarks": {
            "p6_29_rerun": False,
            "p6_30_rerun": False,
            "failure_class_distribution": None,
        },
        "db_unchanged": before == after,
        "db_sha256": before,
        "resolve_timeline_writes": 0,
        "timeline_changes": 0,
        "build_timeline_changes": 0,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
