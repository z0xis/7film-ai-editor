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
