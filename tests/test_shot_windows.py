"""A shot is chosen for what it holds, and the cut for where it holds it.

Until these existed a shot was judged on three frames spanning 0.2 seconds from its middle,
its framing on the single frame between them, and the planner cut a segment out by arithmetic
starting a fixed handle after the shot began. Measured on six clips the editor picked out, the
moment objected to was inside the cut and the measurement had never looked at it: a head
against the frame edge at 0.76 and 1.00 where the stored value was 0.00, a whip at 9 sharpness
against the shoot's 45 to 78, a bystander standing in a doorway.
"""

import unittest
import unittest.mock
from fractions import Fraction
from pathlib import Path

from sevenfilm.domain import MediaAsset, Shot
from sevenfilm.services.planner import (
    BYSTANDER_PENALTY,
    WINDOW_QUALITY_WEIGHT,
    _best_offset,
    _score_candidate,
    _source_range_for_duration,
    _window_score,
)
from sevenfilm.services.windows import (
    SHARPNESS_WIDTH,
    AssetWindowMeasurer,
    ShotWindow,
    _sharpness,
    measure_windows,
)
from sevenfilm.timebase import FrameRate, TimeRange

from tests.test_recording_tail import shot as make_shot

RATE = FrameRate(50)
BAR = 60.0


def window(offset, sharpness=80.0, edge=0.0, bystanders=0):
    return ShotWindow(shot_id="s", offset_frames=offset, sharpness=sharpness, motion=0.0,
                      face_ratio=0.05, face_edge=edge, face_count=1, bystanders=bystanders)


class WindowScoreTests(unittest.TestCase):
    def test_a_crisp_clear_half_second_scores_full(self):
        self.assertEqual(_window_score(window(0), BAR), 1.0)

    def test_a_head_against_the_frame_edge_is_charged_the_whole_way(self):
        """C2075 and C2076 both began on one, at 0.76 and 1.00."""
        self.assertAlmostEqual(_window_score(window(0, edge=1.0), BAR), 0.0)
        self.assertAlmostEqual(_window_score(window(0, edge=0.76), BAR), 0.24)

    def test_a_whip_is_not_usable_at_all_on_the_shoot_own_scale(self):
        """C2155 sat at 9 where this shoot's windows run 45 to 78 — a sixth of the median.

        It used to score 0.15, low but carryable: with no face at the frame edge and nobody
        crossing behind, the rest of the score could lift it back into a cut. Below the
        crispness floor it is simply not picture, and eight cuts an edit were coming from the
        shoot's softest 6% that way.
        """
        self.assertEqual(_window_score(window(0, sharpness=9.0), BAR), 0.0)

    def test_softness_still_grades_above_the_floor(self):
        """The floor is a floor, not a switch: above it crispness is still a share of the
        shoot's own median."""
        self.assertAlmostEqual(_window_score(window(0, sharpness=BAR / 2), BAR), 0.5)

    def test_bystanders_cost_and_the_scale_stops_at_a_crowd(self):
        alone = _window_score(window(0), BAR)
        one = _window_score(window(0, bystanders=1), BAR)
        crowd = _window_score(window(0, bystanders=9), BAR)

        self.assertLess(one, alone)
        self.assertAlmostEqual(alone - crowd, BYSTANDER_PENALTY)

    def test_a_shoot_with_no_measured_sharpness_is_not_judged_on_it(self):
        self.assertEqual(_window_score(window(0, sharpness=1.0), 0.0), 1.0)


class BestOffsetTests(unittest.TestCase):
    def test_it_steps_over_the_bad_opening_the_edit_used_to_land_on(self):
        """The exact shape of C2075: edge at the start, clean half a second in."""
        windows = [window(0, edge=0.76), window(25), window(50), window(75)]

        offset, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=50,
                                     sharpness_bar=BAR)

        self.assertEqual(offset, 25)
        self.assertEqual(value, 1.0)

    def test_the_worst_half_second_in_the_run_decides(self):
        windows = [window(0), window(25, edge=1.0), window(50), window(75)]

        _, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=0,
                                sharpness_bar=BAR)

        self.assertAlmostEqual(value, 0.0)

    def test_a_shot_bad_all_the_way_reports_it_rather_than_hiding_it(self):
        """C2181 held the frame edge across its whole length; there was nowhere to move to."""
        windows = [window(offset, edge=1.0) for offset in (0, 25, 50, 75)]

        _, value = _best_offset(make_shot(0, 100), windows, 50, floor=0, ceiling=50,
                                sharpness_bar=BAR)

        self.assertLessEqual(value, 0.0)

    def test_it_never_starts_before_what_the_shot_has_already_given(self):
        windows = [window(0), window(25, edge=1.0), window(50, edge=1.0)]

        offset, _ = _best_offset(make_shot(0, 100), windows, 25, floor=25, ceiling=75,
                                 sharpness_bar=BAR)

        self.assertGreaterEqual(offset, 25)

    def test_an_unmeasured_shot_keeps_the_offset_it_always_had(self):
        offset, value = _best_offset(make_shot(0, 100), [], 50, floor=12, ceiling=50,
                                     sharpness_bar=BAR)

        self.assertEqual(offset, 12)
        self.assertEqual(value, 1.0)


class SourceRangeTests(unittest.TestCase):
    def test_the_cut_moves_to_the_good_part_of_the_shot(self):
        windows = [window(0, edge=1.0), window(25, edge=1.0), window(50), window(75)]

        chosen = _source_range_for_duration(
            make_shot(1000, 200), Fraction(1), windows=windows, sharpness_bar=BAR)

        self.assertIsNotNone(chosen)
        self.assertGreaterEqual(chosen.start_frame, 1050)

    def test_without_windows_it_cuts_where_it_always_did(self):
        plain = _source_range_for_duration(make_shot(1000, 200), Fraction(1))

        self.assertIsNotNone(plain)
        # The handle is min(an eighth of the shot, a fifth of a second) — ten frames here.
        self.assertEqual(plain.start_frame, 1010)


class UnusableShotsLoseTests(unittest.TestCase):
    """A shot with no cuttable stretch has to give way, not be cut to a different bad moment."""

    def test_the_weight_is_the_one_that_was_swept(self):
        # 40% of cuts held a bad half second; 0.15 brings that to 15% and 0.30 to 13%.
        self.assertAlmostEqual(WINDOW_QUALITY_WEIGHT, 0.15)

    def test_a_shot_with_no_usable_run_is_charged_and_a_clean_one_is_not(self):
        common = {
            "preferred_categories": ("couple",),
            "preferred_scales": ("medium",),
            "energy": "medium",
            "recent": (),
            "desired_duration": Fraction(1),
            "random_jitter": 0.0,
        }
        clean, clean_parts = _score_candidate(make_shot(0, 100), window_quality=1.0, **common)
        bad, bad_parts = _score_candidate(make_shot(0, 100), window_quality=0.0, **common)

        self.assertEqual(clean_parts["window_penalty"], 0.0)
        self.assertAlmostEqual(bad_parts["window_penalty"], WINDOW_QUALITY_WEIGHT)
        self.assertLess(bad, clean)

    def test_an_unmeasured_shot_is_not_charged(self):
        _, parts = _score_candidate(
            make_shot(0, 100),
            preferred_categories=("couple",), preferred_scales=("medium",), energy="medium",
            recent=(), desired_duration=Fraction(1), random_jitter=0.0,
        )

        self.assertEqual(parts["window_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()


class SharpnessIsNotNoiseTests(unittest.TestCase):
    """At 4K the Laplacian variance measures the sensor, not the focus.

    Measured on 60 cuts of one edit: the same frames ranked at full resolution and at 640
    pixels agree at a Spearman of only 0.52, and the disagreements are the ones the editor
    picked out by eye. The film's opening — a neon sign, sharp and clean — sat in the bottom
    1% at full resolution, while two cuts of the bride the editor called blurred sat at the
    45th percentile. Read at 640 the sign is the sharpest frame in the film and the blurred
    cuts are the softest.

    It also answers a finding that had none: across eleven features the clips the editor
    rejected measured better than the clips kept, sharpness 25.2 against 23.0. That number
    was reading noise.
    """

    def setUp(self):
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover - opencv is a runtime dependency
            self.skipTest("opencv yok")
        import numpy as np

        self.cv2 = cv2
        rng = np.random.default_rng(7)
        size = (2160, 3840)
        # One scene, photographed twice. The sharp frame is clean; the soft one is the same
        # picture out of focus and carrying the sensor noise a wide-open lens brings with it.
        # That pairing is what the shoot holds and what the measure has to tell apart.
        scene = rng.integers(0, 256, (size[0] // 24, size[1] // 24), dtype="uint8")
        scene = cv2.resize(scene, (size[1], size[0]), interpolation=cv2.INTER_LINEAR)
        self.sharp = scene
        blurred = cv2.GaussianBlur(scene, (0, 0), 9)
        self.soft = np.clip(
            blurred.astype("float64") + rng.normal(0, 14, size), 0, 255).astype("uint8")

    def test_at_full_resolution_the_noisy_soft_frame_wins(self):
        """Which is the fault: it is the blurred frame that measures sharper."""
        def full(frame):
            return float(self.cv2.Laplacian(frame, self.cv2.CV_64F).var())

        self.assertGreater(full(self.soft), full(self.sharp))

    def test_read_at_a_fixed_width_the_sharp_frame_wins(self):
        self.assertGreater(
            _sharpness(self.cv2, self.sharp), _sharpness(self.cv2, self.soft))

    def test_a_frame_already_small_enough_is_not_touched(self):
        import numpy as np

        small = np.zeros((360, 480), dtype="uint8")
        small[:, ::8] = 255
        plain = float(self.cv2.Laplacian(small, self.cv2.CV_64F).var())

        self.assertAlmostEqual(_sharpness(self.cv2, small), plain)

    def test_the_width_is_well_below_a_4k_frame(self):
        self.assertLess(SHARPNESS_WIDTH, 1920)


class _FakeCapture:
    """A `cv2.VideoCapture` stand-in that never touches a real file: frames are generated
    deterministically from the requested frame index, so two measurement passes over the same
    shot always see the same "video" without any real decode cost -- fast enough to run in a
    normal test suite, and exact rather than approximate proof that the batched measurer reads
    the same frames the per-shot one does.
    """

    WIDTH, HEIGHT = 96, 54

    def __init__(self, path=None):
        self._pos = 0
        self.opens = 1

    def isOpened(self):
        return True

    def get(self, prop):
        import cv2

        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self.WIDTH
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self.HEIGHT
        return 0

    def set(self, prop, value):
        self._pos = value
        return True

    def grab(self):
        # Real `cv2.VideoCapture.grab()` decodes the current frame and advances position by
        # one without the colour-conversion `read()` does -- this fake has no real decode to
        # skip, but still has to advance position the same way for the sequential-walk path
        # (P4.1) to land on the frame the seek path would have.
        self._pos += 1
        return True

    def read(self):
        import numpy as np

        rng = np.random.default_rng(self._pos)
        frame = rng.integers(0, 256, (self.HEIGHT, self.WIDTH, 3), dtype="uint8")
        self._pos += 1
        return True, frame

    def release(self):
        pass


class AssetWindowMeasurerEquivalenceTests(unittest.TestCase):
    """P4: `AssetWindowMeasurer` (one capture/detector shared across an asset's shots) must
    produce exactly what `measure_windows` (a fresh capture/detector per shot) already did --
    the whole basis for calling the batching a safe, semantic-preserving optimisation rather
    than a behaviour change. No face detector here (patched out on both sides equally): the
    point of this test is the seek/read/sharpness/motion path every shot goes through, not the
    ONNX model, which neither call controls differently from the other.
    """

    def setUp(self):
        import cv2

        class _NoFaceDetector:
            def detect(self, frame):
                return True, None

        class _FakeFaceDetectorYN:
            @staticmethod
            def create(*args, **kwargs):
                return _NoFaceDetector()

        patcher = unittest.mock.patch.object(cv2, "VideoCapture", _FakeCapture)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A no-op detector, not a disabled one: the point is that both call paths see the same
        # (absent) faces, not that face detection itself is untested here -- see test_vision.py
        # for that.
        detector_patcher = unittest.mock.patch.object(cv2, "FaceDetectorYN", _FakeFaceDetectorYN)
        detector_patcher.start()
        self.addCleanup(detector_patcher.stop)

        self.asset = MediaAsset(
            id="a1", project_id="p", path=Path("/m/a1.mov"), name="a1.mov",
            duration=Fraction(20), frame_rate=FrameRate(50), width=96, height=54)
        self.shots = [
            Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 150, FrameRate(50))),
            Shot(id="s2", asset_id="a1", source_range=TimeRange(150, 200, FrameRate(50))),
            Shot(id="s3", asset_id="a1", source_range=TimeRange(350, 75, FrameRate(50))),
        ]

    def test_batched_measurement_matches_per_shot_measurement_exactly(self):
        per_shot = [measure_windows(self.asset, shot, self.asset.path) for shot in self.shots]

        with AssetWindowMeasurer(self.asset) as measurer:
            batched = [measurer.measure(shot) for shot in self.shots]

        self.assertEqual(per_shot, batched)
        # Not vacuously equal: each shot actually produced windows to compare.
        self.assertTrue(all(per_shot))

    def test_batched_measurement_opens_the_capture_once_not_per_shot(self):
        opens = []
        real_init = _FakeCapture.__init__

        def counting_init(self, *args, **kwargs):
            opens.append(1)
            real_init(self, *args, **kwargs)

        with (
            unittest.mock.patch.object(_FakeCapture, "__init__", counting_init),
            AssetWindowMeasurer(self.asset) as measurer,
        ):
            for shot in self.shots:
                measurer.measure(shot)
        self.assertEqual(len(opens), 1)

    def test_an_unopenable_asset_returns_empty_for_every_shot_not_an_exception(self):
        class _UnopenableCapture(_FakeCapture):
            def isOpened(self):
                return False

        with (
            unittest.mock.patch("cv2.VideoCapture", _UnopenableCapture),
            AssetWindowMeasurer(self.asset) as measurer,
        ):
            for shot in self.shots:
                self.assertEqual(measurer.measure(shot), [])

    def test_a_shot_whose_asset_frame_range_starts_past_end_of_video_still_closes_cleanly(self):
        # `_FakeCapture.read` always succeeds here (unlike a real decoder past EOF), so this
        # exercises only that close() after a normal pass never raises -- not early-stop
        # behaviour, which real `measure_windows` already covers via its own frame-read guard.
        with AssetWindowMeasurer(self.asset) as measurer:
            measurer.measure(self.shots[0])
        # No exception on __exit__ is the assertion.


class SequentialWalkTests(unittest.TestCase):
    """P4.1: `_seek_and_read` walks forward with `grab()` instead of seeking when the gap is
    small, because a `cap.set()` on this shoot's long-GOP H.264 footage measured at ~600ms a
    call against ~37ms for the `read()` that follows it -- a random seek forces the decoder
    back to the nearest keyframe and forward from there every time, even when the target is a
    handful of frames past wherever it already sits. Measured on four real assets (drone and
    camera), walking instead of seeking cut total decode time 52.6s -> 23.3s with
    byte-identical decoded frames, verified by checksum. These tests prove the operation
    counts the walk is supposed to produce, not wall-clock time -- see P4.1's own instruction
    against flaky absolute-timing assertions.
    """

    def setUp(self):
        import cv2

        self.calls = []
        real_grab = _FakeCapture.grab
        real_set = _FakeCapture.set

        def counting_grab(fake_self):
            self.calls.append("grab")
            return real_grab(fake_self)

        def counting_set(fake_self, prop, value):
            self.calls.append("seek")
            return real_set(fake_self, prop, value)

        patcher = unittest.mock.patch.object(cv2, "VideoCapture", _FakeCapture)
        patcher.start()
        self.addCleanup(patcher.stop)

        class _NoFaceDetector:
            def detect(self, frame):
                return True, None

        class _FakeFaceDetectorYN:
            @staticmethod
            def create(*args, **kwargs):
                return _NoFaceDetector()

        # A no-op detector, not an absent one: only seek/grab counts matter to these tests,
        # but the detector still has to run the same real code path both sides of this
        # comparison would.
        detector_patcher = unittest.mock.patch.object(cv2, "FaceDetectorYN", _FakeFaceDetectorYN)
        detector_patcher.start()
        self.addCleanup(detector_patcher.stop)
        grab_patcher = unittest.mock.patch.object(_FakeCapture, "grab", counting_grab)
        grab_patcher.start()
        self.addCleanup(grab_patcher.stop)
        set_patcher = unittest.mock.patch.object(_FakeCapture, "set", counting_set)
        set_patcher.start()
        self.addCleanup(set_patcher.stop)

        self.asset = MediaAsset(
            id="a1", project_id="p", path=Path("/m/a1.mov"), name="a1.mov",
            duration=Fraction(20), frame_rate=FrameRate(50), width=96, height=54)

    def test_close_targets_within_one_shot_walk_instead_of_seeking(self):
        # A 200-frame shot at 50fps steps every 25 frames (WINDOW_SECONDS=0.5s) -- well inside
        # MAX_SEQUENTIAL_WALK_FRAMES, so only the very first window should seek.
        shot = Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 200, FrameRate(50)))
        with AssetWindowMeasurer(self.asset) as measurer:
            measurer.measure(shot)
        self.assertEqual(self.calls.count("seek"), 1)
        self.assertGreater(self.calls.count("grab"), 0)

    def test_a_far_shot_seeks_rather_than_walking_thousands_of_frames(self):
        first = Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 25, FrameRate(50)))
        far = Shot(id="s2", asset_id="a1",
                  source_range=TimeRange(1_000_000, 25, FrameRate(50)))
        with AssetWindowMeasurer(self.asset) as measurer:
            measurer.measure(first)
            self.calls.clear()
            measurer.measure(far)
        # The huge gap must seek, not grab() a million times.
        self.assertEqual(self.calls.count("seek"), 1)
        self.assertEqual(self.calls.count("grab"), 0)

    def test_position_resets_to_a_seek_after_a_failed_read(self):
        class _OnceThenFailingCapture(_FakeCapture):
            def read(self):
                if self._pos >= 25:
                    return False, None
                return super().read()

        with (
            unittest.mock.patch("cv2.VideoCapture", _OnceThenFailingCapture),
            AssetWindowMeasurer(self.asset) as measurer,
        ):
            shot_a = Shot(id="s1", asset_id="a1",
                         source_range=TimeRange(0, 50, FrameRate(50)))
            measurer.measure(shot_a)  # breaks after the first read fails at frame 25
            self.calls.clear()
            shot_b = Shot(id="s2", asset_id="a1",
                         source_range=TimeRange(30, 25, FrameRate(50)))
            measurer.measure(shot_b)
        # position was left as None by the failed read, so the next shot must seek, not walk
        # forward from a position the capture never actually reached.
        self.assertEqual(self.calls.count("seek"), 1)

    def test_the_second_shot_of_an_asset_still_walks_from_the_first(self):
        # Cross-shot continuity: project_shots orders shots by ascending start_frame within one
        # asset, so consecutive shots' target frames are close too, not just windows within one
        # shot.
        first = Shot(id="s1", asset_id="a1", source_range=TimeRange(0, 25, FrameRate(50)))
        second = Shot(id="s2", asset_id="a1", source_range=TimeRange(25, 25, FrameRate(50)))
        with AssetWindowMeasurer(self.asset) as measurer:
            measurer.measure(first)
            self.calls.clear()
            measurer.measure(second)
        # first shot reads frame 0 and leaves position at 1; second shot's target is frame 25,
        # so the walk is 24 grabs, not 25.
        self.assertEqual(self.calls.count("seek"), 0)
        self.assertEqual(self.calls.count("grab"), 24)
