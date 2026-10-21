import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

MODULE_PATH = Path(__file__).parents[1] / "maibot_core" / "maisaka" / "reply_transaction.py"
SPEC = importlib.util.spec_from_file_location("codex_chat_reply_transaction", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReplyTransactionTest(TestCase):
    def test_flatten_preserves_all_component_order(self):
        text = SimpleNamespace(kind="text")
        image = SimpleNamespace(kind="image")
        emoji = SimpleNamespace(kind="emoji")
        reply = SimpleNamespace(kind="reply")
        sequences = [
            SimpleNamespace(components=[reply, text]),
            SimpleNamespace(components=[image, emoji]),
        ]

        self.assertEqual(
            MODULE.flatten_message_components(sequences),
            [reply, text, image, emoji],
        )

    def test_old_partial_success_is_not_complete_delivery(self):
        self.assertFalse(MODULE.all_send_results_confirmed([]))
        self.assertFalse(
            MODULE.all_send_results_confirmed(
                [{"success": True}, {"success": False}],
            )
        )
        self.assertTrue(
            MODULE.all_send_results_confirmed(
                [{"success": True}, {"success": True}],
            )
        )

    def test_reply_uses_one_merged_platform_send(self):
        source = (
            Path(__file__).parents[1]
            / "maibot_core"
            / "maisaka"
            / "builtin_tool"
            / "reply.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MessageSequence(flatten_message_components(reply_sequences))", source)
        self.assertNotIn("for index, reply_sequence in enumerate(reply_sequences)", source)

    def test_uncertain_receipt_stops_automatic_retry(self):
        reply_source = (
            Path(__file__).parents[1]
            / "maibot_core"
            / "maisaka"
            / "builtin_tool"
            / "reply.py"
        ).read_text(encoding="utf-8")
        host_source = (Path(__file__).parents[1] / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("except send_service.DeliveryUncertainError", reply_source)
        self.assertIn('reply_metadata["pause_execution"] = True', reply_source)
        self.assertIn("raise DeliveryUncertainError", host_source)
