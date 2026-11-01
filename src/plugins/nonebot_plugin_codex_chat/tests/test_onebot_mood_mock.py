"""Isolated delivery accounting tests; no real OneBot calls."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("onebot_test_pkg")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location("onebot_test_pkg." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

mood = load("mood_state")
quota = load("proactive_mood")

async def simulate(group, reservation, sender):
    result = await sender()
    if result is None:
        quota.release_expression(reservation)
        return False
    return quota.confirm_delivered(group, reservation)

class OneBotMockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mood.reset_mood()
        mood.apply_mood_event(valence=20)
        with quota._lock:
            quota._usage.clear()
            quota._reservations.clear()

    async def test_success_commits_once(self):
        reservation = quota.reserve_expression("101")
        sender = AsyncMock(return_value={"message_id": "123"})
        self.assertTrue(await simulate("101", reservation, sender))
        sender.assert_awaited_once()
        self.assertFalse(quota.confirm_delivered("101", reservation))
        self.assertEqual(quota._usage["101"][1], 1)

    async def test_definite_failure_releases(self):
        reservation = quota.reserve_expression("101")
        self.assertFalse(await simulate("101", reservation, AsyncMock(return_value=None)))
        self.assertTrue(quota.can_express("101"))
        self.assertNotIn("101", quota._usage)

    async def test_api_error_keeps_reservation(self):
        reservation = quota.reserve_expression("101")
        with self.assertRaises(ConnectionError):
            await simulate("101", reservation, AsyncMock(side_effect=ConnectionError("unknown")))
        self.assertIn(reservation, quota._reservations)
        self.assertFalse(quota.can_express("101"))

    async def test_timeout_keeps_reservation(self):
        reservation = quota.reserve_expression("101")
        with self.assertRaises(asyncio.TimeoutError):
            await simulate("101", reservation, AsyncMock(side_effect=asyncio.TimeoutError()))
        self.assertIn(reservation, quota._reservations)

    async def test_cancel_keeps_reservation(self):
        reservation = quota.reserve_expression("101")
        with self.assertRaises(asyncio.CancelledError):
            await simulate("101", reservation, AsyncMock(side_effect=asyncio.CancelledError()))
        self.assertIn(reservation, quota._reservations)

    async def test_wrong_group_cannot_confirm(self):
        reservation = quota.reserve_expression("101")
        self.assertFalse(await simulate("202", reservation, AsyncMock(return_value={"message_id": "123"})))
        self.assertIn(reservation, quota._reservations)

    async def test_uncertain_prevents_duplicate(self):
        reservation = quota.reserve_expression("101")
        with self.assertRaises(ConnectionError):
            await simulate("101", reservation, AsyncMock(side_effect=ConnectionError()))
        self.assertIsNone(quota.reserve_expression("101"))

class HostContractTests(unittest.TestCase):
    def test_host_send_accounting(self):
        source = (ROOT / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("release_expression(reply.mood_reservation)", source)
        self.assertIn("confirm_delivered(target_id, reply.mood_reservation)", source)
        self.assertIn("proactive_mood_delivery_uncertain", source)
        self.assertIn("raise DeliveryUncertainError", source)

    def test_reply_uncertain_no_retry(self):
        source = (ROOT / "maibot_core/maisaka/builtin_tool/reply.py").read_text(encoding="utf-8")
        self.assertIn("except send_service.DeliveryUncertainError", source)
        self.assertIn('reply_metadata["pause_execution"] = True', source)

if __name__ == "__main__":
    unittest.main()
