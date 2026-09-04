"""A card that filled mid-recording leaves one unreadable file. It must not cost the shoot."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevenfilm.db import Database, now
from sevenfilm.services import media


def probe_result(duration="10.0"):
    return {
        "streams": [{"codec_type": "video", "avg_frame_rate": "25/1", "width": 1920,
                     "height": 1080, "codec_name": "h264", "duration": duration,
                     "tags": {"timecode": "01:00:00:00"}}],
        "format": {"duration": duration, "tags": {}},
    }


class IndexingBrokenMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "media"
        self.folder.mkdir()
        # Distinct content per file: identical files are deduplicated by hash, correctly.
        for index, name in enumerate(("a_broken.mov", "b_good.mov", "c_good.mov")):
            (self.folder / name).write_bytes(bytes([index]) * 16)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": str(self.folder),
            "target_duration_seconds": "150", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})
        self.database.insert("jobs", {
            "id": "j", "project_id": "p", "kind": "index", "status": "queued", "progress": 0,
            "checkpoint_json": {"completed_paths": []}, "error": None,
            "created_at": now(), "updated_at": now()})

    def index(self, broken):
        def probe(path):
            if path.name in broken:
                raise subprocess.CalledProcessError(1, ["ffprobe", str(path)])
            return probe_result()

        with mock.patch.object(media, "probe", probe), \
             mock.patch.object(media, "require_tool", lambda name: f"/usr/bin/{name}"):
            return media.index_folder(self.database, "p", self.folder, "j")

    def checkpoint(self):
        row = self.database.fetch_one("SELECT checkpoint_json FROM jobs WHERE id = ?", ("j",))
        return json.loads(row["checkpoint_json"])

    def test_the_rest_of_the_shoot_is_still_indexed(self):
        """The broken file sorts first, so it used to abort before anything was indexed."""
        assets = self.index({"a_broken.mov"})

        self.assertEqual([asset.name for asset in assets], ["b_good.mov", "c_good.mov"])

    def test_the_files_that_were_left_out_are_recorded(self):
        self.index({"a_broken.mov"})

        unreadable = [Path(item).name for item in self.checkpoint()["unreadable"]]
        self.assertEqual(unreadable, ["a_broken.mov"])

    def test_several_broken_files_are_all_recorded(self):
        self.index({"a_broken.mov", "c_good.mov"})

        self.assertEqual(len(self.checkpoint()["unreadable"]), 2)

    def test_a_file_with_no_video_stream_is_skipped_the_same_way(self):
        def probe(path):
            if path.name == "a_broken.mov":
                return {"streams": [{"codec_type": "audio"}], "format": {"duration": "10.0"}}
            return probe_result()

        with mock.patch.object(media, "probe", probe), \
             mock.patch.object(media, "require_tool", lambda name: f"/usr/bin/{name}"):
            assets = media.index_folder(self.database, "p", self.folder, "j")

        self.assertEqual(len(assets), 2)

    def test_nothing_readable_at_all_says_so_plainly(self):
        with self.assertRaises(ValueError) as raised:
            self.index({"a_broken.mov", "b_good.mov", "c_good.mov"})

        self.assertIn("hiçbiri okunamadı", str(raised.exception))

    def test_a_missing_ffprobe_is_still_a_hard_stop(self):
        """That is not one bad file, it is the whole installation, and skipping would hide it."""
        def probe(path):
            raise media.MediaToolUnavailable("ffprobe PATH içinde bulunamadı.")

        with mock.patch.object(media, "probe", probe), \
             mock.patch.object(media, "require_tool", lambda name: f"/usr/bin/{name}"), \
             self.assertRaises(media.MediaToolUnavailable):
            media.index_folder(self.database, "p", self.folder, "j")


class DerivativesBrokenMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": "/tmp", "target_duration_seconds": "150",
            "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
        for index in range(3):
            self.database.insert("media_assets", {
                "id": f"a{index}", "project_id": "p", "path": f"/m/A{index}.mov",
                "file_name": f"A{index}.mov", "content_hash": f"h{index}",
                "duration_seconds": "10", "frame_rate": "25/1", "width": 1920, "height": 1080,
                "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})
        self.database.insert("jobs", {
            "id": "j", "project_id": "p", "kind": "derivatives", "status": "queued",
            "progress": 0, "checkpoint_json": {}, "error": None,
            "created_at": now(), "updated_at": now()})
        self.cache = Path(self.temporary.name) / "cache"

    def generate(self, failing):
        def run(command, **kwargs):
            source = command[command.index("-i") + 1]
            if any(name in source for name in failing):
                raise subprocess.CalledProcessError(1, command)
            Path(command[-1]).write_bytes(b"x")
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(media.subprocess, "run", run), \
             mock.patch.object(media, "require_tool", lambda name: f"/usr/bin/{name}"):
            media.generate_derivatives(self.database, "p", self.cache, "j")

    def test_one_clip_ffmpeg_cannot_read_does_not_stop_the_others(self):
        self.generate({"A0.mov"})

        done = self.database.fetch_all("SELECT file_name FROM media_assets WHERE proxy_path IS NOT NULL")
        self.assertEqual(sorted(row["file_name"] for row in done), ["A1.mov", "A2.mov"])

    def test_the_clip_that_failed_is_recorded(self):
        self.generate({"A1.mov"})

        row = self.database.fetch_one("SELECT checkpoint_json FROM jobs WHERE id = ?", ("j",))
        self.assertEqual(json.loads(row["checkpoint_json"])["failed"], ["A1.mov"])

    def test_failing_on_every_clip_says_so_plainly(self):
        with self.assertRaises(ValueError) as raised:
            self.generate({"A0.mov", "A1.mov", "A2.mov"})

        self.assertIn("hiçbiri için proxy üretilemedi", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
