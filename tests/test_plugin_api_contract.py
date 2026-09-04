"""The HTTP contract between the engine and the Resolve plugin.

main.js reads a fixed set of fields out of GET /api/timelines/{id} and hands them to
timeline-builder.js. The planner and that module are each tested on their own; this covers
the payload that actually travels between them, which nothing else does.
"""

import json
import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

_ROOT = tempfile.TemporaryDirectory()
os.environ["SEVENFILM_DATA_ROOT"] = _ROOT.name

from fastapi.testclient import TestClient
from sevenfilm import api
from sevenfilm.db import now
from sevenfilm.domain import BeatGrid, MediaAsset, Shot
from sevenfilm.services.planner import build_timeline, persist_timeline
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)  # The project's own footage is 50 fps against a 25 fps timeline.


class PluginContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(_ROOT.cleanup)
        api.DATABASE.migrate()
        database = api.DATABASE
        database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": _ROOT.name,
            "target_duration_seconds": "150", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})
        assets, shots = [], []
        for index in range(60):
            database.insert("media_assets", {
                "id": f"a{index}", "project_id": "p", "path": f"/m/A{index:03}.mov",
                "file_name": f"A{index:03}.mov", "content_hash": f"h{index}",
                "duration_seconds": "20", "frame_rate": "50/1", "width": 1920, "height": 1080,
                "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})
            assets.append(MediaAsset(
                id=f"a{index}", project_id="p", path=Path(f"/m/A{index:03}.mov"),
                name=f"A{index:03}.mov", duration=Fraction(20), frame_rate=RATE,
                width=1920, height=1080))
            shots.append(Shot(
                id=f"s{index}", asset_id=f"a{index}", source_range=TimeRange(0, 500, RATE),
                category=("couple", "bride", "detail", "venue")[index % 4],
                shot_scale=("medium", "wide", "close_up", "detail")[index % 4],
                technical_quality=.8, aesthetic_score=.8, motion_score=.5, confidence=.7,
                brightness=.36, saturation=.15, highlight_clipping=.01))
        database.insert("music_tracks", {
            "id": "m", "project_id": "p", "path": "/m/track.mp3", "duration_seconds": "200",
            "bpm": 123.0, "beats_json": [], "sections_json": [], "created_at": now()})
        interval = Fraction(60) / Fraction("123")
        music = BeatGrid(
            bpm=123.0, duration=Fraction(200),
            beats=tuple(interval * step for step in range(int(Fraction(200) / interval) + 1)),
            sections=({"start": "0", "end": "200", "energy": "medium"},))
        plan = build_timeline(
            project_id="p", assets=assets, shots=shots, music=music, frame_rate=FrameRate(25),
            target_duration=Fraction(150), seed=3)
        persist_timeline(database, plan)
        cls.timeline_id = plan.id
        cls.client = TestClient(api.app)

    def payload(self):
        response = self.client.get(f"/api/timelines/{self.timeline_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_the_engine_version_the_plugin_waits_for(self):
        """main.js only accepts a backend whose engine_version matches its own constant."""
        health = self.client.get("/api/health").json()
        plugin = (Path("integrations/resolve/com.sevenfilm.ai.editor/main.js")
                  .read_text(encoding="utf-8"))
        self.assertIn(f'ENGINE_VERSION = "{health["engine_version"]}"', plugin)

    def test_every_item_carries_what_the_adapter_reads(self):
        for item in self.payload()["items"]:
            for field in ("id", "source_path", "score", "category", "selection_reason",
                          "asset_duration_frames", "source_in", "timeline_in"):
                self.assertIn(field, item)
            for field in ("start_frame", "duration_frames", "rate"):
                self.assertIn(field, item["source_in"])
            self.assertIn("duration_frames", item["timeline_in"])

    def test_the_music_fields_the_adapter_clamps_against(self):
        payload = self.payload()
        self.assertEqual(payload["music_path"], "/m/track.mp3")
        self.assertEqual(payload["music_duration_seconds"], "200")
        self.assertIn("frame_rate", payload)

    def test_source_ranges_stay_inside_the_media(self):
        for item in self.payload()["items"]:
            end = item["source_in"]["start_frame"] + item["source_in"]["duration_frames"]
            self.assertLessEqual(end, item["asset_duration_frames"], item["source_path"])

    def test_the_source_rate_is_the_footage_rate_not_the_timeline_rate(self):
        """The adapter derives its minimum clip length from this; 50 fps needs 13 frames."""
        payload = self.payload()
        self.assertEqual(payload["frame_rate"], "25/1")
        self.assertEqual({item["source_in"]["rate"] for item in payload["items"]}, {"50/1"})

    def test_no_item_would_become_a_zero_length_range_in_resolve(self):
        """Resolve rejects startFrame == endFrame, which is what a one frame item becomes."""
        for item in self.payload()["items"]:
            self.assertGreaterEqual(item["source_in"]["duration_frames"], 2, item["source_path"])

    def test_the_export_endpoint_gives_the_fcpxml_the_plugin_downloads(self):
        links = self.client.post(f"/api/timelines/{self.timeline_id}/export")
        self.assertEqual(links.status_code, 200, links.text)
        route = links.json()["fcpxml"]

        downloaded = self.client.get(route)

        self.assertEqual(downloaded.status_code, 200)
        self.assertIn(b"<fcpxml", downloaded.content)

    def test_an_unknown_timeline_is_a_clean_404(self):
        response = self.client.get("/api/timelines/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)

    def test_the_project_endpoint_reports_stale_analyses_to_the_ui(self):
        project = self.client.get("/api/projects/p").json()
        self.assertIn("stale_analysis", project)
        self.assertEqual(set(project["stale_analysis"]), {"shots", "music"})

    def test_the_payload_is_json_serialisable_as_the_plugin_parses_it(self):
        json.loads(json.dumps(self.payload()))


if __name__ == "__main__":
    unittest.main()
