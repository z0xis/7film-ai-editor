import unittest

import cv2
import numpy as np
from sevenfilm.services.vision import (
    AESTHETIC_PROMPTS,
    CATEGORY_PROMPTS,
    SCALE_PROMPTS,
    VisionClassifier,
    measure_frames,
)


def row(dominant: int, *others: tuple[int, float], base: float = 0.05) -> list[float]:
    """A probability row over the real category vocabulary, so adding a category cannot break
    these tests the way hard-coded widths of eight did."""
    values = [base] * len(CATEGORY_PROMPTS)
    values[dominant] = 0.6
    for index, value in others:
        values[index] = value
    total = sum(values)
    return [value / total for value in values]


class VisionTests(unittest.TestCase):
    def test_measures_real_frame_content_deterministically(self):
        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (60, 30), (260, 150), (220, 220, 220), -1)
        cv2.line(frame, (0, 0), (319, 179), (255, 255, 255), 4)

        result = measure_frames([frame, np.roll(frame, 8, axis=1), np.roll(frame, 16, axis=1)])

        self.assertGreater(result.technical_quality, 0.2)
        self.assertGreater(result.motion_score, 0.0)
        self.assertEqual(len(result.perceptual_hash), 16)

    def test_blown_out_white_frame_is_not_usable_footage(self):
        """The white blurry areas CLIP mistakes for a wedding dress must score near zero."""
        frame = np.full((180, 320, 3), 253, dtype=np.uint8)

        result = measure_frames([frame, frame, frame])

        self.assertLess(result.technical_quality, 0.05)
        self.assertGreater(result.highlight_clipping, 0.9)

    def test_mostly_blown_out_frame_loses_to_a_clean_frame(self):
        blown = np.full((180, 320, 3), 200, dtype=np.uint8)
        cv2.rectangle(blown, (0, 0), (319, 130), (255, 255, 255), -1)
        clean = np.zeros((180, 320, 3), dtype=np.uint8)
        cv2.rectangle(clean, (60, 30), (260, 150), (150, 120, 90), -1)
        cv2.line(clean, (0, 0), (319, 179), (200, 190, 180), 3)

        blown_quality = measure_frames([blown, blown, blown]).technical_quality
        clean_quality = measure_frames([clean, clean, clean]).technical_quality

        self.assertLess(blown_quality, clean_quality)
        self.assertLess(blown_quality, 0.2)

    def test_flat_featureless_frame_scores_zero_however_bright(self):
        for level in (30, 127, 200):
            frame = np.full((120, 160, 3), level, dtype=np.uint8)
            self.assertEqual(measure_frames([frame]).technical_quality, 0.0, f"level {level}")

    def test_one_sharp_frame_cannot_rescue_a_mostly_blurred_shot(self):
        sharp = np.zeros((180, 320, 3), dtype=np.uint8)
        cv2.rectangle(sharp, (60, 30), (260, 150), (180, 160, 140), -1)
        cv2.line(sharp, (0, 0), (319, 179), (240, 230, 220), 3)
        blurred = cv2.GaussianBlur(sharp, (31, 31), 0)

        mostly_blurred = measure_frames([blurred, blurred, sharp])
        all_sharp = measure_frames([sharp, sharp, sharp])

        self.assertLess(mostly_blurred.technical_quality, all_sharp.technical_quality)
        self.assertLess(mostly_blurred.sharpness, all_sharp.sharpness)

    def test_brightness_and_saturation_are_reported_for_reference_comparison(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[:, :] = (20, 60, 180)

        result = measure_frames([frame])

        self.assertGreater(result.saturation, 0.5)
        self.assertAlmostEqual(result.brightness, 180 / 255, places=2)

    def test_fallback_is_content_metric_based_and_explicit(self):
        frame = np.full((120, 160, 3), 127, dtype=np.uint8)
        metrics = measure_frames([frame])

        result = VisionClassifier._fallback(metrics)

        self.assertIn(result["category"], {"venue", "detail"})
        self.assertIn("opencv_fallback", result["labels"])


if __name__ == "__main__":
    unittest.main()


class CategoryPriorTests(unittest.TestCase):
    """CLIP calls a blurred white ceiling a bride; the prior correction takes that offset off."""

    class FakeClassifier(VisionClassifier):
        """Substitutes fixed probabilities for the model, so the correction is what is tested."""

        def __init__(self, categories):
            super().__init__()
            self._categories = np.asarray(categories, dtype=float)

        def _load(self):
            return True

        def _probabilities(self, features):
            count = len(self._categories)
            scales = np.full((count, len(SCALE_PROMPTS)), 1 / len(SCALE_PROMPTS))
            aesthetics = np.full((count, len(AESTHETIC_PROMPTS)), 1 / len(AESTHETIC_PROMPTS))
            return self._categories.copy(), scales, aesthetics

    def metrics(self, count):
        return [measure_frames([np.full((32, 32, 3), 120, dtype=np.uint8)]) for _ in range(count)]

    def test_a_category_that_always_scores_high_stops_winning_everything(self):
        # One category sits high on every frame regardless of content.
        high = list(CATEGORY_PROMPTS).index("bride")
        rows = [row(high, (index, 0.3)) for index in (2, 4, 5, 6)]
        classifier = self.FakeClassifier(rows)
        features = np.zeros((4, 8))

        raw = classifier.classify_features(features, self.metrics(4))
        prior = classifier.prompt_priors(features)
        corrected = classifier.classify_features(features, self.metrics(4), prior)

        self.assertEqual({r["category"] for r in raw}, {"bride"})
        self.assertGreater(len({r["category"] for r in corrected}), 1)

    def test_the_prior_is_the_average_share_each_category_takes(self):
        rows = [[0.5, 0.1, 0.1, 0.1, 0.05, 0.05, 0.05, 0.05],
                [0.3, 0.3, 0.1, 0.1, 0.05, 0.05, 0.05, 0.05]]
        classifier = self.FakeClassifier(rows)

        priors = classifier.prompt_priors(np.zeros((2, 8)))

        self.assertAlmostEqual(priors.category[0], 0.4)
        self.assertAlmostEqual(priors.category[1], 0.2)

    def test_a_genuinely_distinctive_frame_keeps_its_category(self):
        """Correction removes a standing offset, it does not overturn a clear winner."""
        rows = [
            [0.05, 0.50, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05],
            [0.05, 0.50, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05],
            [0.90, 0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01],
        ]
        classifier = self.FakeClassifier(rows)
        features = np.zeros((3, 8))

        corrected = classifier.classify_features(features, self.metrics(3),
                                                 classifier.prompt_priors(features))

        self.assertEqual(corrected[2]["category"], "couple")

    def test_confidence_stays_a_share_between_zero_and_one(self):
        high = list(CATEGORY_PROMPTS).index("bride")
        rows = [row(high, (2, 0.3)), row(high, (4, 0.3))]
        classifier = self.FakeClassifier(rows)
        features = np.zeros((2, 8))

        for result in classifier.classify_features(features, self.metrics(2),
                                                   classifier.prompt_priors(features)):
            self.assertGreaterEqual(result["confidence"], 0.0)
            self.assertLessEqual(result["confidence"], 1.0)

    def test_without_a_prior_nothing_changes(self):
        rows = [row(list(CATEGORY_PROMPTS).index("bride"))]
        classifier = self.FakeClassifier(rows)

        self.assertEqual(
            classifier.classify_features(np.zeros((1, 8)), self.metrics(1))[0]["category"], "bride"
        )

    def test_no_features_falls_back_to_the_opencv_labels(self):
        classifier = self.FakeClassifier([[0.5] * 8])
        results = classifier.classify_features(None, self.metrics(1))
        self.assertIn("opencv_fallback", results[0]["labels"])


class ProbabilityPathTests(unittest.TestCase):
    """The real tensor path, which a classifier stubbed at _probabilities cannot cover."""

    def test_probabilities_come_back_as_plain_writable_arrays(self):
        torch = __import__("importlib").import_module("torch")

        classifier = VisionClassifier()
        classifier._torch = torch
        classifier._device = "cpu"
        width = len(CATEGORY_PROMPTS) + len(SCALE_PROMPTS) + len(AESTHETIC_PROMPTS)
        # A parameter carries requires_grad, which is what made .numpy() fail outside
        # inference_mode; the text features and logit scale are model parameters in practice.
        classifier._text_features = torch.nn.Parameter(torch.randn(width, 16))
        classifier._model = type("Stub", (), {"logit_scale": torch.nn.Parameter(torch.tensor(2.0))})()
        classifier._load = lambda: True

        categories, scales, aesthetics = classifier._probabilities(
            np.random.rand(3, 16).astype(np.float32)
        )

        for array in (categories, scales, aesthetics):
            self.assertIsInstance(array, np.ndarray)
            self.assertTrue(array.flags.writeable, "the arrays are mutated by the prior correction")
        np.testing.assert_allclose(categories.sum(axis=1), 1.0, rtol=1e-5)
        self.assertEqual(categories.shape, (3, len(CATEGORY_PROMPTS)))

    def test_the_prior_correction_can_write_into_those_arrays(self):
        torch = __import__("importlib").import_module("torch")

        classifier = VisionClassifier()
        classifier._torch = torch
        classifier._device = "cpu"
        width = len(CATEGORY_PROMPTS) + len(SCALE_PROMPTS) + len(AESTHETIC_PROMPTS)
        classifier._text_features = torch.nn.Parameter(torch.randn(width, 16))
        classifier._model = type("Stub", (), {"logit_scale": torch.nn.Parameter(torch.tensor(2.0))})()
        classifier._load = lambda: True
        features = np.random.rand(4, 16).astype(np.float32)
        metrics = [measure_frames([np.full((16, 16, 3), 100, dtype=np.uint8)]) for _ in range(4)]

        results = classifier.classify_features(features, metrics, classifier.prompt_priors(features))

        self.assertEqual(len(results), 4)
        self.assertTrue(all("clip_vision" in r["labels"] for r in results))


class ScalePriorTests(unittest.TestCase):
    """The shot scale carries the same standing offset the categories do."""

    class FakeClassifier(VisionClassifier):
        def __init__(self, scales):
            super().__init__()
            self._scales = np.asarray(scales, dtype=float)

        def _load(self):
            return True

        def _probabilities(self, features):
            count = len(self._scales)
            categories = np.full((count, len(CATEGORY_PROMPTS)), 1 / len(CATEGORY_PROMPTS))
            aesthetics = np.full((count, len(AESTHETIC_PROMPTS)), 1 / len(AESTHETIC_PROMPTS))
            return categories, self._scales.copy(), aesthetics

    def metrics(self, count):
        return [measure_frames([np.full((32, 32, 3), 120, dtype=np.uint8)]) for _ in range(count)]

    def rows(self):
        """Columns are wide, medium, close_up, detail. "medium" sits high on every frame.

        Measured on this shoot: "a medium shot showing people from the waist up" took 60.8%
        of the probability on average against 3.9% for the close-up phrase, and the edit came
        out with 141 clips and no close-up in it.
        """
        return [
            [0.30, 0.62, 0.05, 0.03],
            [0.25, 0.60, 0.12, 0.03],
            [0.20, 0.58, 0.04, 0.18],
            [0.40, 0.55, 0.03, 0.02],
        ]

    def test_a_scale_that_always_scores_high_stops_winning_everything(self):
        classifier = self.FakeClassifier(self.rows())
        features = np.zeros((4, 8))

        raw = classifier.classify_features(features, self.metrics(4))
        corrected = classifier.classify_features(
            features, self.metrics(4), classifier.prompt_priors(features))

        self.assertEqual({r["shot_scale"] for r in raw}, {"medium"})
        self.assertEqual([r["shot_scale"] for r in corrected][1], "close_up")
        self.assertEqual([r["shot_scale"] for r in corrected][2], "detail")

    def test_the_scale_prior_is_the_average_share_each_phrase_takes(self):
        priors = self.FakeClassifier(self.rows()).prompt_priors(np.zeros((4, 8)))

        self.assertAlmostEqual(float(priors.scale[1]), 0.5875)
        self.assertAlmostEqual(float(priors.scale[2]), 0.06)

    def test_a_frame_that_really_is_medium_keeps_its_scale(self):
        rows = [*self.rows(), [0.02, 0.94, 0.02, 0.02]]
        classifier = self.FakeClassifier(rows)
        features = np.zeros((5, 8))

        corrected = classifier.classify_features(
            features, self.metrics(5), classifier.prompt_priors(features))

        self.assertEqual(corrected[4]["shot_scale"], "medium")

    def test_the_scale_labels_follow_the_corrected_choice(self):
        classifier = self.FakeClassifier(self.rows())
        features = np.zeros((4, 8))

        corrected = classifier.classify_features(
            features, self.metrics(4), classifier.prompt_priors(features))

        self.assertIn("close_up", corrected[1]["labels"])
