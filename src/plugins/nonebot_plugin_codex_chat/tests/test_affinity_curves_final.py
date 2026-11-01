"""Focused tests for the approved affinity curves and QQ mood display."""
import ast
import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "himari_curve_contract"
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


class CurveAndMoodTests(unittest.TestCase):
    def setUp(self):
        mood.reset_mood()
        events._recent_sentiment.clear()

    def test_praise_is_visible_and_recent(self):
        events.note_targeted_mood("group", "123", "你太厉害了", addressed=True)
        self.assertEqual(mood.get_mood_label(), "小开心")
        self.assertEqual(mood.get_recent_emotion("123"), "被夸奖，有点高兴😊")
        self.assertEqual(mood.get_recent_emotion("456"), "无明显变化😌")

    def test_repeat_does_not_stack(self):
        events.note_targeted_mood("group", "123", "你真棒", addressed=True)
        first = mood.get_mood_snapshot().valence
        events.note_targeted_mood("group", "123", "你真棒", addressed=True)
        self.assertAlmostEqual(mood.get_mood_snapshot().valence, first, delta=0.01)

    def test_recent_emotion_expiry(self):
        mood.note_recent_emotion("123", "被夸奖，有点高兴😊")
        description, ts = mood._recent_emotions["123"]
        mood._recent_emotions["123"] = (description, ts - mood.EMOTION_SECONDS - 1)
        self.assertEqual(mood.get_recent_emotion("123"), "无明显变化😌")

    def test_curve_contract_from_source(self):
        source = (ROOT / "affinity_evaluator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_affinity_adjustment")
        namespace = {"math": math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<curve>", "exec"), namespace)
        adjust = namespace["_affinity_adjustment"]
        self.assertAlmostEqual(adjust(10, 5, 1), 2 + 23 * math.exp(-10 / 25))
        self.assertGreater(adjust(0, 1, 1), adjust(40, 1, 1))
        self.assertGreater(adjust(-10, 1, 1), adjust(10, 1, 1))
        self.assertLess(adjust(40, -2, 1), 0)
        self.assertEqual(adjust(100, 0, 1), 0)


if __name__ == "__main__":
    unittest.main()
