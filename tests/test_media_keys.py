import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from actions import computer_control


class MediaKeyTests(unittest.TestCase):
    def test_play_pause_media_alias(self):
        out = computer_control.computer_control({"action": "press", "key": "play/pause"})
        self.assertIn("media", out.lower())

    def test_next_track_alias(self):
        out = computer_control.computer_control({"action": "press", "key": "next track"})
        self.assertIn("media", out.lower())

    def test_prev_track_alias(self):
        out = computer_control.computer_control({"action": "press", "key": "previous track"})
        self.assertIn("media", out.lower())


if __name__ == "__main__":
    unittest.main()
