from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p6_30_audit", ROOT / "tools" / "p6_30_phase_provenance_audit.py")
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)


def _result():
    return json.loads((ROOT / "tools" / "fixtures" /
                       "p6_30_phase_provenance_audit.json").read_text())


def test_v7_trace_has_no_speed_or_source_timebase_field():
    trace = json.loads((ROOT / "data" / "reference_editor" / "raw" / "v7_trace.json").read_text())
    assert all(len(item) == 4 for item in trace["items"])
    assert _result()["v7_trace_provenance"]["per_item_speed_present"] is False


def test_v7_contains_physically_out_of_range_source_offsets():
    evidence = _result()["v7_trace_provenance"]
    assert evidence["out_of_source_range"] > 0
    assert evidence["phase_benchmark_valid"] is False


def test_c7309_raw_control_is_outside_the_source():
    control = _result()["c7309_control"]
    assert control["v7_raw_left"] == 3332
    assert control["asset_frames_at_db_rate"] == 1992
    assert control["v7_raw_left_in_range"] is False


def test_c7309_slowmo_normalization_lands_in_the_p6_20_phase():
    control = _result()["c7309_control"]
    assert control["slowmo_normalized_left"] == 1666
    assert control["normalized_human_inside_selected_shot"] is True
    assert control["normalized_human_inside_selected_source_range"] is True


def test_containing_shot_respects_chronological_half_open_ranges():
    shots = [{"id": "early", "start_frame": 0, "duration_frames": 100},
             {"id": "late", "start_frame": 100, "duration_frames": 100}]
    assert AUDIT.containing_shot(shots, 99)["id"] == "early"
    assert AUDIT.containing_shot(shots, 100)["id"] == "late"
    assert AUDIT.containing_shot(shots, 200) is None


def test_duration_fit_guard_uses_required_source_frames():
    shot = {"duration_frames": 50}
    assert AUDIT.duration_fits(shot, 50)
    assert not AUDIT.duration_fits(shot, 51)
    assert not AUDIT.duration_fits(shot, 0)


def test_selector_was_not_run_on_invalid_benchmark():
    classifications = _result()["shadow_phase_classification"]
    assert classifications == {
        "KEEP_PHASE": 0, "SWITCH_PHASE": 0, "REVIEW": 0, "UNKNOWN": 132,
        "reason": "V7 source coordinates lack speed/timebase provenance; selector not run",
    }


def test_audit_is_read_only_and_has_no_resolve_or_planner_write_path():
    source = (ROOT / "tools" / "p6_30_phase_provenance_audit.py").read_text()
    assert "mode=ro" in source
    assert "DaVinciResolve" not in source
    assert "build_timeline(" not in source
    for mutation in ('execute("INSERT', 'execute("UPDATE', 'execute("DELETE'):
        assert mutation not in source
