"""P6.30 read-only audit: can V7 source offsets validly identify detected-shot phases?"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sevenfilm.sqlite3"
PLAN = ROOT / "tools" / "fixtures" / "p6_20_candidate_manifest.json"
V7 = ROOT / "data" / "reference_editor" / "raw" / "v7_trace.json"
OUT = ROOT / "tools" / "fixtures" / "p6_30_phase_provenance_audit.json"
PROJECT = "29cd1e06-0af1-40c4-95bf-77f2add1159f"


def duration_frames(duration: str, rate: str) -> int:
    return round(float(Fraction(duration) * Fraction(rate)))


def containing_shot(shots: list[dict], source_frame: int) -> dict | None:
    return next((shot for shot in shots
                 if shot["start_frame"] <= source_frame
                 < shot["start_frame"] + shot["duration_frames"]), None)


def duration_fits(shot: dict, required_frames: int) -> bool:
    return required_frames > 0 and shot["duration_frames"] >= required_frames


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    before = _hash(DB)
    plan = json.loads(PLAN.read_text())
    trace = json.loads(V7.read_text())
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    assets = {row["file_name"]: dict(row) for row in connection.execute(
        "SELECT id, file_name, duration_seconds, frame_rate FROM media_assets WHERE project_id=?",
        (PROJECT,))}
    shots_by_asset: dict[str, list[dict]] = {}
    for row in connection.execute(
        "SELECT id, asset_id, start_frame, duration_frames, category, shot_scale "
        "FROM shots ORDER BY asset_id, start_frame"
    ):
        shots_by_asset.setdefault(row["asset_id"], []).append(dict(row))
    connection.close()

    mapped, invalid = [], []
    for item in trace["items"]:
        name, timeline_start, timeline_duration, raw_left = item
        asset = assets.get(name)
        if not asset:
            continue
        total = duration_frames(asset["duration_seconds"], asset["frame_rate"])
        row = {"source": name, "timeline_start": timeline_start,
               "timeline_duration": timeline_duration, "raw_left": raw_left,
               "asset_frames": total, "raw_in_range": 0 <= raw_left < total}
        mapped.append(row)
        if not row["raw_in_range"]:
            invalid.append(row)

    selected_assets = Counter(item["asset_id"] for item in plan["items"])
    sibling_counts = [len(shots_by_asset[asset_id]) for asset_id in selected_assets]

    c7309_asset = assets["C7309.MP4"]
    c7309_shots = shots_by_asset[c7309_asset["id"]]
    c7309_plan = [item for item in plan["items"] if item["source_name"] == "C7309.MP4"]
    raw = next(item[3] for item in trace["items"] if item[0] == "C7309.MP4")
    normalized = raw // 2
    raw_shot = containing_shot(c7309_shots, raw)
    normalized_shot = containing_shot(c7309_shots, normalized)
    selected_at_1635 = next(item for item in c7309_plan if item["src_start_frame"] == 1635)

    after = _hash(DB)
    result = {
        "p6_20_plan_hash": plan["plan_hash"],
        "same_source_siblings": {
            "selected_items": len(plan["items"]),
            "selected_assets": len(selected_assets),
            "assets_with_multiple_detected_shots": sum(count > 1 for count in sibling_counts),
            "median_sibling_count": sorted(sibling_counts)[len(sibling_counts) // 2],
            "max_sibling_count": max(sibling_counts),
        },
        "planner_findings": {
            "siblings_ranked_independently": True,
            "explicit_phase_role": False,
            "forward_progression_signal": True,
            "exact_shot_reuse_penalty": True,
            "distinct_phase_reuse_counted_separately": True,
            "explicit_action_phase_preference": False,
        },
        "v7_trace_provenance": {
            "mapped_items": len(mapped), "out_of_source_range": len(invalid),
            "out_of_range_examples": invalid,
            "item_fields": ["source_name", "timeline_start", "timeline_duration", "raw_left"],
            "per_item_speed_present": False, "per_item_source_timebase_present": False,
            "phase_benchmark_valid": False,
        },
        "c7309_control": {
            "asset_frames_at_db_rate": duration_frames(c7309_asset["duration_seconds"],
                                                        c7309_asset["frame_rate"]),
            "v7_raw_left": raw, "v7_raw_left_in_range": raw_shot is not None,
            "slowmo_normalized_left": normalized,
            "normalized_detected_shot": normalized_shot,
            "p6_20_selected_item": selected_at_1635,
            "normalized_human_inside_selected_shot": (
                normalized_shot is not None
                and normalized_shot["id"] == selected_at_1635["shot_id"]
            ),
            "normalized_human_inside_selected_source_range": (
                selected_at_1635["src_start_frame"] <= normalized
                < selected_at_1635["src_start_frame"] + selected_at_1635["src_dur_frames"]
            ),
            "distance_from_p6_20_source_in_frames": normalized - selected_at_1635["src_start_frame"],
        },
        "shadow_phase_classification": {
            "KEEP_PHASE": 0, "SWITCH_PHASE": 0, "REVIEW": 0,
            "UNKNOWN": len(plan["items"]),
            "reason": "V7 source coordinates lack speed/timebase provenance; selector not run",
        },
        "db_unchanged": before == after, "db_sha256": before,
        "resolve_calls": 0, "timeline_writes": 0, "build_timeline_changes": 0,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
