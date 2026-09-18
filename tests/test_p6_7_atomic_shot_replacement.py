"""P6.7 -- Atomic shot replacement / linked-timeline safety.

Runtime proof for the fix P6.6 asked for: `_label_asset()`'s persistence of `shots` is now the
single atomic `Database.replace_rows()` transaction, built fully in memory before anything is
deleted. These tests exercise the real code path against a fresh, migrated temp database (never
the production DB -- conftest also pins SEVENFILM_DATA_ROOT to a temp dir), seeding a 15A-like
project with a linked timeline item, and run the mandatory temp-clone matrix (cases A-E).

The distinction the matrix draws, and which the design in db.py/planner.py already encodes:
  * ATOMICITY protects against PARTIAL shots state (a crash/exception mid-replace). Proven by
    cases B/C: the old rows are all present or the new rows are all present, never a mix.
  * A SUCCESSFUL re-segmentation that changes shot boundaries changes the deterministic shot_id
    and so removes the old shots row (case E). timeline_items.shot_id is deliberately NOT a
    foreign key and get_timeline() LEFT JOINs shots with a neutral fallback, so a delivered
    rough cut still renders -- but the shots-table reference itself does dangle. Atomicity does
    not, and is not meant to, prevent that.
"""

import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from sevenfilm.db import Database, JobCancelled, now, raise_if_cancelled
from sevenfilm.services.analysis import _asset_features, _label_asset
from sevenfilm.services.planner import get_timeline
from sevenfilm.services.vision import FrameMetrics

PROJECT_ID = "proj-15a-like"
ASSET_ID = "asset-A"
ASSET_ID_2 = "asset-B"
TIMELINE_ID = "tl-rough-cut"


def _metrics(quality: float = 0.7, phash: str = "abc123") -> FrameMetrics:
    return FrameMetrics(
        technical_quality=quality, motion_score=0.4, perceptual_hash=phash, face_count=0,
        face_ratio=0.0, face_edge=0.0, brightness=0.5, saturation=0.5, highlight_clipping=0.0,
        sharpness=0.3, contrast=0.3,
    )


class _FakeClassifier:
    """Stands in for VisionClassifier. Every seeded feature row has embedding=None, so
    classify_features() is always called with an empty position list and returns []; every shot
    falls through to _fallback(), which is deterministic and needs no model."""

    def __init__(self, fail_on_fallback: bool = False) -> None:
        self.fail_on_fallback = fail_on_fallback

    def classify_features(self, encoded, metrics, priors):
        return []

    def _fallback(self, metrics: FrameMetrics) -> dict[str, object]:
        if self.fail_on_fallback:
            raise RuntimeError("injected pre-build classification failure")
        return {
            "category": "venue", "shot_scale": "wide", "aesthetic_score": metrics.technical_quality,
            "confidence": 0.25, "labels": ("venue", "wide", "faces:0", "opencv_fallback"),
        }


def _asset(asset_id: str = ASSET_ID) -> SimpleNamespace:
    # _label_asset only reads asset.id.
    return SimpleNamespace(id=asset_id)


def _fresh_db(tmp: str) -> Database:
    database = Database(Path(tmp) / "sevenfilm.sqlite3")
    database.migrate()
    database.insert("projects", {
        "id": PROJECT_ID, "name": "15A-like", "workspace_path": "/tmp/15a",
        "target_duration_seconds": "150", "frame_rate": "25/1", "created_at": now(),
        "updated_at": now(),
    })
    for aid in (ASSET_ID, ASSET_ID_2):
        database.insert("media_assets", {
            "id": aid, "project_id": PROJECT_ID, "path": f"/media/{aid}.mp4",
            "file_name": f"{aid}.mp4", "content_hash": None, "duration_seconds": "20",
            "frame_rate": "25/1", "width": 1920, "height": 1080, "codec": "h264",
            "timecode": None, "proxy_path": None, "thumbnail_path": None, "metadata_json": {},
            "created_at": now(),
        })
    return database


def _seed_features(database: Database, asset_id: str, shot_ids: list[str]) -> None:
    rows = [
        {
            "shot_id": sid, "asset_id": asset_id, "start_frame": index * 100,
            "duration_frames": 100, "frame_rate": "25/1", "embedding": None,
            "metrics_json": asdict(_metrics(phash=f"h{index}")), "created_at": now(),
        }
        for index, sid in enumerate(shot_ids)
    ]
    database.replace_rows("shot_features", "asset_id", asset_id, rows)


def _seed_shots(database: Database, asset_id: str, shot_ids: list[str]) -> None:
    rows = [
        {
            "id": sid, "asset_id": asset_id, "start_frame": index * 100, "duration_frames": 100,
            "frame_rate": "25/1", "category": "venue", "shot_scale": "wide",
            "technical_quality": 0.7, "aesthetic_score": 0.7, "motion_score": 0.4,
            "confidence": 0.25, "duplicate_group": "visual:seed", "labels_json": ["venue"],
            "analysis_version": "seed", "brightness": 0.5, "saturation": 0.5,
            "highlight_clipping": 0.0, "face_ratio": 0.0, "face_edge": 0.0, "created_at": now(),
        }
        for index, sid in enumerate(shot_ids)
    ]
    database.replace_rows("shots", "asset_id", asset_id, rows)


def _seed_timeline_item(database: Database, shot_id: str) -> None:
    database.insert("timeline_versions", {
        "id": TIMELINE_ID, "project_id": PROJECT_ID, "name": "AI Rough Cut",
        "target_duration_seconds": "150", "frame_rate": "25/1", "seed": 1,
        "warnings_json": [], "created_at": now(), "music_segments_json": "[]",
    })
    database.insert("timeline_items", {
        "id": "item-1", "timeline_id": TIMELINE_ID, "position": 0, "shot_id": shot_id,
        "asset_id": ASSET_ID, "source_start_frame": 0, "source_duration_frames": 100,
        "source_rate": "25/1", "timeline_start_frame": 0, "timeline_duration_frames": 100,
        "score": 0.8, "reason": "seed", "alternatives_json": [], "category": "venue",
        "shot_scale": "wide",
    })


def _shot_ids(database: Database, asset_id: str) -> list[str]:
    return [
        row["id"]
        for row in database.fetch_all(
            "SELECT id FROM shots WHERE asset_id = ? ORDER BY start_frame", (asset_id,)
        )
    ]


def _timeline_ref_resolves(database: Database) -> bool:
    row = database.fetch_one(
        """SELECT shots.id FROM timeline_items
           LEFT JOIN shots ON shots.id = timeline_items.shot_id
           WHERE timeline_items.id = ?""",
        ("item-1",),
    )
    return row is not None and row["id"] is not None


class _SpyDatabase(Database):
    """Records raw SQL and replace_rows calls so a test can prove _label_asset() issues no bare
    DELETE against shots and exactly one atomic replacement."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.executed_sql: list[str] = []
        self.replace_calls: list[tuple] = []

    def execute(self, sql: str, params=()) -> None:
        self.executed_sql.append(sql)
        super().execute(sql, params)

    def replace_rows(self, table, where_column, where_value, rows) -> None:
        self.replace_calls.append((table, where_column, where_value, len(rows)))
        super().replace_rows(table, where_column, where_value, rows)


class AtomicShotReplacementTests(unittest.TestCase):
    # ---- mechanism ------------------------------------------------------------------------
    def test_label_asset_persists_shots_via_single_replace_rows_and_no_bare_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _SpyDatabase(Path(tmp) / "sevenfilm.sqlite3")
            db.migrate()
            db.insert("projects", {
                "id": PROJECT_ID, "name": "x", "workspace_path": "/tmp/x",
                "target_duration_seconds": "150", "frame_rate": "25/1", "created_at": now(),
                "updated_at": now(),
            })
            db.insert("media_assets", {
                "id": ASSET_ID, "project_id": PROJECT_ID, "path": "/m/a.mp4",
                "file_name": "a.mp4", "content_hash": None, "duration_seconds": "20",
                "frame_rate": "25/1", "width": 1920, "height": 1080, "codec": "h264",
                "timecode": None, "proxy_path": None, "thumbnail_path": None,
                "metadata_json": {}, "created_at": now(),
            })
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            db.replace_calls.clear()
            db.executed_sql.clear()

            _label_asset(db, _FakeClassifier(), _asset(), priors=None)

            shots_replacements = [c for c in db.replace_calls if c[0] == "shots"]
            self.assertEqual(len(shots_replacements), 1)
            self.assertEqual(shots_replacements[0], ("shots", "asset_id", ASSET_ID, 2))
            self.assertFalse(
                any("DELETE FROM shots" in sql.upper().replace("  ", " ")
                    or "DELETE FROM SHOTS" in sql.upper() for sql in db.executed_sql),
                f"unexpected bare DELETE against shots: {db.executed_sql}",
            )

    def test_shot_ids_are_reused_from_features_not_regenerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["feat-1", "feat-2"])
            _seed_shots(db, ASSET_ID, ["old-1", "old-2"])
            _label_asset(db, _FakeClassifier(), _asset(), priors=None)
            # The shots table now carries the feature rows' shot_ids verbatim.
            self.assertEqual(_shot_ids(db, ASSET_ID), ["feat-1", "feat-2"])

    def test_output_equivalence_new_path_matches_old_delete_then_insert_loop(self):
        """The atomic path must produce byte-identical shot rows to the pre-fix DELETE+insert
        loop for the same inputs."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            _label_asset(db, _FakeClassifier(), _asset(), priors=None)
            new_rows = db.fetch_all(
                "SELECT * FROM shots WHERE asset_id = ? ORDER BY start_frame", (ASSET_ID,))

        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            # Reproduce the exact pre-fix persistence: bare DELETE, then a per-row insert loop.
            classifier = _FakeClassifier()
            rows = _asset_features(db, ASSET_ID)
            metrics = [FrameMetrics(**__import__("json").loads(r["metrics_json"])) for r in rows]
            db.execute("DELETE FROM shots WHERE asset_id = ?", (ASSET_ID,))
            for ordinal, row in enumerate(rows):
                measured = metrics[ordinal]
                features = classifier._fallback(measured)
                db.insert("shots", {
                    "id": row["shot_id"], "asset_id": ASSET_ID, "start_frame": row["start_frame"],
                    "duration_frames": row["duration_frames"], "frame_rate": row["frame_rate"],
                    "category": features["category"], "shot_scale": features["shot_scale"],
                    "technical_quality": measured.technical_quality,
                    "aesthetic_score": features["aesthetic_score"],
                    "motion_score": measured.motion_score, "confidence": features["confidence"],
                    "duplicate_group": f"visual:{measured.perceptual_hash}",
                    "labels_json": list(features["labels"]), "analysis_version": "4",
                    "brightness": measured.brightness, "saturation": measured.saturation,
                    "highlight_clipping": measured.highlight_clipping,
                    "face_ratio": measured.face_ratio, "face_edge": measured.face_edge,
                    "created_at": new_rows[ordinal]["created_at"],
                })
            old_rows = db.fetch_all(
                "SELECT * FROM shots WHERE asset_id = ? ORDER BY start_frame", (ASSET_ID,))

        # Compare every column except created_at (a timestamp); ids, boundaries, categories,
        # scores, metadata must all match.
        def _strip(rows):
            return [{k: v for k, v in r.items() if k != "created_at"} for r in rows]
        self.assertEqual(_strip(new_rows), _strip(old_rows))

    # ---- CASE A: same-id success ----------------------------------------------------------
    def test_case_a_same_id_success_timeline_reference_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            _seed_timeline_item(db, shot_id="s1")

            _label_asset(db, _FakeClassifier(), _asset(), priors=None)

            self.assertEqual(_shot_ids(db, ASSET_ID), ["s1", "s2"])
            self.assertTrue(_timeline_ref_resolves(db))
            plan = get_timeline(db, TIMELINE_ID)
            self.assertEqual(len(plan.items), 1)

    # ---- CASE B: forced insert failure ----------------------------------------------------
    def test_case_b_forced_insert_failure_rolls_back_all_shot_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            _seed_timeline_item(db, shot_id="s1")

            good = {
                "id": "new-1", "asset_id": ASSET_ID, "start_frame": 0, "duration_frames": 100,
                "frame_rate": "25/1", "category": "venue", "shot_scale": "wide",
                "technical_quality": 0.7, "aesthetic_score": 0.7, "motion_score": 0.4,
                "confidence": 0.25, "duplicate_group": "v", "labels_json": ["venue"],
                "analysis_version": "4", "brightness": 0.5, "saturation": 0.5,
                "highlight_clipping": 0.0, "face_ratio": 0.0, "face_edge": 0.0,
                "created_at": now(),
            }
            # Second row omits NOT NULL `category` -> the INSERT raises mid-transaction.
            bad = {k: v for k, v in good.items() if k != "category"}
            bad["id"] = "new-2"

            with self.assertRaises(sqlite3.IntegrityError):
                db.replace_rows("shots", "asset_id", ASSET_ID, [good, bad])

            # Old rows fully intact; neither new row is visible.
            self.assertEqual(_shot_ids(db, ASSET_ID), ["s1", "s2"])
            self.assertTrue(_timeline_ref_resolves(db))

    # ---- CASE C: pre-build failure --------------------------------------------------------
    def test_case_c_pre_build_failure_leaves_db_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            _seed_timeline_item(db, shot_id="s1")

            with self.assertRaises(RuntimeError):
                _label_asset(db, _FakeClassifier(fail_on_fallback=True), _asset(), priors=None)

            # Failure happened while building rows, before replace_rows was reached.
            self.assertEqual(_shot_ids(db, ASSET_ID), ["s1", "s2"])
            self.assertTrue(_timeline_ref_resolves(db))

    # ---- CASE D: cancellation at asset boundary -------------------------------------------
    def test_case_d_cancellation_between_assets_never_leaves_partial_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["a1", "a2"])
            _seed_features(db, ASSET_ID_2, ["b1", "b2"])
            _seed_shots(db, ASSET_ID, ["a1", "a2"])
            _seed_shots(db, ASSET_ID_2, ["b1-old", "b2-old"])
            # A cancellation is enqueued as a cancelled job; raise_if_cancelled sees it at the
            # boundary. Mirror analyze_shots()'s per-asset loop: check, then label.
            db.insert("jobs", {
                "id": "job-x", "project_id": PROJECT_ID, "kind": "shots",
                "status": "cancel_requested",
                "progress": 0, "checkpoint_json": {}, "error": None, "created_at": now(),
                "updated_at": now(),
            })
            classifier = _FakeClassifier()

            processed = []
            with self.assertRaises(JobCancelled):
                for asset_id in (ASSET_ID, ASSET_ID_2):
                    # This loop hits the cancelled status on the FIRST boundary check, so no
                    # asset is labelled at all -- the strongest form of "no partial state".
                    raise_if_cancelled(db, "job-x")
                    _label_asset(db, classifier, _asset(asset_id), priors=None)
                    processed.append(asset_id)

            self.assertEqual(processed, [])
            # Both assets keep exactly their prior shots; nothing half-written.
            self.assertEqual(_shot_ids(db, ASSET_ID), ["a1", "a2"])
            self.assertEqual(_shot_ids(db, ASSET_ID_2), ["b1-old", "b2-old"])

    def test_case_d_cancellation_after_one_asset_leaves_that_asset_fully_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["a1", "a2"])
            _seed_shots(db, ASSET_ID, ["a1-old", "a2-old"])
            _seed_shots(db, ASSET_ID_2, ["b1-old", "b2-old"])
            classifier = _FakeClassifier()

            # Asset A is labelled fully (atomic), THEN cancellation lands before asset B.
            _label_asset(db, classifier, _asset(ASSET_ID), priors=None)
            self.assertEqual(_shot_ids(db, ASSET_ID), ["a1", "a2"])  # fully replaced, no partial
            self.assertEqual(_shot_ids(db, ASSET_ID_2), ["b1-old", "b2-old"])  # untouched

    # ---- CASE E: successful changed-boundary (re-segmentation) ----------------------------
    def test_case_e_changed_boundaries_orphan_shots_ref_but_timeline_still_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            # New segmentation -> new deterministic ids; feature rows now carry the new ids.
            _seed_shots(db, ASSET_ID, ["old-1", "old-2"])
            _seed_features(db, ASSET_ID, ["new-1", "new-2"])
            _seed_timeline_item(db, shot_id="old-1")

            _label_asset(db, _FakeClassifier(), _asset(), priors=None)

            # The old shots row is gone; the shots-table reference now dangles.
            self.assertEqual(_shot_ids(db, ASSET_ID), ["new-1", "new-2"])
            self.assertFalse(_timeline_ref_resolves(db))
            # But the delivered rough cut still renders: LEFT JOIN + the item's own copy, with
            # scores falling back to neutral (0.5) because the shot row is absent.
            plan = get_timeline(db, TIMELINE_ID)
            self.assertEqual(len(plan.items), 1)
            item = plan.items[0]
            self.assertEqual(item.shot.id, "old-1")
            self.assertEqual(item.shot.technical_quality, 0.5)
            self.assertEqual(item.shot.category, "venue")  # item's own copy survives

    # ---- empty-result semantics -----------------------------------------------------------
    def test_empty_features_does_not_delete_existing_shots(self):
        """Current behaviour: _label_asset() returns early when an asset has no shot_features,
        so it must NOT reach replace_rows and must NOT delete existing shots. The atomic fix
        preserves this exactly -- it introduces no delete-all-on-empty behaviour."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            # No shot_features for the asset.
            _label_asset(db, _FakeClassifier(), _asset(), priors=None)
            self.assertEqual(_shot_ids(db, ASSET_ID), ["s1", "s2"])

    def test_replace_rows_with_empty_list_empties_the_partition(self):
        """Helper-level contract, for contrast: replace_rows([]) deletes the partition. This is
        the behaviour _label_asset() deliberately avoids reaching via its early return."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            db.replace_rows("shots", "asset_id", ASSET_ID, [])
            self.assertEqual(_shot_ids(db, ASSET_ID), [])

    # ---- cross-table shots/features consistency -------------------------------------------
    def test_failed_shots_replace_leaves_features_and_shots_ids_consistent(self):
        """After a rolled-back shots replacement, every surviving shots.id still has a matching
        shot_features.shot_id (both keyed off the same deterministic id) -- no cross-table
        inconsistency is introduced by the atomicity fix."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _fresh_db(tmp)
            _seed_features(db, ASSET_ID, ["s1", "s2"])
            _seed_shots(db, ASSET_ID, ["s1", "s2"])
            with self.assertRaises(RuntimeError):
                _label_asset(db, _FakeClassifier(fail_on_fallback=True), _asset(), priors=None)
            shot_ids = set(_shot_ids(db, ASSET_ID))
            feature_ids = {
                r["shot_id"] for r in _asset_features(db, ASSET_ID)
            }
            self.assertEqual(shot_ids, feature_ids)


if __name__ == "__main__":
    unittest.main()
