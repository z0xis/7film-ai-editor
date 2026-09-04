"""Choosing more than one song, from the database row up to the request that starts the job."""

import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

_ROOT = tempfile.TemporaryDirectory()
os.environ.setdefault("SEVENFILM_DATA_ROOT", _ROOT.name)

from sevenfilm.db import Database, now
from sevenfilm.domain import BeatGrid
from sevenfilm.services.analysis import project_music
from sevenfilm.services.music import MusicTrack, plan_music


def grid(seconds, gap="1/2", energy="medium"):
    step = Fraction(gap)
    return BeatGrid(
        bpm=60 / float(step), duration=Fraction(seconds),
        beats=tuple(Fraction(i) * step for i in range(int(Fraction(seconds) / step))),
        # Sections are stored as strings, the way _energy_sections writes them.
        sections=({"energy": energy, "start": "0", "end": str(seconds)},))


class ProjectMusicTests(unittest.TestCase):
    """The running order is the editor's, so it is stored, not inferred from import times."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Database(Path(self.temporary.name) / "sevenfilm.sqlite3")
        self.database.migrate()

    def add(self, identifier, name, position, seconds=100):
        one = grid(seconds)
        self.database.insert("music_tracks", {
            "id": identifier, "project_id": "project-1", "path": f"/m/{name}",
            "duration_seconds": str(one.duration), "bpm": one.bpm,
            "beats_json": [str(b) for b in one.beats], "sections_json": list(one.sections),
            "position": position, "created_at": now()})

    def test_the_songs_come_back_in_the_chosen_order(self):
        # Imported party first, but it is the second song of the edit.
        self.add("b", "hareketli.mp3", 1)
        self.add("a", "yavaş.mp3", 0)

        self.assertEqual([t.path.name for t in project_music(self.database, "project-1")],
                         ["yavaş.mp3", "hareketli.mp3"])

    def test_a_project_with_no_song_returns_nothing(self):
        self.assertEqual(project_music(self.database, "project-1"), [])

    def test_the_grid_survives_the_round_trip(self):
        self.add("a", "yavaş.mp3", 0, seconds=40)

        restored = project_music(self.database, "project-1")[0]

        self.assertEqual(restored.grid.duration, Fraction(40))
        self.assertEqual(len(restored.grid.beats), 80)
        self.assertEqual(restored.grid.sections[0]["energy"], "medium")


class PlanMusicTests(unittest.TestCase):
    def track(self, name, seconds, energy="medium"):
        return MusicTrack(Path(f"/m/{name}"), grid(seconds, energy=energy))

    def test_one_song_plays_from_its_own_beginning(self):
        combined, segments, warnings = plan_music([self.track("tek.mp3", 300)], Fraction(120))

        self.assertEqual(segments[0].source_start, Fraction(0))
        self.assertEqual(segments[0].duration, Fraction(120))
        self.assertEqual(combined.duration, Fraction(120))
        self.assertEqual(warnings, [])

    def test_two_songs_fill_the_target_between_them(self):
        combined, segments, _ = plan_music(
            [self.track("yavaş.mp3", 300), self.track("hareketli.mp3", 300)], Fraction(120))

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].timeline_start, Fraction(0))
        self.assertEqual(segments[1].timeline_end, Fraction(120))
        self.assertEqual(combined.duration, Fraction(120))

    def test_the_target_is_covered_for_any_number_of_songs(self):
        for count in range(1, 6):
            songs = [self.track(f"{i}.mp3", 300) for i in range(count)]

            combined, segments, _ = plan_music(songs, Fraction(120))

            self.assertEqual(combined.duration, Fraction(120), f"{count} şarkı")
            self.assertEqual(segments[-1].timeline_end, Fraction(120), f"{count} şarkı")


class MusicRequestTests(unittest.TestCase):
    """The request takes a list; the old single-path body still works."""

    def request(self, **fields):
        from sevenfilm.api import MusicRequest
        return MusicRequest(**fields)

    def test_a_list_of_songs_is_taken_in_order(self):
        self.assertEqual(self.request(paths=["/m/a.mp3", "/m/b.mp3"]).chosen(),
                         ["/m/a.mp3", "/m/b.mp3"])

    def test_a_single_path_still_works(self):
        self.assertEqual(self.request(path="/m/a.mp3").chosen(), ["/m/a.mp3"])

    def test_the_list_wins_when_both_are_sent(self):
        self.assertEqual(self.request(path="/m/a.mp3", paths=["/m/b.mp3"]).chosen(), ["/m/b.mp3"])

    def test_an_empty_request_chooses_nothing(self):
        self.assertEqual(self.request().chosen(), [])


class MusicEndpointTests(unittest.TestCase):
    """What the desktop app sends when the editor lists more than one song."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from sevenfilm import api
        cls.api = api
        cls.client = TestClient(api.app)
        api.DATABASE.migrate()
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.songs = []
        for name in ("yavaş.mp3", "hareketli.mp3"):
            path = root / name
            path.touch()
            cls.songs.append(str(path))
        response = cls.client.post("/api/projects", json={
            "name": "iki şarkı", "workspace_path": str(root),
            "target_duration_seconds": "120", "frame_rate": "25/1"})
        cls.project = response.json()["id"]

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def post(self, body):
        return self.client.post(f"/api/projects/{self.project}/music", json=body)

    def rows(self):
        return self.api.DATABASE.fetch_all(
            "SELECT path, position FROM music_tracks WHERE project_id = ? ORDER BY position",
            (self.project,))

    def seed(self, paths):
        self.api.DATABASE.execute(
            "DELETE FROM music_tracks WHERE project_id = ?", (self.project,))
        for position, path in enumerate(paths):
            self.api.DATABASE.insert("music_tracks", {
                "id": f"{self.project}-{position}", "project_id": self.project, "path": path,
                "duration_seconds": "100", "bpm": 120.0, "beats_json": [], "sections_json": [],
                "position": position, "created_at": now()})

    def test_a_list_of_songs_is_accepted(self):
        response = self.post({"paths": self.songs})

        self.assertEqual(response.status_code, 202)
        self.assertIn("job_id", response.json())

    def test_a_single_path_is_still_accepted(self):
        self.assertEqual(self.post({"path": self.songs[0]}).status_code, 202)

    def test_an_empty_request_is_refused_rather_than_queued(self):
        self.assertEqual(self.post({"paths": []}).status_code, 422)
        self.assertEqual(self.post({}).status_code, 422)

    def test_choosing_songs_replaces_the_previous_selection(self):
        """Leaving the old rows would put back a song the editor had taken out."""
        self.seed(["/m/eski.mp3"])

        self.post({"paths": self.songs})

        self.assertNotIn("/m/eski.mp3", [row["path"] for row in self.rows()])

    def test_the_project_payload_lists_the_songs_in_order(self):
        self.seed(self.songs)

        payload = self.client.get(f"/api/projects/{self.project}").json()

        self.assertEqual(payload.get("music_paths"), self.songs)
        self.assertEqual(payload.get("music_path"), self.songs[0])
