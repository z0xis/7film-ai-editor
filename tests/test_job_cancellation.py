"""Cooperative cancellation, asset-level atomicity, duplicate-job rejection and orphan recovery.

Phase 1 of the long-running-job audit. Every test here either drives the real HTTP contract
(`TestClient`) or calls the pure functions in `sevenfilm.db` / `sevenfilm.services.analysis`
directly — nothing opens a video, calls OpenCV, or reaches the real project database this
session has been working with all day. `_encode_asset` and friends are monkeypatched where a
test needs to simulate "the worker got partway through and then X happened" without actually
decoding anything.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)

from fastapi.testclient import TestClient
from sevenfilm import api
from sevenfilm.db import (
    TERMINAL_STATUSES,
    VALID_JOB_TRANSITIONS,
    Database,
    DuplicateActiveJobError,
    JobCancelled,
    now,
    raise_if_cancelled,
    recover_orphaned_jobs,
)
from sevenfilm.services import analysis


class JobCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(_ROOT.cleanup)
        api.DATABASE.migrate()
        cls.client = TestClient(api.app)
        cls.workspace = Path(_ROOT.name)

    def _project(self, name: str) -> dict:
        response = self.client.post("/api/projects", json={
            "name": name, "workspace_path": str(self.workspace),
            "target_duration_seconds": "150", "frame_rate": "25/1"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _insert_job(self, project_id: str, kind: str, status: str, progress: float = 0.0,
                    checkpoint: dict | None = None) -> str:
        import uuid
        job_id = str(uuid.uuid4())
        api.DATABASE.insert("jobs", {
            "id": job_id, "project_id": project_id, "kind": kind, "status": status,
            "progress": progress, "checkpoint_json": checkpoint or {}, "error": None,
            "created_at": now(), "updated_at": now(),
        })
        return job_id

    def _status(self, job_id: str) -> str:
        return api.DATABASE.fetch_one("SELECT status FROM jobs WHERE id = ?", (job_id,))["status"]

    # -- cancel: every starting status ---------------------------------------------------

    def test_cancel_queued_job_settles_immediately(self):
        project = self._project("CancelQueued")
        job_id = self._insert_job(project["id"], "shots", "queued")
        response = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancelled")
        self.assertEqual(self._status(job_id), "cancelled")

    def test_cancel_running_job_requests_rather_than_forces(self):
        project = self._project("CancelRunning")
        job_id = self._insert_job(project["id"], "shots", "running", progress=0.24)
        response = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "cancel_requested")
        self.assertEqual(self._status(job_id), "cancel_requested")

    def test_cancel_requested_twice_is_idempotent(self):
        project = self._project("CancelTwiceRequested")
        job_id = self._insert_job(project["id"], "shots", "cancel_requested")
        first = self.client.post(f"/api/jobs/{job_id}/cancel")
        second = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "cancel_requested")

    def test_cancel_cancelled_twice_is_idempotent(self):
        project = self._project("CancelTwiceCancelled")
        job_id = self._insert_job(project["id"], "shots", "cancelled")
        first = self.client.post(f"/api/jobs/{job_id}/cancel")
        second = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(first.json()["status"], "cancelled")
        self.assertEqual(second.json()["status"], "cancelled")

    def test_cancel_completed_job_is_a_safe_no_op(self):
        project = self._project("CancelCompleted")
        job_id = self._insert_job(project["id"], "shots", "completed", progress=1.0)
        response = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(self._status(job_id), "completed")

    def test_cancel_failed_job_is_a_safe_no_op(self):
        project = self._project("CancelFailed")
        job_id = self._insert_job(project["id"], "shots", "failed", progress=0.1)
        response = self.client.post(f"/api/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "failed")

    def test_cancel_unknown_job_is_404(self):
        response = self.client.post("/api/jobs/not-a-real-job/cancel")
        self.assertEqual(response.status_code, 404)


class CancellationHasNoProjectParameterTests(unittest.TestCase):
    """The endpoint is job-id-only by design -- see the endpoint's own docstring."""

    def test_cancel_route_takes_no_project_id(self):
        import inspect
        signature = inspect.signature(api.cancel_job)
        self.assertEqual(list(signature.parameters), ["job_id"])

    def test_cancelling_one_projects_job_cannot_reach_another_projects_rows(self):
        api.DATABASE.migrate()
        client = TestClient(api.app)
        workspace = Path(_ROOT.name)
        project_a = client.post("/api/projects", json={
            "name": "IsolationA", "workspace_path": str(workspace),
            "target_duration_seconds": "150", "frame_rate": "25/1"}).json()
        project_b = client.post("/api/projects", json={
            "name": "IsolationB", "workspace_path": str(workspace),
            "target_duration_seconds": "150", "frame_rate": "25/1"}).json()
        import uuid
        job_b = str(uuid.uuid4())
        api.DATABASE.insert("jobs", {
            "id": job_b, "project_id": project_b["id"], "kind": "shots", "status": "running",
            "progress": 0.5, "checkpoint_json": {}, "error": None,
            "created_at": now(), "updated_at": now()})
        client.post(f"/api/jobs/{job_b}/cancel")
        row = api.DATABASE.fetch_one("SELECT project_id, status FROM jobs WHERE id = ?", (job_b,))
        self.assertEqual(row["project_id"], project_b["id"])
        self.assertEqual(row["status"], "cancel_requested")
        # project_a never appears in the cancel request itself; this checks it truly has no
        # jobs at all rather than trusting that by construction.
        a_jobs = api.DATABASE.fetch_all(
            "SELECT id FROM jobs WHERE project_id = ?", (project_a["id"],))
        self.assertEqual(a_jobs, [])


class DuplicateActiveJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.DATABASE.migrate()
        cls.client = TestClient(api.app)
        cls.workspace = Path(_ROOT.name)

    def _project(self, name: str) -> dict:
        return self.client.post("/api/projects", json={
            "name": name, "workspace_path": str(self.workspace),
            "target_duration_seconds": "150", "frame_rate": "25/1"}).json()

    def _insert_running_job(self, project_id: str, kind: str) -> str:
        # Inserted directly rather than through the HTTP endpoint: `TestClient` runs
        # `BackgroundTasks` synchronously as part of the POST itself, so a "shots" job with no
        # indexed assets would run for real, fail immediately, and be terminal (and so no
        # longer "active") before a second request could ever race it.
        import uuid
        job_id = str(uuid.uuid4())
        api.DATABASE.insert("jobs", {
            "id": job_id, "project_id": project_id, "kind": kind, "status": "running",
            "progress": 0.3, "checkpoint_json": {}, "error": None,
            "created_at": now(), "updated_at": now()})
        return job_id

    def test_second_active_shots_job_for_the_same_project_is_rejected(self):
        project = self._project("DupShots")
        self._insert_running_job(project["id"], "shots")
        second = self.client.post(f"/api/projects/{project['id']}/shots")
        self.assertEqual(second.status_code, 409, second.text)

    def test_a_terminal_old_job_does_not_block_a_new_one(self):
        project = self._project("TerminalThenNew")
        job_id = self._insert_running_job(project["id"], "shots")
        api.DATABASE.update_job(job_id, status="completed", progress=1.0)
        second = self.client.post(f"/api/projects/{project['id']}/shots")
        self.assertEqual(second.status_code, 202, second.text)

    def test_a_cancelled_old_job_does_not_block_a_new_one(self):
        project = self._project("CancelledThenNew")
        job_id = self._insert_running_job(project["id"], "shots")
        self.client.post(f"/api/jobs/{job_id}/cancel")  # running -> cancel_requested
        api.DATABASE.transition_job(
            job_id, "cancelled", from_statuses=frozenset({"cancel_requested"}))
        second = self.client.post(f"/api/projects/{project['id']}/shots")
        self.assertEqual(second.status_code, 202, second.text)

    def test_two_different_projects_each_get_their_own_active_shots_job(self):
        project_a = self._project("SeparateA")
        project_b = self._project("SeparateB")
        response_a = self.client.post(f"/api/projects/{project_a['id']}/shots")
        response_b = self.client.post(f"/api/projects/{project_b['id']}/shots")
        self.assertEqual(response_a.status_code, 202)
        self.assertEqual(response_b.status_code, 202)

    def test_different_kinds_in_the_same_project_do_not_collide(self):
        project = self._project("DifferentKinds")
        shots = self.client.post(f"/api/projects/{project['id']}/shots")
        derivatives = self.client.post(f"/api/projects/{project['id']}/derivatives")
        self.assertEqual(shots.status_code, 202)
        self.assertEqual(derivatives.status_code, 202)

    def test_the_unique_index_itself_rejects_a_second_insert_regardless_of_caller_timing(self):
        # The real race-safety guarantee lives in the database constraint, not in Python
        # sequencing two calls -- this proves the constraint raises on a straightforward second
        # attempt, which is what would also stop two truly concurrent requests.
        project = self._project("RaceProof")
        api.DATABASE.migrate()
        from sevenfilm.api import _create_job
        _create_job(project["id"], "shots", {})
        with self.assertRaises(DuplicateActiveJobError):
            _create_job(project["id"], "shots", {})


class WorkerCancellationTests(unittest.TestCase):
    """`raise_if_cancelled` and `_run_job`'s handling of it, without opening any media."""

    @classmethod
    def setUpClass(cls):
        api.DATABASE.migrate()

    def test_raise_if_cancelled_is_silent_when_not_requested(self):
        job_id = self._job("running")
        raise_if_cancelled(api.DATABASE, job_id)  # must not raise

    def test_raise_if_cancelled_raises_exactly_on_cancel_requested(self):
        job_id = self._job("cancel_requested")
        with self.assertRaises(JobCancelled):
            raise_if_cancelled(api.DATABASE, job_id)

    def test_raise_if_cancelled_is_silent_for_an_unknown_job(self):
        raise_if_cancelled(api.DATABASE, "no-such-job")  # must not raise

    def _job(self, status: str, project_id: str | None = None, kind: str = "shots") -> str:
        import uuid
        job_id = str(uuid.uuid4())
        # A fresh project_id per call: two jobs of the same kind for the same project cannot
        # both be "active" (queued/running/cancel_requested) under the unique index, and
        # several tests in this class each want their own isolated job regardless of status.
        project_id = project_id or f"p-{uuid.uuid4()}"
        api.DATABASE.execute(
            "INSERT INTO jobs (id, project_id, kind, status, progress, checkpoint_json, "
            "error, created_at, updated_at) VALUES (?, ?, ?, ?, 0, '{}', NULL, ?, ?)",
            (job_id, project_id, kind, status, now(), now()))
        return job_id

    def test_run_job_settles_a_cancellation_as_cancelled_not_failed(self):
        # Inserted directly as already-`running`, not through the HTTP endpoint: `TestClient`
        # runs `BackgroundTasks` synchronously inside the POST call, which would execute the
        # real (unmocked) `generate_derivatives` before this test's `patch` ever took effect.
        job_id = self._job("running", kind="derivatives")
        with patch("sevenfilm.api.generate_derivatives", side_effect=JobCancelled(job_id)):
            api._run_job(job_id)
        row = api.DATABASE.fetch_one("SELECT status, error FROM jobs WHERE id = ?", (job_id,))
        self.assertEqual(row["status"], "cancelled")
        self.assertIsNone(row["error"])

    def test_a_cancelled_job_can_never_reach_completed_afterwards(self):
        # `_run_job` finding a terminal job returns immediately rather than re-running it.
        job_id = self._job("cancelled", kind="derivatives")
        with patch("sevenfilm.api.generate_derivatives") as mocked:
            api._run_job(job_id)
        mocked.assert_not_called()
        self.assertEqual(self._current_status(job_id), "cancelled")

    def _current_status(self, job_id: str) -> str:
        return api.DATABASE.fetch_one("SELECT status FROM jobs WHERE id = ?", (job_id,))["status"]


class TransitionTableTests(unittest.TestCase):
    def test_terminal_states_have_no_outgoing_transitions(self):
        for status in TERMINAL_STATUSES:
            self.assertEqual(VALID_JOB_TRANSITIONS[status], frozenset())

    def test_cancel_requested_can_still_land_on_completed_or_failed(self):
        # A cancellation is a request observed at the next checkpoint, not a guaranteed stop:
        # the worker may finish or hit a real error first.
        self.assertIn("completed", VALID_JOB_TRANSITIONS["cancel_requested"])
        self.assertIn("failed", VALID_JOB_TRANSITIONS["cancel_requested"])

    def test_transition_job_only_applies_from_an_allowed_status(self):
        database = api.DATABASE
        import uuid
        job_id = str(uuid.uuid4())
        database.execute(
            "INSERT INTO jobs (id, project_id, kind, status, progress, checkpoint_json, "
            "error, created_at, updated_at) VALUES (?, 'p', 'shots', 'completed', 1, '{}', "
            "NULL, ?, ?)", (job_id, now(), now()))
        applied = database.transition_job(
            job_id, "cancelled", from_statuses=frozenset({"running", "cancel_requested"}))
        self.assertFalse(applied)
        row = database.fetch_one("SELECT status FROM jobs WHERE id = ?", (job_id,))
        self.assertEqual(row["status"], "completed")


class AssetLevelAtomicityTests(unittest.TestCase):
    """`Database.replace_rows`, exercised directly against a throwaway table shaped like
    `shot_features` -- no real asset, no OpenCV, no CLIP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.db = Database(Path(cls.tmp.name) / "atomicity.sqlite3")
        with cls.db.connection() as connection:
            connection.execute(
                "CREATE TABLE rows_under_test (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, "
                "value TEXT NOT NULL)")

    def test_a_full_replacement_lands_every_row(self):
        rows = [{"id": f"r{i}", "asset_id": "a1", "value": str(i)} for i in range(5)]
        self.db.replace_rows("rows_under_test", "asset_id", "a1", rows)
        stored = self.db.fetch_all(
            "SELECT * FROM rows_under_test WHERE asset_id = ? ORDER BY id", ("a1",))
        self.assertEqual(len(stored), 5)

    def test_a_second_replacement_removes_the_first_entirely(self):
        self.db.replace_rows(
            "rows_under_test", "asset_id", "a2",
            [{"id": "old", "asset_id": "a2", "value": "stale"}])
        self.db.replace_rows(
            "rows_under_test", "asset_id", "a2",
            [{"id": "new", "asset_id": "a2", "value": "fresh"}])
        stored = self.db.fetch_all("SELECT id FROM rows_under_test WHERE asset_id = ?", ("a2",))
        self.assertEqual([row["id"] for row in stored], ["new"])

    def test_a_failure_partway_through_leaves_no_partial_rows(self):
        # A row whose PRIMARY KEY collides with an earlier one in the same batch forces sqlite
        # to raise mid-transaction -- the same shape of failure a bad embedding or a disk-full
        # write would produce, without needing to fabricate either.
        self.db.replace_rows(
            "rows_under_test", "asset_id", "a3",
            [{"id": "keep", "asset_id": "a3", "value": "before"}])
        rows = [
            {"id": "dup", "asset_id": "a3", "value": "first"},
            {"id": "dup", "asset_id": "a3", "value": "second"},  # duplicate primary key
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.replace_rows("rows_under_test", "asset_id", "a3", rows)
        stored = self.db.fetch_all("SELECT * FROM rows_under_test WHERE asset_id = ?", ("a3",))
        # The failed attempt's DELETE was inside the same transaction as its inserts, so it
        # rolled back too: the asset is left exactly as it was before this call, not emptied
        # and not holding either of the two conflicting new rows -- never a mix of old and new.
        self.assertEqual(stored, [{"id": "keep", "asset_id": "a3", "value": "before"}])

    def test_a_rerun_after_a_failed_replacement_does_not_see_a_stale_complete_marker(self):
        rows = [
            {"id": "dup2", "asset_id": "a4", "value": "x"},
            {"id": "dup2", "asset_id": "a4", "value": "y"},
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.replace_rows("rows_under_test", "asset_id", "a4", rows)
        # "does this asset have any rows" — the real completeness check `_asset_features`
        # uses — correctly still says no, so a re-run would redo the work rather than
        # mistaking a rolled-back attempt for a finished one.
        stored = self.db.fetch_all("SELECT * FROM rows_under_test WHERE asset_id = ?", ("a4",))
        self.assertEqual(stored, [])


class AnalysisResumeTests(unittest.TestCase):
    """`analyze_shots`'s own two-pass resume logic, with encode/label/classifier faked out."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)

    def test_completed_assets_are_preserved_when_a_later_asset_is_cancelled(self):
        from sevenfilm.domain import MediaAsset
        from sevenfilm.timebase import FrameRate

        database = Database(Path(self.tmp.name) / "resume.sqlite3")
        database.migrate()
        rate = FrameRate(50)
        project_id = "proj-resume"
        database.insert("projects", {
            "id": project_id, "name": "Resume", "workspace_path": "/tmp",
            "target_duration_seconds": "150", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})
        assets = []
        for index in range(3):
            asset_id = f"asset{index}"
            database.insert("media_assets", {
                "id": asset_id, "project_id": project_id, "path": f"/m/{index}.mov",
                "file_name": f"{index}.mov", "content_hash": f"h{index}",
                "duration_seconds": "10", "frame_rate": "50/1", "width": 1920, "height": 1080,
                "codec": "h264", "timecode": None, "metadata_json": {}, "created_at": now()})
            assets.append(MediaAsset(id=asset_id, project_id=project_id, path=Path(f"/m/{index}.mov"),
                                     name=f"{index}.mov", duration=10, frame_rate=rate,
                                     width=1920, height=1080))
        job_id = str(__import__("uuid").uuid4())
        database.insert("jobs", {
            "id": job_id, "project_id": project_id, "kind": "shots", "status": "running",
            "progress": 0.0, "checkpoint_json": {}, "error": None,
            "created_at": now(), "updated_at": now()})

        def fake_encode(db, classifier, asset):
            # A real `_store_features` call: one row, cheaply, so completeness is genuine.
            db.replace_rows("shot_features", "asset_id", asset.id, [{
                "shot_id": f"sf-{asset.id}", "asset_id": asset.id, "start_frame": 0,
                "duration_frames": 10, "frame_rate": "50/1", "embedding": None,
                "metrics_json": "{}", "created_at": now(),
            }])

        cancel_after = {"count": 0}

        def maybe_cancel(db, job_id_arg):
            cancel_after["count"] += 1
            if cancel_after["count"] == 3:  # third boundary check: before the 3rd asset
                raise JobCancelled(job_id_arg)

        with (
            patch("sevenfilm.services.analysis._encode_asset", side_effect=fake_encode),
            patch("sevenfilm.services.analysis.VisionClassifier"),
            patch("sevenfilm.services.analysis.project_assets", return_value=assets),
            patch("sevenfilm.services.analysis.raise_if_cancelled", side_effect=maybe_cancel),
            self.assertRaises(JobCancelled),
        ):
            analysis.analyze_shots(database, project_id, job_id)

        encoded = database.fetch_all("SELECT asset_id FROM shot_features ORDER BY asset_id")
        # Two assets were encoded before the third boundary raised; their rows must survive.
        self.assertEqual({row["asset_id"] for row in encoded}, {"asset0", "asset1"})


class OrphanRecoveryTests(unittest.TestCase):
    """`recover_orphaned_jobs`, against a throwaway fixture database -- never the live one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "orphans.sqlite3")
        self.db.migrate()
        self.db.insert("projects", {
            "id": "p", "name": "Orphans", "workspace_path": "/tmp",
            "target_duration_seconds": "150", "frame_rate": "25/1",
            "created_at": now(), "updated_at": now()})

    def _job(self, job_id: str, status: str, progress: float = 0.3, kind: str = "shots") -> None:
        self.db.insert("jobs", {
            "id": job_id, "project_id": "p", "kind": kind, "status": status,
            "progress": progress, "checkpoint_json": {}, "error": None,
            "created_at": now(), "updated_at": now()})

    def test_queued_running_and_cancel_requested_all_become_failed(self):
        # Three different kinds: the unique-active-job index would otherwise refuse a second
        # "shots" row for project "p" while the first is still queued/running.
        self._job("j1", "queued", kind="index")
        self._job("j2", "running", kind="shots")
        self._job("j3", "cancel_requested", kind="derivatives")
        recovered = recover_orphaned_jobs(self.db)
        self.assertEqual(set(recovered), {"j1", "j2", "j3"})
        for job_id in ("j1", "j2", "j3"):
            row = self.db.fetch_one("SELECT status, error FROM jobs WHERE id = ?", (job_id,))
            self.assertEqual(row["status"], "failed")
            self.assertIn("backend_restart", row["error"])

    def test_terminal_jobs_are_left_exactly_as_they_were(self):
        self._job("done", "completed", progress=1.0)
        self._job("bad", "failed", progress=0.5)
        self._job("stopped", "cancelled", progress=0.2)
        recovered = recover_orphaned_jobs(self.db)
        self.assertEqual(recovered, [])
        for job_id, expected in (("done", "completed"), ("bad", "failed"), ("stopped", "cancelled")):
            row = self.db.fetch_one("SELECT status FROM jobs WHERE id = ?", (job_id,))
            self.assertEqual(row["status"], expected)

    def test_recovered_jobs_progress_value_is_preserved(self):
        self._job("mid", "running", progress=0.63)
        recover_orphaned_jobs(self.db)
        row = self.db.fetch_one("SELECT progress FROM jobs WHERE id = ?", ("mid",))
        self.assertAlmostEqual(row["progress"], 0.63)

    def test_recovery_does_not_touch_any_other_table(self):
        self.db.insert("media_assets", {
            "id": "a1", "project_id": "p", "path": "/m/a.mov", "file_name": "a.mov",
            "content_hash": "h", "duration_seconds": "10", "frame_rate": "50/1",
            "width": 1920, "height": 1080, "codec": "h264", "timecode": None,
            "metadata_json": {}, "created_at": now()})
        self._job("running-job", "running")
        recover_orphaned_jobs(self.db)
        remaining = self.db.fetch_all("SELECT id FROM media_assets")
        self.assertEqual([row["id"] for row in remaining], ["a1"])


class MigrationSafetyTests(unittest.TestCase):
    def test_migrate_is_idempotent_on_a_fresh_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "fresh.sqlite3")
            db.migrate()
            db.migrate()  # must not raise the second time

    def test_migrate_does_not_fail_over_a_pre_existing_duplicate_active_pair(self):
        # A database from before the unique index existed could hold two active rows of the
        # same (project_id, kind) already. migrate() must survive that, not crash every future
        # start of the process over data written before the constraint did.
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "legacy.sqlite3")
            db.migrate()
            db.insert("projects", {
                "id": "p", "name": "Legacy", "workspace_path": "/tmp",
                "target_duration_seconds": "150", "frame_rate": "25/1",
                "created_at": now(), "updated_at": now()})
            # Bypass the index by inserting directly with SQL that predates its existence —
            # in practice this models rows already on disk before this migration shipped.
            with db.connection() as connection:
                connection.execute("DROP INDEX IF EXISTS jobs_one_active_per_kind")
                for job_id in ("dup-a", "dup-b"):
                    connection.execute(
                        "INSERT INTO jobs (id, project_id, kind, status, progress, "
                        "checkpoint_json, error, created_at, updated_at) VALUES "
                        "(?, 'p', 'shots', 'running', 0, '{}', NULL, ?, ?)",
                        (job_id, now(), now()))
            db.migrate()  # must not raise
            rows = db.fetch_all("SELECT id FROM jobs WHERE project_id = 'p'")
            self.assertEqual({row["id"] for row in rows}, {"dup-a", "dup-b"})


if __name__ == "__main__":
    unittest.main()
