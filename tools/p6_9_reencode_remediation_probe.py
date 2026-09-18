"""P6.9 -- Re-encode remediation path: real-15A temp-clone safety & effectiveness proof.

Exercises the REAL feature-recompute path (`_encode_asset` -> frame decode of the actual T7
originals -> measure_frames -> VisionClassifier CLIP encode -> `_store_features`, then
`_label_asset`) against an isolated temp clone of the production DB, for a PRE-REGISTERED sample
of assets. It answers, on real media: does technical_quality restore, do embeddings generate, do
shot ids/boundaries stay stable, and does the 129-item timeline stay safe.

Trigger: the supported code re-encodes an asset only when it has no `shot_features`
(`analyze_shots`: `if not _asset_features(...): _encode_asset(...)`). This probe reproduces that
condition on the CLONE by deleting the sample assets' `shot_features` while LEAVING their `shots`
rows in place -- so `_encode_asset` re-derives ranges from the existing shot boundaries (not a
fresh `_scene_ranges` scan), which is what keeps shot ids stable. (There is no supported API/job
option that deletes features; a real remediation would need that deletion as an explicit,
out-of-band step -- documented in the report.)

Production safety: the real DB is only ever a shutil.copy2 SOURCE; a Database is only built on the
clone; a guard rejects the production path; the clone is deleted at the end.

Usage:
  .venv/bin/python tools/p6_9_reencode_remediation_probe.py          # sample (default)
  .venv/bin/python tools/p6_9_reencode_remediation_probe.py --full   # full 362-asset clone run
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

REAL_DB = ROOT / "data" / "sevenfilm.sqlite3"
CLONE_DIR = Path("/tmp/p69_tempdb")
CLONE_PATH = CLONE_DIR / "clone.sqlite3"
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
TIMELINE_ID = "47dcab29-e8ca-4c78-ba3d-2c40457cc153"
FIXTURE_SAMPLE = ROOT / "tools" / "fixtures" / "p6_9_reencode_sample.json"
FIXTURE_FULL = ROOT / "tools" / "fixtures" / "p6_9_reencode_full.json"

# Pre-registered sample (chosen BEFORE any remediation result), per P6.9 section 7.
SAMPLE = {
    "a778e858-df7a-5aaa-802b-6637991a58ee": "C7309.MP4 (cake source; 16 shots; all tq-zero)",
    "a5ba2e26-8e09-50bc-bc9d-f1b382ba95af": "DJI_0528.MOV (drone; 280 shots; all tq-zero)",
    "dc5f4028-239f-5fad-9530-7f64af7a0760": "DJI_0529.MOV (drone; 56 shots; all tq-zero)",
    "840562e4-3734-5bfe-a657-8073aba43e58": "C7138.MP4 (regular cam; 19 shots; tq NON-zero; timeline-referenced)",
    "db42a2f0-fe41-5bec-a951-3db70a9d2e9a": "C7152.MP4 (regular cam; 15 shots; tq NON-zero; timeline-referenced)",
    "da281bdf-5158-59af-9e6c-bbf751de215d": "C7451.MP4 (venue; 73 shots; all tq-zero; multi-shot)",
}
# NOTE: "kiss source" (section 7B) could not be resolved to a filename in the DB without a
# moment->asset lookup (out of scope); two timeline-referenced regular assets (C7138, C7152)
# cover the timeline-referenced requirement (section 13) in its place.


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shot_rows(db, asset_id):
    return db.fetch_all(
        "SELECT id, start_frame, duration_frames, frame_rate, category, technical_quality, "
        "analysis_version FROM shots WHERE asset_id = ? ORDER BY start_frame, id", (asset_id,))


def _feature_rows(db, asset_id):
    return db.fetch_all(
        "SELECT shot_id, embedding, metrics_json FROM shot_features "
        "WHERE asset_id = ? ORDER BY start_frame, shot_id", (asset_id,))


def _timeline_resolution(db):
    rows = db.fetch_all(
        """SELECT ti.shot_id, s.id AS resolved FROM timeline_items ti
           LEFT JOIN shots s ON s.id = ti.shot_id WHERE ti.timeline_id = ?""", (TIMELINE_ID,))
    return {
        "items": len(rows),
        "resolved": sum(1 for r in rows if r["resolved"] is not None),
    }


def _embedding_stats(feature_rows):
    dims, norms, populated = set(), [], 0
    for f in feature_rows:
        if f["embedding"] is not None:
            v = np.frombuffer(f["embedding"], dtype=np.float32)
            dims.add(int(v.shape[0]))
            norms.append(float(np.linalg.norm(v)))
            populated += 1
    return {
        "populated": populated,
        "total": len(feature_rows),
        "dims": sorted(dims),
        "norm_min": round(min(norms), 4) if norms else None,
        "norm_max": round(max(norms), 4) if norms else None,
    }


def _remediate_asset(db, analysis_module, classifier, asset, counters):
    """Reproduce the supported re-encode condition for one asset on the clone, then relabel."""
    db.execute("DELETE FROM shot_features WHERE asset_id = ?", (asset.id,))
    real_scene = analysis_module._scene_ranges

    def spy_scene(*a, **k):
        counters["scene_ranges"] += 1
        return real_scene(*a, **k)

    analysis_module._scene_ranges = spy_scene
    try:
        analysis_module._encode_asset(db, classifier, asset)
    finally:
        analysis_module._scene_ranges = real_scene


def run(full: bool) -> dict:
    assert REAL_DB.exists()
    prod_checksum_before = _sha256_file(REAL_DB)
    prod_mtime_before = REAL_DB.stat().st_mtime

    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    CLONE_DIR.mkdir(parents=True)
    shutil.copy2(REAL_DB, CLONE_PATH)
    clone_checksum_initial = _sha256_file(CLONE_PATH)

    from sevenfilm.db import Database
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.vision import VisionClassifier

    guard = str(REAL_DB.resolve())
    db = Database(CLONE_PATH)
    assert str(Path(db.path).resolve()) != guard, "REFUSED: probe touched production DB path"

    assets = {a.id: a for a in project_assets(db, P15)}
    target_ids = list(assets) if full else list(SAMPLE)

    counters = {"scene_ranges": 0}
    classifier = VisionClassifier()

    before = {aid: _shot_rows(db, aid) for aid in target_ids}
    tl_before = _timeline_resolution(db)

    per_asset = {}
    failures = []
    t0 = time.time()
    for i, aid in enumerate(target_ids, start=1):
        try:
            _remediate_asset(db, analysis_module, classifier, assets[aid], counters)
            analysis_module._label_asset(
                db, classifier, assets[aid],
                analysis_module._project_prior(db, classifier, P15) if not full else None,
            )
        except Exception as error:  # noqa: BLE001 - record, never mask, a per-asset failure
            failures.append({"asset_id": aid, "error": f"{type(error).__name__}: {error}"[:200]})
            continue
        after_shots = _shot_rows(db, aid)
        after_feats = _feature_rows(db, aid)
        before_ids = [r["id"] for r in before[aid]]
        after_ids = [r["id"] for r in after_shots]
        before_tq = [r["technical_quality"] for r in before[aid]]
        after_tq = [r["technical_quality"] for r in after_shots]
        per_asset[aid] = {
            "label": SAMPLE.get(aid, "full"),
            "before_shot_count": len(before_ids),
            "after_shot_count": len(after_ids),
            "shot_ids_stable": before_ids == after_ids,
            "before_tq_zero": sum(1 for q in before_tq if q == 0),
            "after_tq_zero": sum(1 for q in after_tq if q == 0),
            "after_tq_min": round(min(after_tq), 3) if after_tq else None,
            "after_tq_max": round(max(after_tq), 3) if after_tq else None,
            "embeddings": _embedding_stats(after_feats),
            "analysis_versions": sorted({r["analysis_version"] for r in after_shots}),
        }
        if full and i % 25 == 0:
            print(f"  ... {i}/{len(target_ids)} assets, {time.time()-t0:.0f}s", flush=True)
    runtime = time.time() - t0

    tl_after = _timeline_resolution(db)

    # Aggregate id stability and quality/embedding over the processed set.
    processed = list(per_asset)
    assets_stable = sum(1 for a in processed if per_asset[a]["shot_ids_stable"])
    total_after_zero = sum(per_asset[a]["after_tq_zero"] for a in processed)
    total_before_zero = sum(per_asset[a]["before_tq_zero"] for a in processed)
    total_shots = sum(per_asset[a]["after_shot_count"] for a in processed)
    total_emb = sum(per_asset[a]["embeddings"]["populated"] for a in processed)
    all_dims = sorted({d for a in processed for d in per_asset[a]["embeddings"]["dims"]})

    # Shot<->feature integrity over processed assets.
    shots_wo_features = features_wo_shots = 0
    for aid in processed:
        sids = {r["id"] for r in _shot_rows(db, aid)}
        fids = {r["shot_id"] for r in _feature_rows(db, aid)}
        shots_wo_features += len(sids - fids)
        features_wo_shots += len(fids - sids)

    prod_checksum_after = _sha256_file(REAL_DB)
    result = {
        "mode": "full" if full else "sample",
        "clone": {
            "initial_checksum": clone_checksum_initial,
            "matches_production_initially": clone_checksum_initial == prod_checksum_before,
        },
        "counts": {
            "assets_processed": len(processed),
            "assets_targeted": len(target_ids),
            "failures": failures,
            "runtime_seconds": round(runtime, 1),
            "median_seconds_per_asset": round(runtime / max(1, len(processed)), 2),
        },
        "segmentation": {"scene_ranges_invocations": counters["scene_ranges"]},
        "id_stability": {
            "assets_stable": assets_stable,
            "assets_processed": len(processed),
            "all_stable": assets_stable == len(processed),
            "unstable_assets": [a for a in processed if not per_asset[a]["shot_ids_stable"]],
        },
        "quality": {
            "before_tq_zero": total_before_zero,
            "after_tq_zero": total_after_zero,
            "shots_total": total_shots,
        },
        "embeddings": {
            "populated": total_emb,
            "shots_total": total_shots,
            "dims": all_dims,
        },
        "shot_feature_integrity": {
            "shots_without_features": shots_wo_features,
            "features_without_shots": features_wo_shots,
        },
        "timeline": {
            "items_before": tl_before["items"], "items_after": tl_after["items"],
            "resolved_before": tl_before["resolved"], "resolved_after": tl_after["resolved"],
            "new_dangling": tl_before["resolved"] - tl_after["resolved"],
        },
        "per_asset": per_asset,
        "production_isolation": {
            "prod_checksum_unchanged": prod_checksum_before == prod_checksum_after,
            "prod_mtime_unchanged": prod_mtime_before == REAL_DB.stat().st_mtime,
        },
    }

    fixture = FIXTURE_FULL if full else FIXTURE_SAMPLE
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(result, indent=2, sort_keys=True))
    shutil.rmtree(CLONE_DIR)
    return result


if __name__ == "__main__":
    out = run(full="--full" in sys.argv)
    # Print a compact summary, not the whole per-asset blob.
    summary = {k: v for k, v in out.items() if k != "per_asset"}
    print(json.dumps(summary, indent=2, sort_keys=True))
