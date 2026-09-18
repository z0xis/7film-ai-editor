"""P5: the 15 Ağustos forensic audit's root cause, closed. 2638/2638 shots were analysed by
`opencv_fallback` -- CLIP never loaded -- and nothing checked before a 129-clip wedding rough
cut was planned from labels that fallback can only ever produce as {family, couple, bride,
detail, venue}, never `ceremony`/`party`/`bride_prep`/`groom_prep`/`groom`. This file proves
two things stay true from here on: the backend can tell the two apart (`semantic_readiness`),
and it refuses to plan a rough cut from a project that is not `FULL` (`create_timeline`'s gate).

Fully offline: nothing here downloads or requires the real CLIP model. `VisionClassifier._load`
is mocked where its result matters; everything else reads `labels_json`, the provenance
`classify_features`/`_fallback` have always stamped, off an isolated database.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)

from fastapi.testclient import TestClient
from sevenfilm import api
from sevenfilm.db import Database, now
from sevenfilm.domain import TimelinePlan
from sevenfilm.services.analysis import (
    NOT_READY_FOR_ROUGH_CUT,
    READY_FOR_ROUGH_CUT,
    semantic_readiness,
)
from sevenfilm.services.vision import (
    SEMANTIC_BACKEND_CLIP,
    SEMANTIC_BACKEND_FALLBACK,
    VisionClassifier,
    semantic_backend_status,
)
from sevenfilm.timebase import FrameRate


def _isolated_db(tmp_dir: str) -> Database:
    database = Database(Path(tmp_dir) / "test.sqlite3")
    database.migrate()
    return database


def _project(database: Database, project_id: str = "proj") -> None:
    database.insert("projects", {
        "id": project_id, "name": "T", "workspace_path": "/tmp",
        "target_duration_seconds": "150", "frame_rate": "25/1",
        "created_at": now(), "updated_at": now()})


def _asset(database: Database, project_id: str, asset_id: str) -> None:
    database.insert("media_assets", {
        "id": asset_id, "project_id": project_id, "path": f"/m/{asset_id}.mov",
        "file_name": f"{asset_id}.mov", "content_hash": asset_id,
        "duration_seconds": "10", "frame_rate": "50/1", "width": 1920, "height": 1080,
        "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})


def _shot(database: Database, asset_id: str, shot_id: str, *, labels: list | None,
          category: str = "couple") -> None:
    database.insert("shots", {
        "id": shot_id, "asset_id": asset_id, "start_frame": 0, "duration_frames": 50,
        "frame_rate": "50/1", "category": category, "shot_scale": "medium",
        "technical_quality": 0.8, "aesthetic_score": 0.8, "motion_score": 0.5,
        "confidence": 0.7, "duplicate_group": None, "labels_json": labels or [],
        "brightness": 0.3, "saturation": 0.1, "highlight_clipping": 0.0,
        "analysis_version": "4", "face_ratio": 0.0, "face_edge": 0.0, "created_at": now()})


# -- 1, 2, 3, 13: live capability check (VisionClassifier._load mocked, no real model needed) --

class LiveCapabilityTests(unittest.TestCase):
    def test_model_available_reports_full_capability(self):
        with patch.object(VisionClassifier, "_load", return_value=True):
            status = semantic_backend_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["backend"], SEMANTIC_BACKEND_CLIP)
        self.assertIsNone(status["reason"])

    def test_model_load_failure_reports_fallback_never_falsely_full(self):
        def fake_load(self):
            self._load_error = OSError("Can't load image processor for 'openai/clip-vit-base-patch32'")
            return False

        with patch.object(VisionClassifier, "_load", fake_load):
            status = semantic_backend_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["backend"], SEMANTIC_BACKEND_FALLBACK)
        self.assertNotEqual(status["backend"], SEMANTIC_BACKEND_CLIP)

    def test_load_exception_reason_is_preserved_not_swallowed(self):
        def fake_load(self):
            self._load_error = OSError("model cache missing")
            return False

        with patch.object(VisionClassifier, "_load", fake_load):
            status = semantic_backend_status()
        self.assertIn("OSError", status["reason"])
        self.assertIn("model cache missing", status["reason"])

    def test_a_load_failure_does_not_crash_the_technical_fallback(self):
        # _fallback itself never touches the model at all -- a load failure upstream must not
        # stop technical measurements (face count, quality) from still producing a usable row.
        classifier = VisionClassifier()
        from sevenfilm.services.vision import FrameMetrics
        result = classifier._fallback(FrameMetrics(
            technical_quality=0.7, motion_score=0.2, perceptual_hash="x", face_count=1))
        self.assertEqual(result["category"], "bride")
        self.assertEqual(result["labels"][-1], SEMANTIC_BACKEND_FALLBACK)


# -- 4, 5, 6, 11: semantic_readiness reads real provenance off labels_json ------------------

class SemanticReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)
        _asset(self.db, "proj", "a1")

    def test_all_full_shots_report_full_status(self):
        for i in range(3):
            _shot(self.db, "a1", f"s{i}", labels=["couple", "medium", "faces:2", SEMANTIC_BACKEND_CLIP])
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result["status"], READY_FOR_ROUGH_CUT)
        self.assertEqual(result, {"status": "FULL", "full": 3, "degraded": 0, "unknown": 0, "total": 3})

    def test_all_fallback_shots_report_degraded_status(self):
        for i in range(3):
            _shot(self.db, "a1", f"s{i}", labels=["venue", "wide", "faces:0", SEMANTIC_BACKEND_FALLBACK])
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result["status"], NOT_READY_FOR_ROUGH_CUT)
        self.assertEqual(result["degraded"], 3)
        self.assertEqual(result["full"], 0)

    def test_mixed_full_and_fallback_is_not_ready(self):
        _shot(self.db, "a1", "s0", labels=["couple", "medium", "faces:2", SEMANTIC_BACKEND_CLIP])
        _shot(self.db, "a1", "s1", labels=["venue", "wide", "faces:0", SEMANTIC_BACKEND_FALLBACK])
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result["status"], NOT_READY_FOR_ROUGH_CUT)
        self.assertEqual((result["full"], result["degraded"]), (1, 1))

    def test_legacy_rows_with_no_recognised_provenance_count_as_unknown_not_full(self):
        # Real production data: the "İS" project's shots carry ["family", "placeholder_features"]
        # -- a label shape that predates the clip_vision/opencv_fallback convention entirely.
        _shot(self.db, "a1", "s0", labels=["family", "placeholder_features"])
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result["status"], NOT_READY_FOR_ROUGH_CUT)
        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["full"], 0)

    def test_a_shot_with_empty_labels_counts_as_unknown(self):
        _shot(self.db, "a1", "s0", labels=[])
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result["unknown"], 1)

    def test_zero_shots_is_not_full(self):
        result = semantic_readiness(self.db, "proj")
        self.assertEqual(result, {"status": "DEGRADED", "full": 0, "degraded": 0, "unknown": 0, "total": 0})


# -- 7, 8, 9, 10, 12: the rough-cut HTTP gate ------------------------------------------------

class RoughCutGateTests(unittest.TestCase):
    """`build_timeline`/`persist_timeline` are mocked out entirely: what is under test is
    whether `create_timeline` calls them at all, not what a real plan looks like -- that is
    covered by the planner's own tests. A minimal real `TimelinePlan` stands in for a
    successful build so `plan_as_dict` (which the endpoint still calls on the happy path) has
    real fields to read."""

    @classmethod
    def setUpClass(cls):
        api.DATABASE.migrate()
        cls.client = TestClient(api.app)

    def _project(self, project_id: str) -> None:
        api.DATABASE.insert("projects", {
            "id": project_id, "name": project_id, "workspace_path": "/tmp",
            "target_duration_seconds": "150", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})

    def _asset(self, project_id: str, asset_id: str) -> None:
        _asset(api.DATABASE, project_id, asset_id)

    def _shot(self, asset_id: str, shot_id: str, labels: list) -> None:
        _shot(api.DATABASE, asset_id, shot_id, labels=labels)

    def _fake_plan(self, project_id: str) -> TimelinePlan:
        from fractions import Fraction
        return TimelinePlan(
            id=f"tl-{project_id}", project_id=project_id, name="AI Rough Cut",
            frame_rate=FrameRate(25), target_duration=Fraction(150), items=[], warnings=[])

    def test_all_fallback_project_is_rejected_before_planning_runs(self):
        pid = "gate-fallback"
        self._project(pid)
        self._asset(pid, f"{pid}-a1")
        for i in range(3):
            self._shot(f"{pid}-a1", f"{pid}-s{i}", ["venue", "wide", "faces:0", SEMANTIC_BACKEND_FALLBACK])

        with patch("sevenfilm.api.build_timeline") as fake_build:
            response = self.client.post(f"/api/projects/{pid}/timelines", json={})

        fake_build.assert_not_called()
        self.assertEqual(response.status_code, 422)
        self.assertIn("Semantik", response.json()["detail"])

    def test_all_full_project_reaches_planning(self):
        # `create_timeline` requires a chosen song before it ever reaches `build_timeline` --
        # a pre-existing, unrelated check -- so `plan_music` is mocked out alongside
        # `build_timeline`/`persist_timeline`: what is under test is the semantic gate, not
        # real beat-grid analysis.
        from fractions import Fraction

        from sevenfilm.domain import BeatGrid

        pid = "gate-full"
        self._project(pid)
        self._asset(pid, f"{pid}-a1")
        for i in range(3):
            self._shot(f"{pid}-a1", f"{pid}-s{i}", ["couple", "medium", "faces:2", SEMANTIC_BACKEND_CLIP])
        api.DATABASE.insert("music_tracks", {
            "id": f"{pid}-m1", "project_id": pid, "path": "/m/song.mp3",
            "duration_seconds": "150", "bpm": 120.0, "beats_json": [], "sections_json": [],
            "position": 0, "analysis_version": "4", "created_at": now()})
        fake_grid = BeatGrid(bpm=120.0, beats=(), duration=Fraction(150))

        with (
            patch("sevenfilm.api.build_timeline", return_value=self._fake_plan(pid)) as fake_build,
            patch("sevenfilm.api.persist_timeline"),
            patch("sevenfilm.api.plan_music", return_value=(fake_grid, (), [])),
        ):
            response = self.client.post(f"/api/projects/{pid}/timelines", json={})

        fake_build.assert_called_once()
        self.assertEqual(response.status_code, 201)

    def test_mixed_project_is_rejected(self):
        pid = "gate-mixed"
        self._project(pid)
        self._asset(pid, f"{pid}-a1")
        self._shot(f"{pid}-a1", f"{pid}-s0", ["couple", "medium", "faces:2", SEMANTIC_BACKEND_CLIP])
        self._shot(f"{pid}-a1", f"{pid}-s1", ["venue", "wide", "faces:0", SEMANTIC_BACKEND_FALLBACK])

        with patch("sevenfilm.api.build_timeline") as fake_build:
            response = self.client.post(f"/api/projects/{pid}/timelines", json={})

        fake_build.assert_not_called()
        self.assertEqual(response.status_code, 422)

    def test_zero_shot_project_is_not_blocked_by_the_semantic_gate(self):
        # No shots at all is a different problem than degraded semantics -- `semantic_readiness`
        # returns total=0 for it, and the gate's own `if readiness["total"] and ...` is written
        # to skip entirely rather than produce a misleading "semantic analysis is degraded"
        # message for a project that was never analysed at all. What actually blocks this
        # project (no music chosen yet) is a pre-existing, unrelated check -- proving that one
        # fired, not the semantic one, is exactly what distinguishes "the gate correctly did
        # not fire" from "the gate fired and this happens to also look like it didn't".
        pid = "gate-empty"
        self._project(pid)

        response = self.client.post(f"/api/projects/{pid}/timelines", json={})

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("Semantik", response.json()["detail"])

    def test_legacy_unknown_provenance_project_is_rejected(self):
        pid = "gate-legacy"
        self._project(pid)
        self._asset(pid, f"{pid}-a1")
        self._shot(f"{pid}-a1", f"{pid}-s0", ["family", "placeholder_features"])

        with patch("sevenfilm.api.build_timeline") as fake_build:
            response = self.client.post(f"/api/projects/{pid}/timelines", json={})

        fake_build.assert_not_called()
        self.assertEqual(response.status_code, 422)


# -- 14: API capability response ------------------------------------------------------------

class CapabilitiesEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.DATABASE.migrate()
        cls.client = TestClient(api.app)

    def test_capabilities_endpoint_reports_semantic_backend_live(self):
        with patch.object(VisionClassifier, "_load", return_value=True):
            response = self.client.get("/api/capabilities")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("semantic", body)
        self.assertEqual(body["semantic"]["backend"], SEMANTIC_BACKEND_CLIP)
        self.assertTrue(body["semantic"]["available"])

    def test_capabilities_endpoint_reports_unavailable_honestly(self):
        with patch.object(VisionClassifier, "_load", return_value=False):
            response = self.client.get("/api/capabilities")
        body = response.json()
        self.assertFalse(body["semantic"]["available"])
        self.assertEqual(body["semantic"]["backend"], SEMANTIC_BACKEND_FALLBACK)


# -- 17: the exact 15 Ağustos regression, as a read-only fact against production data --------

class ProductionRegressionTests(unittest.TestCase):
    """Not a fixture: this reads the real 15 Ağustos project this whole package chain exists
    because of, from the real (untouched) production database, read-only. No mutation, no
    rough cut generated."""

    def test_the_real_15_agustos_project_is_now_semantically_full_after_p6_12(self):
        """Was `..._is_not_ready...`: before P6.12 this project was 2638/2638 DEGRADED
        (opencv_fallback, no embeddings) and NOT_READY_FOR_ROUGH_CUT. The authorized P6.12
        controlled force-reencode remediated it -- every shot now carries a real CLIP embedding,
        so `semantic_readiness` reports FULL. This still reads the real production DB read-only;
        it now guards that the remediation stays in place rather than the old degraded state."""
        import sqlite3

        db_path = Path(__file__).parent.parent / "data" / "sevenfilm.sqlite3"
        if not db_path.exists():
            self.skipTest("no production database present in this environment")

        class _ReadOnlyDatabase:
            """Duck-types just the one method `semantic_readiness` calls, backed by a
            genuinely read-only SQLite connection (`mode=ro`) -- this test reads the real
            production database and must not be able to write to it even by accident."""

            def __init__(self, path: Path) -> None:
                self._connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                self._connection.row_factory = sqlite3.Row

            def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
                return [dict(row) for row in self._connection.execute(sql, params).fetchall()]

        database = _ReadOnlyDatabase(db_path)
        result = semantic_readiness(database, "29cd1e06-0af1-40c4-95bf-77f2add1159f")
        self.assertEqual(result["status"], READY_FOR_ROUGH_CUT)
        self.assertEqual(result["total"], 2638)
        self.assertEqual(result["degraded"], 0)
        self.assertEqual(result["full"], 2638)
