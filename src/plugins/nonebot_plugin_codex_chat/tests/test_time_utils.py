import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "maibot_core" / "time_utils.py"
SPEC = importlib.util.spec_from_file_location("codex_chat_time_utils", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class TimeUtilsTest(unittest.TestCase):
    def test_normalizes_seconds_and_milliseconds(self):
        self.assertEqual(MODULE.normalize_unix_timestamp(1_700_000_000, 1_700_000_010)[:2], (1_700_000_000.0, "onebot_event_seconds"))
        self.assertEqual(MODULE.normalize_unix_timestamp(1_700_000_000_000, 1_700_000_010)[:2], (1_700_000_000.0, "onebot_event_milliseconds"))

    def test_invalid_timestamp_uses_marked_receipt_time(self):
        for raw_value in (None, -1, math.nan, 1_800_000_000):
            epoch, source, reason = MODULE.normalize_unix_timestamp(raw_value, 1_700_000_000)
            self.assertEqual((epoch, source), (1_700_000_000.0, "received_at_fallback"))
            self.assertTrue(reason)

    def test_tokyo_wall_clock_is_explicit(self):
        minutes, timezone_name = MODULE.wall_clock_minutes("Asia/Tokyo", 1_704_067_200)
        self.assertEqual((minutes, timezone_name), (9 * 60, "Asia/Tokyo"))


if __name__ == "__main__":
    unittest.main()
