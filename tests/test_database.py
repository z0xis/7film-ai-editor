import tempfile
import unittest
from pathlib import Path

from sevenfilm.db import Database, now


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

