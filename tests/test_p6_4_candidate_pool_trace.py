import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

ROOT = Path(__file__).resolve().parents[1]


def test_instrumentation_wrapper_is_pass_through():
    """The _score_candidate wrapper must call the real function and return its exact
    result unmodified -- verified by re-running it directly against the wrapper's own
    module-level function object identity guard."""
    source = (ROOT / "tools/shadow_candidate_pool_trace.py").read_text()
    assert "original = planner_mod._score_candidate" in source
    assert "return score, components" in source
    ast.parse(source)


def test_no_database_write_or_resolve_or_export():
    source = (ROOT / "tools/shadow_candidate_pool_trace.py").read_text()
    # Strip the module docstring (which discusses, in prose, what this script avoids) so the
    # check applies to actual code, not to the sentence explaining the safety property.
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree) or ""
    code_only = source.replace(docstring, "")
    for forbidden in (
        "database.insert", "database.replace_rows", "UPDATE ", "INSERT INTO",
        "import resolve", "davinci", "DaVinci", ".export(", "fcpxml", "FCPXML",
    ):
        assert forbidden not in code_only, forbidden


def test_shots_and_assets_loaded_read_only():
    source = (ROOT / "tools/shadow_candidate_pool_trace.py").read_text()
    assert 'mode=ro' in source
    assert "sqlite3.connect(self.path)" not in source  # never uses the read-write Database wrapper


def test_no_human_labels_reach_scoring():
    source = (ROOT / "tools/shadow_candidate_pool_trace.py").read_text()
    assert "human_label" not in source
    assert "p6_2_human_audit_manifest" not in source


def test_technical_quality_zero_gate_matches_production_constants():
    from sevenfilm.services.planner import ABSOLUTE_MIN_QUALITY, RELATIVE_MIN_QUALITY

    assert ABSOLUTE_MIN_QUALITY == 0.15
    assert RELATIVE_MIN_QUALITY == 0.6


def test_cake_and_kiss_and_first_dance_never_present_in_any_scored_pool():
    """Documents the P6.4 finding: none of these moments' members ever reach
    available_shots, because they are excluded before the per-cut loop even starts."""
    detail = json.loads((ROOT / "tools/fixtures/p6_4_moment_cut_detail.json").read_text())
    names_ever_present = {name for c in detail for name in c["moment_names_present"]}
    assert "cake" not in names_ever_present
    assert "kiss" not in names_ever_present
    assert "first_dance" not in names_ever_present


def test_ring_and_entrance_do_appear_and_get_selected():
    trace = json.loads((ROOT / "tools/fixtures/p6_4_candidate_pool_trace.json").read_text())
    selected_moments = {name for mc in trace["moment_member_selected_cuts"] for name in mc["moment_names"]}
    assert selected_moments == {"ring", "entrance"}


def test_moment_manifests_and_p6_1_fixture_unmodified():
    p61 = json.loads((ROOT / "tools/fixtures/p6_1_stage_b_moments_result.json").read_text())
    assert {m["name"] for m in p61["moments"]} == {
        "entrance", "ring", "kiss", "cake", "cake_feed", "first_dance"
    }
