"""The editor's own eye, kept.

Some of what makes a shot unusable cannot be measured here at any sensible cost. The man
standing in a doorway behind a couple in C1968 is fifteen ten-thousandths of the frame: the
detector finds him in every frame of the 4K original and in none of the 1280x720 proxy, and
upscaling the proxy does not bring him back because the information is not in it. Measuring
the whole shoot at full resolution runs 661 milliseconds a frame. A bride catching her step
has no measure at all.
"""

import unittest
from fractions import Fraction
from pathlib import Path

from sevenfilm.db import Database
from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import build_timeline
from sevenfilm.services.rejections import (
    project_rejections,
    reject_clips,
    rejected_names,
    restore_clips,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


class RejectionStoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / "test.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "p", "workspace_path": "/m", "target_duration_seconds": "150",
            "frame_rate": "25", "created_at": "now", "updated_at": "now"})
        for index in (1968, 2181):
            self.database.insert("media_assets", {
                "id": f"a{index}", "project_id": "p", "path": f"/m/C{index}.MP4",
                "file_name": f"C{index}.MP4", "duration_seconds": "10", "frame_rate": "25",
                "width": 1920, "height": 1080, "created_at": "now"})

    def test_a_clip_can_be_named_the_way_resolve_shows_it(self):
        for name in ("C1968", "C1968.MP4", "c1968.mp4", "/somewhere/C1968.MP4"):
            with self.subTest(name=name):
                taken, unknown = reject_clips(self.database, "p", [name])

                self.assertEqual((taken, unknown), ([name], []))
                self.assertEqual(project_rejections(self.database, "p")[0], frozenset({"a1968"}))
                restore_clips(self.database, "p", [name])

    def test_naming_the_same_clip_twice_leaves_one_row(self):
        reject_clips(self.database, "p", ["C1968"])
        reject_clips(self.database, "p", ["C1968.MP4"], reason="gelin takılıyor")

        self.assertEqual(rejected_names(self.database, "p"), ["C1968.MP4"])

    def test_a_name_that_is_not_in_the_project_comes_back_rather_than_failing(self):
        """A typo should say so, not lose the names beside it that were right."""
        taken, unknown = reject_clips(self.database, "p", ["C1968", "C9999"])

        self.assertEqual(taken, ["C1968"])
        self.assertEqual(unknown, ["C9999"])

    def test_a_rejection_can_be_taken_back(self):
        reject_clips(self.database, "p", ["C1968", "C2181"])
        restore_clips(self.database, "p", ["C1968"])

        self.assertEqual(rejected_names(self.database, "p"), ["C2181.MP4"])

    def test_an_untouched_project_rejects_nothing(self):
        self.assertEqual(project_rejections(self.database, "p"), (frozenset(), frozenset()))


class TheEditLeavesRejectedClipsAloneTests(unittest.TestCase):
    def plan(self, rejected=None):
        assets, shots = [], []
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=Path(f"/m/{index}.mov"),
                             name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 500, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.8,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": "medium", "start": "0", "end": "350"},))
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              rejected=rejected)

    def test_a_rejected_clip_reaches_no_cut_at_all(self):
        used = {item.asset.id for item in self.plan().items}
        self.assertIn("a0", used)

        after = self.plan(rejected=(frozenset({"a0"}), frozenset()))

        self.assertNotIn("a0", {item.asset.id for item in after.items})

    def test_a_rejected_shot_goes_without_taking_its_clip_with_it(self):
        after = self.plan(rejected=(frozenset(), frozenset({"s0"})))

        self.assertNotIn("s0", {item.shot.id for item in after.items})

    def test_the_edit_still_reaches_its_target_without_them(self):
        after = self.plan(rejected=(frozenset({f"a{i}" for i in range(20)}), frozenset()))

        self.assertGreaterEqual(float(after.duration), 149.9)


if __name__ == "__main__":
    unittest.main()
