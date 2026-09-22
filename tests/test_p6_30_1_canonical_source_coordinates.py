from __future__ import annotations

import importlib.util
import json
from fractions import Fraction
from pathlib import Path

from sevenfilm.services.canonical_source_coordinates import (
    CoordinateConfidence,
    CoordinateEvidence,
    canonicalize,
    duration_is_consistent,
    expected_source_duration,
    range_relation,
    rational_rate,
    seconds_to_frame,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "p6_30_1_coordinate_fidelity.json"


def evidence(**changes):
    values = {
        "asset_id": "asset", "source_filename": "clip.mov",
        "physical_asset_frames": 1000, "source_fps": "25/1",
        "timeline_fps": "50/1", "raw_resolve_left_offset": 400,
        "raw_resolve_right_offset": 100, "raw_timeline_start": 0,
        "raw_timeline_end": 200, "retime_mode": "constant",
        "speed_ratio": "1/1", "api_source_in_frame": 100,
        "api_source_out_frame": 200,
    }
    values.update(changes)
    return CoordinateEvidence(**values)


def test_schema_emits_physical_source_domain_fields():
    result = canonicalize(evidence()).as_dict()
    assert result["coordinate_schema_version"] == "p6.30.1-canonical-source-v1"
    assert result["canonical_source_in"] == 100
    assert result["canonical_source_out"] == 200
    assert result["canonical_source_duration"] == 100
    assert result["coordinate_confidence"] == CoordinateConfidence.AUTHORITATIVE


def test_rational_fps_and_source_time_conversion_are_exact():
    rate = rational_rate("30000/1001")
    assert rate == Fraction(30000, 1001)
    assert seconds_to_frame(Fraction(1001, 30000), rate) == 1


def test_timeline_domain_offset_is_never_promoted_to_source_frame():
    result = canonicalize(evidence(
        api_source_in_frame=None, api_source_out_frame=None,
        api_source_in_seconds=None, api_source_out_seconds=None,
    ))
    assert result.coordinate_confidence == CoordinateConfidence.UNKNOWN_COORDINATE
    assert result.canonical_source_in is None
    assert result.raw_resolve_left_offset == 400


def test_authoritative_source_seconds_require_native_fps():
    result = canonicalize(evidence(
        api_source_in_frame=None, api_source_out_frame=None,
        api_source_in_seconds="4", api_source_out_seconds="8",
    ))
    assert result.canonical_source_in == 100
    assert result.canonical_source_out == 200
    assert result.coordinate_method == "resolve_source_time_api_x_native_fps"


def test_physical_bounds_are_strict():
    result = canonicalize(evidence(api_source_out_frame=1001))
    assert result.coordinate_confidence == CoordinateConfidence.UNKNOWN_COORDINATE
    assert result.bounds_valid is False


def test_duration_mapping_uses_explicit_source_time_per_timeline_time_ratio():
    assert expected_source_duration(
        timeline_duration_frames=200, timeline_fps=Fraction(50),
        source_fps=Fraction(25), speed_ratio=Fraction(1),
    ) == 100
    assert expected_source_duration(
        timeline_duration_frames=200, timeline_fps=Fraction(50),
        source_fps=Fraction(25), speed_ratio=Fraction(1, 2),
    ) == 50
    assert expected_source_duration(
        timeline_duration_frames=200, timeline_fps=Fraction(50),
        source_fps=Fraction(25), speed_ratio=Fraction(1, 4),
    ) == 25


def test_equal_timebases_and_boundary_rounding():
    assert expected_source_duration(
        timeline_duration_frames=25, timeline_fps=Fraction(25),
        source_fps=Fraction(25), speed_ratio=Fraction(1),
    ) == 25
    assert duration_is_consistent(
        canonical_duration=1000, timeline_duration_frames=1001,
        timeline_fps=Fraction(30000, 1001), source_fps=Fraction(30000, 1001),
        speed_ratio=Fraction(1), tolerance_frames=1,
    )


def test_inconsistent_retime_stays_unknown():
    result = canonicalize(evidence(api_source_out_frame=250))
    assert result.coordinate_confidence == CoordinateConfidence.UNKNOWN_COORDINATE
    assert result.duration_consistent is False


def test_same_asset_reuse_relations_preserve_distinct_forward_ranges():
    first = canonicalize(evidence(api_source_in_frame=100, api_source_out_frame=200))
    second = canonicalize(evidence(
        raw_timeline_end=200, api_source_in_frame=250, api_source_out_frame=350,
    ))
    exact = canonicalize(evidence(api_source_in_frame=100, api_source_out_frame=200))
    assert range_relation(first, second) == "FORWARD_DISTINCT"
    assert range_relation(first, exact) == "EXACT_REPEAT"


def test_c7309_regression_never_certifies_divide_by_two_guess():
    fixture = json.loads(FIXTURE.read_text())
    control = fixture["c7309_regression"]
    assert control["raw_resolve_left_offset"] == 3332
    assert control["physical_asset_frames"] == 1992
    assert control["old_divide_by_two_value"] == 1666
    assert control["old_divide_by_two_is_canonical"] is False
    assert control["coordinate_confidence"] == "UNKNOWN_COORDINATE"


def test_fidelity_gate_blocks_benchmarks_when_authority_is_missing():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["fidelity_gate"]["status"] == "FAIL"
    assert fixture["benchmarks"]["p6_29_rerun"] is False
    assert fixture["benchmarks"]["p6_30_rerun"] is False


def test_audit_and_probe_have_no_project_mutation_calls():
    audit = (ROOT / "tools" / "p6_30_1_coordinate_fidelity_audit.py").read_text()
    probe = (ROOT / "tools" / "p6_30_1_resolve_coordinate_probe.py").read_text()
    assert "mode=ro" in audit
    assert "build_timeline(" not in audit + probe
    forbidden = ("SetCurrentTimeline", "SetProperty", "ImportTimeline", "CreateTimeline",
                 "DeleteTimeline", "AppendToTimeline", "InsertGeneratorIntoTimeline")
    for name in forbidden:
        assert name not in probe


def test_audit_execution_does_not_change_database():
    spec = importlib.util.spec_from_file_location(
        "p6_30_1_audit", ROOT / "tools" / "p6_30_1_coordinate_fidelity_audit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.run()["db_unchanged"] is True
