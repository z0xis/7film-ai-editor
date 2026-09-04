"""Analyses left over from an older version look fine and quietly produce a worse edit."""

import tempfile
import unittest
from pathlib import Path

from sevenfilm.db import Database, now
from sevenfilm.services.analysis import ANALYSIS_VERSION, stale_analysis


class StaleAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": "/t", "target_duration_seconds": "150",
            "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
        self.database.insert("media_assets", {
            "id": "a", "project_id": "p", "path": "/m/x.mov", "file_name": "x.mov",
            "content_hash": "h", "duration_seconds": "10", "frame_rate": "25/1", "width": 1920,
            "height": 1080, "codec": "h264", "timecode": None, "metadata_json": {},
            "created_at": now()})

    def add_shot(self, shot_id, version):
        row = {
            "id": shot_id, "asset_id": "a", "start_frame": 0, "duration_frames": 100,
            "frame_rate": "25/1", "category": "couple", "shot_scale": "medium",
            "technical_quality": .8, "aesthetic_score": .8, "motion_score": .4,
            "confidence": .7, "duplicate_group": None, "labels_json": [], "created_at": now()}
        if version is not None:
            row["analysis_version"] = version
        self.database.insert("shots", row)

    def add_music(self, version):
        row = {
            "id": "m", "project_id": "p", "path": "/m/track.mp3", "duration_seconds": "200",
            "bpm": 123.0, "beats_json": [], "sections_json": [], "created_at": now()}
        if version is not None:
            row["analysis_version"] = version
        self.database.insert("music_tracks", row)

    def test_a_project_analysed_by_this_version_is_not_stale(self):
        self.add_shot("s1", ANALYSIS_VERSION)
        self.add_music(ANALYSIS_VERSION)

        self.assertEqual(stale_analysis(self.database, "p"), {"shots": False, "music": False})

    def test_rows_migrated_from_before_the_stamp_read_as_stale(self):
        """Every row already in a user's database has an empty version."""
        self.add_shot("s1", None)
        self.add_music(None)

        self.assertEqual(stale_analysis(self.database, "p"), {"shots": True, "music": True})

    def test_music_can_be_stale_on_its_own(self):
        # This is exactly what happened: the shots were re-analysed and the music was not,
        # which cut the edit twice as fast as the references.
        self.add_shot("s1", ANALYSIS_VERSION)
        self.add_music(None)

        self.assertEqual(stale_analysis(self.database, "p"), {"shots": False, "music": True})

    def test_one_stale_shot_among_fresh_ones_is_reported(self):
        self.add_shot("s1", ANALYSIS_VERSION)
        self.add_shot("s2", "1")
        self.add_music(ANALYSIS_VERSION)

        self.assertTrue(stale_analysis(self.database, "p")["shots"])

    def test_an_empty_project_is_not_reported_as_stale(self):
        self.assertEqual(stale_analysis(self.database, "p"), {"shots": False, "music": False})

    def test_another_project_does_not_leak_in(self):
        self.database.insert("projects", {
            "id": "other", "name": "O", "workspace_path": "/o", "target_duration_seconds": "150",
            "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
        self.add_shot("s1", None)
        self.add_music(None)

        self.assertEqual(stale_analysis(self.database, "other"), {"shots": False, "music": False})


if __name__ == "__main__":
    unittest.main()
