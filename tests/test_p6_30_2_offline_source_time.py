from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from sevenfilm.services.offline_source_time import (
    from_resolve_item,
    parse_fcpxml_source_ranges,
    parse_otio_source_ranges,
    rational_seconds,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "p6_30_2_offline_coordinate_audit.json"


def resolve_item(*, speed=50.0, source_in=1666, source_out=1691, online="Offline"):
    return {
        "name": "C7309.MP4",
        "timeline": {"start": 100, "end": 150, "duration": 50},
        "legacy_offsets": {"left": 3332, "right": 602},
        "canonical_api": {
            "source_start_frame": source_in, "source_end_frame": source_out,
            "source_start_time": 73053.28, "source_end_time": 73053.79,
        },
        "speed": {"Percentage": speed},
        "media": {"properties": {
            "FPS": 50.0, "Frames": "1992", "Online Status": online,
        }},
    }


def test_canonical_source_time_schema_accepts_offline_resolve_metadata():
    row = from_resolve_item(resolve_item(), 50)
    assert row.coordinate_method == "RESOLVE_EXPLICIT_SOURCE_FRAME"
    assert row.online_status == "Offline"
    assert row.source_start_seconds == Fraction(833, 25)
    assert (row.logical_source_frame_in, row.logical_source_frame_out) == (1666, 1691)
    assert row.bounds_valid is True and row.duration_consistent is True


def test_raw_left_is_not_a_fallback_when_explicit_source_metadata_is_missing():
    item = resolve_item()
    item["canonical_api"]["source_start_frame"] = {"error": "unavailable"}
    row = from_resolve_item(item, 50)
    assert row.coordinate_method == "UNKNOWN"
    assert row.logical_source_frame_in is None


def test_unknown_project_duration_produces_unknown_bounds():
    item = resolve_item()
    item["media"]["properties"]["Frames"] = ""
    row = from_resolve_item(item, 50)
    assert row.bounds_valid is None
    assert row.duration_consistent is True


def test_reverse_retime_preserves_playback_direction_and_validates_duration():
    item = resolve_item(speed=-100, source_in=1049, source_out=967)
    item["timeline"] = {"start": 100, "end": 182, "duration": 82}
    row = from_resolve_item(item, 50)
    assert row.logical_source_frame_in > row.logical_source_frame_out
    assert row.bounds_valid is True
    assert row.duration_consistent is True


def test_fractional_fcpxml_seconds_are_exact():
    assert rational_seconds("30000/1001s") == Fraction(30000, 1001)


def test_fcpxml_time_map_recovers_retimed_local_source_time(tmp_path):
    path = tmp_path / "control.fcpxml"
    path.write_text("""<?xml version="1.0"?><fcpxml><resources>
      <asset id="a1" name="clip.mov" start="100/1s" duration="40/1s"/>
      </resources><library><event><project><sequence><spine>
      <clip name="clip.mov" start="120/1s" duration="2/1s">
        <timeMap><timept time="100/1s" value="100/1s"/>
        <timept time="140/1s" value="120/1s"/></timeMap>
        <video ref="a1"/></clip>
      </spine></sequence></project></event></library></fcpxml>""")
    row = parse_fcpxml_source_ranges(path)[0]
    assert row["source_start_seconds"] == 10
    assert row["source_end_seconds"] == 11
    assert row["coordinate_method"] == "FCPXML_SOURCE_TIME"


def test_otio_source_range_and_timewarp_recover_logical_frames(tmp_path):
    path = tmp_path / "control.otio"
    clip = {
        "OTIO_SCHEMA": "Clip.2", "name": "clip.mov",
        "source_range": {
            "start_time": {"rate": 50.0, "value": 200.0},
            "duration": {"rate": 50.0, "value": 100.0},
        },
        "effects": [{"OTIO_SCHEMA": "LinearTimeWarp.1", "time_scalar": 0.5}],
        "active_media_reference_key": "DEFAULT_MEDIA",
        "media_references": {"DEFAULT_MEDIA": {"available_range": {
            "start_time": {"rate": 50.0, "value": 0.0},
            "duration": {"rate": 50.0, "value": 1000.0},
        }}},
    }
    path.write_text(json.dumps({
        "global_start_time": {"rate": 50.0, "value": 0},
        "tracks": {"children": [{"name": "Video 1", "kind": "Video",
                                   "children": [clip]}]},
    }))
    row = parse_otio_source_ranges(path, track_name="Video 1")[0]
    assert (row.logical_source_frame_in, row.logical_source_frame_out) == (200, 250)
    assert row.speed_ratio == Fraction(1, 2)


def test_live_capture_fidelity_gate_and_coverage_are_locked():
    result = json.loads(FIXTURE.read_text())
    assert result["offline_fidelity_gate"]["status"] == "PASS"
    assert result["canonical"] == {
        "bounds_fail": 0, "duration_fail": 0,
        "is_edit_ambiguous": 0, "is_edit_logical_frames": 187,
        "is_edit_source_time": 187, "v7_ambiguous": 0,
        "v7_logical_frames": 87, "v7_source_time": 87,
    }
    assert result["exports"]["otio_v7_main_exact_matches"] == 87
    assert result["exports"]["otio_is_edit_exact_matches"] == 187


def test_c7309_uses_explicit_api_and_never_heuristic_divide_by_two():
    control = json.loads(FIXTURE.read_text())["c7309"]
    assert control["raw_left"] == 3332
    assert control["logical_source_frame_in"] == 1666
    assert control["logical_source_frame_out"] == 1691
    assert control["speed_ratio"] == "1/2"
    assert control["method"] == "RESOLVE_EXPLICIT_SOURCE_FRAME"
    assert control["heuristic_divide_by_two_used"] is False
    assert control["otio_exact_match"] is True


def test_failure_distribution_points_upstream():
    audit = json.loads(FIXTURE.read_text())["failure_class_audit"]
    assert audit["population"] == 132
    assert sum(audit[key] for key in (
        "A_same_shot_different_in", "B_same_source_different_region",
        "C_different_source_asset", "D_effectively_same_moment")) == 132
    assert audit["C_different_source_asset"] > audit["B_same_source_different_region"]


def test_tools_contain_no_resolve_or_database_mutation_paths():
    sources = "\n".join((ROOT / path).read_text() for path in (
        "tools/p6_30_2_resolve_offline_export.py",
        "tools/p6_30_2_offline_coordinate_audit.py",
    ))
    assert "mode=ro" in sources
    assert "build_timeline(" not in sources
    for forbidden in ("SetCurrentTimeline", "SetProperty", "CreateTimeline",
                      "DeleteTimeline", "ImportTimeline", "AppendToTimeline"):
        assert forbidden not in sources
