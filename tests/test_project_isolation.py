"""A job belongs to the project it was created for, and to nothing else.

This exists because of an incident, not a hypothesis: a newly created project's shot
extraction wrote 362 assets into an older, unrelated project, and a music analysis wiped that
older project's own song out from under it in the same few minutes. Tracing it back, the
backend was never the ambient-state hazard — `start_shot_analysis`, `start_index` and
`start_music_analysis` all take `project_id` from the URL, validate it with `_project`, and
hand that exact value to `_create_job`, which stores it on the job row `_run_job` later reads
back. There is no module-level "current project" for a background task to drift onto. The
hazard was the desktop client holding a *display* of "current project" in React state that two
in-flight async calls could each try to set — covered separately in `apps/desktop/src/main.tsx`
and not testable from here, since this repository has no frontend test harness (no vitest, no
testing-library; adding one was treated as out of scope for a recovery/regression package).

What is tested here is the contract the frontend fix now depends on staying true: every
job-creating endpoint is scoped by the `project_id` in its own URL, two projects' jobs never
share an identity, an unknown project is refused before any job is created, and a music
selection for one project can never delete another project's rows.
"""

import os
import tempfile
import unittest
from pathlib import Path

_ROOT = tempfile.TemporaryDirectory()
os.environ["SEVENFILM_DATA_ROOT"] = _ROOT.name

from fastapi.testclient import TestClient
from sevenfilm import api
from sevenfilm.db import now


class ProjectIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(_ROOT.cleanup)
        api.DATABASE.migrate()
        cls.client = TestClient(api.app)
        cls.workspace = Path(_ROOT.name)

    def _make_project(self, name: str) -> dict:
        response = self.client.post("/api/projects", json={
            "name": name, "workspace_path": str(self.workspace),
            "target_duration_seconds": "150", "frame_rate": "25/1"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # -- 1. two projects, two jobs: each job belongs to the project it was created for --------

    def test_a_shot_job_created_for_project_a_is_bound_to_project_a(self):
        project_a = self._make_project("Project A")
        response = self.client.post(f"/api/projects/{project_a['id']}/shots")
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["job_id"]
        job = api.DATABASE.fetch_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        self.assertEqual(job["project_id"], project_a["id"])

    def test_two_projects_jobs_never_share_an_identity(self):
        project_a = self._make_project("Project A2")
        project_b = self._make_project("Project B2")
        job_a = self.client.post(f"/api/projects/{project_a['id']}/shots").json()["job_id"]
        job_b = self.client.post(f"/api/projects/{project_b['id']}/shots").json()["job_id"]
        row_a = api.DATABASE.fetch_one("SELECT project_id FROM jobs WHERE id = ?", (job_a,))
        row_b = api.DATABASE.fetch_one("SELECT project_id FROM jobs WHERE id = ?", (job_b,))
        self.assertEqual(row_a["project_id"], project_a["id"])
        self.assertEqual(row_b["project_id"], project_b["id"])
        self.assertNotEqual(row_a["project_id"], row_b["project_id"])

    # -- 2. a job already running for A keeps its own identity regardless of what a client ----
    #       does afterwards; there is nothing here for it to "follow" ------------------------

    def test_a_running_jobs_project_id_is_immutable_after_creation(self):
        project_a = self._make_project("Project A3")
        project_b = self._make_project("Project B3")
        job_id = self.client.post(f"/api/projects/{project_a['id']}/shots").json()["job_id"]
        before = api.DATABASE.fetch_one("SELECT project_id FROM jobs WHERE id = ?", (job_id,))
        # Whatever a client does with project B next (open it, start its own job, ...) cannot
        # be expressed as a write to an existing job row: nothing in this schema lets a job's
        # project_id be changed after `_create_job` sets it.
        self.client.post(f"/api/projects/{project_b['id']}/shots")
        after = api.DATABASE.fetch_one("SELECT project_id FROM jobs WHERE id = ?", (job_id,))
        self.assertEqual(before["project_id"], after["project_id"])
        self.assertEqual(after["project_id"], project_a["id"])

    # -- 3. an unknown project is refused before any job row exists ---------------------------

    def test_an_unknown_project_id_fails_closed_with_no_job_created(self):
        before = api.DATABASE.fetch_all("SELECT id FROM jobs")
        response = self.client.post("/api/projects/not-a-real-project-id/shots")
        self.assertEqual(response.status_code, 404)
        after = api.DATABASE.fetch_all("SELECT id FROM jobs")
        self.assertEqual({row["id"] for row in before}, {row["id"] for row in after})

    def test_index_and_derivatives_also_fail_closed_on_an_unknown_project(self):
        self.assertEqual(
            self.client.post("/api/projects/nope/index", json={"folder": str(self.workspace)})
            .status_code, 404)
        self.assertEqual(
            self.client.post("/api/projects/nope/derivatives").status_code, 404)

    # -- 4. no ambient "current project" exists for a background task to drift onto ----------

    def test_run_job_reads_project_id_from_the_jobs_own_row_not_a_global(self):
        import inspect

        from sevenfilm import api as api_module
        source = inspect.getsource(api_module._run_job)
        # It has to come from `job["project_id"]` — the row `_run_job` was handed by id — and
        # nowhere in this module is there a shared "current" project a background task could
        # read instead.
        self.assertIn('job["project_id"]', source)
        for forbidden in ("current_project", "CURRENT_PROJECT", "active_project", "session"):
            self.assertNotIn(forbidden, Path(api_module.__file__).read_text())

    # -- 5. a music selection for one project cannot touch another project's rows -------------

    def test_selecting_music_for_project_b_does_not_touch_project_as_tracks(self):
        project_a = self._make_project("Project A4")
        project_b = self._make_project("Project B4")
        api.DATABASE.insert("music_tracks", {
            "id": "keep-me", "project_id": project_a["id"], "path": "/m/a-song.mp3",
            "duration_seconds": "180", "bpm": 120.0, "beats_json": [], "sections_json": [],
            "created_at": now(), "analysis_version": "1", "position": 0})

        song = self.workspace / "b-song.mp3"
        song.write_bytes(b"")
        response = self.client.post(
            f"/api/projects/{project_b['id']}/music", json={"paths": [str(song)]})
        self.assertEqual(response.status_code, 202, response.text)

        remaining = api.DATABASE.fetch_all(
            "SELECT * FROM music_tracks WHERE project_id = ?", (project_a["id"],))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], "keep-me")
        self.assertEqual(remaining[0]["path"], "/m/a-song.mp3")

    def test_selecting_music_only_deletes_the_requested_projects_own_rows(self):
        project_a = self._make_project("Project A5")
        api.DATABASE.insert("music_tracks", {
            "id": "old-a-track", "project_id": project_a["id"], "path": "/m/old.mp3",
            "duration_seconds": "180", "bpm": 120.0, "beats_json": [], "sections_json": [],
            "created_at": now(), "analysis_version": "1", "position": 0})
        song = self.workspace / "new-a-song.mp3"
        song.write_bytes(b"")
        self.client.post(f"/api/projects/{project_a['id']}/music",
                          json={"paths": [str(song)]})
        remaining = api.DATABASE.fetch_all(
            "SELECT id FROM music_tracks WHERE project_id = ?", (project_a["id"],))
        self.assertNotIn("old-a-track", {row["id"] for row in remaining})


if __name__ == "__main__":
    unittest.main()
