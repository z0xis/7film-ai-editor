"""A backend left running from before a release must not corrupt the next job it is given.

The desktop app spawns the engine once and keeps it. After a release the process is older than
the code it serves: its schema migration ran with the previous column list, so the first job
that writes a new column dies — and the app showed "Error: [object Object]", which says nothing.
"""

import re
import tempfile
import unittest
from pathlib import Path

from sevenfilm.db import ADDED_COLUMNS, Database, now


class MigrationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "sevenfilm.sqlite3"
        self.database = Database(self.path)
        self.database.migrate()

    def drop(self, table, column):
        """Put the file back the way an older release left it."""
        self.database.execute(f"ALTER TABLE {table} DROP COLUMN {column}")

    def columns(self, table):
        with self.database.connection() as connection:
            return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}

    def test_a_second_migration_restores_a_column_an_older_release_never_had(self):
        self.drop("music_tracks", "position")
        self.assertNotIn("position", self.columns("music_tracks"))

        self.database.migrate()

        self.assertIn("position", self.columns("music_tracks"))

    def test_every_added_column_is_restored_the_same_way(self):
        for table, column, _ in ADDED_COLUMNS:
            self.drop(table, column)

        self.database.migrate()

        for table, column, _ in ADDED_COLUMNS:
            self.assertIn(column, self.columns(table), f"{table}.{column}")

    def test_migrating_again_leaves_the_rows_alone(self):
        self.database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": "/m", "target_duration_seconds": "120",
            "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
        self.database.insert("music_tracks", {
            "id": "m", "project_id": "p", "path": "/m/a.mp3", "duration_seconds": "100",
            "bpm": 120.0, "beats_json": [], "sections_json": [], "position": 1,
            "created_at": now()})

        self.database.migrate()
        self.database.migrate()

        rows = self.database.fetch_all("SELECT path, position FROM music_tracks", ())
        self.assertEqual([(row["path"], row["position"]) for row in rows], [("/m/a.mp3", 1)])

    def test_a_running_job_migrates_before_it_writes(self):
        """_run_job calls migrate, so an old process repairs itself on the next job."""
        import inspect

        from sevenfilm import api

        source = inspect.getsource(api._run_job)
        self.assertIn("DATABASE.migrate()", source)


class EngineVersionTests(unittest.TestCase):
    """The plugin replaces a running engine only when the two versions disagree."""

    def plugin_version(self):
        source = Path("integrations/resolve/com.sevenfilm.ai.editor/main.js").read_text()
        match = re.search(r'const ENGINE_VERSION = "([^"]+)"', source)
        self.assertIsNotNone(match, "main.js'de ENGINE_VERSION bulunamadı")
        return match.group(1)

    def test_the_plugin_and_the_engine_agree_on_the_version(self):
        """They are written apart, and a mismatch means the plugin can never reuse the engine
        it just started — while agreeing when the contract has changed means it keeps an old
        one, which is how "path: Field required" reached the user."""
        from sevenfilm.api import ENGINE_VERSION

        self.assertEqual(self.plugin_version(), ENGINE_VERSION)

    def test_the_health_endpoint_reports_it(self):
        from fastapi.testclient import TestClient
        from sevenfilm import api

        body = TestClient(api.app).get("/api/health").json()

        self.assertEqual(body["engine_version"], api.ENGINE_VERSION)
