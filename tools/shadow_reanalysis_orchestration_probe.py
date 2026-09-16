"""P6.6: orchestration safety probe against an ISOLATED TEMP CLONE of the DB (never the real
production database -- the clone lives under /tmp and is copied read-only from the real DB,
then only the clone is ever written to). Uses the real `Database` class (db.py) unmodified.

Verifies, empirically rather than by reading code alone:
1. Whether PRAGMA foreign_keys is actually enforced on a normal (non-migrate) connection.
2. Whether `_label_asset()`'s DELETE-then-insert-loop pattern for the `shots` table creates a
   real, observable window where a `timeline_items` row's `shot_id` points at a row that does
   not exist -- reproducing exactly what a crash between the DELETE and the matching INSERT
   would leave behind, using the exact same SQL `_label_asset()` issues.
3. Whether job-uniqueness (the partial unique index) is enforced.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "apps/api")

from sevenfilm.db import Database

REAL_DB = Path("data/sevenfilm.sqlite3")
CLONE_DIR = Path("/tmp/p66_tempdb")
CLONE_PATH = CLONE_DIR / "clone.sqlite3"
PROJECT_ID = "29cd1e06-0af1-40c4-95bf-77f2add1159f"
TIMELINE_ID = "47dcab29-e8ca-4c78-ba3d-2c40457cc153"


def main() -> int:
    CLONE_DIR.mkdir(exist_ok=True)
    shutil.copy2(REAL_DB, CLONE_PATH)
    print(f"cloned {REAL_DB} -> {CLONE_PATH} ({CLONE_PATH.stat().st_size} bytes)")

    db = Database(CLONE_PATH)
    results = {}

    # --- 1. FK enforcement on a normal connection ---
    with db.connection() as conn:
        fk_state = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    results["foreign_keys_pragma_on_normal_connection"] = fk_state
    print(f"PRAGMA foreign_keys on a normal Database.connection(): {fk_state} (1=enforced, 0=not)")

    # --- 2. pick a real timeline_items row referencing a real shots row for 15A ---
    row = db.fetch_one(
        "SELECT ti.id AS item_id, ti.shot_id FROM timeline_items ti "
        "WHERE ti.timeline_id = ? LIMIT 1",
        (TIMELINE_ID,),
    )
    shot_id = row["shot_id"]
    shot_row = db.fetch_one("SELECT * FROM shots WHERE id = ?", (shot_id,))
    print(f"probe shot_id={shot_id} (referenced by timeline_item {row['item_id']}); exists in shots: {shot_row is not None}")
    results["probe_shot_id"] = shot_id
    results["shot_present_before_delete"] = shot_row is not None

    # --- 3. reproduce _label_asset()'s exact DELETE for that shot's asset (analysis.py:271) ---
    asset_id = shot_row["asset_id"]
    db.execute("DELETE FROM shots WHERE asset_id = ?", (asset_id,))
    print(f"issued DELETE FROM shots WHERE asset_id = {asset_id!r} (no exception raised)")
    results["delete_raised_fk_error"] = False  # we reached this line, so it didn't raise

    # --- 4. check: is the timeline_items row now dangling? ---
    shot_after = db.fetch_one("SELECT * FROM shots WHERE id = ?", (shot_id,))
    timeline_item_after = db.fetch_one(
        "SELECT * FROM timeline_items WHERE id = ?", (row["item_id"],)
    )
    results["shot_present_after_delete"] = shot_after is not None
    results["timeline_item_still_present_after_delete"] = timeline_item_after is not None
    results["timeline_item_now_dangling"] = (
        timeline_item_after is not None and shot_after is None
    )
    print(f"after DELETE: shot row present={shot_after is not None}, "
          f"timeline_item row present={timeline_item_after is not None}, "
          f"DANGLING REFERENCE={results['timeline_item_now_dangling']}")

    # --- 5. how many of the 129 timeline items reference shots under this one asset? ---
    affected = db.fetch_all(
        "SELECT ti.id FROM timeline_items ti WHERE ti.timeline_id = ? AND ti.asset_id = ?",
        (TIMELINE_ID, asset_id),
    )
    results["timeline_items_referencing_this_asset"] = len(affected)
    print(f"timeline_items referencing this specific asset: {len(affected)} of 129")

    # --- 6. job uniqueness: try to insert two concurrent 'shots' jobs for the same project ---
    import uuid

    from sevenfilm.db import now

    job1 = str(uuid.uuid4())
    job2 = str(uuid.uuid4())
    db.insert("jobs", {
        "id": job1, "project_id": PROJECT_ID, "kind": "shots", "status": "queued",
        "progress": 0.0, "checkpoint_json": "{}", "error": None,
        "created_at": now(), "updated_at": now(),
    })
    uniqueness_enforced = False
    try:
        db.insert("jobs", {
            "id": job2, "project_id": PROJECT_ID, "kind": "shots", "status": "queued",
            "progress": 0.0, "checkpoint_json": "{}", "error": None,
            "created_at": now(), "updated_at": now(),
        })
    except sqlite3.IntegrityError:
        uniqueness_enforced = True
    results["job_uniqueness_enforced"] = uniqueness_enforced
    print(f"second concurrent 'shots' job for same project blocked by unique index: {uniqueness_enforced}")

    Path("tools/fixtures/p6_6_orchestration_probe.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print("wrote tools/fixtures/p6_6_orchestration_probe.json")

    # Clean up the temp clone -- never touches the real DB.
    shutil.rmtree(CLONE_DIR, ignore_errors=True)
    print(f"removed temp clone dir {CLONE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
