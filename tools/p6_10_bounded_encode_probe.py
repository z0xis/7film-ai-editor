"""P6.10 -- Bounded-memory large-asset encode: equivalence, DJI_0528 regression, DJI_0530 closure.

Proves that the chunked `_encode_asset` (bounded raw-frame retention) is semantically equivalent to
the pre-fix materialise-everything path, then that DJI_0528 (280-shot 4K) still restores, and that
DJI_0530 (501-shot 4K) -- which was signal-killed under the old path -- now completes within bounded
memory. All work is on an isolated temp clone of the real production DB; the real DB is only a
copy source; clones are deleted at the end.

Modes:
  equiv   -- legacy-vs-chunked feature equivalence on small assets + CLIP batch-vs-chunk (default)
  dji528  -- DJI_0528 regression
  dji530  -- DJI_0530 decisive memory + output test
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

REAL_DB = ROOT / "data" / "sevenfilm.sqlite3"
CLONE_DIR = Path("/tmp/p610_tempdb")
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
FIX = ROOT / "tools" / "fixtures"
ASSETS = {
    "C7309": "a778e858-df7a-5aaa-802b-6637991a58ee",
    "C7152": "db42a2f0-fe41-5bec-a951-3db70a9d2e9a",
    "DJI_0528": "a5ba2e26-8e09-50bc-bc9d-f1b382ba95af",
    "DJI_0530": "9171be37-e07f-5ed8-999a-e9e9ebf821c5",
}


def _clone() -> Path:
    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)
    CLONE_DIR.mkdir(parents=True)
    dst = CLONE_DIR / "clone.sqlite3"
    shutil.copy2(REAL_DB, dst)
    return dst


def _feature_snapshot(db, asset_id):
    rows = db.fetch_all(
        "SELECT shot_id, embedding, metrics_json FROM shot_features WHERE asset_id = ? "
        "ORDER BY start_frame, shot_id", (asset_id,))
    out = {}
    for r in rows:
        emb = None if r["embedding"] is None else np.frombuffer(r["embedding"], dtype=np.float32)
        out[r["shot_id"]] = (emb, json.loads(r["metrics_json"]))
    return out


def _legacy_materialised_encode(database, classifier, asset, analysis_module):
    """The pre-fix path, reconstructed verbatim, for equivalence comparison on the clone."""
    from sevenfilm.services.vision import measure_frames
    rows = database.fetch_all(
        "SELECT start_frame, duration_frames, frame_rate FROM shots WHERE asset_id = ? "
        "ORDER BY start_frame", (asset.id,))
    from sevenfilm.timebase import FrameRate, TimeRange
    ranges = [
        seg for row in rows for seg in analysis_module._split_long_range(
            TimeRange(int(row["start_frame"]), int(row["duration_frames"]),
                      FrameRate.parse(str(row["frame_rate"]))))
    ]
    frame_groups = list(analysis_module._shot_frame_groups(asset, ranges))
    metrics = [measure_frames(f) for f in frame_groups]
    middle = [f[len(f) // 2] if f else None for f in frame_groups]
    positions = [i for i, f in enumerate(middle) if f is not None]
    encoded = classifier.encode([middle[i] for i in positions])
    embeddings = {} if encoded is None else dict(zip(positions, encoded))
    analysis_module._store_features(database, asset, ranges, metrics, embeddings)


def run_equiv() -> dict:
    from sevenfilm.db import Database
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.vision import VisionClassifier

    # (a) CLIP batch-vs-chunk equivalence on deterministic frames.
    c = VisionClassifier()
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (240, 320, 3), dtype=np.uint8) for _ in range(70)]
    full = c.encode(frames)
    chunks = np.concatenate([c.encode(frames[i:i + 32]) for i in range(0, len(frames), 32)])
    cos = [float(np.dot(full[i], chunks[i])) for i in range(len(frames))]
    max_delta = float(np.max(np.abs(full - chunks)))

    # (b) feature-row equivalence: legacy vs chunked on two small assets (fresh clones).
    per_asset = {}
    for name in ("C7309", "C7152"):
        aid = ASSETS[name]
        db_l = Database(_clone_named("legacy"))
        asset = {a.id: a for a in project_assets(db_l, P15)}[aid]
        db_l.execute("DELETE FROM shot_features WHERE asset_id = ?", (aid,))
        _legacy_materialised_encode(db_l, VisionClassifier(), asset, analysis_module)
        legacy = _feature_snapshot(db_l, aid)

        db_c = Database(_clone_named("chunked"))
        asset_c = {a.id: a for a in project_assets(db_c, P15)}[aid]
        db_c.execute("DELETE FROM shot_features WHERE asset_id = ?", (aid,))
        analysis_module._encode_asset(db_c, VisionClassifier(), asset_c)
        chunked = _feature_snapshot(db_c, aid)

        same_ids = set(legacy) == set(chunked)
        tq_exact = all(legacy[s][1]["technical_quality"] == chunked[s][1]["technical_quality"]
                       for s in legacy)
        metrics_exact = all(legacy[s][1] == chunked[s][1] for s in legacy)
        emb_cos = []
        for s in legacy:
            a, b = legacy[s][0], chunked[s][0]
            if a is None or b is None:
                emb_cos.append(1.0 if (a is None and b is None) else 0.0)
            else:
                emb_cos.append(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))))
        per_asset[name] = {
            "shots": len(legacy),
            "same_shot_ids": same_ids,
            "metrics_exact": metrics_exact,
            "tq_exact": tq_exact,
            "embedding_min_cosine": round(min(emb_cos), 6) if emb_cos else None,
        }
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
    result = {
        "clip_batch_vs_chunk": {
            "min_cosine": round(min(cos), 6),
            "max_abs_delta": round(max_delta, 6),
            "dim": int(full.shape[1]),
        },
        "feature_equivalence": per_asset,
    }
    (FIX / "p6_10_equivalence.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def _clone_named(tag: str) -> Path:
    CLONE_DIR.mkdir(parents=True, exist_ok=True)
    dst = CLONE_DIR / f"clone_{tag}.sqlite3"
    shutil.copy2(REAL_DB, dst)
    return dst


def run_single(name: str) -> dict:
    import resource
    import time

    from sevenfilm.db import Database
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.vision import VisionClassifier
    aid = ASSETS[name]
    db = Database(_clone())
    asset = {a.id: a for a in project_assets(db, P15)}[aid]
    before = db.fetch_all(
        "SELECT id, start_frame, technical_quality FROM shots WHERE asset_id = ? ORDER BY start_frame",
        (aid,))
    db.execute("DELETE FROM shot_features WHERE asset_id = ?", (aid,))
    t = time.time()
    analysis_module._encode_asset(db, VisionClassifier(), asset)
    # relabel so shots.technical_quality reflects the fresh measurement
    analysis_module._label_asset(db, VisionClassifier(), asset, None)
    runtime = time.time() - t
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # bytes on macOS
    after_shots = db.fetch_all(
        "SELECT id, start_frame, technical_quality FROM shots WHERE asset_id = ? ORDER BY start_frame",
        (aid,))
    feats = _feature_snapshot(db, aid)
    before_ids = [r["id"] for r in before]
    after_ids = [r["id"] for r in after_shots]
    dims = sorted({int(e.shape[0]) for e, _ in feats.values() if e is not None})
    norms = [float(np.linalg.norm(e)) for e, _ in feats.values() if e is not None]
    result = {
        "asset": name,
        "shots_before": len(before_ids),
        "shots_after": len(after_ids),
        "shot_ids_stable": before_ids == after_ids,
        "tq_zero_before": sum(1 for r in before if r["technical_quality"] == 0),
        "tq_zero_after": sum(1 for r in after_shots if r["technical_quality"] == 0),
        "tq_after_min": round(min(r["technical_quality"] for r in after_shots), 3),
        "tq_after_max": round(max(r["technical_quality"] for r in after_shots), 3),
        "embeddings_populated": sum(1 for e, _ in feats.values() if e is not None),
        "embedding_dims": dims,
        "embedding_norm_min": round(min(norms), 4) if norms else None,
        "embedding_norm_max": round(max(norms), 4) if norms else None,
        "runtime_seconds": round(runtime, 1),
        "peak_rss_bytes": peak_rss,
        "peak_rss_gb": round(peak_rss / (1024**3), 2),
        "completed": True,
    }
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
    (FIX / f"p6_10_{name.lower()}.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def run_full() -> dict:
    """Full 362-asset remediation on a clone with the fixed chunked path -- the P6.9 GATE F
    closure, and the residual-shot reconciliation (section 1/20). Enumerates every shot that
    remains tq-zero or embedding-null after remediation, with its asset."""
    import resource
    import time

    from sevenfilm.db import Database
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.vision import VisionClassifier
    TIMELINE_ID = "47dcab29-e8ca-4c78-ba3d-2c40457cc153"

    db = Database(_clone())
    assets = {a.id: a for a in project_assets(db, P15)}
    ids = list(assets)

    def _shots(aid):
        return [r["id"] for r in db.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame, id", (aid,))]

    def _tl():
        rows = db.fetch_all(
            "SELECT ti.shot_id, s.id r FROM timeline_items ti LEFT JOIN shots s ON s.id=ti.shot_id "
            "WHERE ti.timeline_id = ?", (TIMELINE_ID,))
        return len(rows), sum(1 for x in rows if x["r"] is not None)

    before_ids = {aid: _shots(aid) for aid in ids}
    tl_items_b, tl_res_b = _tl()
    classifier = VisionClassifier()
    failures = []
    t0 = time.time()
    for i, aid in enumerate(ids, 1):
        try:
            db.execute("DELETE FROM shot_features WHERE asset_id = ?", (aid,))
            analysis_module._encode_asset(db, classifier, assets[aid])
            analysis_module._label_asset(db, classifier, assets[aid], None)
        except Exception as e:  # noqa: BLE001 - record, never mask
            failures.append({"asset_id": aid, "error": f"{type(e).__name__}: {e}"[:200]})
        if i % 50 == 0:
            print(f"  ... {i}/{len(ids)} assets, {time.time()-t0:.0f}s", flush=True)
    runtime = time.time() - t0
    peak_gb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**3), 2)

    after_ids = {aid: _shots(aid) for aid in ids}
    assets_stable = sum(1 for aid in ids if before_ids[aid] == after_ids[aid])
    total_shots_b = sum(len(v) for v in before_ids.values())
    total_shots_a = sum(len(v) for v in after_ids.values())
    tl_items_a, tl_res_a = _tl()

    tq_zero = db.fetch_all(
        "SELECT s.id, m.file_name FROM shots s JOIN media_assets m ON m.id=s.asset_id "
        "WHERE m.project_id=? AND s.technical_quality=0 ORDER BY m.file_name, s.id", (P15,))
    emb_null = db.fetch_all(
        "SELECT sf.shot_id, m.file_name FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
        "WHERE m.project_id=? AND sf.embedding IS NULL ORDER BY m.file_name, sf.shot_id", (P15,))
    feat_total = db.fetch_one(
        "SELECT COUNT(*) c FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
        "WHERE m.project_id=?", (P15,))["c"]
    emb_pop = db.fetch_one(
        "SELECT COUNT(*) c FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
        "WHERE m.project_id=? AND sf.embedding IS NOT NULL", (P15,))["c"]
    shots_wo_feat = db.fetch_one(
        "SELECT COUNT(*) c FROM shots s JOIN media_assets m ON m.id=s.asset_id WHERE m.project_id=? "
        "AND s.id NOT IN (SELECT shot_id FROM shot_features)", (P15,))["c"]

    result = {
        "assets_completed": len(ids) - len(failures),
        "assets_total": len(ids),
        "failures": failures,
        "runtime_seconds": round(runtime, 1),
        "peak_rss_gb": peak_gb,
        "shots_before": total_shots_b, "shots_after": total_shots_a,
        "assets_id_stable": assets_stable, "assets_id_stable_total": len(ids),
        "tq_zero_after": len(tq_zero),
        "tq_zero_shots": [f"{r['file_name']}:{r['id']}" for r in tq_zero],
        "embeddings_populated": emb_pop, "embeddings_of": feat_total,
        "embedding_null_after": len(emb_null),
        "embedding_null_shots": [f"{r['file_name']}:{r['shot_id']}" for r in emb_null],
        "shots_without_features": shots_wo_feat,
        "timeline_items_before": tl_items_b, "timeline_items_after": tl_items_a,
        "timeline_resolved_before": tl_res_b, "timeline_resolved_after": tl_res_a,
    }
    (FIX / "p6_10_full.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
    return result


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "equiv"
    if mode == "equiv":
        out = run_equiv()
    elif mode == "dji528":
        out = run_single("DJI_0528")
    elif mode == "dji530":
        out = run_single("DJI_0530")
    elif mode == "full":
        out = run_full()
    else:
        raise SystemExit(f"unknown mode {mode}")
    summary = {k: v for k, v in out.items()
               if k not in ("tq_zero_shots", "embedding_null_shots")}
    print(json.dumps(summary, indent=2, sort_keys=True))
