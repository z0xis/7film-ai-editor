"""P6.12 -- Controlled real 15A force-reencode with verified snapshot / rollback / strict
postconditions. This is the FIRST authorized mutation of the real production feature state.

Protocol (aborts before any write if a gate fails):
  preflight -> verified snapshot (SQLite backup API) -> immutable PRE manifest -> restorability
  check -> ONE real force_reencode=true job via the supported POST /shots route -> strict
  read-only validation -> ACCEPT (keep snapshot) or verified ROLLBACK (restore snapshot).

Only the supported P6.11 path is used: no manual feature deletion, no ad-hoc SQL, no bypass.
The snapshot lives under data/backups/ (gitignored) and is NEVER committed or deleted here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# No SEVENFILM_DATA_ROOT override -> config resolves the real production data dir.
os.environ.pop("SEVENFILM_DATA_ROOT", None)

PROD_DB = ROOT / "data" / "sevenfilm.sqlite3"
BACKUP_DIR = ROOT / "data" / "backups"
# The physical file checksum is RECORDED but is NOT a PRE gate: an SQLite backup/restore
# re-paginates the file, so a semantically-identical restored PRE baseline has a different
# checksum. The authoritative PRE gate is the semantic manifest -- counts plus these content
# hashes (shot-id set, shot boundaries, timeline items), which are stable across re-pagination.
EXPECTED_HASHES = {
    "shot_id_set_hash": "c00b7fa1259b8d6efdef7f3991e687ffdcff5be80fcf12008502482d99d7d6eb",
    "boundary_hash": "392ab3356f4e04621f4540a40f03bb81c2ceba29b7a35fb1a091cdc4b22b5f6c",
    "timeline_manifest_hash": "78d13b0bd642311eb44ce9d9b62bb76550e680a6066430c0aa64a35dd734f36a",
}
P15 = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
RESULT = ROOT / "tools" / "fixtures" / "p6_12_run_result.json"

_spec = importlib.util.spec_from_file_location("p6_11_safety", ROOT / "tools/p6_11_reencode_safety.py")
safety = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safety)

EXPECTED_BASELINE = {
    "assets": 362, "shots": 2638, "features": 2638, "embeddings_populated": 0,
    "tq_zero": 2327, "timeline_items": 129, "timeline_resolved": 129, "elenora_embeddings": 1405,
    "shots_without_features": 0, "features_without_shots": 0,
}


def _log(msg):
    print(f"[p6.12 {datetime.now(UTC).strftime('%H:%M:%S')}] {msg}", flush=True)


def abort(reason: str, extra: dict | None = None) -> dict:
    _log(f"ABORT before write: {reason}")
    out = {"phase": "aborted_before_write", "reason": reason, **(extra or {})}
    RESULT.write_text(json.dumps(out, indent=2, sort_keys=True))
    return out


def main() -> dict:
    # --- resolve production path via config, positively ---
    from sevenfilm.config import database_path
    resolved = Path(database_path()).resolve()
    if resolved != PROD_DB.resolve():
        return abort(f"config DB path {resolved} != expected {PROD_DB.resolve()}")
    if not PROD_DB.exists():
        return abort("production DB missing")

    pre = safety.build_manifest(PROD_DB, P15)
    checksum_pre = safety._sha256(PROD_DB)
    mtime_pre = PROD_DB.stat().st_mtime

    # --- HARD SEMANTIC SAFETY GATE (abort before write on any mismatch) ---
    # Physical checksum is recorded, never gated (see EXPECTED_HASHES note).
    if not safety.integrity_ok(PROD_DB):
        return abort("integrity_check != ok")
    for k, v in EXPECTED_BASELINE.items():
        if pre.get(k) != v:
            return abort(f"baseline mismatch {k}={pre.get(k)} expected {v}", {"pre": pre})
    for k, v in EXPECTED_HASHES.items():
        if pre.get(k) != v:
            return abort(f"PRE manifest hash mismatch {k}", {"got": pre.get(k), "expected": v})
    if pre["active_shots_jobs"] != 0:
        return abort("an active shots job exists", {"active": pre["active_shots_jobs"]})
    _log(f"hard semantic safety gate PASS (checksum {checksum_pre[:12]} recorded, not gated)")

    # --- media preflight (read-only) ---
    conn = sqlite3.connect(f"file:{PROD_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    assets = conn.execute("SELECT path FROM media_assets WHERE project_id=?", (P15,)).fetchall()
    conn.close()
    reachable = sum(1 for a in assets if os.path.exists(a["path"]))
    if reachable != 362:
        return abort(f"media reachable {reachable}/362")
    _log(f"media reachable {reachable}/362")

    # --- verified snapshot (SQLite online backup API) ---
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    snap_path = BACKUP_DIR / f"sevenfilm-pre-p6_12-{ts}.sqlite3"
    if snap_path.exists():
        return abort("snapshot path already exists (never overwrite)")
    snap = safety.snapshot_db(PROD_DB, snap_path)
    if not snap["integrity_ok"]:
        return abort("snapshot integrity_check failed", {"snapshot": snap})
    _log(f"snapshot ok: {snap_path} sha={snap['sha256'][:12]}")

    # --- freeze PRE manifest beside snapshot ---
    manifest_path = BACKUP_DIR / f"pre-manifest-p6_12-{ts}.json"
    manifest_path.write_text(json.dumps(
        {"pre": pre, "checksum": checksum_pre, "mtime": mtime_pre, "snapshot": snap,
         "snapshot_path": str(snap_path)}, indent=2, sort_keys=True))

    # --- restorability check (read-only, on the snapshot itself) ---
    snap_manifest = safety.build_manifest(snap_path, P15)
    if not (safety.integrity_ok(snap_path) and snap_manifest["assets"] == 362
            and snap_manifest["shots"] == 2638 and snap_manifest["features"] == 2638
            and snap_manifest["timeline_items"] == 129 and snap_manifest["elenora_shots"] == pre["elenora_shots"]):
        return abort("snapshot restorability check failed", {"snap_manifest": snap_manifest})
    _log("snapshot restorability check PASS")

    # --- pre-write checkpoint ---
    _log(f"CHECKPOINT head=db395f2 db={PROD_DB} checksum={checksum_pre[:12]} "
         f"snapshot={snap_path.name} snap_sha={snap['sha256'][:12]} assets=362 shots=2638 "
         f"features=2638 embeddings=0 tq_zero=2327 timeline=129 elenora=1405 active_jobs=0 "
         f"media=362/362 clip=ready snapshot_integrity=ok")

    # --- start EXACTLY ONE real force-reencode via the supported route ---
    from fastapi.testclient import TestClient
    from sevenfilm import api
    if Path(api.DATABASE.path).resolve() != PROD_DB.resolve():
        return abort(f"api.DATABASE points at {api.DATABASE.path}, not production")

    _log("starting real force_reencode=true job via POST /shots ...")
    started = time.time()
    with TestClient(api.app) as client:
        resp = client.post(f"/api/projects/{P15}/shots", json={"force_reencode": True})
        _log(f"POST /shots -> {resp.status_code} {resp.json()}")
        if resp.status_code != 202:
            return abort(f"force job not accepted: {resp.status_code} {resp.text}")
        job_id = resp.json()["job_id"]
        # TestClient runs the BackgroundTask (=_run_job) synchronously before post() returns.
    duration = time.time() - started
    job = api.DATABASE.fetch_one("SELECT status, error FROM jobs WHERE id=?", (job_id,))
    _log(f"job {job_id} status={job['status']} duration={duration:.0f}s error={job['error']}")

    checksum_post = safety._sha256(PROD_DB)
    post = safety.build_manifest(PROD_DB, P15)

    # --- strict validation (job success AND validator PASS) ---
    validation = safety.validate_postconditions(PROD_DB, pre, P15)
    accepted = job["status"] == "completed" and validation["ok"]

    result = {
        "phase": "run_complete",
        "job_id": job_id, "job_status": job["status"], "job_error": job["error"],
        "duration_seconds": round(duration, 1),
        "snapshot_path": str(snap_path), "snapshot_sha256": snap["sha256"],
        "pre_manifest_path": str(manifest_path),
        "checksum_pre": checksum_pre, "checksum_post": checksum_post,
        "mtime_pre": mtime_pre, "mtime_post": PROD_DB.stat().st_mtime,
        "pre": pre, "post": post,
        "validation": validation,
        "accepted": accepted,
        "resolve_running": bool(os.popen("pgrep -x Resolve").read().strip()),
    }

    if accepted:
        _log("ACCEPTED: job completed AND validator PASS. Snapshot retained.")
        result["decision"] = "accepted"
    else:
        _log(f"NOT ACCEPTED (status={job['status']} validator_ok={validation['ok']}). "
             f"Rolling back from snapshot ...")
        result["decision"] = "rollback"
        # Ensure no writer: TestClient context has exited; _run_job is synchronous and done.
        restore = safety.restore_db(snap_path, PROD_DB)
        post_restore = safety.build_manifest(PROD_DB, P15)
        result["rollback"] = {
            "restore": restore,
            "checksum_after_restore": safety._sha256(PROD_DB),
            "matches_pre_checksum": safety._sha256(PROD_DB) == checksum_pre,
            "post_restore_manifest": post_restore,
        }
        _log(f"rollback restore integrity={restore['integrity_ok']} "
             f"matches_pre={result['rollback']['matches_pre_checksum']}")

    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    out = main()
    print(json.dumps({k: v for k, v in out.items() if k not in ("pre", "post")}, indent=2,
                     sort_keys=True, default=str))
