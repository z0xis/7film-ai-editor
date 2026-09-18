"""P6.10 -- Bounded-memory large-asset encode.

Two kinds of test:
  * pure unit tests that exercise the chunked `_encode_asset` on a fresh temp DB with a fake
    classifier and injected frames (no real media) -- these prove the chunking behaviour, raw-frame
    release, asset-level atomicity, and empty-frame handling deterministically and fast;
  * fixture assertions that lock the recorded outcomes of tools/p6_10_bounded_encode_probe.py
    (real-media equivalence, DJI_0528 regression, DJI_0530 closure).
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from sevenfilm.db import Database, now
from sevenfilm.services import analysis as analysis_module
from sevenfilm.services.vision import FrameMetrics

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tools/fixtures"


def _metrics(q=0.5):
    return FrameMetrics(q, 0.4, "h", 0, 0.0, 0.0, 0.5, 0.5, 0.0, 0.3, 0.3)


class _RecordingClassifier:
    def __init__(self):
        self.encode_calls = 0
        self.batch_sizes = []

    def encode(self, frames):
        self.encode_calls += 1
        self.batch_sizes.append(len(frames))
        # Deterministic per-frame vector so batch composition cannot change the result.
        return np.stack([np.full(4, float(f.reshape(-1)[0]), dtype=np.float32) for f in frames])

    def _fallback(self, metrics):
        return {"category": "venue", "shot_scale": "wide", "aesthetic_score": metrics.technical_quality,
                "confidence": 0.25, "labels": ("venue",)}

    def classify_features(self, encoded, metrics, priors):
        return []


def _seed(db, asset_id, n_shots):
    db.insert("projects", {"id": "p", "name": "x", "workspace_path": "/t", "target_duration_seconds": "1",
                           "frame_rate": "25/1", "created_at": now(), "updated_at": now()})
    db.insert("media_assets", {"id": asset_id, "project_id": "p", "path": "/m/a.mp4", "file_name": "a.mp4",
                               "content_hash": None, "duration_seconds": "20", "frame_rate": "25/1",
                               "width": 1920, "height": 1080, "codec": "h264", "timecode": None,
                               "proxy_path": None, "thumbnail_path": None, "metadata_json": {},
                               "created_at": now()})
    rows = [{"id": f"s{i}", "asset_id": asset_id, "start_frame": i * 100, "duration_frames": 100,
             "frame_rate": "25/1", "category": "venue", "shot_scale": "wide", "technical_quality": 0.0,
             "aesthetic_score": 0.0, "motion_score": 0.0, "confidence": 0.0, "duplicate_group": "g",
             "labels_json": ["venue"], "analysis_version": "seed", "brightness": 0.0, "saturation": 0.0,
             "highlight_clipping": 0.0, "face_ratio": 0.0, "face_edge": 0.0, "created_at": now()}
            for i in range(n_shots)]
    db.replace_rows("shots", "asset_id", asset_id, rows)
    db.execute("DELETE FROM shot_features WHERE asset_id = ?", (asset_id,))


class ChunkedEncodeUnitTests(unittest.TestCase):
    def _patch_frames(self, per_shot_frames):
        # Returns a generator-compatible stand-in for _shot_frame_groups.
        def fake(asset, ranges):
            yield from per_shot_frames
        return fake

    def test_encode_flushes_in_bounded_chunks_for_a_large_asset(self):
        n = 70  # > 2 * chunk (32) -> at least 3 flushes
        frames_per_shot = [[np.full((4, 4, 3), i + 1, np.uint8)] for i in range(n)]
        clf = _RecordingClassifier()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(analysis_module, "_shot_frame_groups",
                                           self._patch_frames(frames_per_shot)), \
                mock.patch.object(analysis_module, "measure_frames", lambda f: _metrics()):
            db = Database(Path(tmp) / "d.sqlite3"); db.migrate(); _seed(db, "A", n)
            analysis_module._encode_asset(db, clf, SimpleNamespace(id="A"))
            feats = db.fetch_all("SELECT shot_id, embedding FROM shot_features WHERE asset_id='A'")
        self.assertEqual(len(feats), n)
        self.assertTrue(all(f["embedding"] is not None for f in feats))
        # Bounded: no single CLIP batch exceeds the chunk size, and it took multiple flushes.
        self.assertGreaterEqual(clf.encode_calls, 3)
        self.assertLessEqual(max(clf.batch_sizes), analysis_module._ENCODE_CHUNK_SHOTS)

    def test_small_asset_still_uses_a_single_encode_call(self):
        frames_per_shot = [[np.full((4, 4, 3), 7, np.uint8)] for _ in range(3)]
        clf = _RecordingClassifier()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(analysis_module, "_shot_frame_groups",
                                           self._patch_frames(frames_per_shot)), \
                mock.patch.object(analysis_module, "measure_frames", lambda f: _metrics()):
            db = Database(Path(tmp) / "d.sqlite3"); db.migrate(); _seed(db, "A", 3)
            analysis_module._encode_asset(db, clf, SimpleNamespace(id="A"))
        self.assertEqual(clf.encode_calls, 1)

    def test_unreadable_frames_persist_a_row_without_an_embedding(self):
        frames_per_shot = [[], []]  # both shots decode nothing
        clf = _RecordingClassifier()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(analysis_module, "_shot_frame_groups",
                                           self._patch_frames(frames_per_shot)), \
                mock.patch.object(analysis_module, "measure_frames", lambda f: _metrics(0.0)):
            db = Database(Path(tmp) / "d.sqlite3"); db.migrate(); _seed(db, "A", 2)
            analysis_module._encode_asset(db, clf, SimpleNamespace(id="A"))
            feats = db.fetch_all("SELECT embedding FROM shot_features WHERE asset_id='A'")
        self.assertEqual(len(feats), 2)
        self.assertTrue(all(f["embedding"] is None for f in feats))
        self.assertEqual(clf.encode_calls, 0)  # never called with an empty batch

    def test_failure_mid_encode_persists_no_partial_features(self):
        n = 70
        frames_per_shot = [[np.full((4, 4, 3), i + 1, np.uint8)] for i in range(n)]

        class Boom(_RecordingClassifier):
            def encode(self, frames):
                super().encode(frames)
                if self.encode_calls >= 2:  # fail on the second chunk
                    raise RuntimeError("injected encode failure")
                return np.stack([np.full(4, 1.0, np.float32) for _ in frames])

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(analysis_module, "_shot_frame_groups",
                                           self._patch_frames(frames_per_shot)), \
                mock.patch.object(analysis_module, "measure_frames", lambda f: _metrics()):
            db = Database(Path(tmp) / "d.sqlite3"); db.migrate(); _seed(db, "A", n)
            with self.assertRaises(RuntimeError):
                analysis_module._encode_asset(db, Boom(), SimpleNamespace(id="A"))
            feats = db.fetch_all("SELECT shot_id FROM shot_features WHERE asset_id='A'")
        # _store_features runs only after all chunks succeed, so a mid-encode failure writes nothing.
        self.assertEqual(feats, [])


class FixtureTests(unittest.TestCase):
    def test_gate_b_clip_batch_vs_chunk_equivalent(self):
        d = json.loads((FIX / "p6_10_equivalence.json").read_text())["clip_batch_vs_chunk"]
        self.assertEqual(d["dim"], 512)
        self.assertGreaterEqual(d["min_cosine"], 0.9999)

    def test_gate_b_feature_rows_equivalent_legacy_vs_chunked(self):
        fe = json.loads((FIX / "p6_10_equivalence.json").read_text())["feature_equivalence"]
        for name, a in fe.items():
            self.assertTrue(a["same_shot_ids"], name)
            self.assertTrue(a["metrics_exact"], name)
            self.assertTrue(a["tq_exact"], name)
            self.assertGreaterEqual(a["embedding_min_cosine"], 0.9999, name)

    def test_dji_0528_regression_restores_under_chunked_path(self):
        d = json.loads((FIX / "p6_10_dji_0528.json").read_text())
        self.assertEqual(d["shots_after"], 280)
        self.assertTrue(d["shot_ids_stable"])
        self.assertEqual(d["tq_zero_after"], 0)
        self.assertEqual(d["embeddings_populated"], 280)
        self.assertEqual(d["embedding_dims"], [512])

    def test_gate_c_d_dji_0530_completes_and_restores(self):
        d = json.loads((FIX / "p6_10_dji_0530.json").read_text())
        self.assertTrue(d["completed"])
        self.assertEqual(d["shots_after"], 501)
        self.assertTrue(d["shot_ids_stable"])
        self.assertEqual(d["embeddings_populated"], 501)
        self.assertEqual(d["embedding_dims"], [512])
        self.assertEqual(d["tq_zero_after"], 0)
        # The gate is COMPLETION: the legacy materialise-everything path needed ~37 GB (501 x 3
        # x 4K frames) and was signal-killed; the chunked path completes with peak RSS dominated
        # by the fixed CLIP/torch/MPS footprint, not by asset-wide frame retention. Assert a sane
        # ceiling that proves the catastrophic O(shots x frame) blow-up is gone -- not an arbitrary
        # tight target (see probe section 16).
        self.assertLess(d["peak_rss_gb"], 8.0)

    def test_gate_e_f_g_full_362_asset_remediation_closes(self):
        d = json.loads((FIX / "p6_10_full.json").read_text())
        # GATE E: whole population completes.
        self.assertEqual(d["assets_completed"], 362)
        self.assertEqual(d["failures"], [])
        self.assertEqual(d["shots_after"], 2638)
        # GATE F: full feature restoration, no residual degraded population.
        self.assertEqual(d["tq_zero_after"], 0)
        self.assertEqual(d["embeddings_populated"], 2638)
        self.assertEqual(d["embedding_null_after"], 0)
        self.assertEqual(d["shots_without_features"], 0)
        # GATE G: ids + timeline safe.
        self.assertEqual(d["assets_id_stable"], 362)
        self.assertEqual(d["shots_before"], d["shots_after"])
        self.assertEqual(d["timeline_items_after"], 129)
        self.assertEqual(d["timeline_resolved_after"], 129)


if __name__ == "__main__":
    unittest.main()
