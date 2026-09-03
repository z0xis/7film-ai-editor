import json
import tempfile
import unittest
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree as ET

from sevenfilm.db import Database, now
from sevenfilm.domain import BeatGrid, MediaAsset, Shot, TimelineItem, TimelinePlan
from sevenfilm.services.exporter import export_all, plan_as_dict
from sevenfilm.services.planner import build_timeline, get_timeline
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
        self.assertEqual(plan.items[0].timeline_range.duration_seconds, Fraction(38, 25))
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
            self.assertEqual(music_clip.attrib["offset"], "0s")
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
    })
