import importlib.util
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "onebot_reply.py"
SPEC = importlib.util.spec_from_file_location("codex_chat_onebot_reply", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def run_immediate(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("coroutine unexpectedly required an event loop")


class Component:
    def __init__(self, kind, *, text="", binary_data=b""):
        self.kind = kind
        self.text = text
        self.binary_data = binary_data

    def format_name(self):
        return self.kind


def outbound(*components, text=""):
    raw = SimpleNamespace(components=list(components)) if components else None
    return SimpleNamespace(raw_message=raw, processed_plain_text=text)


class FakeBot:
    def __init__(self):
        self.calls = []

    async def call_api(self, api, **kwargs):
        self.calls.append((api, kwargs))
        return {"message_id": 321}


class OneBotNativeReplyTest(unittest.TestCase):
    def test_reply_id_resolution_preserves_negative_fallback_id(self):
        message = SimpleNamespace(reply_to=-123)
        reply_message = SimpleNamespace(message_id=-456)
        self.assertEqual(MODULE.resolve_reply_message_id("", message, reply_message), "-123")
        self.assertEqual(MODULE.resolve_reply_message_id("-7", message, reply_message), "-7")

    def test_negative_reply_id_and_component_order(self):
        message, unsupported = run_immediate(MODULE.build_onebot_message(
            outbound(
                Component("text", text="回答"),
                Component("image", binary_data=b"image"),
                Component("emoji", binary_data=b"emoji"),
            ),
            "-123456789",
        ))
        self.assertEqual(unsupported, [])
        self.assertEqual([segment.type for segment in message], ["reply", "text", "image", "image"])
        self.assertEqual(message[0].data["id"], "-123456789")

    def test_plain_text_reply_and_no_reply(self):
        quoted, _ = run_immediate(MODULE.build_onebot_message(outbound(text="回答"), "42"))
        plain, _ = run_immediate(MODULE.build_onebot_message(outbound(text="回答")))
        self.assertEqual([segment.type for segment in quoted], ["reply", "text"])
        self.assertEqual([segment.type for segment in plain], ["text"])

    def test_existing_reply_components_never_duplicate_native_reply(self):
        message, _ = run_immediate(MODULE.build_onebot_message(
            outbound(Component("reply"), Component("text", text="回答"), Component("reply")),
            "88",
        ))
        self.assertEqual([segment.type for segment in message], ["reply", "text"])

    def test_route_validation_rejects_cross_target_bot_and_expiry(self):
        now = time.time()
        routes = {
            "1": {"is_group": True, "target_id": "100", "bot_self_id": "200", "ts": now},
            "2": {"is_group": True, "target_id": "100", "bot_self_id": "200", "ts": now - 601},
        }
        valid = MODULE.validate_reply_route(routes, "1", is_group=True, target_id="100", bot_self_id="200", ttl_seconds=600, now=now)
        cross_group = MODULE.validate_reply_route(routes, "1", is_group=True, target_id="101", bot_self_id="200", ttl_seconds=600, now=now)
        cross_bot = MODULE.validate_reply_route(routes, "1", is_group=True, target_id="100", bot_self_id="201", ttl_seconds=600, now=now)
        expired = MODULE.validate_reply_route(routes, "2", is_group=True, target_id="100", bot_self_id="200", ttl_seconds=600, now=now)
        self.assertEqual(valid, ("1", ""))
        self.assertEqual(cross_group, ("", "target_mismatch"))
        self.assertEqual(cross_bot, ("", "bot_mismatch"))
        self.assertEqual(expired, ("", "route_expired"))

    def test_final_group_api_receives_native_reply_segment(self):
        bot = FakeBot()
        message, _ = run_immediate(MODULE.build_onebot_message(outbound(text="回答"), "-7"))
        result = run_immediate(MODULE.call_onebot_send(bot, is_group=True, target_id="100", message=message))
        self.assertEqual(result, {"message_id": 321})
        api, kwargs = bot.calls[0]
        self.assertEqual(api, "send_group_msg")
        self.assertEqual(kwargs["group_id"], 100)
        self.assertEqual(kwargs["message"][0].type, "reply")
        self.assertEqual(kwargs["message"][0].data["id"], "-7")

    def test_captured_fallback_preserves_validated_reply(self):
        bot = FakeBot()
        bot.self_id = "200"
        reply = SimpleNamespace(reply_to_message_id="-9", raw=None, text="回退回答")
        routes = {
            "-9": {"is_group": True, "target_id": "100", "bot_self_id": "200", "ts": time.time()},
        }
        _, validated_id, reason, message = run_immediate(MODULE.send_captured_reply(
            bot,
            reply,
            routes,
            is_group=True,
            target_id="100",
            bot_self_id="200",
            ttl_seconds=600,
        ))
        self.assertEqual((validated_id, reason), ("-9", ""))
        self.assertEqual([segment.type for segment in message], ["reply", "text"])
        self.assertEqual(bot.calls[0][1]["message"][0].data["id"], "-9")

    def test_captured_fallback_downgrades_cross_group_to_plain_text(self):
        bot = FakeBot()
        reply = SimpleNamespace(reply_to_message_id="10", raw=None, text="普通回答")
        routes = {
            "10": {"is_group": True, "target_id": "999", "bot_self_id": "200", "ts": time.time()},
        }
        _, validated_id, reason, message = run_immediate(MODULE.send_captured_reply(
            bot,
            reply,
            routes,
            is_group=True,
            target_id="100",
            bot_self_id="200",
            ttl_seconds=600,
        ))
        self.assertEqual((validated_id, reason), ("", "target_mismatch"))
        self.assertEqual([segment.type for segment in message], ["text"])


if __name__ == "__main__":
    unittest.main()
