import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

ROOT = Path(__file__).resolve().parents[1]


def test_day_by_asset_contract_matches_production_function():
    """The shadow builder must reuse planner.py's own _day_position/_timecode_seconds,
    not a reimplementation -- this is a direct identity check, not a behavioral guess."""
    import shadow_day_by_asset as sut
    from sevenfilm.services.planner import _day_position, _timecode_seconds

    assert sut._day_position is _day_position
    assert sut._timecode_seconds is _timecode_seconds


def test_drone_assets_have_no_timecode_and_are_excluded():
    data = json.loads((ROOT / "tools/fixtures/p6_3_shadow_day_by_asset.json").read_text())
    assert data["without_timecode"] == 10
    assert all(name.startswith("DJI_") for name in data["unmapped_names"])
    for info in data["day_by_asset"].values():
        if info["name"].startswith("DJI_"):
            assert info["day_position"] is None


def test_day_positions_are_normalized_0_to_1():
    data = json.loads((ROOT / "tools/fixtures/p6_3_shadow_day_by_asset.json").read_text())
    positions = [
        info["day_position"] for info in data["day_by_asset"].values()
        if info["day_position"] is not None
    ]
    assert positions
    assert min(positions) >= 0.0
    assert max(positions) <= 1.0


def test_no_database_write_in_shadow_scripts():
    for script in ("shadow_day_by_asset.py", "shadow_planner_trace.py"):
        source = (ROOT / "tools" / script).read_text()
        ast.parse(source)
        assert "database.insert" not in source
        assert "database.replace_rows" not in source
        assert "UPDATE media_assets" not in source
        assert "INSERT INTO" not in source
        assert "import build_timeline" not in source
        assert "from sevenfilm.services.planner import build_timeline" not in source


def test_no_human_labels_feed_chronology_or_due_now():
    for script in ("shadow_day_by_asset.py", "shadow_planner_trace.py"):
        source = (ROOT / "tools" / script).read_text()
        assert "human_label" not in source
        assert "p6_2_human_audit_manifest" not in source


def test_moment_bonus_and_day_spread_constants_unchanged():
    from sevenfilm.services.planner import MOMENT_BONUS, MOMENT_DAY_SPREAD

    assert MOMENT_BONUS == 0.1
    assert MOMENT_DAY_SPREAD == 0.05


def test_cake_moment_day_anchored_on_full_membership():
    """Positive control: cake's members all share one asset, so its moment_day is not
    anchored on a subset the way first_dance's is."""
    trace = json.loads((ROOT / "tools/fixtures/p6_3_planner_trace.json").read_text())
    cake_contributors = trace["contributors"]["cake"]
    assert all(c["day_position"] is not None for c in cake_contributors)
    assert len({c["day_position"] for c in cake_contributors}) == 1


def test_first_dance_moment_day_anchored_on_minority_of_members():
    """Documents the P6.3 finding: only 2/8 first_dance members carry a day_position
    (the two confusables), while the drone majority is excluded from moment_day."""
    trace = json.loads((ROOT / "tools/fixtures/p6_3_planner_trace.json").read_text())
    fd_contributors = trace["contributors"]["first_dance"]
    timed = [c for c in fd_contributors if c["day_position"] is not None]
    assert len(timed) == 2
