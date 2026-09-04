import tempfile
import unittest
from pathlib import Path

from sevenfilm.services.media import VIDEO_EXTENSIONS, iter_media_files


class VideoExtensionTests(unittest.TestCase):
    """A container missing from the list is skipped without a word."""

    def folder(self, names):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "CARD_A").mkdir()
        for name in names:
            (root / "CARD_A" / name).write_bytes(b"x")
        return root

    def found(self, names):
        return {path.name for path in iter_media_files(self.folder(names), VIDEO_EXTENSIONS)}

    def test_a_professional_camera_card_is_indexed(self):
        """Canon XF, Sony XDCAM and Panasonic P2 all write MXF; none of it was picked up."""
        self.assertEqual(self.found(["A001.MXF", "B002.mxf"]), {"A001.MXF", "B002.mxf"})

    def test_the_containers_already_supported_still_are(self):
        names = ["a.mp4", "b.MOV", "c.mts", "d.m2ts", "e.mkv", "f.avi", "g.webm"]

        self.assertEqual(self.found(names), set(names))

    def test_sidecars_and_stills_are_left_alone(self):
        self.assertEqual(self.found(["A001.XML", "A001.JPG", "notes.txt", ".DS_Store"]), set())

    def test_audio_is_not_indexed_as_footage(self):
        self.assertEqual(self.found(["track.wav", "track.mp3"]), set())
