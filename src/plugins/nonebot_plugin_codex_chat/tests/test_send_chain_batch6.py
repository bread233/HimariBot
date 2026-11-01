"""OneBot integration contract tests."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SendChainTests(unittest.TestCase):
    def test_outbound_context(self):
        source = (ROOT / 'maibot_core/outbound.py').read_text(encoding='utf-8')
        self.assertIn('mood_reservation=_current_mood_reservation.get()', source)

    def test_bridge_forwards_reservation(self):
        source = (ROOT / 'maibot_core/bridge.py').read_text(encoding='utf-8')
        self.assertIn('mood_reservation=getattr(msg, "mood_reservation", None)', source)

    def test_reply_sets_and_resets_scope(self):
        source = (ROOT / 'maibot_core/maisaka/builtin_tool/reply.py').read_text(encoding='utf-8')
        self.assertIn('reserve_expression(mood_group_id)', source)
        self.assertIn('set_mood_reservation(mood_reservation)', source)
        self.assertIn('reset_mood_reservation(reservation_scope)', source)

    def test_host_confirms_after_send(self):
        source = (ROOT / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('if onebot_message is None:', source)
        self.assertIn('confirm_delivered(target_id, reply.mood_reservation)', source)

    def test_outbound_capture_propagates_scope(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('batch6_outbound', ROOT / 'maibot_core/outbound.py')
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with module.OutboundCapture() as capture:
            scope = module.set_mood_reservation('reservation-example')
            try:
                self.assertTrue(module.capture_outbound_message('hello'))
            finally:
                module.reset_mood_reservation(scope)
            self.assertEqual(capture.messages[0].mood_reservation, 'reservation-example')
        self.assertFalse(module.capture_outbound_message('outside'))

    def test_outbound_scope_reset_on_exception(self):
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location('batch6_outbound_exception', ROOT / 'maibot_core/outbound.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        with module.OutboundCapture() as capture:
            scope = module.set_mood_reservation('temporary')
            try:
                raise RuntimeError('simulated')
            except RuntimeError:
                pass
            finally:
                module.reset_mood_reservation(scope)
            module.capture_outbound_message('normal')
            self.assertIsNone(capture.messages[0].mood_reservation)

if __name__ == '__main__':
    unittest.main()
