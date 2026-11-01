"""Deterministic local tests, without external services."""
import ast
import importlib.util
import sys
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("local_himari")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location("local_himari." + name, ROOT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

m = load("mood_state")
p = load("proactive_mood")

class MoodTests(unittest.TestCase):
    def setUp(self):
        m.reset_mood()

    def test_baseline_and_event_clamp(self):
        self.assertEqual(m.get_mood_snapshot().valence, 55)
        self.assertAlmostEqual(m.apply_mood_event(valence=999).valence, 75, places=2)

    def test_nonfinite(self):
        with self.assertRaises(ValueError):
            m.apply_mood_event(energy=float("nan"))

    def test_half_life(self):
        m.apply_mood_event(valence=20)
        with m._LOCK:
            m._updated_at -= m.DECAY_HALF_LIFE_SECONDS
        self.assertAlmostEqual(m.get_mood_snapshot().valence, 65, delta=0.1)

class QuotaTests(unittest.TestCase):
    def setUp(self):
        p._usage.clear()
        p._reservations.clear()
        m.reset_mood()
        m.apply_mood_event(valence=20)

    def test_reserve_release_confirm(self):
        t = p.reserve_expression("100")
        self.assertTrue(t)
        self.assertFalse(p.can_express("100"))
        self.assertTrue(p.release_expression(t))
        t = p.reserve_expression("100")
        self.assertTrue(p.confirm_delivered("100", t))
        self.assertFalse(p.confirm_delivered("100", t))
        self.assertFalse(p.can_express("100"))

    def test_group_isolation(self):
        t = p.reserve_expression("100")
        self.assertTrue(p.reserve_expression("200"))
        self.assertFalse(p.confirm_delivered("200", t))

    def test_concurrent(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(p.reserve_expression, ["300"] * 24))
        self.assertEqual(sum(bool(x) for x in results), 1)

    def test_expiry(self):
        t = p.reserve_expression("100")
        gid, day, ts = p._reservations[t]
        p._reservations[t] = (gid, day, ts - p.RESERVATION_SECONDS - 1)
        self.assertTrue(p.can_express("100"))

    def test_daily_limit(self):
        for i in range(2):
            t = p.reserve_expression("100")
            self.assertTrue(p.confirm_delivered("100", t))
            if i == 0:
                day, count, ts = p._usage["100"]
                p._usage["100"] = (day, count, ts - p.COOLDOWN_SECONDS - 1)
        self.assertIsNone(p.reserve_expression("100"))

class ContractTests(unittest.TestCase):
    def test_pipeline(self):
        out = (ROOT / "maibot_core/outbound.py").read_text(encoding="utf-8")
        bridge = (ROOT / "maibot_core/bridge.py").read_text(encoding="utf-8")
        reply = (ROOT / "maibot_core/maisaka/builtin_tool/reply.py").read_text(encoding="utf-8")
        host = (ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("mood_reservation=_current_mood_reservation.get()", out)
        self.assertIn('mood_reservation=getattr(msg, "mood_reservation", None)', bridge)
        self.assertIn("reserve_expression(mood_group_id)", reply)
        self.assertIn("reset_mood_reservation(reservation_scope)", reply)
        self.assertIn("except send_service.DeliveryUncertainError", reply)
        self.assertIn("confirm_delivered(target_id, reply.mood_reservation)", host)
        self.assertIn("OneBot send result unknown after API exception", host)
        ast.parse(reply)
        ast.parse(host)

if __name__ == "__main__":
    unittest.main()
