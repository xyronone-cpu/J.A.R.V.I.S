import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from actions import screen_processor


class CameraBackendFallbackTests(unittest.TestCase):
    def test_camera_backend_candidates_include_any_fallback(self):
        candidates = screen_processor.camera_backend_candidates("windows")
        self.assertIsInstance(candidates, list)
        self.assertGreaterEqual(len(candidates), 2)
        self.assertIn(0, candidates)
        self.assertTrue(any(c in candidates for c in (screen_processor.cv2.CAP_DSHOW, screen_processor.cv2.CAP_ANY)))

    def test_camera_backend_candidates_handles_linux(self):
        candidates = screen_processor.camera_backend_candidates("linux")
        self.assertTrue(candidates)
        self.assertEqual(candidates[0], 0)


if __name__ == "__main__":
    unittest.main()
