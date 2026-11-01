"""Second-batch isolated regression tests. No production DB, network or QQ traffic."""
import ast
import asyncio
import importlib.util
import json
import math
import re
import sys
import types
import unittest
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "affinity_evaluator.py"
HOST = ROOT / "__init__.py"


def extract_function(path, name, globals_dict):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    code = compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec")
    exec(code, globals_dict)
    return globals_dict[name]


class EvaluationParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(EVALUATOR.read_text(encoding="utf-8"))
        ranges = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EVENT_RANGES" for t in node.targets))
        cls.parse = staticmethod(extract_function(EVALUATOR, "_parse_evaluation", {"json": json, "re": re, "EVENT_RANGES": ranges}))

    def test_valid_positive(self):
        self.assertEqual(self.parse('{"event_type":"friendly","confidence":0.9,"base_delta":1.5}'), ("friendly", 1.5))

    def test_low_confidence(self):
        self.assertIsNone(self.parse('{"event_type":"friendly","confidence":0.64,"base_delta":1}'))

    def test_out_of_range_and_unknown(self):
        self.assertIsNone(self.parse('{"event_type":"friendly","confidence":0.99,"base_delta":5}'))
        self.assertIsNone(self.parse('{"event_type":"unknown","confidence":0.99,"base_delta":1}'))

    def test_bad_json_nonfinite_and_missing(self):
        self.assertIsNone(self.parse("not JSON"))
        self.assertIsNone(self.parse('{"event_type":"friendly"}'))
        self.assertIsNone(self.parse('{"event_type":"friendly","confidence":0.9,"base_delta":NaN}'))


class AsyncEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.history = defaultdict(lambda: deque(maxlen=8))
        self.inflight = set()
        self.recent = {}
        self.calls = []
        self.record = types.SimpleNamespace(last_evaluated_at=None, daily_reset_date="", daily_change_count=0)
        async def generate(*args, **kwargs):
            self.calls.append("llm")
            return types.SimpleNamespace(ok=True, text='{"event_type":"friendly","confidence":0.9,"base_delta":1}')
        def persist(*args):
            self.calls.append("persist")
            return True
        self.globals = {
            "asyncio": asyncio, "datetime": datetime, "json": json, "re": re, "math": math, "time": __import__("time"),
            "_history": self.history, "_inflight": self.inflight, "_recent_events": self.recent,
            "COOLDOWN_SECONDS": 60, "MAX_DAILY_CHANGES": 20, "REPEAT_WINDOW_SECONDS": 1800,
            "EVENT_RANGES": {"ordinary": (0, 0), "friendly": (0.5, 2), "negative": (-3, -1)},
            "is_bot_directed": lambda message, addressed: addressed,
            "_as_utc": lambda value: value.replace(tzinfo=__import__("datetime").timezone.utc) if value.tzinfo is None else value,
            "timezone": __import__("datetime").timezone,
            "JST": __import__("zoneinfo").ZoneInfo("Asia/Tokyo"),
            "_social_rules": lambda: {"instruction": "", "mood_max_delta": 10.0},
            "_recent_mood": {},
            "apply_mood_event": Mock(), "note_recent_emotion": Mock(),
            "get_or_create_affinity": lambda qq: self.record,
            "generate_text": generate, "_persist_evaluation": persist,
            "log": Mock(),
        }
        self.globals["_parse_evaluation"] = extract_function(EVALUATOR, "_parse_evaluation", self.globals)
        self.evaluate = extract_function(EVALUATOR, "evaluate_affinity_event", self.globals)

    async def test_nonaddressed_skips_llm(self):
        await self.evaluate("123", "5", "hello", addressed=False)
        self.assertEqual(self.calls, [])

    async def test_positive_event_and_duplicate_suppression(self):
        await self.evaluate("123", "5", "thank you", addressed=True)
        await self.evaluate("123", "5", "thank you", addressed=True)
        self.assertEqual(self.calls.count("persist"), 1)
        self.assertEqual(self.calls.count("llm"), 2)

    async def test_cooldown_and_daily_limit(self):
        self.record.last_evaluated_at = datetime.now()
        await self.evaluate("123", "5", "thank you", addressed=True)
        self.assertEqual(self.calls.count("persist"), 0)
        self.assertEqual(self.calls.count("llm"), 1)
        self.calls.clear()
        self.record.last_evaluated_at = None
        self.record.daily_reset_date = datetime.now().date().isoformat()
        self.record.daily_change_count = 20
        await self.evaluate("123", "5", "thank you", addressed=True)
        self.assertEqual(self.calls.count("persist"), 0)
        self.assertEqual(self.calls.count("llm"), 1)

    async def test_llm_failure_does_not_block(self):
        self.globals["generate_text"] = AsyncMock(side_effect=RuntimeError("offline"))
        await self.evaluate("123", "5", "thank you", addressed=True)
        self.assertNotIn("123", self.inflight)

    async def test_touch_semantics_positive_negative_neutral(self):
        for kind, delta, mood in (("friendly", 1, 3), ("negative", -2, -4), ("ordinary", 0, 0)):
            self.calls.clear()
            self.globals["_recent_events"].clear()
            self.globals["_recent_mood"].clear()
            self.globals["apply_mood_event"].reset_mock()
            payload = json.dumps({"event_type": kind, "confidence": 0.9, "base_delta": delta, "mood_delta": mood, "emotion": "互动"})
            self.globals["generate_text"] = AsyncMock(return_value=types.SimpleNamespace(ok=True, text=payload))
            await self.evaluate("123", "5", "QQ戳一戳", addressed=True)
            self.assertEqual(self.calls.count("persist"), 1)
            self.assertEqual(self.globals["apply_mood_event"].call_count, int(bool(mood)))

    async def test_mood_survives_affinity_cooldown_without_repeat(self):
        self.record.last_evaluated_at = datetime.now()
        self.globals["generate_text"] = AsyncMock(return_value=types.SimpleNamespace(ok=True, text='{"event_type":"friendly","confidence":0.9,"base_delta":1,"mood_delta":3,"emotion":"开心"}'))
        await self.evaluate("123", "5", "摸摸头", addressed=True)
        await self.evaluate("123", "5", "摸摸头", addressed=True)
        self.assertEqual(self.calls.count("persist"), 0)
        self.globals["apply_mood_event"].assert_called_once_with(valence=3.0, sociability=1.5)

    async def test_poke_handler_dispatch_contract(self):
        tree = ast.parse(HOST.read_text(encoding="utf-8"))
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_poke")
        calls = [n for n in ast.walk(handler) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "evaluate_affinity_event"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.literal_eval(calls[0].args[2]), "QQ戳一戳")
        self.assertTrue(any(k.arg == "addressed" and isinstance(k.value, ast.Constant) and k.value.value is True for k in calls[0].keywords))


class HostSendTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_exception_is_uncertain(self):
        source = HOST.read_text(encoding="utf-8")
        tree = ast.parse(source)
        candidates = [n for n in ast.walk(tree) if isinstance(n, ast.Try) and any(isinstance(x, ast.Await) and isinstance(x.value, ast.Call) and isinstance(x.value.func, ast.Name) and x.value.func.id == "call_onebot_send" for statement in n.body for x in ast.walk(statement))]
        self.assertTrue(candidates)
        handler = next(h for h in candidates[0].handlers if isinstance(h.type, ast.Name) and h.type.id == "Exception")
        self.assertTrue(any(isinstance(n, ast.Raise) for n in ast.walk(handler)))
        self.assertFalse(any(isinstance(n, ast.Return) for n in ast.walk(handler)))


if __name__ == "__main__":
    unittest.main()
