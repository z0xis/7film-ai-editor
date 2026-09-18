"""P6.9 -- Re-encode remediation temp-clone proof (sample).

Assert the recorded outcome of tools/p6_9_reencode_remediation_probe.py, which cloned the real
production DB to /tmp, reproduced the supported re-encode condition (features absent) for a
pre-registered sample of real 15A assets, ran the real `_encode_asset` (T7-original frame decode +
CLIP) + `_label_asset` path on the clone, and deleted the clone. Tests read only the JSON fixture.
"""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/fixtures/p6_9_reencode_sample.json"
PROBE = ROOT / "tools/p6_9_reencode_remediation_probe.py"


def _result() -> dict:
    return json.loads(FIXTURE.read_text())


def test_probe_only_reads_production_db_and_guards_the_path():
    source = PROBE.read_text()
    ast.parse(source)
    assert "shutil.copy2(REAL_DB, CLONE_PATH)" in source
    assert "shutil.rmtree(CLONE_DIR)" in source
    assert "REFUSED: probe touched production DB path" in source


def test_production_db_untouched():
    iso = _result()["production_isolation"]
    assert iso["prod_checksum_unchanged"] is True
    assert iso["prod_mtime_unchanged"] is True


def test_clone_started_byte_identical_to_production():
    assert _result()["clone"]["matches_production_initially"] is True


def test_sample_ran_without_per_asset_failures():
    counts = _result()["counts"]
    assert counts["failures"] == []
    assert counts["assets_processed"] == counts["assets_targeted"]


# GATE B -- quality restoration: formerly-zero tq becomes non-zero on the sample.
def test_gate_b_quality_restored_on_sample():
    q = _result()["quality"]
    # The sample was chosen to include large tq-zero populations; after re-encode almost none
    # remain zero.
    assert q["before_tq_zero"] > 0
    assert q["after_tq_zero"] == 0


# GATE C -- embedding restoration: valid 512-dim embeddings for every sample shot.
def test_gate_c_embeddings_restored_512_dim():
    emb = _result()["embeddings"]
    assert emb["dims"] == [512]
    assert emb["populated"] == emb["shots_total"]


# GATE D -- shot-id stability across the re-encode.
def test_gate_d_shot_ids_stable_across_reencode():
    ids = _result()["id_stability"]
    assert ids["all_stable"] is True
    assert ids["unstable_assets"] == []


def test_gate_d_segmentation_not_rescanned():
    # Ranges were re-derived from existing shots, so the media scene detector never ran.
    assert _result()["segmentation"]["scene_ranges_invocations"] == 0


# GATE E -- timeline integrity: no new dangling references.
def test_gate_e_timeline_no_new_dangling():
    tl = _result()["timeline"]
    assert tl["items_before"] == 129
    assert tl["items_after"] == 129
    assert tl["new_dangling"] == 0


def test_shot_feature_relationship_clean():
    rel = _result()["shot_feature_integrity"]
    assert rel["shots_without_features"] == 0
    assert rel["features_without_shots"] == 0
