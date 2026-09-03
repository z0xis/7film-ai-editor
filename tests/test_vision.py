import unittest

import cv2
import numpy as np
from sevenfilm.services.vision import VisionClassifier, measure_frames


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
