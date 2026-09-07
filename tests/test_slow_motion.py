"""Half speed where the film pauses to look and the music is not driving.

The editor asked for it in the quiet passages: "başta müzik daha slow, daha uzun akorlar var,
orda slow olabilir". Measured on the chosen song, the opening runs 2.2 to 4.6 onsets a second
against 4.4 to 6.2 after the drop, at a third of the energy, and the analyser's own section
pass draws the same two quiet stretches — 0 to 63 seconds and 107 to 139.

Delivered through FCPXML, because the Resolve scripting API has no way to set a timeline
item's speed: TimelineItem.SetProperty offers pan, tilt, zoom, crop and the retime *method*,
and nothing else. Measured against Resolve 21.0.2, an imported timeMap comes back at exactly
the speed it asks for.
"""

import unittest
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.exporter import export_fcpxml
from sevenfilm.services.planner import (
    SLOW_MOTION_ENERGY,
    SLOW_MOTION_SPEED,
    build_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)


def _plan(energy: str, tmp: Path):
    assets, shots = [], []
    categories = ("couple", "bride", "groom", "party", "venue", "detail")
    for index in range(200):
        one = MediaAsset(id=f"a{index}", project_id="p", path=tmp / f"{index}.mov",
                         name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                         width=1920, height=1080)
        assets.append(one)
        shots.append(Shot(
            id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 1400, RATE),
            category=categories[index % len(categories)], shot_scale="medium",
            technical_quality=.9, aesthetic_score=.9, motion_score=.3, confidence=.9,
            duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
            highlight_clipping=.01))
    beats = tuple(Fraction(i, 2) for i in range(700))
    music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                     sections=({"energy": energy, "start": "0", "end": "350"},))
    profile = {"held_shots": {"share_by_band": [0.25] * 10, "median_seconds": 4.0}}
    return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                          frame_rate=RATE, target_duration=Fraction(150), seed=1,
                          style_profile=profile)


def _slowed(plan):
    return [
        item for item in plan.items
        if item.source_range.duration_seconds != item.timeline_range.duration_seconds
    ]


class WhereTheEditSlowsDownTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)
        for index in range(200):
            (self.tmp / f"{index}.mov").write_bytes(b"")

    def test_the_quiet_passages_hold_a_shot_at_half_speed(self):
        slowed = _slowed(_plan(SLOW_MOTION_ENERGY, self.tmp))

        self.assertTrue(slowed)
        for item in slowed:
            played = item.source_range.duration_seconds
            occupied = item.timeline_range.duration_seconds
            self.assertAlmostEqual(float(played / occupied), float(SLOW_MOTION_SPEED), places=2)

    def test_nothing_is_slowed_while_the_music_is_driving(self):
        self.assertEqual(_slowed(_plan("high", self.tmp)), [])

    def test_only_the_held_shots_are_slowed(self):
        """Slowing the cutting rhythm instead would only make the edit sluggish."""
        plan = _plan(SLOW_MOTION_ENERGY, self.tmp)
        slowed = _slowed(plan)
        # The closing shot is deliberately the longest cut in the film and is not a held shot.
        ordinary = [item for item in plan.items[:-1] if item not in slowed]
        longest_ordinary = max(item.timeline_range.duration_seconds for item in ordinary)

        for item in slowed:
            self.assertGreaterEqual(item.timeline_range.duration_seconds, longest_ordinary)

    def test_a_slowed_shot_still_lands_on_a_beat(self):
        """Deriving the length back from the source put one 0.04 seconds off."""
        plan = _plan(SLOW_MOTION_ENERGY, self.tmp)

        for item in _slowed(plan):
            end = item.timeline_range.start_seconds + item.timeline_range.duration_seconds
            self.assertEqual(end % Fraction(1, 2), 0, f"{float(end)} sn beat'e oturmuyor")

    def test_the_edit_still_fills_its_target_exactly(self):
        self.assertEqual(_plan(SLOW_MOTION_ENERGY, self.tmp).duration, Fraction(150))


class TheRetimeReachesTheFileTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)
        for index in range(200):
            (self.tmp / f"{index}.mov").write_bytes(b"")

    def test_every_slowed_shot_carries_a_time_map_and_no_other_does(self):
        plan = _plan(SLOW_MOTION_ENERGY, self.tmp)
        written = export_fcpxml(plan, self.tmp / "edit.fcpxml")
        root = ET.parse(written).getroot()

        self.assertEqual(len(root.findall(".//timeMap")), len(_slowed(plan)))

    def test_the_map_is_written_on_the_media_clock_not_from_zero(self):
        """Relative values came back from Resolve at 0.01x — silently wrong, with no error."""
        plan = _plan(SLOW_MOTION_ENERGY, self.tmp)
        written = export_fcpxml(plan, self.tmp / "edit.fcpxml")
        root = ET.parse(written).getroot()
        clip = next(
            element for element in root.findall(".//asset-clip")
            if element.find("timeMap") is not None
        )
        points = clip.find("timeMap").findall("timept")

        def seconds(raw: str) -> Fraction:
            return Fraction(raw.rstrip("s"))

        self.assertEqual(seconds(points[0].get("time")), seconds(clip.get("start")))
        self.assertEqual(seconds(points[0].get("value")), seconds(clip.get("start")))
        occupied = seconds(points[1].get("time")) - seconds(points[0].get("time"))
        played = seconds(points[1].get("value")) - seconds(points[0].get("value"))
        self.assertEqual(occupied, seconds(clip.get("duration")))
        self.assertAlmostEqual(float(played / occupied), float(SLOW_MOTION_SPEED), places=3)

    def test_a_retimed_clip_keeps_the_moment_it_was_cut_from(self):
        """The fault this exists to catch, found in Resolve rather than here.

        An asset-clip carrying a timeMap has its `start` — its in point — ignored by Resolve
        21.0.2, and plays from the beginning of the media whatever the map says. Four ways of
        writing the map were tried and all four did it. So the slow motion was quietly playing
        the opening of a clip where the cut had been chosen 76 seconds in, and the editor saw a
        man in a grey shirt crossing the foreground instead of the cake being cut.

        A retimed clip therefore gets an asset of its own whose start *is* the in point, so
        that "the beginning of the media" is the right place. Verified back out of Resolve:
        source 32246.12 seconds at 0.50x, which is the frame the plan asked for.
        """
        plan = _plan(SLOW_MOTION_ENERGY, self.tmp)
        written = export_fcpxml(plan, self.tmp / "edit.fcpxml")
        root = ET.parse(written).getroot()
        assets = {element.get("id"): element for element in root.findall(".//asset")}

        def seconds(raw: str) -> Fraction:
            return Fraction(raw.rstrip("s"))

        retimed = [
            element for element in root.findall(".//asset-clip")
            if element.find("timeMap") is not None
        ]
        self.assertTrue(retimed)
        for clip in retimed:
            source = assets[clip.get("ref")]
            self.assertEqual(
                seconds(source.get("start")), seconds(clip.get("start")),
                "retime edilen klip kendi giriş noktasından başlayan bir asset'e bakmalı")

    def test_an_ordinary_clip_still_shares_its_asset(self):
        """One asset per file, or a hundred and ten clips become a hundred and ten assets."""
        plan = _plan("high", self.tmp)
        written = export_fcpxml(plan, self.tmp / "edit.fcpxml")
        root = ET.parse(written).getroot()

        self.assertLess(len(root.findall(".//asset")), len(plan.items))

    def test_a_plan_at_normal_speed_writes_none(self):
        plan = _plan("high", self.tmp)
        written = export_fcpxml(plan, self.tmp / "edit.fcpxml")

        self.assertEqual(ET.parse(written).getroot().findall(".//timeMap"), [])


class NothingWeakIsStretchedTests(unittest.TestCase):
    """Half speed doubles a shot's time on screen, so it doubles whatever is wrong with it.

    Measured on an edit that shipped: the six slowed shots had a median worst window of 0.44
    against 0.77 for the film as a whole, and two of them held a face against the frame edge —
    stretched to twice the length they were shot at.
    """

    def setUp(self):
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)
        for index in range(200):
            (self.tmp / f"{index}.mov").write_bytes(b"")

    def plan(self):
        from sevenfilm.services.windows import ShotWindow

        assets, shots, windows = [], [], {}
        categories = ("couple", "bride", "groom", "party", "venue", "detail")
        for index in range(200):
            one = MediaAsset(id=f"a{index}", project_id="p", path=self.tmp / f"{index}.mov",
                             name=f"{index}.mov", duration=Fraction(30), frame_rate=RATE,
                             width=1920, height=1080)
            assets.append(one)
            shots.append(Shot(
                id=f"s{index}", asset_id=one.id, source_range=TimeRange(0, 1400, RATE),
                category=categories[index % len(categories)], shot_scale="medium",
                technical_quality=.9, aesthetic_score=.9, motion_score=.3, confidence=.9,
                duplicate_group=f"visual:{index:016x}", brightness=.36, saturation=.15,
                highlight_clipping=.01))
            # Half the shoot has its subject against the frame edge throughout.
            edge = 0.9 if index % 2 else 0.0
            windows[f"s{index}"] = [
                ShotWindow(shot_id=f"s{index}", offset_frames=offset, sharpness=80.0,
                           motion=1.0, face_ratio=0.05, face_edge=edge, face_count=2,
                           bystanders=0)
                for offset in range(0, 1400, 25)
            ]
        beats = tuple(Fraction(i, 2) for i in range(700))
        music = BeatGrid(bpm=120, beats=beats, duration=Fraction(350),
                         sections=({"energy": SLOW_MOTION_ENERGY, "start": "0", "end": "350"},))
        profile = {"held_shots": {"share_by_band": [0.25] * 10, "median_seconds": 4.0}}
        return build_timeline(project_id="p", assets=assets, shots=shots, music=music,
                              frame_rate=RATE, target_duration=Fraction(150), seed=1,
                              style_profile=profile, windows_by_shot=windows)

    def test_a_shot_below_the_shoot_own_middle_is_never_stretched(self):
        plan = self.plan()
        slowed = [
            item for item in plan.items
            if item.source_range.duration_seconds != item.timeline_range.duration_seconds
        ]

        self.assertTrue(slowed, "hiç yavaş çekim yok, test bir şey ölçmüyor")
        for item in slowed:
            self.assertEqual(int(item.shot.id[1:]) % 2, 0, f"{item.shot.id} kenarı kesik")


if __name__ == "__main__":
    unittest.main()
