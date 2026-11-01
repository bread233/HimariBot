
import unittest
from concurrent.futures import ThreadPoolExecutor

from test_onebot_mood_mock import mood, quota


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        mood.reset_mood()
        mood.apply_mood_event(valence=20)
        with quota._lock:
            quota._usage.clear()
            quota._reservations.clear()

    def expire(self, token):
        group, day, created = quota._reservations[token]
        quota._reservations[token] = (
            group, day, created - quota.RESERVATION_SECONDS - 1
        )

    def test_expired_token_rejected(self):
        token = quota.reserve_expression("groupA")
        self.expire(token)
        self.assertFalse(quota.confirm_delivered("groupA", token))
        self.assertNotIn("groupA", quota._usage)

    def test_late_ack_preserves_new_reservation(self):
        old = quota.reserve_expression("groupA")
        self.expire(old)
        new = quota.reserve_expression("groupA")
        self.assertIsNotNone(new)
        self.assertFalse(quota.confirm_delivered("groupA", old))
        self.assertTrue(quota.confirm_delivered("groupA", new))
        self.assertEqual(quota._usage["groupA"][1], 1)

    def test_old_release_preserves_new_reservation(self):
        old = quota.reserve_expression("groupA")
        self.expire(old)
        new = quota.reserve_expression("groupA")
        quota.release_expression(old)
        self.assertIn(new, quota._reservations)

    def test_parallel_confirm_once(self):
        token = quota.reserve_expression("groupA")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: quota.confirm_delivered("groupA", token),
                range(16),
            ))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(quota._usage["groupA"][1], 1)

    def test_parallel_release_once(self):
        token = quota.reserve_expression("groupA")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: quota.release_expression(token),
                range(16),
            ))
        self.assertEqual(results.count(True), 1)

    def test_cross_group_expiry_isolation(self):
        old = quota.reserve_expression("groupA")
        other = quota.reserve_expression("groupB")
        self.expire(old)
        self.assertFalse(quota.confirm_delivered("groupA", old))
        self.assertTrue(quota.confirm_delivered("groupB", other))
        self.assertNotIn("groupA", quota._usage)


if __name__ == "__main__":
    unittest.main()
