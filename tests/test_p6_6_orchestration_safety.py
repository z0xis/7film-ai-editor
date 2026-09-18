import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_probe_script_only_touches_temp_clone_path():
    source = (ROOT / "tools/shadow_reanalysis_orchestration_probe.py").read_text()
    ast.parse(source)
    assert 'CLONE_DIR = Path("/tmp/p66_tempdb")' in source
    assert "shutil.copy2(REAL_DB, CLONE_PATH)" in source
    assert "shutil.rmtree(CLONE_DIR" in source
    # The real DB path is only ever the *source* of a copy, never opened for writing.
    assert 'Database(REAL_DB)' not in source


def test_probe_confirms_fk_not_enforced_on_normal_connection():
    result = json.loads((ROOT / "tools/fixtures/p6_6_orchestration_probe.json").read_text())
    assert result["foreign_keys_pragma_on_normal_connection"] == 0


def test_probe_confirms_dangling_timeline_reference_reproducible():
    """Documents the P6.6 hard-blocker finding: _label_asset()'s DELETE-then-insert-loop
    pattern, run verbatim against a cloned DB, leaves a real timeline_items row pointing at
    a shots row that no longer exists."""
    result = json.loads((ROOT / "tools/fixtures/p6_6_orchestration_probe.json").read_text())
    assert result["shot_present_before_delete"] is True
    assert result["shot_present_after_delete"] is False
    assert result["timeline_item_still_present_after_delete"] is True
    assert result["timeline_item_now_dangling"] is True


def test_probe_confirms_job_uniqueness_enforced():
    result = json.loads((ROOT / "tools/fixtures/p6_6_orchestration_probe.json").read_text())
    assert result["job_uniqueness_enforced"] is True


def test_label_asset_no_longer_uses_non_atomic_delete_then_insert_loop():
    """P6.6 found and locked the pre-fix shape (a bare DELETE followed by a loop of
    individually-committed inserts). P6.7 replaced it with the atomic replace_rows() path --
    this test now asserts the fixed shape is gone, as the historical test said it should be
    revisited for."""
    source = (ROOT / "apps/api/sevenfilm/services/analysis.py").read_text()
    label_asset_start = source.index("def _label_asset(")
    label_asset_end = source.index("def analyze_shots(")
    label_asset_body = source[label_asset_start:label_asset_end]
    assert 'database.execute("DELETE FROM shots WHERE asset_id = ?"' not in label_asset_body
    assert 'database.replace_rows("shots", "asset_id", asset.id, new_rows)' in label_asset_body


def test_store_features_still_uses_atomic_replace_rows():
    """Contrast case: shot_features IS atomic via replace_rows(), unlike shots used to be."""
    source = (ROOT / "apps/api/sevenfilm/services/analysis.py").read_text()
    assert 'database.replace_rows("shot_features", "asset_id", asset.id, rows)' in source


def test_semantic_readiness_gate_would_block_create_timeline_for_15a_today():
    """create_timeline() refuses (422) when semantic_readiness().status is
    NOT_READY_FOR_ROUGH_CUT -- confirms the existing 129-item rough cut predates or bypassed
    this gate, since 15A is 100% opencv_fallback today."""
    source = (ROOT / "apps/api/sevenfilm/api.py").read_text()
    assert "NOT_READY_FOR_ROUGH_CUT" in source
    assert "semantic_readiness(DATABASE, project_id)" in source


def test_no_production_db_write_in_probe():
    source = (ROOT / "tools/shadow_reanalysis_orchestration_probe.py").read_text()
    assert 'Database(REAL_DB)' not in source
    assert 'db = Database(CLONE_PATH)' in source


def test_cancellation_checked_at_asset_boundaries_not_inside_label_asset():
    """raise_if_cancelled() is called at the top of analyze_shots()'s per-asset loops, never
    inside _label_asset()'s own delete/insert body -- so cooperative cancellation cannot land
    mid-asset, only a hard crash/restart can. This is the precise distinction P6.6 draws
    between the two hazards."""
    source = (ROOT / "apps/api/sevenfilm/services/analysis.py").read_text()
    label_asset_start = source.index("def _label_asset(")
    label_asset_end = source.index("def analyze_shots(")
    label_asset_body = source[label_asset_start:label_asset_end]
    assert "raise_if_cancelled" not in label_asset_body


def test_replace_rows_helper_exists_and_is_now_used_by_label_asset():
    """The atomic helper that fixed _label_asset()'s gap already existed (proven by
    _store_features() using it for shot_features) and P6.7 wired _label_asset() to use it too
    for shots -- historically this test asserted the helper was unused there; it now asserts
    the fix landed."""
    source = (ROOT / "apps/api/sevenfilm/services/analysis.py").read_text()
    label_asset_start = source.index("def _label_asset(")
    label_asset_end = source.index("def analyze_shots(")
    label_asset_body = source[label_asset_start:label_asset_end]
    assert "replace_rows" in label_asset_body
    db_source = (ROOT / "apps/api/sevenfilm/db.py").read_text()
    assert "def replace_rows(" in db_source


def test_no_timeline_writes_anywhere_in_shots_analysis_call_graph():
    for path in ("analysis.py", "windows.py", "vision.py"):
        source = (ROOT / "apps/api/sevenfilm/services" / path).read_text()
        assert "timeline_items" not in source
        assert "timeline_versions" not in source


def test_orphan_recovery_does_not_touch_shots_or_shot_features():
    """recover_orphaned_jobs() only settles job status on restart; it does not repair any
    partial shots/shot_features state a crash left behind mid-_label_asset()."""
    source = (ROOT / "apps/api/sevenfilm/db.py").read_text()
    start = source.index("def recover_orphaned_jobs(")
    body = source[start:start + 1200]
    assert 'UPDATE shots' not in body
    assert 'UPDATE shot_features' not in body
    assert 'DELETE FROM shots' not in body
    assert 'DELETE FROM shot_features' not in body


def test_shot_id_is_deterministic_uuid5_of_asset_and_boundaries():
    """Locks the exact shot_id formula: changing start_frame/duration_frames by even one
    frame produces a different id, which is what makes a segmentation change a PERMANENT
    orphan risk (not just a transient crash-window risk) for any timeline_items row still
    pointing at the old id."""
    source = (ROOT / "apps/api/sevenfilm/services/analysis.py").read_text()
    assert 'f"sevenfilm:{asset_id}:{source_range.start_frame}:{source_range.duration_frames}"' in source
