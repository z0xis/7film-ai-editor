import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sevenfilm.services.moments import MOMENT_LIFT, MOMENT_NAMES, MOMENT_PROMPTS


def test_moment_prompts_unchanged_from_production():
    """P6.1 must not tune/rewrite moment prompts -- this locks the exact production dict."""
    assert MOMENT_PROMPTS["first_dance"] == (
        "a bride in a white dress and a groom in a suit slow dancing together,"
        " holding each other"
    )
    assert MOMENT_PROMPTS["cake"] == "a bride and groom cutting a wedding cake together with a knife"
    assert set(MOMENT_PROMPTS) == {"entrance", "ring", "kiss", "cake", "cake_feed", "first_dance"}


def test_moment_lift_threshold_unchanged():
    assert MOMENT_LIFT == 1.25


def test_moment_names_unchanged():
    assert MOMENT_NAMES["first_dance"] == "ilk dans"
    assert MOMENT_NAMES["cake"] == "pasta kesme"


def test_shadow_scripts_do_not_import_database_write_path():
    """The shadow harness scripts must never import anything that could write to the real DB."""
    import ast

    for script in ("shadow_moment_activation.py", "shadow_full_embedding_recovery.py", "shadow_moments_full.py"):
        path = Path(__file__).resolve().parents[1] / "tools" / script
        tree = ast.parse(path.read_text())
        source = path.read_text()
        assert "database.insert" not in source
        assert "database.replace_rows" not in source
        assert "UPDATE shots" not in source
        assert "INSERT INTO" not in source
        del tree


def test_no_ground_truth_fields_reach_moment_computation():
    """shadow_moments_full.py's moment/distraction/obstruction functions take only
    (shot_ids, vectors) -- no human_label or case metadata field."""
    import shadow_moments_full as smf

    sig = inspect.signature(smf.shadow_project_moments)
    assert list(sig.parameters) == ["shot_ids", "vectors"]
    sig2 = inspect.signature(smf.shadow_project_distractions)
    assert list(sig2.parameters) == ["shot_ids", "vectors"]


def test_stage_a_case_paths_are_read_only_jpgs_not_db_rows():
    import shadow_moment_activation as sma

    for case in sma.STAGE_A_CASES:
        assert case["path"].endswith(".jpg")
        assert "human_label" in case  # evaluation-only field, never passed to the encoder
