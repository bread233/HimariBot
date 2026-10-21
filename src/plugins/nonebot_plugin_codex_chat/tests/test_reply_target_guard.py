import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "maibot_core" / "maisaka" / "reply_target_guard.py"
SPEC = importlib.util.spec_from_file_location("codex_chat_reply_target_guard", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def message(message_id, epoch, *, session_id="group:1", text="闲聊", is_at=False, is_mentioned=False, source="onebot_event_seconds"):
    info = SimpleNamespace(additional_config={"event_timestamp_epoch": epoch, "event_timestamp_source": source})
    return SimpleNamespace(message_id=message_id, session_id=session_id, processed_plain_text=text, is_at=is_at, is_mentioned=is_mentioned, message_info=info)


class ReplyTargetGuardTest(unittest.TestCase):
    def evaluate(self, target, candidates=(), now=1_000.0):
        return MODULE.evaluate_reply_target(target, current_session_id="group:1", now_epoch=now, max_age_seconds=180, candidate_messages=candidates)

    def test_expiry_applies_to_direct_target_and_fallback_time(self):
        target = message("old", 800, text="在吗？", is_at=True, source="received_at_fallback")
        result = self.evaluate(target)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "expired:received_at_fallback")

    def test_direct_target_survives_newer_message(self):
        target = message("question", 900, text="怎么做？")
        self.assertTrue(self.evaluate(target, [target, message("new", 950)]).allowed)

    def test_ordinary_target_is_superseded(self):
        target = message("chat", 900)
        result = self.evaluate(target, [target, message("new", 950)])
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "superseded")

    def test_question_mark_alone_does_not_force_direct_target(self):
        target = message("chat", 900, text="这样？")
        self.assertFalse(self.evaluate(target, [target, message("new", 950)]).direct_target)

    def test_name_mention_is_a_direct_target(self):
        target = message("name", 900, text="绯玛丽，帮我看看", is_mentioned=True)
        self.assertTrue(self.evaluate(target, [target, message("new", 950)]).allowed)

    def test_cross_session_target_is_rejected(self):
        result = self.evaluate(message("other", 950, session_id="group:2", text="什么？"))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "cross_session")


if __name__ == "__main__":
    unittest.main()
