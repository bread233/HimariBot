import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1]


class SourceContractTest(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (PLUGIN_ROOT / relative_path).read_text(encoding="utf-8")

    def test_visible_send_contracts(self):
        service = self.read("maibot_core/services/send_service.py")
        self.assertIn("_session_send_cooldown.send(", service)
        self.assertIn("reply_message_id", service)
        self.assertIn("DeliveryUncertainError", service)

    def test_each_visible_tool_rechecks_target_immediately_before_send(self):
        reply = self.read("maibot_core/maisaka/builtin_tool/reply.py")
        image = self.read("maibot_core/maisaka/builtin_tool/send_image.py")
        emoji = self.read("maibot_core/maisaka/builtin_tool/send_emoji.py")
        emoji_service = self.read("maibot_core/emoji_system/maisaka_tool.py")
        self.assertIn("target_guard = evaluate_runtime_target", reply)
        self.assertIn("guard_result = evaluate_runtime_target", image)
        self.assertIn("send_guard=send_guard", emoji)
        self.assertLess(emoji_service.index("guard_error = send_guard()"), emoji_service.index("target_session ="))

    def test_timing_and_planner_contracts(self):
        engine = self.read("maibot_core/maisaka/reasoning_engine.py")
        self.assertIn("def _mark_timing_gate_completed", engine)
        self.assertIn("return True", engine)
        self.assertIn("_visible_delivery_succeeded", engine)
        self.assertIn("_check_visible_target", engine)

    def test_new_config_fields_have_defaults(self):
        config = self.read("maibot_core/config/official_configs.py")
        self.assertIn("reply_target_max_age_seconds: float = Field(default=180", config)
        self.assertIn('talk_value_timezone: str = Field(default="Asia/Tokyo")', config)


if __name__ == "__main__":
    unittest.main()
