"""P6.11 -- Safe force-reencode trigger, snapshot/restore, strict postcondition validator."""

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)

from sevenfilm.db import Database, now
from sevenfilm.services import analysis as analysis_module

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"

# Load the tools/ safety module by path (not importable as a package).
_spec = importlib.util.spec_from_file_location(
    "p6_11_safety", ROOT / "tools/p6_11_reencode_safety.py")
safety = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safety)

P15 = safety.P15
ELENORA = safety.ELENORA
TL = safety.TIMELINE_15A


def _db(tmp):
    d = Database(Path(tmp) / "d.sqlite3")
    d.migrate()
    return d


def _project(d, pid):
    d.insert("projects", {"id": pid, "name": pid, "workspace_path": "/t",
                          "target_duration_seconds": "150", "frame_rate": "25/1",
                          "created_at": now(), "updated_at": now()})


def _asset(d, aid, pid):
    d.insert("media_assets", {"id": aid, "project_id": pid, "path": f"/m/{aid}.mp4",
                              "file_name": f"{aid}.mp4", "content_hash": None,
                              "duration_seconds": "20", "frame_rate": "25/1", "width": 1920,
                              "height": 1080, "codec": "h264", "timecode": None, "proxy_path": None,
                              "thumbnail_path": None, "metadata_json": {}, "created_at": now()})


def _shot(d, sid, aid, start, tq=0.5):
    d.insert("shots", {"id": sid, "asset_id": aid, "start_frame": start, "duration_frames": 100,
                       "frame_rate": "25/1", "category": "venue", "shot_scale": "wide",
                       "technical_quality": tq, "aesthetic_score": 0.5, "motion_score": 0.4,
                       "confidence": 0.3, "duplicate_group": "g", "labels_json": ["venue"],
                       "analysis_version": "4", "brightness": 0.5, "saturation": 0.5,
                       "highlight_clipping": 0.0, "face_ratio": 0.0, "face_edge": 0.0,
                       "created_at": now()})


def _job(d, jid, pid, status="queued"):
    d.insert("jobs", {"id": jid, "project_id": pid, "kind": "shots", "status": status,
                      "progress": 0.0, "checkpoint_json": {"force_reencode": True}, "error": None,
                      "created_at": now(), "updated_at": now()})


def _feature(d, sid, aid, start, embed=True):
    emb = np.ones(512, np.float32).tobytes() if embed else None
    d.insert("shot_features", {"shot_id": sid, "asset_id": aid, "start_frame": start,
                               "duration_frames": 100, "frame_rate": "25/1", "embedding": emb,
                               "metrics_json": {"technical_quality": 0.5}, "created_at": now()})


def _seed_valid(d):
    """A clean, fully-remediated post-state for the 15A project + a protected Elenora project."""
    _project(d, P15)
    _project(d, ELENORA)
    _asset(d, "a1", P15)
    _asset(d, "e1", ELENORA)
    for i, sid in enumerate(("s1", "s2", "s3")):
        _shot(d, sid, "a1", i * 100, tq=0.5)
        _feature(d, sid, "a1", i * 100, embed=True)
    _shot(d, "es1", "e1", 0, tq=0.5)
    _feature(d, "es1", "e1", 0, embed=True)
    d.insert("timeline_versions", {"id": TL, "project_id": P15, "name": "AI Rough Cut",
                                   "target_duration_seconds": "150", "frame_rate": "25/1",
                                   "seed": 1, "warnings_json": [], "created_at": now(),
                                   "music_segments_json": "[]"})
    d.insert("timeline_items", {"id": "it1", "timeline_id": TL, "position": 0, "shot_id": "s1",
                                "asset_id": "a1", "source_start_frame": 0,
                                "source_duration_frames": 100, "source_rate": "25/1",
                                "timeline_start_frame": 0, "timeline_duration_frames": 100,
                                "score": 0.8, "reason": "x", "alternatives_json": [],
                                "category": "venue", "shot_scale": "wide"})


# ---- force-reencode trigger (API plumbing + analyze gate) ----------------------------------
class TriggerTests(unittest.TestCase):
    def _analyze_with_spy(self, force, has_features):
        calls = {"encode": 0, "scene": 0}
        with tempfile.TemporaryDirectory() as tmp:
            d = _db(tmp)
            _project(d, "p")
            _asset(d, "a1", "p")
            _shot(d, "s1", "a1", 0)
            if has_features:
                _feature(d, "s1", "a1", 0, embed=True)

            def fake_encode(db, clf, asset):
                calls["encode"] += 1

            with mock.patch.object(analysis_module, "_encode_asset", fake_encode), \
                    mock.patch.object(analysis_module, "_scene_ranges",
                                      lambda a: (_ for _ in ()).throw(AssertionError("segmented"))), \
                    mock.patch.object(analysis_module, "VisionClassifier", lambda: object()), \
                    mock.patch.object(analysis_module, "_project_prior", lambda *a: None), \
                    mock.patch.object(analysis_module, "_label_asset", lambda *a: None), \
                    mock.patch.object(analysis_module, "_measure_shot_windows", lambda *a, **k: None):
                analysis_module.analyze_shots(d, "p", "job", force_reencode=force)
        return calls["encode"]

    def test_default_reuses_features_no_encode(self):
        self.assertEqual(self._analyze_with_spy(force=False, has_features=True), 0)

    def test_force_true_bypasses_reuse_and_encodes(self):
        self.assertEqual(self._analyze_with_spy(force=True, has_features=True), 1)

    def test_without_features_encodes_regardless(self):
        self.assertEqual(self._analyze_with_spy(force=False, has_features=False), 1)

    def test_force_encode_failure_preserves_old_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _db(tmp)
            _project(d, "p"); _asset(d, "a1", "p"); _shot(d, "s1", "a1", 0)
            _feature(d, "s1", "a1", 0, embed=True)
            before = d.fetch_all("SELECT shot_id, embedding FROM shot_features WHERE asset_id='a1'")

            def boom(db, clf, asset):
                raise RuntimeError("encode failed")

            with mock.patch.object(analysis_module, "_encode_asset", boom), \
                    mock.patch.object(analysis_module, "VisionClassifier", lambda: object()), \
                    self.assertRaises(RuntimeError):
                analysis_module.analyze_shots(d, "p", "job", force_reencode=True)
            after = d.fetch_all("SELECT shot_id, embedding FROM shot_features WHERE asset_id='a1'")
        self.assertEqual([r["shot_id"] for r in before], [r["shot_id"] for r in after])
        self.assertEqual(len(after), 1)

    def test_concurrency_guard_rejects_second_shots_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _db(tmp); _project(d, "p")
            _job(d, "j1", "p")
            # The partial unique index on (project_id, kind) for active jobs rejects the second.
            with self.assertRaises(sqlite3.IntegrityError):
                _job(d, "j2", "p")


# ---- snapshot / restore --------------------------------------------------------------------
class SnapshotTests(unittest.TestCase):
    def test_snapshot_then_restore_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _db(tmp); _seed_valid(d)
            src = Path(tmp) / "d.sqlite3"
            snap = Path(tmp) / "snap.sqlite3"
            info = safety.snapshot_db(src, snap)
            self.assertTrue(info["integrity_ok"])
            before = safety.build_manifest(src)

            # Mutate the working DB destructively.
            d.execute("DELETE FROM shot_features WHERE asset_id = 'a1'")
            d.execute("UPDATE shots SET technical_quality = 0 WHERE asset_id = 'a1'")
            self.assertNotEqual(safety.build_manifest(src)["features"], before["features"])

            r = safety.restore_db(snap, src)
            self.assertTrue(r["integrity_ok"])
            self.assertEqual(safety.build_manifest(src), before)


# ---- strict postcondition validator --------------------------------------------------------
class ValidatorTests(unittest.TestCase):
    def _valid_db_and_pre(self, tmp):
        d = _db(tmp); _seed_valid(d)
        src = Path(tmp) / "d.sqlite3"
        return d, src, safety.build_manifest(src)

    def test_validator_passes_on_clean_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, src, pre = self._valid_db_and_pre(tmp)
            out = safety.validate_postconditions(src, pre)
            self.assertTrue(out["ok"], out["failures"])

    def _assert_fails(self, mutate, expect_contains):
        with tempfile.TemporaryDirectory() as tmp:
            d, src, pre = self._valid_db_and_pre(tmp)
            mutate(d)
            out = safety.validate_postconditions(src, pre)
            self.assertFalse(out["ok"])
            self.assertTrue(any(expect_contains in x for x in out["failures"]),
                            f"{expect_contains} not in {out['failures']}")

    def test_fails_on_tq_zero(self):
        self._assert_fails(lambda d: d.execute("UPDATE shots SET technical_quality=0 WHERE id='s2'"),
                           "technical_quality_zero")

    def test_fails_on_missing_embedding(self):
        self._assert_fails(
            lambda d: d.execute("UPDATE shot_features SET embedding=NULL WHERE shot_id='s2'"),
            "embeddings_populated")

    def test_fails_on_missing_feature_row(self):
        self._assert_fails(lambda d: d.execute("DELETE FROM shot_features WHERE shot_id='s3'"),
                           "shots_without_features")

    def test_fails_on_changed_boundary(self):
        self._assert_fails(
            lambda d: d.execute("UPDATE shots SET duration_frames=999 WHERE id='s2'"),
            "boundaries_unchanged")

    def test_fails_on_timeline_count_mismatch(self):
        self._assert_fails(lambda d: d.execute("DELETE FROM timeline_items WHERE id='it1'"),
                           "timeline_items")

    def test_fails_on_cross_project_mutation(self):
        self._assert_fails(
            lambda d: d.execute("UPDATE shot_features SET embedding=NULL WHERE shot_id='es1'"),
            "elenora_embeddings_unchanged")

    def test_fails_on_unresolved_active_job(self):
        self._assert_fails(lambda d: _job(d, "jx", P15, "running"), "no_active_or_orphan_job")


# ---- real-media force fixture --------------------------------------------------------------
class RealForceFixtureTests(unittest.TestCase):
    def test_supported_trigger_recomputes_existing_features_without_predelete(self):
        d = json.loads((FIX / "p6_11_realforce.json").read_text())
        self.assertEqual(d["features_present_before"], 16)   # features existed
        self.assertEqual(d["feature_deletes_before_store"], 0)  # NO pre-delete
        self.assertEqual(d["embeddings_before"], 0)
        self.assertEqual(d["embeddings_after"], 16)
        self.assertEqual(d["embedding_dims"], [512])
        self.assertEqual(d["tq_zero_before"], 16)
        self.assertEqual(d["tq_zero_after"], 0)
        self.assertTrue(d["shot_ids_stable"])
        self.assertTrue(d["prod_checksum_unchanged"])


if __name__ == "__main__":
    unittest.main()
