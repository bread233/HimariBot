import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

MODULE_PATH = Path(__file__).parents[1] / "maibot_core" / "services" / "send_cooldown.py"
SPEC = importlib.util.spec_from_file_location("codex_chat_send_cooldown", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SessionSendCooldown = MODULE.SessionSendCooldown


def _message(session_id: str, message_id: str):
    return SimpleNamespace(session_id=session_id, message_id=message_id)


class VisibleSendCooldownTest(TestCase):
    def setUp(self):
        self.cooldown = SessionSendCooldown()

    def test_is_session_scoped_and_success_only(self):
        calls = []

        async def fake_send(message, **kwargs):
            calls.append(message.message_id)
            return None if message.message_id == "failed" else message

        async def run():
            result, _ = await self.cooldown.send("group-a", 3.0, lambda: fake_send(_message("group-a", "failed")))
            self.assertIsNone(result)
            result, _ = await self.cooldown.send("group-a", 3.0, lambda: fake_send(_message("group-a", "sent-a")))
            self.assertIsNotNone(result)
            result, remaining = await self.cooldown.send(
                "group-a", 3.0, lambda: fake_send(_message("group-a", "blocked"))
            )
            self.assertIsNone(result)
            self.assertGreater(remaining, 0)
            result, _ = await self.cooldown.send("group-b", 3.0, lambda: fake_send(_message("group-b", "sent-b")))
            self.assertIsNotNone(result)

        asyncio.run(asyncio.wait_for(run(), timeout=2))
        self.assertEqual(calls, ["failed", "sent-a", "sent-b"])

    def test_serializes_concurrent_sends(self):
        calls = []

        async def fake_send(message, **kwargs):
            calls.append(message.message_id)
            await asyncio.sleep(0)
            return message

        async def run():
            return await asyncio.gather(
                self.cooldown.send("group-a", 3.0, lambda: fake_send(_message("group-a", "first"))),
                self.cooldown.send("group-a", 3.0, lambda: fake_send(_message("group-a", "second"))),
            )

        results = asyncio.run(asyncio.wait_for(run(), timeout=2))
        self.assertEqual(sum(result is not None for result, _ in results), 1)
        self.assertEqual(len(calls), 1)
