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
    def evaluate(self, target, candidates=(), now=1_000.0, allow_expired_direct=False):
        return MODULE.evaluate_reply_target(
            target,
            current_session_id="group:1",
            now_epoch=now,
            max_age_seconds=180,
            candidate_messages=candidates,
            allow_expired_direct=allow_expired_direct,
        )

    def test_expiry_applies_to_direct_target_and_fallback_time(self):
        target = message("old", 800, text="在吗？", is_at=True, source="received_at_fallback")
        result = self.evaluate(target)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "expired:received_at_fallback")

    def test_active_at_target_survives_expiry_and_newer_message(self):
        target = message("question", 700, text="教我配队", is_at=True)
        result = self.evaluate(target, [target, message("new", 950)], allow_expired_direct=True)
        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "active_direct_expired:onebot_event_seconds")

    def test_active_registration_uses_only_current_new_message_batch(self):
        current_at = message("current-at", 700, is_at=True)
        current_normal = message("current-normal", 700)
        historical_at = message("historical-at", 600, is_at=True)

        active_ids = MODULE.collect_active_reply_request_ids([current_at])
        self.assertEqual(active_ids, {"current-at"})
        active_ids.update(MODULE.collect_active_reply_request_ids([]))
        self.assertEqual(active_ids, {"current-at"})
        self.assertEqual(MODULE.collect_active_reply_request_ids([]), set())
        self.assertEqual(MODULE.collect_active_reply_request_ids([current_normal]), {"current-normal"})
        self.assertNotIn(historical_at.message_id, MODULE.collect_active_reply_request_ids([current_normal]))
        runtime = SimpleNamespace(_active_reply_request_ids={"current-at"})
        MODULE.clear_active_reply_request_ids(runtime)
        self.assertEqual(runtime._active_reply_request_ids, set())

    def test_direct_target_survives_newer_message(self):
        target = message("question", 900, text="帮我看看", is_at=True)
        self.assertTrue(self.evaluate(target, [target, message("new", 950)]).allowed)

    def test_ordinary_target_is_superseded(self):
        target = message("chat", 900)
        result = self.evaluate(target, [target, message("new", 950)])
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "superseded")

    def test_question_mark_alone_does_not_force_direct_target(self):
        target = message("chat", 900, text="这样？")
        self.assertFalse(self.evaluate(target, [target, message("new", 950)]).direct_target)

    def test_question_cues_do_not_force_direct_target_or_expiry_bypass(self):
        target = message("chat", 700, text="终末地怎么配队？")
        result = self.evaluate(target, allow_expired_direct=True)
        self.assertFalse(result.allowed)
        self.assertFalse(result.direct_target)
        self.assertEqual(result.reason, "expired:onebot_event_seconds")

    def test_at_other_does_not_receive_expiry_bypass(self):
        target = message("other", 700, text="@别人 怎么配队？")
        self.assertFalse(self.evaluate(target, allow_expired_direct=True).allowed)

    def test_name_mention_is_a_direct_target(self):
        target = message("name", 700, text="绯玛丽，帮我看看", is_mentioned=True)
        self.assertTrue(
            self.evaluate(target, [target, message("new", 950)], allow_expired_direct=True).allowed
        )

    def test_cross_session_target_is_rejected(self):
        result = self.evaluate(message("other", 950, session_id="group:2", text="什么？"))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "cross_session")

    def test_runtime_expiry_bypass_requires_active_unanswered_target(self):
        target = message("direct", 700, is_at=True)
        runtime = SimpleNamespace(
            session_id="group:1",
            message_cache=[target],
            _active_reply_request_ids={"direct"},
            _answered_msg_ids=set(),
        )
        self.assertTrue(MODULE.evaluate_runtime_target(runtime, target, 180, 1_000).allowed)
        runtime._active_reply_request_ids.clear()
        self.assertFalse(MODULE.evaluate_runtime_target(runtime, target, 180, 1_000).allowed)
        runtime._active_reply_request_ids.add("direct")
        runtime._answered_msg_ids.add("direct")
        self.assertFalse(MODULE.evaluate_runtime_target(runtime, target, 180, 1_000).allowed)


if __name__ == "__main__":
    unittest.main()
