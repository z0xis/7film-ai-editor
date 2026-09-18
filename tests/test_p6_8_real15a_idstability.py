"""P6.8 -- Real-15A temp-clone reanalysis ID-stability verification.

These assert the recorded outcome of tools/p6_8_real15a_idstability_probe.py, which cloned the
real production DB to /tmp, exercised today's supported `shots` reanalysis path against the
actual 362-asset / 2638-shot 15A state, and deleted the clone. The probe never opens the
production DB for writing (only shutil.copy2 reads it). The tests here read only its JSON
fixture -- they do not touch any DB.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/fixtures/p6_8_real15a_idstability.json"
PROBE = ROOT / "tools/p6_8_real15a_idstability_probe.py"


def _result() -> dict:
    return json.loads(FIXTURE.read_text())


# ---- probe hygiene / production isolation --------------------------------------------------
def test_probe_only_reads_production_db_never_opens_it_for_writing():
    source = PROBE.read_text()
    ast.parse(source)
    assert "shutil.copy2(REAL_DB, CLONE_PATH)" in source
    assert "shutil.rmtree(CLONE_DIR)" in source
    # The real DB is only ever a copy source; a Database is never constructed on it.
    assert "Database(REAL_DB)" not in source
    assert "_assert_not_production" in source


def test_production_db_untouched_by_probe():
    result = _result()
    iso = result["production_isolation"]
    assert iso["prod_checksum_unchanged"] is True
    assert iso["prod_mtime_unchanged"] is True
    assert result["production_baseline"]["prod_checksum_before"] == iso["prod_checksum_after"]


def test_clone_started_byte_identical_to_production():
    clone = _result()["clone"]
    assert clone["matches_production_initially"] is True


# ---- baseline ------------------------------------------------------------------------------
def test_baseline_matches_known_15a_identity():
    base = _result()["production_baseline"]
    assert base["assets"] == 362
    assert base["shots_before"] == 2638
    assert base["features"] == 2638
    assert base["timeline_items"] == 129


# ---- GATE A: actual 15A shot-id stability --------------------------------------------------
def test_gate_a_shot_id_set_and_manifest_are_identical():
    shots = _result()["before_after_shots"]
    assert shots["before_count"] == 2638
    assert shots["after_count"] == 2638
    assert shots["shot_id_set_equal"] is True
    assert shots["boundary_equal"] is True
    assert shots["full_row_identical"] is True
    assert shots["classification"] == "A"
    assert (shots["before_shot_manifest_hash_full"]
            == shots["after_shot_manifest_hash_full"])


# ---- GATE B: all-asset stability -----------------------------------------------------------
def test_gate_b_all_362_assets_stable():
    shots = _result()["before_after_shots"]
    assert shots["assets_total"] == 362
    assert shots["assets_stable"] == 362
    assert shots["assets_differ"] == []


# ---- GATE C: timeline integrity ------------------------------------------------------------
def test_gate_c_timeline_unchanged_and_no_new_dangling():
    tl = _result()["timeline"]
    assert tl["items_before"] == 129
    assert tl["items_after"] == 129
    assert tl["item_manifest_equal"] is True
    assert tl["resolved_before"] == 129
    assert tl["resolved_after"] == 129
    assert tl["new_dangling_references"] == 0


# ---- GATE D: shot<->feature relationship ---------------------------------------------------
def test_gate_d_shot_feature_relationship_is_one_to_one():
    rel = _result()["shot_feature_relationship"]
    assert rel["shots_with_features"] == 2638
    assert rel["shots_without_features"] == 0
    assert rel["features_without_shots"] == 0


# ---- GATE E: segmentation / heavy path skipped ---------------------------------------------
def test_gate_e_supported_path_does_not_resegment_or_run_heavy_models():
    path = _result()["supported_path"]
    assert path["encode_asset_invocations"] == 0
    assert path["scene_ranges_invocations"] == 0
    assert path["clip_encode_invocations"] == 0


# ---- GATE F: real-data forced-failure rollback ---------------------------------------------
def test_gate_f_forced_failure_rolls_back_on_real_data():
    rb = _result()["forced_failure_rollback"]
    assert rb["raised"] is True
    assert rb["target_old_ids_preserved"] is True
    assert rb["other_asset_untouched"] is True
    assert rb["target_shot_count"] >= 1
