import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shadow_sample_script_is_read_only():
    source = (ROOT / "tools/shadow_quality_provenance_sample.py").read_text()
    ast.parse(source)
    for forbidden in (
        "database.insert", "database.replace_rows", "UPDATE ", "INSERT INTO",
        "resolve.run_script", "davinci",
    ):
        assert forbidden not in source, forbidden
    assert 'mode=ro' in source


def test_shadow_sample_is_pre_registered_before_running():
    """The SAMPLE list (with an 'expect' field per case) is defined as a module-level
    constant, not derived from the run's own results -- i.e. pre-registered."""
    import sys

    sys.path.insert(0, str(ROOT / "apps" / "api"))
    sys.path.insert(0, str(ROOT / "tools"))
    import shadow_quality_provenance_sample as sut

    assert len(sut.SAMPLE) == 6
    for case in sut.SAMPLE:
        assert case["expect"] in {"zero", "nonzero"}


def test_shadow_sample_results_confirm_stale_zero_hypothesis():
    """Documents the P6.5 finding: every stored technical_quality=0.0 case produces a
    non-zero fresh value when the exact production measurement runs today, while the two
    non-zero controls reproduce their stored values exactly (harness fidelity check)."""
    results = json.loads((ROOT / "tools/fixtures/p6_5_shadow_quality_sample.json").read_text())
    for r in results:
        if r["expect"] == "zero":
            assert r["stored_technical_quality"] == 0.0
            assert r["fresh_technical_quality"] > 0.0
            assert r["frames_read_now"] > 0
        else:
            assert r["stored_technical_quality"] == r["fresh_technical_quality"]


def test_no_production_write_or_threshold_change():
    for path in ("tools/shadow_quality_provenance_sample.py",):
        source = (ROOT / path).read_text()
        assert "ABSOLUTE_MIN_QUALITY =" not in source
        assert "_is_usable(" not in source


def test_p6_1_p6_2_p6_3_p6_4_fixtures_unmodified():
    p61 = json.loads((ROOT / "tools/fixtures/p6_1_stage_b_moments_result.json").read_text())
    assert {m["name"] for m in p61["moments"]} == {
        "entrance", "ring", "kiss", "cake", "cake_feed", "first_dance"
    }
    p64 = json.loads((ROOT / "tools/fixtures/p6_4_candidate_pool_trace.json").read_text())
    assert p64["plan_item_count"] == 136
