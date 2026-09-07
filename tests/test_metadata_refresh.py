"""A file the project already knows about is read again, not skipped.

An indexed file used to be passed over entirely, so a fix to how metadata is read never
reached footage indexed before it. Measured on this shoot: the rotation fix — a phone shooting
vertically codes a landscape frame and attaches a matrix saying to turn it — landed after the
345 clips were indexed, and sixteen portrait clips kept the landscape shape they were first
given. Their proxies came out portrait, because ffmpeg applies the matrix, while the FCPXML
went on declaring them 3840x2160.
"""

import unittest
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from sevenfilm.db import Database
from sevenfilm.services.media import _refresh_metadata


class MetadataRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "test.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "p", "workspace_path": "/m", "target_duration_seconds": "150",
            "frame_rate": "25", "created_at": "now", "updated_at": "now"})
        # Indexed before the rotation fix: a portrait clip recorded as landscape.
        self.database.insert("media_assets", {
            "id": "a1", "project_id": "p", "path": "/m/C1996.MP4", "file_name": "C1996.MP4",
            "duration_seconds": "10", "frame_rate": "50/1", "width": 3840, "height": 2160,
            "codec": "h264", "timecode": "08:41:18:34", "created_at": "now"})

    def stored(self):
        return self.database.fetch_one(
            "SELECT width, height, timecode FROM media_assets WHERE id = 'a1'")

    def refresh(self, **details):
        payload = {
            "duration": Fraction(10), "frame_rate": Fraction(50), "width": 3840,
            "height": 2160, "codec": "h264", "timecode": "08:41:18:34", "raw": "{}",
        }
        payload.update(details)
        with mock.patch("sevenfilm.services.media.probe", return_value={}), \
                mock.patch("sevenfilm.services.media.metadata_from_probe",
                           return_value=payload):
            _refresh_metadata(self.database, "a1", Path("/m/C1996.MP4"), "p")

    def test_a_shape_read_wrong_the_first_time_is_corrected(self):
        self.refresh(width=2160, height=3840)

        row = self.stored()
        self.assertEqual((row["width"], row["height"]), (2160, 3840))

    def test_a_row_that_is_already_right_is_left_alone(self):
        self.refresh()

        row = self.stored()
        self.assertEqual((row["width"], row["height"]), (3840, 2160))

    def test_it_corrects_the_other_fields_too(self):
        self.refresh(timecode="09:00:00:00")

        self.assertEqual(self.stored()["timecode"], "09:00:00:00")

    def test_a_file_that_has_become_unreadable_leaves_the_row_standing(self):
        """It was readable when it was indexed; a file that has since gone bad must not blank
        an edit's source out from under it."""
        with mock.patch("sevenfilm.services.media.probe",
                        side_effect=ValueError("Süre bilgisi bulunamadı")):
            _refresh_metadata(self.database, "a1", Path("/m/C1996.MP4"), "p")

        row = self.stored()
        self.assertEqual((row["width"], row["height"]), (3840, 2160))

    def test_a_broken_toolchain_is_not_treated_as_a_broken_file(self):
        """ffprobe missing is the environment, not the footage, and it stops the run for a new
        file too. Swallowing it here would silently leave every clip uncorrected."""
        from sevenfilm.services.media import MediaToolUnavailable

        with mock.patch("sevenfilm.services.media.probe",
                        side_effect=MediaToolUnavailable("ffprobe yok")), \
                self.assertRaises(MediaToolUnavailable):
            _refresh_metadata(self.database, "a1", Path("/m/C1996.MP4"), "p")


if __name__ == "__main__":
    unittest.main()
