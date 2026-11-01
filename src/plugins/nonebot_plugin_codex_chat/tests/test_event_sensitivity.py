"""Focused mood sensitivity tests; no database or model calls."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "sensitivity_local"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mood = load("mood_state")
events = load("mood_events")


class EventSensitivityTests(unittest.TestCase):
    def setUp(self):
        mood.reset_mood()
        events._recent_sentiment.clear()

    def test_directed_positive_and_negative(self):
        events.note_targeted_mood("1", "100", "谢谢你", addressed=True)
        self.assertGreater(mood.get_mood_snapshot().valence, 55)
        mood.reset_mood()
        events.note_targeted_mood("1", "101", "你真烦", addressed=True)
        self.assertLess(mood.get_mood_snapshot().valence, 55)

    def test_named_without_at(self):
        self.assertTrue(events.is_bot_directed("Himari，谢谢你", False))
        self.assertFalse(events.is_bot_directed("我谢谢隔壁群友", False))

    def test_unrelated_chat_and_repeat(self):
        events.note_targeted_mood("1", "100", "谢谢你", addressed=False)
        self.assertAlmostEqual(mood.get_mood_snapshot().valence, 55, places=2)
        events.note_targeted_mood("1", "100", "谢谢你", addressed=True)
        first = mood.get_mood_snapshot().valence
        events.note_targeted_mood("1", "100", "谢谢你", addressed=True)
        self.assertAlmostEqual(mood.get_mood_snapshot().valence, first, delta=0.01)


if __name__ == "__main__":
    unittest.main()
