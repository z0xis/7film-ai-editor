"""Shot analysis must survive a crash and must not re-decode video to re-label."""

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

import numpy as np
from sevenfilm.db import Database, now
from sevenfilm.domain import MediaAsset
from sevenfilm.services import analysis
from sevenfilm.services.vision import CATEGORY_PROMPTS, FrameMetrics
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(25)


def measurements(quality=0.6):
    return FrameMetrics(
        technical_quality=quality, motion_score=0.4, perceptual_hash="abcd", face_count=1,
        brightness=0.36, saturation=0.15, highlight_clipping=0.01, sharpness=0.5, contrast=0.4,
    )


class FakeClassifier:
    """Stands in for CLIP, counting how often the expensive encode step is reached."""

    def __init__(self, categories=None):
        self.encode_calls = 0
        self._categories = categories

    def encode(self, frames):
        self.encode_calls += 1
        return np.asarray([[float(index), 1.0, 0.0] for index in range(len(frames))], dtype=np.float32)

    def category_prior(self, features):
        return np.full(len(CATEGORY_PROMPTS), 1 / len(CATEGORY_PROMPTS))

    def classify_features(self, features, metrics, prior=None):
        name = "couple" if prior is not None else "bride"
        return [
            {"category": name, "shot_scale": "medium", "aesthetic_score": 0.7,
             "confidence": 0.4, "labels": (name, "medium", "faces:1", "clip_vision")}
            for _ in metrics
        ]

    @staticmethod
    def _fallback(metrics):
        return {"category": "venue", "shot_scale": "wide", "aesthetic_score": 0.3,
                "confidence": 0.25, "labels": ("venue", "wide", "opencv_fallback")}


class ResumableAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()
        self.database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": "/tmp", "target_duration_seconds": "150",
            "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
        self.assets = []
        for index in range(3):
            self.database.insert("media_assets", {
                "id": f"asset-{index}", "project_id": "p", "path": f"/m/A{index}.mov",
                "file_name": f"A{index}.mov", "content_hash": f"h{index}", "duration_seconds": "10",
                "frame_rate": "25/1", "width": 1920, "height": 1080, "codec": "h264",
                "timecode": None, "metadata_json": {}, "created_at": now()})
            self.assets.append(MediaAsset(
                id=f"asset-{index}", project_id="p", path=Path(f"/m/A{index}.mov"),
                name=f"A{index}.mov", duration=Fraction(10), frame_rate=RATE, width=1920, height=1080))
        self.database.insert("jobs", {
            "id": "job", "project_id": "p", "kind": "shots", "status": "queued", "progress": 0,
            "checkpoint_json": {}, "error": None, "created_at": now(), "updated_at": now()})

    def run_analysis(self, classifier, fail_on=None):
        ranges = [TimeRange(0, 100, RATE), TimeRange(100, 100, RATE)]
        seen = {"count": 0}

        def scene_ranges(asset):
            seen["count"] += 1
            if fail_on is not None and seen["count"] > fail_on:
                raise RuntimeError("çöktü")
            return list(ranges)

        with mock.patch.object(analysis, "VisionClassifier", lambda: classifier), \
             mock.patch.object(analysis, "_scene_ranges", scene_ranges), \
             mock.patch.object(analysis, "_shot_frame_groups",
                               lambda asset, rs: [[np.zeros((8, 8, 3), np.uint8)] for _ in rs]), \
             mock.patch.object(analysis, "measure_frames", lambda frames: measurements()):
            return analysis.analyze_shots(self.database, "p", "job")

    def test_a_crash_keeps_the_work_already_encoded(self):
        classifier = FakeClassifier()
        with self.assertRaises(RuntimeError):
            self.run_analysis(classifier, fail_on=2)

        encoded = self.database.fetch_all("SELECT DISTINCT asset_id FROM shot_features")
        self.assertEqual(len(encoded), 2, "the two assets that finished must be kept")

    def test_the_rerun_only_encodes_what_is_missing(self):
        with self.assertRaises(RuntimeError):
            self.run_analysis(FakeClassifier(), fail_on=2)

        resumed = FakeClassifier()
        shots = self.run_analysis(resumed)

        self.assertEqual(resumed.encode_calls, 1, "only the unfinished asset is decoded again")
        self.assertEqual(len(shots), 6)

    def test_relabelling_costs_no_decoding_at_all(self):
        self.run_analysis(FakeClassifier())

        again = FakeClassifier()
        self.run_analysis(again)

        self.assertEqual(again.encode_calls, 0, "a second run must reuse the stored embeddings")

    def test_every_shot_is_labelled_against_the_project_wide_prior(self):
        shots = self.run_analysis(FakeClassifier())
        # The fake reports "couple" only when a prior was passed in.
        self.assertEqual({shot.category for shot in shots}, {"couple"})

    def test_the_measurements_survive_the_round_trip(self):
        self.run_analysis(FakeClassifier())

        row = self.database.fetch_one("SELECT * FROM shot_features LIMIT 1")
        stored = FrameMetrics(**json.loads(row["metrics_json"]))

        self.assertEqual(stored, measurements())
        self.assertEqual(len(np.frombuffer(row["embedding"], dtype=np.float32)), 3)

    def test_shots_and_stored_features_stay_in_step(self):
        self.run_analysis(FakeClassifier())

        features = self.database.fetch_all("SELECT shot_id FROM shot_features ORDER BY shot_id")
        shots = self.database.fetch_all("SELECT id FROM shots ORDER BY id")

        self.assertEqual([r["shot_id"] for r in features], [r["id"] for r in shots])

    def test_a_frame_that_could_not_be_read_falls_back_without_an_embedding(self):
        classifier = FakeClassifier()
        with mock.patch.object(analysis, "VisionClassifier", lambda: classifier), \
             mock.patch.object(analysis, "_scene_ranges", lambda asset: [TimeRange(0, 100, RATE)]), \
             mock.patch.object(analysis, "_shot_frame_groups", lambda asset, rs: [[] for _ in rs]), \
             mock.patch.object(analysis, "measure_frames", lambda frames: measurements(0.0)):
            shots = analysis.analyze_shots(self.database, "p", "job")

        self.assertTrue(all(shot.category == "venue" for shot in shots), "opencv fallback")
        self.assertIsNone(self.database.fetch_one("SELECT embedding FROM shot_features LIMIT 1")["embedding"])


if __name__ == "__main__":
    unittest.main()
