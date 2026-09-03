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

    def test_fallback_is_content_metric_based_and_explicit(self):
        frame = np.full((120, 160, 3), 127, dtype=np.uint8)
        metrics = measure_frames([frame])

        result = VisionClassifier._fallback(metrics)

        self.assertIn(result["category"], {"venue", "detail"})
        self.assertIn("opencv_fallback", result["labels"])


if __name__ == "__main__":
    unittest.main()
