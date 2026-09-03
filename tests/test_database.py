import sqlite3
import tempfile
import unittest
from pathlib import Path

from sevenfilm.db import Database, now

LEGACY_SHOTS_SCHEMA = """
CREATE TABLE shots (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    start_frame INTEGER NOT NULL,
    duration_frames INTEGER NOT NULL,
    frame_rate TEXT NOT NULL,
    category TEXT NOT NULL,
    shot_scale TEXT NOT NULL,
    technical_quality REAL NOT NULL,
    aesthetic_score REAL NOT NULL,
    motion_score REAL NOT NULL,
    confidence REAL NOT NULL,
    duplicate_group TEXT,
    labels_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


class DatabaseTests(unittest.TestCase):
    def test_schema_persists_a_resumable_job_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "sevenfilm.sqlite3")
            database.migrate()
            database.insert("projects", {
                "id": "project", "name": "Test", "workspace_path": "/tmp/test", "target_duration_seconds": "150",
                "frame_rate": "25/1", "created_at": now(), "updated_at": now(),
            })
            database.insert("jobs", {
                "id": "job", "project_id": "project", "kind": "index", "status": "queued", "progress": 0,
                "checkpoint_json": {"completed_paths": ["/media/A001.mov"]}, "error": None, "created_at": now(), "updated_at": now(),
            })
            database.update_job("job", status="running", progress=.5, checkpoint={"completed_paths": ["/media/A001.mov", "/media/A002.mov"]})
            row = database.fetch_one("SELECT status, progress, checkpoint_json FROM jobs WHERE id = ?", ("job",))
            self.assertEqual(row["status"], "running")
            self.assertEqual(row["progress"], .5)
            self.assertIn("A002.mov", row["checkpoint_json"])


    def test_migrate_widens_a_database_created_before_the_visual_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sevenfilm.sqlite3"
            database = Database(path)
            database.migrate()
            _insert_project_asset_and_shot(database)

            # A second migration must be a no-op for existing rows.
            database.migrate()

            row = database.fetch_one("SELECT * FROM shots WHERE id = ?", ("shot",))
            self.assertEqual(row["brightness"], 0)
            self.assertEqual(row["saturation"], 0)
            self.assertEqual(row["highlight_clipping"], 0)
            self.assertEqual(row["category"], "couple")

    def test_migrate_adds_the_visual_columns_to_a_legacy_shots_table(self):
        """A shots table written by the released version predates the visual columns."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sevenfilm.sqlite3"
            with sqlite3.connect(path) as legacy:
                legacy.executescript(LEGACY_SHOTS_SCHEMA)
                legacy.execute(
                    "INSERT INTO shots VALUES ('shot','asset',0,100,'25/1','couple','medium',"
                    ".8,.8,.4,.7,NULL,'[]','2026-09-03T00:00:00+00:00')"
                )

            Database(path).migrate()

            row = Database(path).fetch_one("SELECT * FROM shots WHERE id = ?", ("shot",))
            self.assertEqual(row["brightness"], 0)
            self.assertEqual(row["saturation"], 0)
            self.assertEqual(row["highlight_clipping"], 0)
            self.assertEqual(row["technical_quality"], .8)

    def test_visual_measurements_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "sevenfilm.sqlite3")
            database.migrate()
            _insert_project_asset_and_shot(database, brightness=.35, saturation=.29, clipping=.02)

            row = database.fetch_one("SELECT * FROM shots WHERE id = ?", ("shot",))
            self.assertAlmostEqual(row["brightness"], .35)
            self.assertAlmostEqual(row["saturation"], .29)
            self.assertAlmostEqual(row["highlight_clipping"], .02)


def _insert_project_asset_and_shot(database, *, brightness=None, saturation=None, clipping=None):
    database.insert("projects", {
        "id": "project", "name": "Test", "workspace_path": "/tmp/test",
        "target_duration_seconds": "150", "frame_rate": "25/1", "created_at": now(), "updated_at": now(),
    })
    database.insert("media_assets", {
        "id": "asset", "project_id": "project", "path": "/media/A001.mov", "file_name": "A001.mov",
        "content_hash": "hash", "duration_seconds": "10", "frame_rate": "25/1", "width": 1920,
        "height": 1080, "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now(),
    })
    shot = {
        "id": "shot", "asset_id": "asset", "start_frame": 0, "duration_frames": 100,
        "frame_rate": "25/1", "category": "couple", "shot_scale": "medium",
        "technical_quality": .8, "aesthetic_score": .8, "motion_score": .4, "confidence": .7,
        "duplicate_group": None, "labels_json": [], "created_at": now(),
    }
    if brightness is not None:
        shot |= {"brightness": brightness, "saturation": saturation, "highlight_clipping": clipping}
    database.insert("shots", shot)
