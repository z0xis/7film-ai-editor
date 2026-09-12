"""Letting the moment search see the whole clip, beside the one that sees one shot.

Windows are measured a shot at a time and handed to the planner grouped by shot, so
`_best_offset` can only look inside the shot it was given. Measured on the 54 clips this edit
and the editor's both use, the editor's moment falls outside that range in 22 of them, and in
19 it sits in a different detected shot. A search bounded that way cannot reach the right
moment on two clips in five, whatever its scoring says.

Nothing here is wired into the plan: the shadow search is computed beside the planner's own
answer and compared with it. These tests hold that line — the production range must come out
of the planner unchanged — and check that the wider search stays inside the clip, keeps the
quality gate, reuses what is already measured, and falls back rather than guessing.
"""

import unittest

from sevenfilm.domain import Shot
from sevenfilm.services import shadow
from sevenfilm.services.planner import _best_offset, _window_score
from sevenfilm.services.windows import AssetWindow, ShotWindow
from sevenfilm.timebase import FrameRate, TimeRange

RATE = FrameRate(50)
BAR = 100.0


def _shot(start=0, duration=250, identifier="s1", category="couple"):
    return Shot(id=identifier, asset_id="a1",
                source_range=TimeRange(start, duration, RATE), category=category,
                shot_scale="medium", technical_quality=.8, aesthetic_score=.8,
                motion_score=.5, confidence=.8)


def _window(frame, sharpness=BAR, edge=0.0, faces=2, bystanders=0,
            shot_id="s1", category="couple"):
    return AssetWindow(shot_id=shot_id, asset_frame=frame, category=category,
                       sharpness=sharpness, motion=1.0, face_ratio=0.02,
                       face_edge=edge, face_count=faces, bystanders=bystanders)


def _clip(count=40, step=25, **kwargs):
    return [_window(index * step, **kwargs) for index in range(count)]


class TheSearchRangesTests(unittest.TestCase):
    def test_the_shot_search_stops_at_the_shot(self):
        span = shadow.legacy_search_range(_shot(start=1000, duration=250), frames=50)
        self.assertGreaterEqual(span.first_frame, 1000)
        self.assertLessEqual(span.last_frame, 1250)

    def test_the_clip_search_reaches_past_the_shot(self):
        shot = _shot(start=1000, duration=250)
        narrow = shadow.legacy_search_range(shot, frames=50)
        wide = shadow.asset_search_range(_clip(), asset_duration_frames=1000 * 5,
                                         frames=50, rate=RATE)
        self.assertLess(wide.first_frame, narrow.first_frame)
        self.assertGreater(wide.last_frame, narrow.last_frame)

    def test_the_clip_search_never_leaves_the_clip(self):
        total = 1000
        span = shadow.asset_search_range(_clip(), asset_duration_frames=total,
                                         frames=50, rate=RATE)
        self.assertGreaterEqual(span.first_frame, 0)
        self.assertLessEqual(span.last_frame + 50, total)

    def test_a_second_cut_from_one_clip_starts_later_than_the_first(self):
        windows = _clip()
        early = shadow.asset_search_range(windows, 1000, 50, RATE)
        later = shadow.asset_search_range(windows, 1000, 50, RATE, floor_frame=400)
        self.assertGreater(later.first_frame, early.first_frame)
        self.assertEqual(later.first_frame, 400)


class WhatTheWiderSearchCanReachTests(unittest.TestCase):
    def test_a_moment_in_a_neighbouring_shot_comes_into_reach(self):
        shot = _shot(start=500, duration=250)
        elsewhere = 120                      # in an earlier shot of the same clip
        narrow = shadow.legacy_search_range(shot, frames=50)
        wide = shadow.asset_search_range(_clip(), 1000, 50, RATE)
        self.assertFalse(shadow.reachable(narrow, elsewhere))
        self.assertTrue(shadow.reachable(wide, elsewhere))

    def test_a_moment_in_another_clip_stays_out_of_reach(self):
        wide = shadow.asset_search_range(_clip(), 1000, 50, RATE)
        self.assertFalse(shadow.reachable(wide, 4000))


class TheScoringIsTheSameTests(unittest.TestCase):
    """The only thing this change moves is where the search may look."""

    def test_the_same_run_scores_the_same_either_way(self):
        windows = _clip(count=10)
        shot_windows = [
            ShotWindow(shot_id="s1", offset_frames=w.asset_frame, sharpness=w.sharpness,
                       motion=w.motion, face_ratio=w.face_ratio, face_edge=w.face_edge,
                       face_count=w.face_count, bystanders=w.bystanders)
            for w in windows
        ]
        shot = _shot(start=0, duration=250)
        legacy_offset, legacy_value = _best_offset(
            shot, shot_windows, 50, floor=10, ceiling=200, sharpness_bar=BAR)
        span = shadow.SearchRange(10, 200)
        found = shadow.shadow_offset(windows, span, 50, BAR, window_score=_window_score)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found[1], legacy_value)
        self.assertEqual(found[0], legacy_offset)

    def test_a_window_below_the_quality_floor_cannot_win(self):
        good = _window(0, sharpness=BAR)
        blurred = [_window(frame, sharpness=BAR * 0.1) for frame in (25, 50, 75)]
        windows = [good, *blurred]
        span = shadow.SearchRange(0, 75)
        found = shadow.shadow_offset(windows, span, 25, BAR, window_score=_window_score)
        self.assertEqual(found[0], 0)
        self.assertGreater(found[1], 0.0)

    def test_a_clip_of_nothing_but_blur_scores_nothing(self):
        windows = [_window(frame, sharpness=BAR * 0.1) for frame in (0, 25, 50)]
        span = shadow.SearchRange(0, 50)
        found = shadow.shadow_offset(windows, span, 25, BAR, window_score=_window_score)
        self.assertEqual(found[1], 0.0)


class WhenItCannotRunTests(unittest.TestCase):
    def test_a_clip_with_no_windows_falls_back(self):
        result = shadow.evaluate(
            _shot(), frames=50, asset_duration_frames=1000, windows=[],
            sharpness_bar=BAR, window_score=_window_score)
        self.assertTrue(result.fallback)
        self.assertIsNone(result.shadow_start)
        self.assertIn("no measured windows", result.reason)

    def test_a_fallback_carries_the_planner_s_own_answer(self):
        result = shadow.evaluate(
            _shot(), frames=50, asset_duration_frames=1000, windows=[],
            sharpness_bar=BAR, window_score=_window_score, legacy_start=137)
        self.assertEqual(result.legacy_start, 137)
        self.assertEqual(result.shadow_time_range(RATE).start_frame, 137)

    def test_asking_for_no_frames_falls_back(self):
        result = shadow.evaluate(
            _shot(), frames=0, asset_duration_frames=1000, windows=_clip(),
            sharpness_bar=BAR, window_score=_window_score)
        self.assertTrue(result.fallback)

    def test_a_measured_clip_does_not_fall_back(self):
        result = shadow.evaluate(
            _shot(), frames=50, asset_duration_frames=1000, windows=_clip(),
            sharpness_bar=BAR, window_score=_window_score)
        self.assertFalse(result.fallback)
        self.assertIsNotNone(result.shadow_start)
        self.assertEqual(result.reason, "ok")


class TheProductionAnswerIsUntouchedTests(unittest.TestCase):
    def test_the_shadow_reports_the_planner_s_range_unchanged(self):
        shot = _shot(start=500, duration=250)
        result = shadow.evaluate(
            shot, frames=50, asset_duration_frames=1000, windows=_clip(),
            sharpness_bar=BAR, window_score=_window_score, legacy_start=610)
        self.assertEqual(result.legacy_time_range(RATE), TimeRange(610, 50, RATE))

    def test_the_two_answers_are_reported_apart(self):
        shot = _shot(start=500, duration=250)
        result = shadow.evaluate(
            shot, frames=50, asset_duration_frames=1000,
            windows=_clip(count=40, step=25), sharpness_bar=BAR,
            window_score=_window_score, legacy_start=510)
        self.assertEqual(result.legacy_start, 510)
        self.assertIsNotNone(result.shadow_start)
        self.assertIsNotNone(result.host_shot_id)


class TheAssetViewTests(unittest.TestCase):
    """The asset view is the stored rows re-based, never a second measurement."""

    def test_a_window_keeps_its_measurements(self):
        window = _window(300, sharpness=42.0, edge=0.5, faces=3, bystanders=1)
        same = window.as_shot_window()
        self.assertEqual(same.sharpness, 42.0)
        self.assertEqual(same.face_edge, 0.5)
        self.assertEqual(same.face_count, 3)
        self.assertEqual(same.bystanders, 1)
        self.assertEqual(same.offset_frames, 300)

    def test_a_window_carries_the_category_of_the_shot_it_was_measured_in(self):
        windows = [_window(0, category="couple"), _window(25, shot_id="s2",
                                                          category="detail")]
        self.assertEqual(windows[0].category, "couple")
        self.assertEqual(windows[1].category, "detail")


if __name__ == "__main__":
    unittest.main()


class TheStoredRowsAreReusedTests(unittest.TestCase):
    """The asset view reads what is already measured; it never measures again."""

    def _project(self, database):
        from sevenfilm.db import now
        database.insert("projects", {
            "id": "p", "name": "T", "workspace_path": "/tmp/t",
            "target_duration_seconds": "150", "frame_rate": "50/1",
            "created_at": now(), "updated_at": now()})
        database.insert("media_assets", {
            "id": "a1", "project_id": "p", "path": "/tmp/a1.mp4", "file_name": "a1.mp4",
            "content_hash": "h", "duration_seconds": "20", "frame_rate": "50/1",
            "width": 1920, "height": 1080, "codec": "h264", "timecode": None,
            "proxy_path": None, "thumbnail_path": None, "metadata_json": {},
            "created_at": now()})
        for index, start in enumerate((0, 500)):
            database.insert("shots", {
                "id": f"s{index}", "asset_id": "a1", "start_frame": start,
                "duration_frames": 500, "frame_rate": "50/1", "category": "couple",
                "shot_scale": "medium", "technical_quality": 0.8, "aesthetic_score": 0.8,
                "motion_score": 0.5, "confidence": 0.8, "duplicate_group": None,
                "labels_json": [], "created_at": now()})

    def test_windows_of_two_shots_become_one_view_of_the_clip(self):
        import tempfile
        from pathlib import Path

        from sevenfilm.db import Database
        from sevenfilm.services.windows import asset_windows, store_windows

        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "db.sqlite3")
            database.migrate()
            self._project(database)
            for shot_id in ("s0", "s1"):
                store_windows(database, shot_id, [
                    ShotWindow(shot_id=shot_id, offset_frames=offset, sharpness=100.0,
                               motion=1.0, face_ratio=0.02, face_edge=0.0,
                               face_count=2, bystanders=0)
                    for offset in (0, 25, 50)])

            view = asset_windows(database, "p")
            self.assertEqual(len(view["a1"]), 6)
            frames = [window.asset_frame for window in view["a1"]]
            self.assertEqual(frames, [0, 25, 50, 500, 525, 550])

    def test_a_measured_shot_is_never_queued_again(self):
        import tempfile
        from pathlib import Path

        from sevenfilm.db import Database
        from sevenfilm.services.windows import store_windows, unmeasured_shots

        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "db.sqlite3")
            database.migrate()
            self._project(database)
            self.assertEqual(unmeasured_shots(database, "p"), ["s0", "s1"])

            store_windows(database, "s0", [
                ShotWindow(shot_id="s0", offset_frames=0, sharpness=100.0, motion=1.0,
                           face_ratio=0.02, face_edge=0.0, face_count=2, bystanders=0)])
            self.assertEqual(unmeasured_shots(database, "p"), ["s1"])

    def test_storing_twice_replaces_rather_than_duplicates(self):
        import tempfile
        from pathlib import Path

        from sevenfilm.db import Database
        from sevenfilm.services.windows import asset_windows, store_windows

        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "db.sqlite3")
            database.migrate()
            self._project(database)
            rows = [ShotWindow(shot_id="s0", offset_frames=offset, sharpness=100.0,
                               motion=1.0, face_ratio=0.02, face_edge=0.0,
                               face_count=2, bystanders=0) for offset in (0, 25)]
            store_windows(database, "s0", rows)
            store_windows(database, "s0", rows)
            self.assertEqual(len(asset_windows(database, "p")["a1"]), 2)
