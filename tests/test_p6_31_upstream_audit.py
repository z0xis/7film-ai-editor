from __future__ import annotations

import json
from pathlib import Path

from sevenfilm.services.upstream_audit import (
    RootCause,
    SelectMembership,
    SourceRange,
    classify_select_membership,
    cross_project_status,
    eligibility_stage,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools" / "fixtures" / "p6_31_upstream_disagreement_audit.json"


def result():
    return json.loads(FIXTURE.read_text())


def test_canonical_select_membership_exact_overlap_same_source_and_outside():
    selects = [SourceRange("A.mov", 100, 200)]
    assert classify_select_membership(SourceRange("A.mov", 120, 160), selects) == SelectMembership.EXACT_OR_OVERLAP
    assert classify_select_membership(SourceRange("A.mov", 250, 300), selects) == SelectMembership.SAME_SOURCE_DIFFERENT_MOMENT
    assert classify_select_membership(SourceRange("B.mov", 100, 200), selects) == SelectMembership.OUTSIDE_SELECTS
    assert classify_select_membership(SourceRange("", 0, 0), selects) == SelectMembership.UNKNOWN


def test_membership_counts_lock_human_pipeline_without_item_index_alignment():
    audit = result()
    assert audit["method"]["alignment"].endswith("never item index")
    assert audit["reference_pipeline_15a"]["v7_to_is_edit"] == {
        "exact_or_overlap": 87, "same_source_alternate": 0, "outside": 0}
    assert sum(audit["reference_pipeline_15a"]["p6_20_to_is_edit"].values()) == 132


def test_candidate_eligibility_funnel_reports_first_proven_loss():
    assert eligibility_stage(in_pool=False, technical=None, duration=None, semantic=None,
                             chronology=None, reuse=None, scored=False) == "NOT_IN_POOL"
    assert eligibility_stage(in_pool=True, technical=False, duration=True, semantic=True,
                             chronology=True, reuse=True, scored=False) == "QUALITY"
    assert eligibility_stage(in_pool=True, technical=True, duration=True, semantic=True,
                             chronology=True, reuse=True, scored=True) == "SCORED"


def test_score_component_replay_is_factorized_and_frozen():
    replay = result()["score_replay"]
    assert replay["comparisons"] == 4
    assert all(case["margin"] > 0 for case in replay["cases"])
    assert all(case["largest_terms"] for case in replay["cases"])
    assert result()["method"]["score_replay"].startswith("exact production")


def test_disagreement_taxonomy_is_exhaustive_and_valid():
    assert RootCause.HIGH_LEVEL_STORY_INTENT_FAILURE.value in result()["root_cause_taxonomy"]
    assert sum(result()["root_cause_taxonomy"].values()) == result()["temporal_visual_audit"]["sample_size"]
    assert sum(result()["canonical_disagreements"].values()) == 132


def test_visual_audit_does_not_call_all_different_sources_errors():
    visual = result()["temporal_visual_audit"]
    assert visual["sample_size"] == 12
    assert visual["HUMAN_CLEARLY_BETTER"] == 3
    assert visual["BOTH_VALID"] + visual["DIFFERENT_EDITORIAL_INTENT"] == 9


def test_elenora_tier1_trace_schema_and_canonical_coverage():
    elenora = result()["elenora"]
    assert elenora["tier1_verified"] is True
    assert elenora["timeline"] == "Elenora Mustafa Wedding Day"
    assert elenora["video_source_items"] == 167
    assert elenora["canonical_source_items"] == 167
    assert elenora["otio_crosscheck_items"] == 167
    assert elenora["bounds_failures"] == elenora["duration_retime_failures"] == 0


def test_elenora_statistics_stay_separate_from_15a():
    audit = result()
    assert "elenora" in audit and "reference_pipeline_15a" in audit
    assert audit["elenora"]["raw_assets"] == 345
    assert audit["reference_pipeline_15a"]["raw_analysed_assets"] == 362
    assert "raw_assets" not in audit["reference_pipeline_15a"]


def test_cross_project_root_cause_classification():
    assert cross_project_status(True, True) == "CROSS_PROJECT_CONFIRMED"
    assert cross_project_status(True, False) == "CONTRADICTED_BY_ELENORA"
    assert result()["cross_project"]["sequence_story_intent"] == "CROSS_PROJECT_CONFIRMED"


def test_candidate_eligibility_is_not_main_cross_project_blocker():
    elenora = result()["elenora"]
    assert elenora["analysed_human_moments_mapped"] == 167
    assert elenora["production_quality_usable"] == 166
    assert result()["architectural_conclusion"]["candidate_eligibility"] == "NOT_MATERIAL"


def test_capture_and_audit_paths_contain_no_mutation_calls():
    sources = "\n".join((ROOT / path).read_text() for path in (
        "tools/p6_31_elenora_capture.py",
        "apps/api/sevenfilm/services/upstream_audit.py",
    ))
    assert "build_timeline(" not in sources
    for forbidden in ("SetCurrentTimeline", "SetProperty", "CreateTimeline",
                      "DeleteTimeline", "AppendToTimeline", "persist_timeline"):
        assert forbidden not in sources
    assert result()["safety"] == {
        "db_writes": 0, "resolve_project_writes": 0, "timeline_changes": 0,
        "planner_behavior_changes": 0, "reference_mutations": 0}
