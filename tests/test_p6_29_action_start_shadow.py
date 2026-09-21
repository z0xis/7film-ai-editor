from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sevenfilm.services.action_start_shadow import (
    CutInVerdict,
    TemporalEvidence,
    candidate_starts,
    rank_cut_in,
)


def _e(start: int, **values) -> TemporalEvidence:
    defaults = {"subject_readiness": .35, "action_onset": .25, "camera_settle": .45,
                "technical_usability": .7, "obstruction_clearance": .6,
                "semantic_continuity": .9, "confidence": .9}
    defaults.update(values)
    return TemporalEvidence(start_frame=start, **defaults)


def test_candidate_generation_is_bounded_and_deterministic():
    expected = (100, 110, 120, 130, 140, 150)
    assert candidate_starts(original_start=100, shot_end=200, required_source_frames=50, fps=50) == expected
    assert candidate_starts(original_start=100, shot_end=200, required_source_frames=50, fps=50) == expected


def test_duration_fit_guard_rejects_impossible_input():
    assert candidate_starts(original_start=80, shot_end=100, required_source_frames=30, fps=50) == ()


def test_slow_motion_guard_uses_required_source_frames_not_timeline_frames():
    # A 2 s timeline cut at 0.5 speed consumes 1 s / 50 source frames. The caller passes that
    # source requirement, leaving a safe 0.4 s shift. Passing 100 would correctly yield none.
    assert candidate_starts(original_start=100, shot_end=170, required_source_frames=50, fps=50)[-1] == 120
    assert candidate_starts(original_start=100, shot_end=170, required_source_frames=100, fps=50) == ()


def test_action_onset_with_subject_readiness_proposes_trim():
    result = rank_cut_in(original_start=100, evidence=(
        _e(100, subject_readiness=.2, action_onset=.1),
        _e(120, subject_readiness=.62, action_onset=.62),
    ))
    assert result.verdict == CutInVerdict.TRIM_PROPOSAL
    assert result.proposed_start == 120


def test_camera_settle_with_technical_improvement_proposes_trim():
    result = rank_cut_in(original_start=100, evidence=(
        _e(100, camera_settle=.12, technical_usability=.46),
        _e(130, camera_settle=.7, technical_usability=.72),
    ))
    assert result.verdict == CutInVerdict.TRIM_PROPOSAL


def test_intentional_still_keeps_original():
    result = rank_cut_in(original_start=100, intentional_still=True, evidence=(
        _e(100, action_onset=.05), _e(120, action_onset=.7, subject_readiness=.8)))
    assert result.verdict == CutInVerdict.KEEP_ORIGINAL


def test_beat_proximity_cannot_override_bad_visual_start():
    base = _e(100, beat_proximity=0, technical_usability=.7)
    later = _e(120, beat_proximity=1, technical_usability=.3, action_onset=.8,
               subject_readiness=.8)
    assert rank_cut_in(original_start=100, evidence=(base, later)).verdict != CutInVerdict.TRIM_PROPOSAL


def test_unknown_on_insufficient_evidence():
    assert rank_cut_in(original_start=100, evidence=(_e(100),)).verdict == CutInVerdict.UNKNOWN


def test_ambiguous_case_is_review():
    result = rank_cut_in(original_start=100, evidence=(
        _e(100), _e(120, action_onset=.48, subject_readiness=.42)))
    assert result.verdict == CutInVerdict.REVIEW


def test_manual_reference_cannot_be_passed_to_ranker():
    import inspect

    assert "human" not in inspect.signature(rank_cut_in).parameters
    assert "manual" not in inspect.signature(rank_cut_in).parameters


def test_module_has_no_database_resolve_or_planner_write_path():
    from sevenfilm.services import action_start_shadow

    source = Path(action_start_shadow.__file__).read_text()
    for forbidden in ("Database", "DaVinciResolve", "build_timeline", "execute(", "commit("):
        assert forbidden not in source


def test_evaluator_is_read_only_and_has_no_resolve_surface():
    source = (Path(__file__).resolve().parents[1] / "tools" /
              "p6_29_action_start_shadow.py").read_text()
    assert "mode=ro" in source
    assert "DaVinciResolve" not in source
    assert "build_timeline(" not in source
    assert ".execute(\"INSERT" not in source
    assert ".execute(\"UPDATE" not in source
    assert ".execute(\"DELETE" not in source


def test_evidence_is_immutable_and_deterministic():
    base = _e(100)
    later = replace(base, start_frame=120)
    assert rank_cut_in(original_start=100, evidence=(base, later)) == rank_cut_in(
        original_start=100, evidence=(base, later))
