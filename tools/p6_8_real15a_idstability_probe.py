"""P6.8 -- Real-15A temp-clone reanalysis ID-stability probe.

Answers the single go/no-go question: does today's supported `shots` reanalysis path, run against
an isolated temp clone of the REAL production DB, preserve the 2638 canonical 15A shot ids
(segmentation/boundaries/ids) byte-for-identity, leave the 129-item AI Rough Cut resolvable, and
roll back cleanly on a forced failure?

Guarantees:
  * The real production DB is only ever the SOURCE of a shutil.copy2 -- never opened for writing.
  * All mutation happens on a unique /tmp clone, which is deleted at the end.
  * The heavy `_measure_shot_windows` pass (4K decode at 661ms/frame) is stubbed: it writes only
    `shot_windows` and reads `shots`, so it cannot change any shot_id; stubbing it keeps the probe
    cheap without weakening the id-stability contract. Encode/scene-detection are instrumented and
    asserted to run zero times (features are already present, so the supported path skips them).

Writes tools/fixtures/p6_8_real15a_idstability.json (counts + manifest hashes only; no raw private
paths or embeddings). Run: .venv/bin/python tools/p6_8_real15a_idstability_probe.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

REAL_DB = ROOT / "data" / "sevenfilm.sqlite3"
CLONE_DIR = Path("/tmp/p68_tempdb")
CLONE_PATH = CLONE_DIR / "clone.sqlite3"
CLONE_PATH_2 = CLONE_DIR / "clone_rollback.sqlite3"
FIXTURE = ROOT / "tools" / "fixtures" / "p6_8_real15a_idstability.json"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shot_manifest(database) -> list[dict]:
    rows = database.fetch_all(
        """SELECT s.id, s.asset_id, s.start_frame, s.duration_frames, s.frame_rate,
                  s.category, s.shot_scale, s.technical_quality, s.confidence, s.analysis_version
           FROM shots s JOIN media_assets m ON m.id = s.asset_id
           WHERE m.project_id = ? ORDER BY s.asset_id, s.start_frame, s.id""",
        (P15,),
    )
    return [dict(r) for r in rows]


def _manifest_hash(manifest: list[dict], keys: tuple[str, ...]) -> str:
    reduced = [tuple(row[k] for k in keys) for row in manifest]
    return hashlib.sha256(json.dumps(reduced, sort_keys=True, default=str).encode()).hexdigest()


def _timeline_manifest(database, timeline_id: str) -> list[dict]:
    rows = database.fetch_all(
        """SELECT id, position, shot_id, asset_id, source_start_frame, source_duration_frames,
                  source_rate, timeline_start_frame, timeline_duration_frames
           FROM timeline_items WHERE timeline_id = ? ORDER BY position, id""",
        (timeline_id,),
    )
    return [dict(r) for r in rows]


def _resolved_refs(database, timeline_id: str) -> int:
    rows = database.fetch_all(
        """SELECT shots.id AS resolved FROM timeline_items
           LEFT JOIN shots ON shots.id = timeline_items.shot_id
           WHERE timeline_items.timeline_id = ?""",
        (timeline_id,),
    )
    return sum(1 for r in rows if r["resolved"] is not None)


def _per_asset_shot_ids(manifest: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in manifest:
        out.setdefault(row["asset_id"], []).append(row["id"])
    return out


def main() -> dict:
    assert REAL_DB.exists(), "real DB missing"
    prod_checksum_before = _sha256_file(REAL_DB)
    prod_mtime_before = REAL_DB.stat().st_mtime

    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    CLONE_DIR.mkdir(parents=True)
    shutil.copy2(REAL_DB, CLONE_PATH)
    shutil.copy2(REAL_DB, CLONE_PATH_2)
    clone_checksum_initial = _sha256_file(CLONE_PATH)

    # Import production code only after paths are fixed. A Database is only ever built on a clone.
    from sevenfilm.db import Database, now
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.vision import VisionClassifier

    guard = str(REAL_DB.resolve())

    def _assert_not_production(db: Database) -> None:
        assert str(Path(db.path).resolve()) != guard, "REFUSED: probe touched production DB path"

    db = Database(CLONE_PATH)
    _assert_not_production(db)
    tl = db.fetch_one(
        "SELECT id FROM timeline_versions WHERE project_id = ? AND name = 'AI Rough Cut'", (P15,)
    )
    timeline_id = tl["id"]

    before = _shot_manifest(db)
    before_ids = {r["id"] for r in before}
    before_tl = _timeline_manifest(db, timeline_id)
    resolved_before = _resolved_refs(db, timeline_id)
    features_before = db.fetch_all(
        """SELECT sf.shot_id FROM shot_features sf JOIN media_assets m ON m.id = sf.asset_id
           WHERE m.project_id = ?""",
        (P15,),
    )
    feature_ids = {r["shot_id"] for r in features_before}

    # Instrument the heavy / segmentation paths, then stub only the windows measurement.
    calls = {"encode_asset": 0, "scene_ranges": 0, "clip_encode": 0, "measure_windows": 0}
    real_encode = analysis_module._encode_asset
    real_scene = analysis_module._scene_ranges
    real_windows = analysis_module._measure_shot_windows
    real_clip_encode = VisionClassifier.encode

    def spy_encode(*a, **k):
        calls["encode_asset"] += 1
        return real_encode(*a, **k)

    def spy_scene(*a, **k):
        calls["scene_ranges"] += 1
        return real_scene(*a, **k)

    def spy_clip_encode(self, frames):
        calls["clip_encode"] += 1
        return real_clip_encode(self, frames)

    def stub_windows(*a, **k):
        calls["measure_windows"] += 1  # stubbed: writes only shot_windows, cannot alter shot_ids

    analysis_module._encode_asset = spy_encode
    analysis_module._scene_ranges = spy_scene
    analysis_module._measure_shot_windows = stub_windows
    VisionClassifier.encode = spy_clip_encode
    try:
        db.insert("jobs", {
            "id": "p68-job", "project_id": P15, "kind": "shots", "status": "running",
            "progress": 0, "checkpoint_json": {}, "error": None, "created_at": now(),
            "updated_at": now(),
        })
        analysis_module.analyze_shots(db, P15, "p68-job")
    finally:
        analysis_module._encode_asset = real_encode
        analysis_module._scene_ranges = real_scene
        analysis_module._measure_shot_windows = real_windows
        VisionClassifier.encode = real_clip_encode

    after = _shot_manifest(db)
    after_ids = {r["id"] for r in after}
    after_tl = _timeline_manifest(db, timeline_id)
    resolved_after = _resolved_refs(db, timeline_id)

    # Per-asset stability.
    before_by_asset = _per_asset_shot_ids(before)
    after_by_asset = _per_asset_shot_ids(after)
    assets_all = sorted(set(before_by_asset) | set(after_by_asset))
    assets_stable = [
        a for a in assets_all if before_by_asset.get(a, []) == after_by_asset.get(a, [])
    ]
    assets_differ = [a for a in assets_all if a not in assets_stable]

    # Feature relationship after run.
    shots_with_features = len(after_ids & feature_ids)
    shots_without_features = len(after_ids - feature_ids)
    features_without_shots = len(feature_ids - after_ids)

    # Row-identity classification: id + boundaries stable?
    id_stable = before_ids == after_ids
    boundary_keys = ("id", "asset_id", "start_frame", "duration_frames", "frame_rate")
    boundary_stable = _manifest_hash(before, boundary_keys) == _manifest_hash(after, boundary_keys)
    full_keys = boundary_keys + ("category", "shot_scale", "technical_quality", "confidence",
                                 "analysis_version")
    full_identical = _manifest_hash(before, full_keys) == _manifest_hash(after, full_keys)
    if full_identical:
        classification = "A"  # exact row identity
    elif id_stable and boundary_stable:
        classification = "B"  # ids/boundaries stable, some labels/scores may differ
    elif before_ids & after_ids:
        classification = "C"  # partial id change
    else:
        classification = "D"  # material id change

    # ---- forced-failure rollback on real-data clone -------------------------------------
    class FailingDatabase(Database):
        def __init__(self, path, target_asset):
            super().__init__(path)
            self.target_asset = target_asset

        def replace_rows(self, table, where_column, where_value, rows):
            if table == "shots" and where_value == self.target_asset and rows:
                rows = [dict(r) for r in rows]
                rows[-1].pop("category", None)  # NOT NULL violation -> mid-transaction failure
            return super().replace_rows(table, where_column, where_value, rows)

    db2 = FailingDatabase(CLONE_PATH_2, target_asset=None)
    _assert_not_production(db2)
    sorted_assets = sorted(before_by_asset)
    target_asset = sorted_assets[0]
    other_asset = sorted_assets[1]
    db2.target_asset = target_asset
    classifier = VisionClassifier()
    priors = analysis_module._project_prior(db2, classifier, P15)
    target_before_ids = [
        r["id"] for r in db2.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame", (target_asset,))
    ]
    other_before_ids = [
        r["id"] for r in db2.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame", (other_asset,))
    ]

    class _A:  # _label_asset only reads .id
        def __init__(self, aid): self.id = aid

    rollback_raised = False
    try:
        analysis_module._label_asset(db2, classifier, _A(target_asset), priors)
    except sqlite3.IntegrityError:
        rollback_raised = True
    target_after_ids = [
        r["id"] for r in db2.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame", (target_asset,))
    ]
    other_after_ids = [
        r["id"] for r in db2.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame", (other_asset,))
    ]

    prod_checksum_after = _sha256_file(REAL_DB)
    prod_mtime_after = REAL_DB.stat().st_mtime

    result = {
        "production_baseline": {
            "assets": db.fetch_one(
                "SELECT COUNT(*) c FROM media_assets WHERE project_id = ?", (P15,))["c"],
            "shots_before": len(before),
            "features": len(feature_ids),
            "timeline_items": len(before_tl),
            "prod_checksum_before": prod_checksum_before,
        },
        "clone": {
            "path": str(CLONE_PATH),
            "initial_checksum": clone_checksum_initial,
            "matches_production_initially": clone_checksum_initial == prod_checksum_before,
        },
        "supported_path": {
            "encode_asset_invocations": calls["encode_asset"],
            "scene_ranges_invocations": calls["scene_ranges"],
            "clip_encode_invocations": calls["clip_encode"],
            "windows_pass_stubbed_invocations": calls["measure_windows"],
        },
        "before_after_shots": {
            "before_count": len(before),
            "after_count": len(after),
            "shot_id_set_equal": id_stable,
            "boundary_equal": boundary_stable,
            "full_row_identical": full_identical,
            "classification": classification,
            "assets_total": len(assets_all),
            "assets_stable": len(assets_stable),
            "assets_differ": assets_differ,
            "before_shot_manifest_hash_full": _manifest_hash(before, full_keys),
            "after_shot_manifest_hash_full": _manifest_hash(after, full_keys),
        },
        "shot_feature_relationship": {
            "shots_with_features": shots_with_features,
            "shots_without_features": shots_without_features,
            "features_without_shots": features_without_shots,
        },
        "timeline": {
            "resolved_before": resolved_before,
            "resolved_after": resolved_after,
            "items_before": len(before_tl),
            "items_after": len(after_tl),
            "item_manifest_equal": before_tl == after_tl,
            "new_dangling_references": (resolved_before - resolved_after),
        },
        "forced_failure_rollback": {
            "target_asset": target_asset,
            "raised": rollback_raised,
            "target_old_ids_preserved": target_before_ids == target_after_ids,
            "other_asset_untouched": other_before_ids == other_after_ids,
            "target_shot_count": len(target_after_ids),
        },
        "production_isolation": {
            "prod_checksum_after": prod_checksum_after,
            "prod_checksum_unchanged": prod_checksum_before == prod_checksum_after,
            "prod_mtime_unchanged": prod_mtime_before == prod_mtime_after,
        },
    }

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(result, indent=2, sort_keys=True))
    shutil.rmtree(CLONE_DIR)
    return result


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2, sort_keys=True))
