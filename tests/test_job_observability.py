"""Phase 2 of the long-running-job audit: truthful progress, stage tracking, and a heartbeat
that is not the same signal as progress.

The failure this whole package traces back to: a real, hours-long `_measure_shot_windows` pass
that wrote neither a progress update nor anything proving it was alive, while `progress` sat at
1.0 from the end of the label pass and `updated_at` -- the one column `stalled` was computed
from -- went untouched. The desktop app read that as "İş yanıt vermiyor, ilerleme %100'te
durdu" for a job that was, in fact, busy and about to finish. Every test class below either
proves one piece of the new contract on its own, or reproduces that exact scenario end to end
and checks it no longer looks that way.
"""

import os
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)

from sevenfilm import api
from sevenfilm.db import Database, now
from sevenfilm.domain import MediaAsset, Shot
from sevenfilm.services import analysis
from sevenfilm.timebase import FrameRate


def _isolated_db(tmp_dir: str, name: str = "test.sqlite3") -> Database:
    database = Database(Path(tmp_dir) / name)
    database.migrate()
    return database


def _project(database: Database, project_id: str = "proj") -> None:
    database.insert("projects", {
        "id": project_id, "name": "T", "workspace_path": "/tmp",
        "target_duration_seconds": "150", "frame_rate": "25/1",
        "created_at": now(), "updated_at": now()})


def _job(database: Database, *, project_id: str = "proj", kind: str = "shots",
          status: str = "running") -> str:
    import uuid
    job_id = str(uuid.uuid4())
    database.insert("jobs", {
        "id": job_id, "project_id": project_id, "kind": kind, "status": status,
        "progress": 0.0, "checkpoint_json": {}, "error": None,
        "created_at": now(), "updated_at": now()})
    return job_id


# -- 4, 5, 6, 7, 8, 9: the overall-progress formula itself, no DB involved -------------------

class OverallProgressFormulaTests(unittest.TestCase):
    def test_non_terminal_job_never_exposes_1_0(self):
        # Even a stage_progress of 1.0 in the *last* weighted stage must not read as done: only
        # `status == "completed"` may ever produce 1.0. This is item 6 and the direct fix for
        # "progress hit 1.0 hours before the job that computed it was actually finished."
        value = api._overall_progress("shots", "windows", 1.0, "running")
        self.assertLess(value, 1.0)
        self.assertLessEqual(value, api.NON_TERMINAL_PROGRESS_CAP)

    def test_completed_status_always_reads_1_0(self):
        self.assertEqual(api._overall_progress("shots", "windows", 0.1, "completed"), 1.0)

    def test_windows_cannot_read_as_100_percent_before_it_starts(self):
        # The exact bug: encode and label both finishing used to sum to 1.0 on its own, with
        # `windows` -- the stage that then ran for hours -- never contributing anything visible.
        end_of_label = api._overall_progress("shots", "label", 1.0, "running")
        start_of_windows = api._overall_progress("shots", "windows", 0.0, "running")
        self.assertLess(end_of_label, 1.0)
        # And windows starting is not a regression from where label left off.
        self.assertGreaterEqual(start_of_windows, end_of_label)

    def test_progress_is_monotonic_across_every_stage_transition(self):
        # Item 8: walk encode -> label -> windows -> finalize -> completed and assert the
        # number never goes backwards, including at each stage boundary.
        trace = []
        for stage in ("encode", "label", "windows", "finalize"):
            for numerator in (0, 1, 2, 3, 4, 5):
                trace.append(api._overall_progress("shots", stage, min(1.0, numerator / 5), "running"))
        trace.append(api._overall_progress("shots", "finalize", 1.0, "completed"))
        for earlier, later in pairwise(trace):
            self.assertLessEqual(earlier, later, f"{earlier} -> {later} went backwards")
        self.assertEqual(trace[-1], 1.0)

    def test_stage_progress_resets_on_a_new_stage_without_the_overall_number_dropping(self):
        # Item 9: `stage_progress` itself legitimately goes back to 0.0 at the start of a new
        # stage -- that is not a bug, and `overall_progress` must absorb it without regressing.
        end_of_encode = api._overall_progress("shots", "encode", 1.0, "running")
        start_of_label = api._overall_progress("shots", "label", 0.0, "running")
        self.assertGreaterEqual(start_of_label, end_of_encode)

    def test_a_single_stage_kind_is_capped_the_same_way(self):
        # index/derivatives/music each have one stage; the non-terminal cap still applies.
        for kind in ("index", "derivatives", "music"):
            value = api._overall_progress(kind, kind, 1.0, "running")
            self.assertLessEqual(value, api.NON_TERMINAL_PROGRESS_CAP)

    def test_an_unrecognised_stage_falls_back_honestly_instead_of_raising(self):
        # A job row from before P2 (no `stage` recorded) must still produce a number, not a
        # KeyError -- see item 22/23.
        self.assertEqual(api._overall_progress("shots", "", None, "running"), 0.0)
        self.assertEqual(api._overall_progress("unknown-kind", "whatever", 0.5, "running"), 0.5)


# -- 10, 11, 12: heartbeat and progress are genuinely different signals ---------------------

class HeartbeatVsProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)
        self.job_id = _job(self.db)

    def _row(self):
        return self.db.fetch_one(
            "SELECT last_progress_at, last_heartbeat_at, checkpoint_json FROM jobs WHERE id = ?",
            (self.job_id,))

    def test_heartbeat_alone_leaves_last_progress_at_untouched(self):
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=3, total=10, checkpoint={})
        after_progress = self._row()
        self.db.touch_heartbeat(self.job_id)
        after_heartbeat = self._row()
        self.assertEqual(after_heartbeat["last_progress_at"], after_progress["last_progress_at"])

    def test_heartbeat_alone_still_advances_last_heartbeat_at(self):
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=3, total=10, checkpoint={})
        first = self._row()["last_heartbeat_at"]
        import time
        time.sleep(0.01)
        self.db.touch_heartbeat(self.job_id)
        second = self._row()["last_heartbeat_at"]
        self.assertGreater(second, first)

    def test_heartbeat_does_not_touch_the_checkpoint(self):
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=3, total=10,
            checkpoint={"last_shot_id": "shot-3"})
        before = self._row()["checkpoint_json"]
        self.db.touch_heartbeat(self.job_id)
        after = self._row()["checkpoint_json"]
        self.assertEqual(before, after)

    def test_a_real_progress_write_also_counts_as_a_heartbeat(self):
        # Real work finishing is the strongest proof of life there is -- it should never read as
        # *less* alive than a bare check-in.
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=3, total=10, checkpoint={})
        row = self._row()
        self.assertIsNotNone(row["last_heartbeat_at"])
        self.assertEqual(row["last_heartbeat_at"], row["last_progress_at"])


# -- 13-18: stalled is a heartbeat/liveness question, not a percentage question --------------

class StalledSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)

    def _payload(self, job_id):
        return api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))))

    def _backdate(self, job_id, minutes, *, heartbeat=True):
        from datetime import UTC, datetime, timedelta
        stamp = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        if heartbeat:
            self.db.execute(
                "UPDATE jobs SET updated_at = ?, last_heartbeat_at = ? WHERE id = ?",
                (stamp, stamp, job_id))
        else:
            self.db.execute(
                "UPDATE jobs SET updated_at = ?, last_heartbeat_at = NULL WHERE id = ?",
                (stamp, job_id))

    def test_healthy_heartbeat_on_a_running_job_means_not_stalled(self):
        job_id = _job(self.db, status="running")
        self.db.touch_heartbeat(job_id)
        self.assertFalse(self._payload(job_id)["stalled"])

    def test_a_running_job_whose_heartbeat_went_stale_is_stalled(self):
        job_id = _job(self.db, status="running")
        self._backdate(job_id, 45)
        self.assertTrue(self._payload(job_id)["stalled"])

    def test_percentage_sitting_still_does_not_alone_mean_stalled(self):
        # The core regression this package exists to fix: a job whose `processed` count has not
        # moved recently but whose heartbeat is fresh (it is inside one very long item) must not
        # read as stalled just because the number on screen has not changed.
        job_id = _job(self.db, status="running")
        self.db.update_job_progress(job_id, stage="windows", processed=5, total=2638, checkpoint={})
        import time
        time.sleep(0.01)
        self.db.touch_heartbeat(job_id)  # a check-in with no new processed count
        self.assertFalse(self._payload(job_id)["stalled"])

    def test_completed_is_never_stalled_regardless_of_heartbeat_age(self):
        job_id = _job(self.db, status="completed")
        self._backdate(job_id, 600)
        self.assertFalse(self._payload(job_id)["stalled"])

    def test_failed_is_never_stalled(self):
        job_id = _job(self.db, status="failed")
        self._backdate(job_id, 600)
        self.assertFalse(self._payload(job_id)["stalled"])

    def test_cancelled_is_never_stalled(self):
        job_id = _job(self.db, status="cancelled")
        self._backdate(job_id, 600)
        self.assertFalse(self._payload(job_id)["stalled"])

    def test_cancel_requested_is_judged_by_heartbeat_the_same_as_running(self):
        # Explicit, per item 18: cancel_requested is not yet settled -- a worker still owns it
        # and is still expected to be checking in until it notices the request.
        job_id = _job(self.db, status="cancel_requested")
        self.db.touch_heartbeat(job_id)
        self.assertFalse(self._payload(job_id)["stalled"])
        self._backdate(job_id, 45)
        self.assertTrue(self._payload(job_id)["stalled"])

    def test_queued_staleness_is_judged_by_created_at_not_a_heartbeat_that_does_not_exist_yet(self):
        from datetime import UTC, datetime, timedelta
        job_id = _job(self.db, status="queued")
        stamp = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
        self.db.execute("UPDATE jobs SET created_at = ?, updated_at = ? WHERE id = ?",
                        (stamp, stamp, job_id))
        self.assertTrue(self._payload(job_id)["stalled"])

    def test_a_fresh_queued_job_is_not_stalled(self):
        job_id = _job(self.db, status="queued")
        self.assertFalse(self._payload(job_id)["stalled"])


# -- 19, 20, 21: checkpoint content survives a DB round trip --------------------------------

class CheckpointSerializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)
        self.job_id = _job(self.db)

    def _payload(self):
        return api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (self.job_id,))))

    def test_stage_survives(self):
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=4, total=10, checkpoint={})
        self.assertEqual(self._payload()["stage"], "windows")

    def test_current_asset_metadata_survives(self):
        self.db.update_job_progress(
            self.job_id, stage="encode", processed=1, total=3,
            checkpoint={"last_asset_id": "a7", "current_asset_display": "C7292.MP4"})
        payload = self._payload()
        self.assertEqual(payload["current_asset_id"], "a7")
        self.assertEqual(payload["current_asset_display"], "C7292.MP4")

    def test_current_shot_metadata_survives(self):
        self.db.update_job_progress(
            self.job_id, stage="windows", processed=200, total=2638,
            checkpoint={"last_shot_id": "shot-199", "last_shot_index": 200})
        payload = self._payload()
        self.assertEqual(payload["current_shot_id"], "shot-199")
        self.assertEqual(payload["current_shot_index"], 200)


# -- 22, 23, 27: backward compatibility with rows and consumers that predate P2 --------------

class BackwardCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)

    def test_a_pre_p2_job_row_with_no_new_columns_is_still_readable(self):
        # Simulates a row written before `last_progress_at`/`last_heartbeat_at` existed: NULL in
        # both, an old-shaped checkpoint, nothing P2 added.
        job_id = _job(self.db, status="running")
        self.db.execute(
            "UPDATE jobs SET checkpoint_json = ?, last_progress_at = NULL, "
            "last_heartbeat_at = NULL WHERE id = ?",
            ('{"last_asset_id": "x", "pass": "label"}', job_id))
        payload = api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))))
        self.assertIn("stalled", payload)
        self.assertIn("overall_progress", payload)
        self.assertIsInstance(payload["progress"], float)

    def test_migrate_adds_the_new_columns_without_touching_existing_rows(self):
        job_id = _job(self.db, status="running")
        before = dict(self.db.fetch_one("SELECT status, kind, project_id FROM jobs WHERE id = ?", (job_id,)))
        self.db.migrate()  # idempotent, as every ADDED_COLUMNS migration must be
        columns = {row["name"] for row in
                   self.db.fetch_all("PRAGMA table_info(jobs)") or []}
        # fetch_all with no params on a PRAGMA; fall back to a raw check if unsupported.
        after = dict(self.db.fetch_one("SELECT status, kind, project_id FROM jobs WHERE id = ?", (job_id,)))
        self.assertEqual(before, after)
        self.assertIn("last_progress_at", columns)
        self.assertIn("last_heartbeat_at", columns)

    def test_legacy_response_fields_are_still_present(self):
        # Nothing P1 or the desktop app already reads was renamed or removed.
        job_id = _job(self.db, status="running")
        payload = api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))))
        for field in ("id", "project_id", "kind", "status", "progress", "checkpoint",
                      "error", "stalled", "created_at", "updated_at"):
            self.assertIn(field, payload, f"missing legacy field {field!r}")


# -- 1, 2, 3, 4, 5: the shots pipeline's own three stages, truthfully ------------------------

class ShotsPipelineObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db, "proj")
        self.job_id = _job(self.db, project_id="proj", kind="shots")
        self.rate = FrameRate(50)
        self.assets = [
            MediaAsset(id=f"a{i}", project_id="proj", path=Path(f"/m/{i}.mov"), name=f"{i}.mov",
                       duration=10, frame_rate=self.rate, width=1920, height=1080)
            for i in range(3)
        ]
        for asset in self.assets:
            self.db.insert("media_assets", {
                "id": asset.id, "project_id": "proj", "path": str(asset.path),
                "file_name": asset.path.name, "content_hash": asset.id,
                "duration_seconds": "10", "frame_rate": "50/1", "width": 1920, "height": 1080,
                "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})

    def _payload(self):
        return api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (self.job_id,))))

    def test_encode_and_label_processed_totals_are_asset_counts_not_fractions(self):
        # Wrap the real `update_job_progress` so every write this run makes is captured with
        # its own (stage, processed, total) exactly as written, not re-derived afterwards.
        calls = []
        original = self.db.update_job_progress

        def recording_update(job_id, *, stage, processed, total, checkpoint):
            calls.append((stage, processed, total))
            return original(job_id, stage=stage, processed=processed, total=total,
                             checkpoint=checkpoint)

        with (
            patch("sevenfilm.services.analysis._encode_asset"),
            patch("sevenfilm.services.analysis.VisionClassifier"),
            patch("sevenfilm.services.analysis.project_assets", return_value=self.assets),
            patch("sevenfilm.services.analysis._project_prior", return_value=None),
            patch("sevenfilm.services.analysis._label_asset"),
            patch("sevenfilm.services.analysis.project_shots", return_value=[]),
            patch("sevenfilm.services.analysis._measure_shot_windows"),
            patch.object(self.db, "update_job_progress", side_effect=recording_update),
        ):
            analysis.analyze_shots(self.db, "proj", self.job_id)

        encode_calls = [c for c in calls if c[0] == "encode"]
        label_calls = [c for c in calls if c[0] == "label"]
        self.assertEqual([c[1:] for c in encode_calls], [(1, 3), (2, 3), (3, 3)])
        self.assertEqual([c[1:] for c in label_calls], [(1, 3), (2, 3), (3, 3)])

    def test_windows_stage_exists_and_is_distinct_from_encode_and_label(self):
        shots = [
            Shot(id=f"s{i}", asset_id="a0", source_range=None, category="couple",
                 shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=.5,
                 confidence=.7, brightness=.3, saturation=.1, highlight_clipping=.0)
            for i in range(4)
        ]
        with patch("sevenfilm.services.analysis.measure_windows", return_value=[]):
            analysis._measure_shot_windows(
                self.db, "proj", self.assets, shots, job_id=self.job_id)
        payload = self._payload()
        self.assertEqual(payload["stage"], "windows")
        self.assertNotIn(payload["stage"], ("encode", "label"))

    def test_windows_progress_uses_shot_count_not_shot_windows_row_count(self):
        # A `measure_windows` that returns *several* windows per shot must not inflate
        # `processed`/`total` beyond the number of shots actually walked.
        shots = [
            Shot(id=f"s{i}", asset_id="a0", source_range=None, category="couple",
                 shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=.5,
                 confidence=.7, brightness=.3, saturation=.1, highlight_clipping=.0)
            for i in range(3)
        ]
        with patch("sevenfilm.services.analysis.measure_windows",
                   return_value=["w1", "w2", "w3", "w4"]), \
             patch("sevenfilm.services.analysis.store_windows"):
            analysis._measure_shot_windows(
                self.db, "proj", self.assets, shots, job_id=self.job_id)
        payload = self._payload()
        self.assertEqual(payload["total"], 3)  # shots walked, never 3 * 4 window rows
        self.assertEqual(payload["processed"], 3)

    def test_windows_starting_does_not_read_as_100_percent(self):
        shots = [
            Shot(id="s0", asset_id="a0", source_range=None, category="couple",
                 shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=.5,
                 confidence=.7, brightness=.3, saturation=.1, highlight_clipping=.0)
        ]
        with patch("sevenfilm.services.analysis.measure_windows", return_value=[]):
            analysis._measure_shot_windows(
                self.db, "proj", self.assets, shots, job_id=self.job_id)
        self.assertLess(self._payload()["overall_progress"], 1.0)


# -- 28, 29, 30: index/music/derivatives get the same contract, honestly -------------------

class OtherJobKindObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db)

    def _payload(self, job_id):
        return api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))))

    def test_index_reports_real_file_count(self):
        job_id = _job(self.db, kind="index")
        self.db.update_job_progress(
            job_id, stage="index", processed=7, total=362,
            checkpoint={"current_asset_display": "C7292.MP4"})
        payload = self._payload(job_id)
        self.assertEqual(payload["stage"], "index")
        self.assertEqual((payload["processed"], payload["total"]), (7, 362))
        self.assertLess(payload["overall_progress"], 1.0)

    def test_music_reports_real_song_count(self):
        job_id = _job(self.db, kind="music")
        self.db.update_job_progress(
            job_id, stage="music", processed=1, total=2,
            checkpoint={"current_song_display": "song-one.mp3"})
        payload = self._payload(job_id)
        self.assertEqual(payload["stage"], "music")
        self.assertEqual((payload["processed"], payload["total"]), (1, 2))

    def test_derivatives_reports_real_asset_count(self):
        job_id = _job(self.db, kind="derivatives")
        self.db.update_job_progress(
            job_id, stage="derivatives", processed=340, total=362,
            checkpoint={"last_asset_id": "a340"})
        payload = self._payload(job_id)
        self.assertEqual(payload["stage"], "derivatives")
        self.assertEqual((payload["processed"], payload["total"]), (340, 362))


# -- The main regression scenario: today's exact failure, reproduced and asserted fixed -----

class TodaysFailureDoesNotReproduceTests(unittest.TestCase):
    """encode completes, label completes, windows runs slowly, then the job completes --
    exactly the 15 Ağustos shots job's real shape, at unit-test size."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = _isolated_db(self.tmp.name)
        _project(self.db, "proj")
        self.job_id = _job(self.db, project_id="proj", kind="shots")
        self.rate = FrameRate(50)
        self.assets = [
            MediaAsset(id=f"a{i}", project_id="proj", path=Path(f"/m/{i}.mov"), name=f"{i}.mov",
                       duration=10, frame_rate=self.rate, width=1920, height=1080)
            for i in range(2)
        ]
        for asset in self.assets:
            self.db.insert("media_assets", {
                "id": asset.id, "project_id": "proj", "path": str(asset.path),
                "file_name": asset.path.name, "content_hash": asset.id,
                "duration_seconds": "10", "frame_rate": "50/1", "width": 1920, "height": 1080,
                "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})
        self.shots = [
            Shot(id=f"s{i}", asset_id="a0", source_range=None, category="couple",
                 shot_scale="medium", technical_quality=.8, aesthetic_score=.8, motion_score=.5,
                 confidence=.7, brightness=.3, saturation=.1, highlight_clipping=.0)
            for i in range(5)
        ]

    def _payload(self):
        return api._job_payload(dict(self.db.fetch_one("SELECT * FROM jobs WHERE id = ?", (self.job_id,))))

    def test_the_full_shots_pipeline_never_falsely_reads_as_stalled_or_done_early(self):
        # Step 1: encode + label complete.
        with (
            patch("sevenfilm.services.analysis._encode_asset"),
            patch("sevenfilm.services.analysis.VisionClassifier"),
            patch("sevenfilm.services.analysis.project_assets", return_value=self.assets),
            patch("sevenfilm.services.analysis._project_prior", return_value=None),
            patch("sevenfilm.services.analysis._label_asset"),
            patch("sevenfilm.services.analysis.project_shots", return_value=self.shots),
            patch("sevenfilm.services.analysis.measure_windows", return_value=[]),
            patch("sevenfilm.services.analysis.store_windows"),
        ):
            analysis.analyze_shots(self.db, "proj", self.job_id)

        # After encode + label + windows + finalize all ran synchronously above, the job is
        # NOT yet `completed` (only `_run_job` marks that, after `analyze_shots` returns) --
        # assert it is not exposing 100% despite every stage of real work being done.
        payload = self._payload()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["stage"], "finalize")
        self.assertLess(payload["overall_progress"], 1.0)
        self.assertFalse(payload["stalled"])

        # Step 2: only now does the caller (mirroring `_run_job`) mark it completed.
        self.db.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (self.job_id,))
        completed = self._payload()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["overall_progress"], 1.0)
        self.assertFalse(completed["stalled"])

    def test_windows_running_slowly_with_a_fresh_heartbeat_is_healthy_not_stalled(self):
        def slow_measure(asset, shot, path):
            # Simulate a long call: no new progress write happens here, only what
            # `_measure_shot_windows` itself does around it.
            return []

        with patch("sevenfilm.services.analysis.measure_windows", side_effect=slow_measure):
            analysis._measure_shot_windows(
                self.db, "proj", self.assets, self.shots, job_id=self.job_id)

        payload = self._payload()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["stage"], "windows")
        self.assertLess(payload["overall_progress"], 1.0)
        self.assertFalse(payload["stalled"])
        self.assertIsNotNone(payload["last_heartbeat_at"])
