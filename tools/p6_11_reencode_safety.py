"""P6.11 -- Safe force-reencode support: consistent snapshot, restore, and a strict read-only
postcondition validator for the future controlled real 15A force-reencode (P6.12).

Nothing here touches production. The functions operate on whatever DB path they are given; the
tests drive them against temp DBs, and the `realforce` CLI mode operates on a temp clone.

Snapshot method: the production DB is journal_mode=delete (no WAL, no sidecars), so the correct
consistent snapshot is SQLite's online backup API (`sqlite3.Connection.backup`), which copies a
transactionally consistent image even with a concurrent reader -- not a bare filesystem copy.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
ELENORA = "df2a4a62-e821-40f7-86fc-b6a9259e9ee9"
TIMELINE_15A = "47dcab29-e8ca-4c78-ba3d-2c40457cc153"


# ---- snapshot / restore -------------------------------------------------------------------
def snapshot_db(src: Path, dst: Path) -> dict:
    """Consistent snapshot via the SQLite online backup API, then verify integrity."""
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
    return {
        "path": str(dst),
        "sha256": _sha256(dst),
        "size": dst.stat().st_size,
        "integrity_ok": integrity_ok(dst),
    }


def restore_db(snapshot: Path, target: Path) -> dict:
    """Restore a snapshot over a target DB via the backup API (reverse direction)."""
    snap_conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    tgt_conn = sqlite3.connect(str(target))
    try:
        snap_conn.backup(tgt_conn)
    finally:
        snap_conn.close()
        tgt_conn.close()
    return {"sha256": _sha256(target), "integrity_ok": integrity_ok(target)}


def integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- manifest (read-only) -----------------------------------------------------------------
def build_manifest(db_path: Path, project_id: str = P15) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        def one(sql, *a):
            return conn.execute(sql, a).fetchone()[0]

        shot_rows = conn.execute(
            "SELECT s.id, s.asset_id, s.start_frame, s.duration_frames FROM shots s "
            "JOIN media_assets m ON m.id = s.asset_id WHERE m.project_id = ? "
            "ORDER BY s.id", (project_id,)).fetchall()
        shot_id_set = sorted(r["id"] for r in shot_rows)
        boundaries = sorted((r["id"], r["start_frame"], r["duration_frames"]) for r in shot_rows)
        tl_rows = conn.execute(
            "SELECT id, position, shot_id, asset_id, source_start_frame, source_duration_frames "
            "FROM timeline_items WHERE timeline_id = ? ORDER BY position, id", (TIMELINE_15A,)
        ).fetchall()
        tl_manifest = [tuple(r) for r in tl_rows]
        return {
            "project_id": project_id,
            "project_exists": one("SELECT COUNT(*) FROM projects WHERE id = ?", project_id) == 1,
            "assets": one("SELECT COUNT(*) FROM media_assets WHERE project_id = ?", project_id),
            "shots": len(shot_rows),
            "shot_id_set_hash": _hash(shot_id_set),
            "boundary_hash": _hash(boundaries),
            "features": one(
                "SELECT COUNT(*) FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
                "WHERE m.project_id = ?", project_id),
            "embeddings_populated": one(
                "SELECT COUNT(*) FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
                "WHERE m.project_id = ? AND sf.embedding IS NOT NULL", project_id),
            "tq_zero": one(
                "SELECT COUNT(*) FROM shots s JOIN media_assets m ON m.id=s.asset_id "
                "WHERE m.project_id = ? AND s.technical_quality = 0", project_id),
            "shots_without_features": one(
                "SELECT COUNT(*) FROM shots s JOIN media_assets m ON m.id=s.asset_id "
                "WHERE m.project_id = ? AND s.id NOT IN (SELECT shot_id FROM shot_features)",
                project_id),
            "features_without_shots": one(
                "SELECT COUNT(*) FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
                "WHERE m.project_id = ? AND sf.shot_id NOT IN (SELECT id FROM shots)", project_id),
            "timeline_items": len(tl_manifest),
            "timeline_resolved": one(
                "SELECT COUNT(*) FROM timeline_items ti JOIN shots s ON s.id = ti.shot_id "
                "WHERE ti.timeline_id = ?", TIMELINE_15A),
            "timeline_manifest_hash": _hash(tl_manifest),
            "elenora_embeddings": one(
                "SELECT COUNT(*) FROM shot_features sf JOIN media_assets m ON m.id=sf.asset_id "
                "WHERE m.project_id = ? AND sf.embedding IS NOT NULL", ELENORA),
            "elenora_shots": one(
                "SELECT COUNT(*) FROM shots s JOIN media_assets m ON m.id=s.asset_id "
                "WHERE m.project_id = ?", ELENORA),
            "active_shots_jobs": one(
                "SELECT COUNT(*) FROM jobs WHERE project_id = ? AND kind='shots' "
                "AND status IN ('queued','running','cancel_requested')", project_id),
        }
    finally:
        conn.close()


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---- strict postcondition validator (read-only) -------------------------------------------
def validate_postconditions(db_path: Path, pre: dict, project_id: str = P15) -> dict:
    """Return {'ok': bool, 'failures': [...]} for the mandatory checks. Read-only. Compares the
    post state against the frozen PRE manifest for invariants, and asserts the remediation goals
    absolutely (all shots measured + embedded). No warning-only acceptance."""
    post = build_manifest(db_path, project_id)
    f = []

    def check(cond, name, detail=""):
        if not cond:
            f.append(f"{name}: {detail}")

    check(post["project_exists"], "project_exists")
    check(post["assets"] == pre["assets"], "assets", f"{post['assets']} != {pre['assets']}")
    check(post["shots"] == pre["shots"], "shots", f"{post['shots']} != {pre['shots']}")
    check(post["features"] == post["shots"], "features_eq_shots",
          f"{post['features']} != {post['shots']}")
    check(post["shots_without_features"] == 0, "shots_without_features",
          str(post["shots_without_features"]))
    check(post["features_without_shots"] == 0, "features_without_shots",
          str(post["features_without_shots"]))
    check(post["embeddings_populated"] == post["shots"], "embeddings_populated",
          f"{post['embeddings_populated']} != {post['shots']}")
    check(post["tq_zero"] == 0, "technical_quality_zero", str(post["tq_zero"]))
    check(post["shot_id_set_hash"] == pre["shot_id_set_hash"], "shot_id_set_unchanged")
    check(post["boundary_hash"] == pre["boundary_hash"], "boundaries_unchanged")
    check(post["timeline_items"] == pre["timeline_items"], "timeline_items",
          f"{post['timeline_items']} != {pre['timeline_items']}")
    check(post["timeline_resolved"] == post["timeline_items"], "timeline_resolved",
          f"{post['timeline_resolved']} != {post['timeline_items']}")
    check(post["timeline_manifest_hash"] == pre["timeline_manifest_hash"], "timeline_unchanged")
    # Cross-project protection: Elenora untouched.
    check(post["elenora_embeddings"] == pre["elenora_embeddings"], "elenora_embeddings_unchanged",
          f"{post['elenora_embeddings']} != {pre['elenora_embeddings']}")
    check(post["elenora_shots"] == pre["elenora_shots"], "elenora_shots_unchanged")
    check(post["active_shots_jobs"] == 0, "no_active_or_orphan_job", str(post["active_shots_jobs"]))
    return {"ok": not f, "failures": f, "post": post}


# ---- real-media force-reencode proof (temp clone) -----------------------------------------
def run_realforce() -> dict:
    """Prove the supported trigger recomputes an asset whose features ALREADY EXIST, without any
    pre-delete, on real media. Uses a spy DB to confirm the only shot_features mutation is the
    atomic replace_rows inside _store_features (no standalone DELETE before computation)."""
    import shutil

    import numpy as np
    from sevenfilm.db import Database
    from sevenfilm.services import analysis as analysis_module
    from sevenfilm.services.media import project_assets
    from sevenfilm.services.vision import VisionClassifier

    real = ROOT / "data" / "sevenfilm.sqlite3"
    clone_dir = Path("/tmp/p611_tempdb")
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    clone_dir.mkdir(parents=True)
    clone = clone_dir / "clone.sqlite3"
    prod_before = _sha256(real)
    src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
    dst = sqlite3.connect(str(clone))
    src.backup(dst); src.close(); dst.close()

    C7309 = "a778e858-df7a-5aaa-802b-6637991a58ee"

    class SpyDatabase(Database):
        def __init__(self, path):
            super().__init__(path)
            self.feature_deletes_before_store = 0
            self.store_done = False

        def execute(self, sql, params=()):
            if "DELETE FROM shot_features" in sql and not self.store_done:
                self.feature_deletes_before_store += 1
            return super().execute(sql, params)

        def replace_rows(self, table, where_column, where_value, rows):
            super().replace_rows(table, where_column, where_value, rows)
            if table == "shot_features":
                self.store_done = True

    db = SpyDatabase(clone)
    asset = {a.id: a for a in project_assets(db, P15)}[C7309]
    before = db.fetch_all(
        "SELECT shot_id, embedding, metrics_json FROM shot_features WHERE asset_id=? "
        "ORDER BY start_frame", (C7309,))
    features_present_before = len(before)
    emb_before = sum(1 for r in before if r["embedding"] is not None)
    tq_before_zero = sum(1 for r in before if json.loads(r["metrics_json"])["technical_quality"] == 0)
    before_shot_ids = [r["shot_id"] for r in before]

    # The supported trigger's engine call: encode an asset that ALREADY has features. No delete.
    analysis_module._encode_asset(db, VisionClassifier(), asset)

    after = db.fetch_all(
        "SELECT shot_id, embedding, metrics_json FROM shot_features WHERE asset_id=? "
        "ORDER BY start_frame", (C7309,))
    emb_after = sum(1 for r in after if r["embedding"] is not None)
    dims = sorted({int(np.frombuffer(r["embedding"], dtype=np.float32).shape[0])
                   for r in after if r["embedding"] is not None})
    tq_after = [json.loads(r["metrics_json"])["technical_quality"] for r in after]
    after_shot_ids = [r["shot_id"] for r in after]

    result = {
        "asset": "C7309",
        "features_present_before": features_present_before,
        "embeddings_before": emb_before,
        "tq_zero_before": tq_before_zero,
        "feature_deletes_before_store": db.feature_deletes_before_store,
        "features_after": len(after),
        "embeddings_after": emb_after,
        "embedding_dims": dims,
        "tq_zero_after": sum(1 for q in tq_after if q == 0),
        "tq_after_min": round(min(tq_after), 3),
        "shot_ids_stable": before_shot_ids == after_shot_ids,
        "prod_checksum_unchanged": _sha256(real) == prod_before,
    }
    shutil.rmtree(clone_dir, ignore_errors=True)
    (ROOT / "tools" / "fixtures" / "p6_11_realforce.json").write_text(
        json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    print(json.dumps(run_realforce(), indent=2, sort_keys=True))
