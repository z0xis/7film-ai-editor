import json
import tempfile
import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree as ET

from sevenfilm.db import Database, now
from sevenfilm.domain import BeatGrid, MediaAsset, MusicSegment, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.exporter import export_all, plan_as_dict
from sevenfilm.services.planner import (
    OPENING_SECONDS,
    build_timeline,
    get_timeline,
    persist_timeline,
)
from sevenfilm.timebase import FrameRate, TimeRange


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.rate = FrameRate(25)
        self.assets = []
        self.shots = []
        categories = ("venue", "detail", "bride", "groom", "couple", "family", "ceremony", "party")
        scales = ("wide", "medium", "close_up", "detail")
        for index in range(160):
            asset = MediaAsset(
                id=f"asset-{index}", project_id="project-1", path=Path(f"/media/A{index:03}.mov"),
                name=f"A{index:03}.mov", duration=Fraction(4), frame_rate=self.rate, width=1920, height=1080,
            )
            self.assets.append(asset)
            self.shots.append(Shot(
                id=f"shot-{index}", asset_id=asset.id, source_range=TimeRange(0, 100, self.rate),
                category=categories[index % len(categories)], shot_scale=scales[index % len(scales)],
                technical_quality=.8, aesthetic_score=.8, motion_score=.2 + (index % 4) * .2, confidence=.35,
            ))
        self.music = BeatGrid(bpm=120, beats=tuple(Fraction(step, 2) for step in range(301)), duration=Fraction(150), sections=(
            {"start": "0", "end": "30", "energy": "low"}, {"start": "30", "end": "120", "energy": "medium"}, {"start": "120", "end": "150", "energy": "high"},
        ))

    def test_plan_is_contiguous_non_repeating_and_target_length(self):
        plan = build_timeline(project_id="project-1", assets=self.assets, shots=self.shots, music=self.music, frame_rate=self.rate, target_duration=Fraction(120), seed=7)
        self.assertEqual(plan.duration, Fraction(120))
        self.assertEqual(len({item.shot.id for item in plan.items}), len(plan.items))
        self.assertEqual(plan.items[0].timeline_range.start_frame, 0)
        for previous, current in zip(plan.items, plan.items[1:]):
            self.assertEqual(previous.timeline_range.end_frame, current.timeline_range.start_frame)
        self.assertTrue(all("Skor bileşenleri" in item.selection_reason for item in plan.items))

    def test_reference_style_controls_cut_density(self):
        plan = build_timeline(
            project_id="project-1",
            assets=self.assets,
            shots=self.shots,
            music=self.music,
            frame_rate=self.rate,
            target_duration=Fraction(120),
            style_profile={"reference_count": 11, "beats_per_cut": {"low": 3, "medium": 2, "high": 1}},
            seed=7,
        )
        # Past the opening ramp, where the pace is the reference style's own rather than the
        # film's arrival. Two beats of this grid; the ramp starts the body a frame further
        # along it than it used to, so the beat the cut lands on is 1.48 rather than 1.52.
        self.assertEqual(
            plan.items[len(OPENING_SECONDS)].timeline_range.duration_seconds, Fraction(37, 25)
        )
        self.assertIn("11 referanstan", plan.warnings[0])

    def test_export_writes_otio_fcpxml_and_explainable_plan(self):
        plan = build_timeline(project_id="project-1", assets=self.assets, shots=self.shots, music=self.music, frame_rate=self.rate, target_duration=Fraction(120), seed=3)
        with tempfile.TemporaryDirectory() as temporary:
            paths = export_all(plan, Path(temporary))
            payload = json.loads(paths["plan"].read_text())
            self.assertEqual(payload["actual_duration_seconds"], "120")
            self.assertEqual(json.loads(paths["otio"].read_text())["OTIO_SCHEMA"], "Timeline.1")
            fcpxml = ET.parse(paths["fcpxml"]).getroot()
            self.assertEqual(fcpxml.tag, "fcpxml")
            asset = fcpxml.find("./resources/asset")
            self.assertIsNotNone(asset)
            self.assertNotIn("src", asset.attrib)
            self.assertEqual(asset.find("media-rep").attrib["kind"], "original-media")

    def test_fcpxml_includes_connected_music_asset_with_clamped_duration(self):
        plan = build_timeline(
            project_id="project-1",
            assets=self.assets,
            shots=self.shots,
            music=self.music,
            frame_rate=self.rate,
            target_duration=Fraction(120),
            seed=3,
        )
        with tempfile.TemporaryDirectory() as temporary:
            music_path = Path(temporary) / "music.wav"
            music_path.touch()
            plan.music_path = music_path
            plan.music_duration = Fraction(150)

            paths = export_all(plan, Path(temporary))
            fcpxml = ET.parse(paths["fcpxml"]).getroot()

            music_asset = fcpxml.find("./resources/asset[@id='m1']")
            self.assertIsNotNone(music_asset)
            self.assertEqual(music_asset.attrib["name"], "music.wav")
            self.assertEqual(
                Fraction(music_asset.attrib["duration"].removesuffix("s")),
                Fraction(150),
            )

            media_rep = music_asset.find("media-rep")
            self.assertIsNotNone(media_rep)
            self.assertEqual(media_rep.attrib["kind"], "original-media")
            self.assertEqual(media_rep.attrib["src"], music_path.resolve().as_uri())

            music_clip = fcpxml.find(
                "./library/event/project/sequence/spine/asset-clip/asset-clip[@ref='m1']"
            )
            self.assertIsNotNone(music_clip)
            self.assertEqual(music_clip.attrib["lane"], "-1")
            # An anchored item's offset is measured in the parent clip's own timeline, whose
            # origin is that clip's `start`. This clip is trimmed 5 frames (1/5s at 25fps) into
            # its source, so the music sitting at the edit's first frame reads 1/5s, not 0s.
            self.assertEqual(music_clip.attrib["offset"], "1/5s")
            self.assertEqual(music_clip.attrib["start"], "0s")
            self.assertEqual(music_clip.attrib["audioRole"], "music")
            self.assertEqual(
                Fraction(music_clip.attrib["duration"].removesuffix("s")),
                Fraction(120),
            )

    def test_reuses_only_unconsumed_source_segments_when_first_pass_is_short(self):
        assets = self.assets[:20]
        shots = [
            Shot(
                id=f"long-shot-{index}",
                asset_id=asset.id,
                source_range=TimeRange(0, 250, self.rate),
                category=self.shots[index].category,
                shot_scale=self.shots[index].shot_scale,
                technical_quality=.8,
                aesthetic_score=.8,
                motion_score=.5,
                confidence=.8,
            )
            for index, asset in enumerate(assets)
        ]

        plan = build_timeline(
            project_id="project-1",
            assets=assets,
            shots=shots,
            music=self.music,
            frame_rate=self.rate,
            target_duration=Fraction(120),
            seed=11,
        )

        self.assertEqual(plan.duration, Fraction(120))
        self.assertLess(len({item.shot.id for item in plan.items}), len(plan.items))
        for shot in shots:
            ranges = sorted(
                (item.source_range for item in plan.items if item.shot.id == shot.id),
                key=lambda source_range: source_range.start_frame,
            )
            for previous, current in pairwise(ranges):
                self.assertLessEqual(previous.end_frame, current.start_frame)


class ResolveHandoffTests(unittest.TestCase):
    """Guards for the Resolve adapter contract: picture-only clips and in-bounds ranges."""

    def setUp(self):
        self.rate = FrameRate(25)
        self.asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=self.rate, width=1920, height=1080,
        )
        self.shot = Shot(
            id="shot-1", asset_id="asset-1", source_range=TimeRange(0, 250, self.rate),
            category="couple", shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
            motion_score=.5, confidence=.8,
        )

    def _plan(self, source_range, timeline_duration=50):
        plan = TimelinePlan(
            id="timeline-1", project_id="project-1", name="AI Rough Cut", frame_rate=self.rate,
            target_duration=Fraction(120),
        )
        plan.items.append(TimelineItem(
            id="item-1", shot=self.shot, asset=self.asset, source_range=source_range,
            timeline_range=TimeRange(0, timeline_duration, self.rate), score=.9,
            selection_reason="test",
        ))
        return plan

    def test_plan_payload_exposes_media_and_music_limits_for_the_adapter(self):
        plan = self._plan(TimeRange(10, 50, self.rate))
        plan.music_path = Path("/media/track.wav")
        plan.music_duration = Fraction(90)

        payload = plan_as_dict(plan)

        self.assertEqual(payload["music_path"], "/media/track.wav")
        self.assertEqual(payload["music_duration_seconds"], "90")
        self.assertEqual(payload["items"][0]["asset_duration_frames"], 250)

    def test_fcpxml_source_assets_declare_no_camera_audio(self):
        plan = self._plan(TimeRange(10, 50, self.rate))
        with tempfile.TemporaryDirectory() as temporary:
            paths = export_all(plan, Path(temporary))
            asset = ET.parse(paths["fcpxml"]).getroot().find("./resources/asset")
            self.assertEqual(asset.attrib["hasVideo"], "1")
            self.assertEqual(asset.attrib["hasAudio"], "0")
            self.assertEqual(asset.attrib["audioSources"], "0")

    def test_stored_source_range_is_clamped_to_the_real_media_length(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "sevenfilm.sqlite3")
            database.migrate()
            _seed_timeline(database, self.asset, self.shot, source_start=240, source_duration=40)

            plan = get_timeline(database, "timeline-1")

            source_range = plan.items[0].source_range
            # The asset really holds 250 frames (10s @ 25fps): the last usable frame is 249.
            self.assertEqual(source_range.start_frame, 240)
            self.assertEqual(source_range.duration_frames, 10)
            self.assertEqual(source_range.end_frame, 250)

    def test_in_bounds_source_range_survives_the_round_trip_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "sevenfilm.sqlite3")
            database.migrate()
            _seed_timeline(database, self.asset, self.shot, source_start=25, source_duration=50)

            source_range = get_timeline(database, "timeline-1").items[0].source_range

            self.assertEqual(source_range.start_frame, 25)
            self.assertEqual(source_range.duration_frames, 50)


def _seed_timeline(database, asset, shot, *, source_start, source_duration):
    database.insert("projects", {
        "id": asset.project_id, "name": "Test", "workspace_path": "/tmp/test",
        "target_duration_seconds": "120", "frame_rate": "25/1", "created_at": now(), "updated_at": now(),
    })
    database.insert("media_assets", {
        "id": asset.id, "project_id": asset.project_id, "path": str(asset.path), "file_name": asset.name,
        "content_hash": "hash", "duration_seconds": str(asset.duration), "frame_rate": "25/1",
        "width": asset.width, "height": asset.height, "codec": "h264", "timecode": None,
        "metadata_json": {}, "created_at": now(),
    })
    database.insert("shots", {
        "id": shot.id, "asset_id": asset.id, "start_frame": shot.source_range.start_frame,
        "duration_frames": shot.source_range.duration_frames, "frame_rate": "25/1",
        "category": shot.category, "shot_scale": shot.shot_scale,
        "technical_quality": shot.technical_quality, "aesthetic_score": shot.aesthetic_score,
        "motion_score": shot.motion_score, "confidence": shot.confidence,
        "duplicate_group": None, "labels_json": [], "created_at": now(),
    })
    database.insert("timeline_versions", {
        "id": "timeline-1", "project_id": asset.project_id, "name": "AI Rough Cut",
        "target_duration_seconds": "120", "frame_rate": "25/1", "seed": 1, "warnings_json": [],
        "created_at": now(),
    })
    database.insert("timeline_items", {
        "id": "item-1", "timeline_id": "timeline-1", "position": 0, "shot_id": shot.id,
        "asset_id": asset.id, "source_start_frame": source_start,
        "source_duration_frames": source_duration, "source_rate": "25/1",
        "timeline_start_frame": 0, "timeline_duration_frames": source_duration,
        "score": .9, "reason": "test", "alternatives_json": [],
        "category": shot.category, "shot_scale": shot.shot_scale,
    })


class FcpxmlTimecodeTests(unittest.TestCase):
    """Resolve rejects the whole file if an asset claims to start at zero when it does not."""

    def setUp(self):
        self.rate = FrameRate(25)
        self.asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=self.rate, width=1920, height=1080,
            timecode="08:19:21:02")

    def plan(self, timecode="08:19:21:02", rate=None):
        rate = rate or self.rate
        asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=rate, width=1920, height=1080, timecode=timecode)
        shot = Shot(id="shot-1", asset_id="asset-1", source_range=TimeRange(0, 250, rate))
        plan = TimelinePlan(id="t", project_id="p", name="AI Rough Cut", frame_rate=self.rate,
                            target_duration=Fraction(4))
        plan.items.append(TimelineItem(
            id="i", shot=shot, asset=asset, source_range=TimeRange(50, 50, rate),
            timeline_range=TimeRange(0, 50, self.rate), score=.9, selection_reason="r"))
        return plan

    def exported(self, plan):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return ET.parse(export_all(plan, Path(folder.name))["fcpxml"]).getroot()

    def test_the_asset_starts_where_the_camera_says_it_does(self):
        asset = self.exported(self.plan()).find("./resources/asset")

        # 08:19:21:02 at 25 fps is 749027 frames.
        self.assertEqual(Fraction(asset.attrib["start"].removesuffix("s")), Fraction(749027, 25))

    def test_the_clip_start_is_on_the_media_clock_too(self):
        clip = self.exported(self.plan()).find("./library/event/project/sequence/spine/asset-clip")

        # Two seconds into a file that starts at 749027/25s.
        self.assertEqual(
            Fraction(clip.attrib["start"].removesuffix("s")), Fraction(749027, 25) + 2)

    def test_the_frame_part_is_read_at_the_footage_rate(self):
        asset = self.exported(self.plan(rate=FrameRate(50))).find("./resources/asset")

        # At 50 fps the same timecode is 1498052 frames, not 749027.
        self.assertEqual(Fraction(asset.attrib["start"].removesuffix("s")), Fraction(1498052, 50))

    def test_footage_without_a_timecode_still_starts_at_zero(self):
        asset = self.exported(self.plan(timecode=None)).find("./resources/asset")

        self.assertEqual(asset.attrib["start"], "0s")

    def test_a_timecode_that_makes_no_sense_is_ignored(self):
        for timecode in ("", "nonsense", "08:19:21", "08:19:21:02:11", "aa:bb:cc:dd"):
            with self.subTest(timecode=timecode):
                asset = self.exported(self.plan(timecode=timecode)).find("./resources/asset")
                self.assertEqual(asset.attrib["start"], "0s")

    def test_a_semicolon_means_nothing_at_a_whole_frame_rate(self):
        """There is no drop-frame at 25 fps, whatever separator the camera wrote."""
        asset = self.exported(self.plan(timecode="08:19:21;02")).find("./resources/asset")

        self.assertEqual(Fraction(asset.attrib["start"].removesuffix("s")), Fraction(749027, 25))

    def test_drop_frame_timecode_is_counted_as_drop_frame(self):
        """Counting it continuously runs 30 seconds fast at this time of day, which puts every
        clip start outside its own media - the very thing that made Resolve refuse the file."""
        ntsc = FrameRate(30000, 1001)

        asset = self.exported(self.plan(timecode="08:19:21;02", rate=ntsc)).find("./resources/asset")

        # 898832 frames counted continuously, 900 of them never existed.
        self.assertEqual(
            Fraction(asset.attrib["start"].removesuffix("s")), Fraction(897932) / ntsc.value)

    def test_non_drop_ntsc_is_left_alone(self):
        ntsc = FrameRate(30000, 1001)

        asset = self.exported(self.plan(timecode="08:19:21:02", rate=ntsc)).find("./resources/asset")

        self.assertEqual(
            Fraction(asset.attrib["start"].removesuffix("s")), Fraction(898832) / ntsc.value)

    def test_drop_frame_at_fifty_nine_ninety_four_drops_four_a_minute(self):
        rate = FrameRate(60000, 1001)

        asset = self.exported(self.plan(timecode="01:00:00;00", rate=rate)).find("./resources/asset")

        # One hour: 60 minutes less the 6 tenth minutes, four frames each.
        self.assertEqual(
            Fraction(asset.attrib["start"].removesuffix("s")),
            Fraction(3600 * 60 - 4 * (60 - 6)) / rate.value)

    def test_the_first_ten_minutes_of_drop_frame_lose_eighteen_frames(self):
        ntsc = FrameRate(30000, 1001)

        asset = self.exported(self.plan(timecode="00:10:00;00", rate=ntsc)).find("./resources/asset")

        # Minutes 1 to 9 drop two frames each; minute 10 does not.
        self.assertEqual(
            Fraction(asset.attrib["start"].removesuffix("s")), Fraction(600 * 30 - 18) / ntsc.value)


class FcpxmlFormatTests(unittest.TestCase):
    """A shoot mixing frame rates must not declare every source at the timeline's rate."""

    def setUp(self):
        self.rate = FrameRate(50)

    def plan_of(self, *rates):
        plan = TimelinePlan(id="t", project_id="p", name="AI", frame_rate=self.rate,
                            target_duration=Fraction(2 * len(rates)))
        for index, rate in enumerate(rates):
            asset = MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/A{index}.mov"),
                name=f"A{index}.mov", duration=Fraction(20), frame_rate=rate,
                width=3840, height=2160)
            shot = Shot(id=f"s{index}", asset_id=asset.id,
                        source_range=TimeRange(0, 500, rate))
            plan.items.append(TimelineItem(
                id=f"i{index}", shot=shot, asset=asset, source_range=TimeRange(0, 50, rate),
                timeline_range=TimeRange(100 * index, 100, self.rate), score=.9,
                selection_reason="r"))
        return plan

    def exported(self, plan):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return ET.parse(export_all(plan, Path(folder.name))["fcpxml"]).getroot()

    def test_each_frame_rate_gets_its_own_format(self):
        root = self.exported(self.plan_of(FrameRate(50), FrameRate(25), FrameRate(50)))

        durations = {f.attrib["frameDuration"] for f in root.findall("./resources/format")}

        self.assertEqual(durations, {"1/50s", "1/25s"})

    def test_a_source_points_at_the_format_that_matches_it(self):
        root = self.exported(self.plan_of(FrameRate(50), FrameRate(25)))
        formats = {f.attrib["id"]: f.attrib["frameDuration"]
                   for f in root.findall("./resources/format")}

        for asset in root.findall("./resources/asset"):
            if asset.attrib["name"] == "A1.mov":
                self.assertEqual(formats[asset.attrib["format"]], "1/25s")
            elif asset.attrib["name"] == "A0.mov":
                self.assertEqual(formats[asset.attrib["format"]], "1/50s")

    def test_the_sequence_keeps_the_timeline_rate(self):
        root = self.exported(self.plan_of(FrameRate(25), FrameRate(25)))
        sequence = root.find("./library/event/project/sequence")
        formats = {f.attrib["id"]: f.attrib["frameDuration"]
                   for f in root.findall("./resources/format")}

        # Every source is 25 fps, but the timeline is 50.
        self.assertEqual(formats[sequence.attrib["format"]], "1/50s")

    def test_one_rate_throughout_still_writes_the_pair(self):
        root = self.exported(self.plan_of(FrameRate(50), FrameRate(50)))

        self.assertEqual(len(root.findall("./resources/format")), 2)

    def test_sources_of_the_same_rate_and_size_share_one_format(self):
        root = self.exported(self.plan_of(*([FrameRate(50)] * 6)))

        references = {a.attrib["format"] for a in root.findall("./resources/asset")}
        self.assertEqual(len(references), 1)

    def test_the_clip_carries_its_source_format_too(self):
        root = self.exported(self.plan_of(FrameRate(25)))
        formats = {f.attrib["id"]: f.attrib["frameDuration"]
                   for f in root.findall("./resources/format")}
        clip = root.find("./library/event/project/sequence/spine/asset-clip")

        self.assertEqual(formats[clip.attrib["format"]], "1/25s")


class FootageQualityTests(unittest.TestCase):
    """A blurry blown-out frame reads to CLIP as a bride; it must never reach the timeline."""

    def setUp(self):
        self.rate = FrameRate(25)
        self.music = BeatGrid(
            bpm=123, beats=tuple(Fraction(step, 2) for step in range(401)), duration=Fraction(200),
            sections=({"start": "0", "end": "200", "energy": "medium"},),
        )
        # The measured signature of the 18 finished 7Film reference edits.
        self.profile = {
            "reference_count": 18,
            "beats_per_cut": {"low": 3, "medium": 2, "high": 1},
            "median_shot_duration_seconds": 1.0,
            "shot_duration_p25_seconds": 0.64,
            "shot_duration_p75_seconds": 1.6,
            "section_median_shot_duration_seconds": {
                "intro": 1.17, "build": 1.13, "core": 0.99, "finale": 0.959,
            },
            "beat_alignment_ratio_120ms": 0.6064,
            "visual_profile": {"mean_brightness": 0.3474, "mean_saturation": 0.2863},
        }

    def _asset(self, index):
        return MediaAsset(
            id=f"asset-{index}", project_id="project-1", path=Path(f"/media/A{index:03}.mov"),
            name=f"A{index:03}.mov", duration=Fraction(20), frame_rate=self.rate,
            width=1920, height=1080,
        )

    def _shot(self, index, source_frames=250, **overrides):
        categories = ("venue", "detail", "bride", "groom", "couple", "family", "ceremony", "party")
        scales = ("wide", "medium", "close_up", "detail")
        values = {
            "technical_quality": .82, "aesthetic_score": .8, "motion_score": .5, "confidence": .7,
            "brightness": .35, "saturation": .29, "highlight_clipping": .01,
        }
        values.update(overrides)
        return Shot(
            id=f"shot-{index}", asset_id=f"asset-{index}",
            source_range=TimeRange(0, source_frames, self.rate),
            category=categories[index % len(categories)], shot_scale=scales[index % len(scales)],
            **values,
        )

    def _blown_out(self, index):
        """A frame CLIP is confident is a bride, that is really an out-of-focus white wall."""
        return self._shot(
            index, technical_quality=.04, aesthetic_score=.9, confidence=.9,
            brightness=.97, saturation=.02, highlight_clipping=.71,
        )

    def _plan(self, shots, assets, target=Fraction(120)):
        return build_timeline(
            project_id="project-1", assets=assets, shots=shots, music=self.music,
            frame_rate=self.rate, target_duration=target, style_profile=self.profile, seed=5,
        )

    def test_blown_out_shots_never_reach_the_timeline(self):
        assets = [self._asset(index) for index in range(80)]
        shots = [
            self._blown_out(index) if index % 4 == 0 else self._shot(index)
            for index in range(80)
        ]

        plan = self._plan(shots, assets)

        used = {item.shot.id for item in plan.items}
        blown = {shot.id for shot in shots if shot.technical_quality < .1}
        self.assertEqual(used & blown, set())
        self.assertTrue(any("teknik kalite eşiğinin altında" in w for w in plan.warnings))

    def test_a_high_confidence_bride_label_cannot_rescue_an_unusable_frame(self):
        """The CLIP label and aesthetic score are deliberately flattering here."""
        assets = [self._asset(index) for index in range(60)]
        shots = [self._shot(index) for index in range(60)]
        shots[7] = self._shot(
            7, technical_quality=.05, aesthetic_score=.99, confidence=.99,
            brightness=.99, saturation=.01, highlight_clipping=.9,
        )

        plan = self._plan(shots, assets)

        self.assertNotIn("shot-7", {item.shot.id for item in plan.items})

    def test_clipped_highlights_alone_are_enough_to_reject_a_sharp_shot(self):
        assets = [self._asset(index) for index in range(60)]
        shots = [self._shot(index) for index in range(60)]
        shots[3] = self._shot(3, technical_quality=.9, highlight_clipping=.6, brightness=.9)

        plan = self._plan(shots, assets)

        self.assertNotIn("shot-3", {item.shot.id for item in plan.items})

    def test_unusable_footage_is_used_but_flagged_when_there_is_nothing_better(self):
        """Only 24s of usable material for a 120s target: the rest is used, and the plan says so."""
        assets = [self._asset(index) for index in range(60)]
        shots = [self._blown_out(index) for index in range(45)]
        shots += [self._shot(index, source_frames=50) for index in range(45, 60)]

        plan = self._plan(shots, assets)

        self.assertEqual(plan.duration, Fraction(120))
        self.assertTrue(
            any("Kalite eşiğini geçen görüntü hedef süreyi doldurmuyor" in w for w in plan.warnings),
            plan.warnings,
        )

    def test_a_shoot_that_simply_measures_low_is_not_thrown_away(self):
        """Raw footage measures below a graded reference; the bar is relative to this shoot."""
        assets = [self._asset(index) for index in range(60)]
        shots = [self._shot(index, technical_quality=.2, aesthetic_score=.5) for index in range(60)]

        plan = self._plan(shots, assets)

        self.assertEqual(plan.duration, Fraction(120))
        self.assertFalse(
            [warning for warning in plan.warnings if "kalite eşiğinin altında" in warning],
            plan.warnings,
        )

    def test_the_worst_of_a_shoot_is_still_rejected_when_the_whole_shoot_measures_low(self):
        assets = [self._asset(index) for index in range(60)]
        shots = [self._shot(index, technical_quality=.3) for index in range(59)]
        shots.append(self._shot(59, technical_quality=.05, brightness=.98, highlight_clipping=.8))

        plan = self._plan(shots, assets)

        self.assertNotIn("shot-59", {item.shot.id for item in plan.items})

    def test_brightness_is_judged_against_the_references_not_a_blown_out_shoot(self):
        """With half the shoot blown out, the shoot's own median is no longer a usable centre."""
        assets = [self._asset(index) for index in range(200)]
        on_look = [self._shot(index) for index in range(100)]
        blown = [
            self._shot(index, brightness=.92, saturation=.03, technical_quality=.5)
            for index in range(100, 200)
        ]

        plan = self._plan(on_look + blown, assets)

        on_look_ids = {shot.id for shot in on_look}
        on_look_frames = sum(
            item.timeline_range.duration_frames for item in plan.items if item.shot.id in on_look_ids
        )
        self.assertGreater(on_look_frames, plan.duration_frames - on_look_frames)

    def test_shots_matching_the_reference_look_outrank_equally_sharp_off_look_shots(self):
        # More shots than the edit needs cuts, so the planner is choosing rather than scraping.
        assets = [self._asset(index) for index in range(200)]
        on_look = [self._shot(index) for index in range(100)]
        off_look = [
            self._shot(index, brightness=.92, saturation=.03) for index in range(100, 200)
        ]

        plan = self._plan(on_look + off_look, assets, target=Fraction(120))

        # Both groups are equally sharp and equally long, so screen time reflects the look.
        on_look_ids = {shot.id for shot in on_look}
        on_look_frames = sum(
            item.timeline_range.duration_frames for item in plan.items if item.shot.id in on_look_ids
        )
        off_look_frames = plan.duration_frames - on_look_frames
        self.assertGreater(on_look_frames, off_look_frames)

    def test_cuts_follow_the_reference_length_when_the_beats_are_too_sparse(self):
        assets = [self._asset(index) for index in range(80)]
        shots = [self._shot(index) for index in range(80)]
        sparse_beats = BeatGrid(
            bpm=60, beats=tuple(Fraction(step * 5) for step in range(41)), duration=Fraction(200),
            sections=({"start": "0", "end": "200", "energy": "low"},),
        )

        plan = build_timeline(
            project_id="project-1", assets=assets, shots=shots, music=sparse_beats,
            frame_rate=self.rate, target_duration=Fraction(120), style_profile=self.profile, seed=5,
        )

        # A five second beat gap used to make every cut five seconds long. An ordinary cut now
        # takes the reference length instead of chasing the grid; the deliberate held shots the
        # references spend a quarter of their time on are the exception, and they land on a beat.
        # The last cut absorbs whatever is left of the target, so it is judged separately.
        body = plan.items[:-1]
        ordinary = [i for i in body if i.timeline_range.duration_seconds <= Fraction(2)]
        held = [i for i in body if i.timeline_range.duration_seconds > Fraction(2)]

        self.assertGreater(len(ordinary), len(held))
        for item in held:
            end = item.timeline_range.start_seconds + item.timeline_range.duration_seconds
            self.assertEqual(end % Fraction(5), 0, f"{float(end)} sn beat'e oturmuyor")

    def test_reference_visual_fit_is_neutral_without_measurements(self):
        """Projects analysed before the visual columns existed must plan exactly as before."""
        assets = [self._asset(index) for index in range(60)]
        unmeasured = [
            self._shot(index, brightness=0.0, saturation=0.0, highlight_clipping=0.0)
            for index in range(60)
        ]

        plan = self._plan(unmeasured, assets)

        self.assertEqual(plan.duration, Fraction(120))
        self.assertFalse([w for w in plan.warnings if "kalite eşiğinin altında" in w])


class SavedTimelineSurvivesReanalysisTests(unittest.TestCase):
    """A rough cut the editor already has must not be hollowed out by re-analysing the footage."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.rate = FrameRate(25)
        self.asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=self.rate, width=1920, height=1080,
        )
        self.shot = Shot(
            id="shot-1", asset_id="asset-1", source_range=TimeRange(0, 250, self.rate),
            category="ceremony", shot_scale="close_up", technical_quality=.8, aesthetic_score=.8,
            motion_score=.5, confidence=.8,
        )
        _seed_timeline(self.database, self.asset, self.shot, source_start=25, source_duration=50)

    def reanalyse(self):
        """What analyse_shots does to a clip: every shot row for it is replaced."""
        self.database.execute("DELETE FROM shots WHERE asset_id = ?", ("asset-1",))
        self.database.insert("shots", {
            "id": "shot-new", "asset_id": "asset-1", "start_frame": 0, "duration_frames": 125,
            "frame_rate": "25/1", "category": "party", "shot_scale": "wide",
            "technical_quality": .4, "aesthetic_score": .4, "motion_score": .4, "confidence": .3,
            "duplicate_group": None, "labels_json": [], "created_at": now(),
        })

    def test_the_timeline_keeps_all_of_its_clips(self):
        before = len(get_timeline(self.database, "timeline-1").items)

        self.reanalyse()

        self.assertEqual(len(get_timeline(self.database, "timeline-1").items), before)
        self.assertEqual(before, 1)

    def test_each_clip_keeps_what_it_was(self):
        self.reanalyse()

        item = get_timeline(self.database, "timeline-1").items[0]

        self.assertEqual(item.shot.category, "ceremony")
        self.assertEqual(item.shot.shot_scale, "close_up")

    def test_the_cut_points_are_untouched(self):
        self.reanalyse()

        item = get_timeline(self.database, "timeline-1").items[0]

        self.assertEqual(item.source_range.start_frame, 25)
        self.assertEqual(item.source_range.duration_frames, 50)
        self.assertEqual(item.timeline_range.duration_frames, 50)

    def test_the_timeline_still_exports(self):
        self.reanalyse()

        plan = get_timeline(self.database, "timeline-1")
        with tempfile.TemporaryDirectory() as folder:
            paths = export_all(plan, Path(folder))
            spine = ET.parse(paths["fcpxml"]).getroot().findall(
                "./library/event/project/sequence/spine/asset-clip")
        self.assertEqual(len(spine), 1)

    def test_a_timeline_written_before_the_columns_existed_still_loads(self):
        """Rows migrated from an older database have no category of their own."""
        self.database.execute(
            "UPDATE timeline_items SET category = '', shot_scale = '' WHERE id = ?", ("item-1",))
        self.reanalyse()

        item = get_timeline(self.database, "timeline-1").items[0]

        self.assertEqual(item.shot.category, "b_roll")
        self.assertEqual(item.source_range.duration_frames, 50)


class SequenceResolutionTests(unittest.TestCase):
    """A mixed-orientation shoot was given a timeline shaped like neither of its cameras."""

    def setUp(self):
        self.rate = FrameRate(25)

    def plan(self, shapes):
        """shapes: (width, height, frames) per clip, laid end to end."""
        plan = TimelinePlan(id="t", project_id="p", name="AI Rough Cut", frame_rate=self.rate,
                            target_duration=Fraction(8))
        start = 0
        for index, (width, height, frames) in enumerate(shapes, start=1):
            asset = MediaAsset(
                id=f"asset-{index}", project_id="p", path=Path(f"/media/A00{index}.mov"),
                name=f"A00{index}.mov", duration=Fraction(10), frame_rate=self.rate,
                width=width, height=height, timecode="08:19:21:02")
            shot = Shot(id=f"shot-{index}", asset_id=asset.id, source_range=TimeRange(0, 250, self.rate))
            plan.items.append(TimelineItem(
                id=f"i{index}", shot=shot, asset=asset,
                source_range=TimeRange(0, frames, self.rate),
                timeline_range=TimeRange(start, frames, self.rate), score=.9, selection_reason="r"))
            start += frames
        return plan

    def sequence_format(self, plan):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = ET.parse(export_all(plan, Path(folder.name))["fcpxml"]).getroot()
        element = root.find("./resources/format[@id='r0']")
        return int(element.attrib["width"]), int(element.attrib["height"])

    def test_a_vertical_clip_does_not_make_the_timeline_square(self):
        shape = self.sequence_format(self.plan([(1920, 1080, 200), (1080, 1920, 50)]))

        self.assertEqual(shape, (1920, 1080))

    def test_the_shape_holding_the_most_time_wins(self):
        shape = self.sequence_format(self.plan([(1920, 1080, 50), (3840, 2160, 400)]))

        self.assertEqual(shape, (3840, 2160))

    def test_a_tie_keeps_the_first_shape_on_the_timeline(self):
        shape = self.sequence_format(self.plan([(1080, 1920, 100), (1920, 1080, 100)]))

        self.assertEqual(shape, (1080, 1920))

    def test_an_unmeasured_asset_does_not_decide_the_timeline(self):
        shape = self.sequence_format(self.plan([(0, 0, 300), (3840, 2160, 50)]))

        self.assertEqual(shape, (3840, 2160))

    def test_an_empty_plan_still_exports(self):
        self.assertEqual(self.sequence_format(self.plan([])), (1920, 1080))


class MusicRoundTripTests(unittest.TestCase):
    """The songs an edit was cut to belong to the edit, not to whatever was imported since."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.rate = FrameRate(25)
        self.asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=self.rate, width=1920, height=1080)
        self.shot = Shot(id="shot-1", asset_id="asset-1", source_range=TimeRange(0, 250, self.rate),
                         technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.8)

    def segments(self):
        return (
            MusicSegment(path=Path("/m/yavaş şarkı.mp3"), timeline_start=Fraction(0),
                         duration=Fraction(984, 10)),
            MusicSegment(path=Path("/m/hareketli.mp3"), timeline_start=Fraction(984, 10),
                         duration=Fraction(216, 10), source_start=Fraction(90)),
        )

    def save(self, segments):
        plan = TimelinePlan(id="timeline-1", project_id="project-1", name="AI Rough Cut",
                            frame_rate=self.rate, target_duration=Fraction(120),
                            music_segments=segments,
                            music_path=segments[0].path if segments else None,
                            music_duration=segments[0].duration if segments else None)
        plan.items.append(TimelineItem(
            id="item-1", shot=self.shot, asset=self.asset,
            source_range=TimeRange(25, 50, self.rate), timeline_range=TimeRange(0, 50, self.rate),
            score=.9, selection_reason="r"))
        self.database.insert("projects", {
            "id": "project-1", "name": "p", "workspace_path": "/media",
            "target_duration_seconds": "120", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})
        self.database.insert("media_assets", {
            "id": "asset-1", "project_id": "project-1", "path": "/media/A001.mov",
            "file_name": "A001.mov", "content_hash": "h", "duration_seconds": "10",
            "frame_rate": "25/1", "width": 1920, "height": 1080, "codec": "h264",
            "timecode": None, "metadata_json": {}, "created_at": now()})
        self.database.insert("shots", {
            "id": "shot-1", "asset_id": "asset-1", "start_frame": 0, "duration_frames": 250,
            "frame_rate": "25/1", "category": "couple", "shot_scale": "medium",
            "technical_quality": .8, "aesthetic_score": .8, "motion_score": .5, "confidence": .8,
            "duplicate_group": None, "labels_json": [], "created_at": now()})
        persist_timeline(self.database, plan)
        return get_timeline(self.database, "timeline-1")

    def test_both_songs_come_back(self):
        restored = self.save(self.segments())

        self.assertEqual([s.path.name for s in restored.music_segments],
                         ["yavaş şarkı.mp3", "hareketli.mp3"])

    def test_the_part_of_the_song_that_was_used_comes_back_exactly(self):
        restored = self.save(self.segments())

        self.assertEqual(restored.music_segments[1].source_start, Fraction(90))
        self.assertEqual(restored.music_segments[1].timeline_start, Fraction(984, 10))
        self.assertEqual(restored.music_segments[1].duration, Fraction(216, 10))

    def test_the_first_song_still_answers_the_old_single_track_callers(self):
        restored = self.save(self.segments())

        self.assertEqual(restored.music_path, Path("/m/yavaş şarkı.mp3"))
        self.assertEqual(restored.music_duration, Fraction(984, 10))

    def test_importing_another_song_afterwards_does_not_change_a_saved_edit(self):
        restored = self.save(self.segments())
        self.database.insert("music_tracks", {
            "id": "later", "project_id": "project-1", "path": "/m/başka.mp3",
            "duration_seconds": "200", "bpm": 120.0, "beats_json": [], "sections_json": [],
            "created_at": now()})

        again = get_timeline(self.database, "timeline-1")

        self.assertEqual([s.path.name for s in again.music_segments],
                         [s.path.name for s in restored.music_segments])

    def test_an_edit_saved_before_multiple_songs_falls_back_to_the_music_row(self):
        self.save(())
        self.database.insert("music_tracks", {
            "id": "only", "project_id": "project-1", "path": "/m/tek.mp3",
            "duration_seconds": "150", "bpm": 120.0, "beats_json": [], "sections_json": [],
            "created_at": now()})

        restored = get_timeline(self.database, "timeline-1")

        self.assertEqual(restored.music_path, Path("/m/tek.mp3"))
        self.assertEqual(restored.music_duration, Fraction(150))
        self.assertEqual(len(restored.music_segments), 1)


class TwoSongExportTests(unittest.TestCase):
    """Both songs have to reach the exports, each playing the part that was chosen."""

    def setUp(self):
        self.rate = FrameRate(25)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.slow = self.folder / "yavaş.mp3"
        self.fast = self.folder / "hareketli.mp3"
        for path in (self.slow, self.fast):
            path.touch()

    def plan(self, segments=None):
        plan = TimelinePlan(id="t", project_id="p", name="AI Rough Cut", frame_rate=self.rate,
                            target_duration=Fraction(120))
        start = 0
        for index in range(1, 5):  # 4 x 750 frames = 120 seconds
            asset = MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/media/A00{index}.mov"),
                name=f"A00{index}.mov", duration=Fraction(60), frame_rate=self.rate,
                width=1920, height=1080)
            shot = Shot(id=f"s{index}", asset_id=asset.id, source_range=TimeRange(0, 1500, self.rate))
            plan.items.append(TimelineItem(
                id=f"i{index}", shot=shot, asset=asset, source_range=TimeRange(0, 750, self.rate),
                timeline_range=TimeRange(start, 750, self.rate), score=.9, selection_reason="r"))
            start += 750
        if segments is None:
            segments = (
                MusicSegment(path=self.slow, timeline_start=Fraction(0), duration=Fraction(90),
                             source_total=Fraction(200)),
                MusicSegment(path=self.fast, timeline_start=Fraction(90), duration=Fraction(30),
                             source_start=Fraction(40), source_total=Fraction(150)),
            )
        plan.music_segments = segments
        plan.music_path = segments[0].path if segments else None
        plan.music_duration = segments[0].duration if segments else None
        return plan

    def exported(self, plan=None):
        paths = export_all(plan or self.plan(), self.folder / "out")
        return (ET.parse(paths["fcpxml"]).getroot(), json.loads(paths["otio"].read_text()))

    def audio_track(self, otio):
        for track in otio["tracks"]["children"]:
            if track.get("kind") == "Audio":
                return track
        raise AssertionError("Ses parçası yok")

    # --- FCPXML ---

    def test_each_song_is_declared_once(self):
        fcpxml, _ = self.exported()
        assets = fcpxml.findall("./resources/asset[@hasAudio='1']")

        self.assertEqual([a.attrib["name"] for a in assets], ["yavaş.mp3", "hareketli.mp3"])

    def test_a_song_declares_its_whole_length_not_the_part_used(self):
        fcpxml, _ = self.exported()
        second = fcpxml.findall("./resources/asset[@hasAudio='1']")[1]

        self.assertEqual(Fraction(second.attrib["duration"].removesuffix("s")), Fraction(150))

    def test_the_second_song_hangs_off_the_clip_that_is_playing_when_it_enters(self):
        fcpxml, _ = self.exported()
        spine = fcpxml.find("./library/event/project/sequence/spine")
        # 90 seconds in is the fourth clip, which starts at 90.
        owners = [i for i, clip in enumerate(spine) if clip.find("asset-clip[@ref='m2']") is not None]

        self.assertEqual(owners, [3])

    def test_the_second_song_starts_where_it_was_cut_from(self):
        fcpxml, _ = self.exported()
        music = fcpxml.find(".//asset-clip[@ref='m2']")

        self.assertEqual(Fraction(music.attrib["start"].removesuffix("s")), Fraction(40))
        self.assertEqual(Fraction(music.attrib["duration"].removesuffix("s")), Fraction(30))

    def test_each_song_is_on_the_music_lane(self):
        fcpxml, _ = self.exported()

        for reference in ("m1", "m2"):
            clip = fcpxml.find(f".//asset-clip[@ref='{reference}']")
            self.assertEqual(clip.attrib["lane"], "-1", reference)
            self.assertEqual(clip.attrib["audioRole"], "music", reference)

    def test_a_song_entering_mid_clip_is_offset_inside_its_parent(self):
        segments = (
            MusicSegment(path=self.slow, timeline_start=Fraction(0), duration=Fraction(100),
                         source_total=Fraction(200)),
            MusicSegment(path=self.fast, timeline_start=Fraction(100), duration=Fraction(20),
                         source_total=Fraction(150)),
        )
        fcpxml, _ = self.exported(self.plan(segments))
        music = fcpxml.find(".//asset-clip[@ref='m2']")

        # The fourth clip starts at 90s and is untrimmed, so 100s is 10s into it.
        self.assertEqual(Fraction(music.attrib["offset"].removesuffix("s")), Fraction(10))

    # --- OTIO ---

    def test_the_otio_music_track_holds_both_songs_in_order(self):
        _, otio = self.exported()
        track = self.audio_track(otio)

        self.assertEqual([c["name"] for c in track["children"]], ["yavaş.mp3", "hareketli.mp3"])

    def test_the_otio_clips_are_laid_end_to_end(self):
        _, otio = self.exported()
        track = self.audio_track(otio)
        durations = [Fraction(str(c["source_range"]["duration"]["value"])) /
                     Fraction(str(c["source_range"]["duration"]["rate"])) for c in track["children"]]

        self.assertEqual(durations, [Fraction(90), Fraction(30)])

    def test_the_otio_second_clip_starts_inside_its_song(self):
        _, otio = self.exported()
        track = self.audio_track(otio)
        start = track["children"][1]["source_range"]["start_time"]

        self.assertEqual(Fraction(str(start["value"])) / Fraction(str(start["rate"])), Fraction(40))

    def test_one_song_still_produces_a_single_clip(self):
        segments = (MusicSegment(path=self.slow, timeline_start=Fraction(0),
                                 duration=Fraction(120), source_total=Fraction(200)),)
        fcpxml, otio = self.exported(self.plan(segments))
        track = self.audio_track(otio)

        self.assertEqual(len(track["children"]), 1)
        self.assertEqual(len(fcpxml.findall("./resources/asset[@hasAudio='1']")), 1)


class PlanIdentityTests(unittest.TestCase):
    """An edit built minutes ago and one from this morning look identical without a time."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.rate = FrameRate(25)
        self.asset = MediaAsset(
            id="asset-1", project_id="project-1", path=Path("/media/A001.mov"), name="A001.mov",
            duration=Fraction(10), frame_rate=self.rate, width=1920, height=1080)
        self.shot = Shot(id="shot-1", asset_id="asset-1", source_range=TimeRange(0, 250, self.rate),
                         technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.8)
        _seed_timeline(self.database, self.asset, self.shot, source_start=25, source_duration=50)

    def test_a_saved_plan_reports_when_it_was_built(self):
        restored = get_timeline(self.database, "timeline-1")

        self.assertTrue(restored.created_at)
        self.assertIn("T", restored.created_at)

    def test_the_time_reaches_the_payload_the_app_reads(self):
        restored = get_timeline(self.database, "timeline-1")

        self.assertEqual(plan_as_dict(restored)["created_at"], restored.created_at)

    def test_persisting_stamps_a_plan_that_has_no_time_yet(self):
        plan = TimelinePlan(id="timeline-2", project_id="project-1", name="AI Rough Cut",
                            frame_rate=self.rate, target_duration=Fraction(120))
        plan.items.append(TimelineItem(
            id="item-2", shot=self.shot, asset=self.asset,
            source_range=TimeRange(0, 50, self.rate), timeline_range=TimeRange(0, 50, self.rate),
            score=.9, selection_reason="r"))

        persist_timeline(self.database, plan)

        self.assertTrue(plan.created_at)
        self.assertEqual(get_timeline(self.database, "timeline-2").created_at, plan.created_at)
