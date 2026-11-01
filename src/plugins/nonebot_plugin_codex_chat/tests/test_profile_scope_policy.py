"""P0 群作用域隔离契约。"""
import importlib.util
import unittest
from types import SimpleNamespace
from pathlib import Path

POLICY = Path(__file__).parents[1] / "maibot_core/A_memorix/core/runtime/profile_scope_policy.py"
spec = importlib.util.spec_from_file_location("profile_scope_policy_test", POLICY)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ProfileScopePolicyTests(unittest.TestCase):
    def test_scope_comes_from_runtime_not_model_arguments(self):
        stream = SimpleNamespace(platform="qq", user_id="42", group_id="100")
        runtime = SimpleNamespace(chat_stream=stream, session_id="session-1")
        scope = policy.TrustedProfileScope.from_runtime(runtime)
        self.assertEqual((scope.platform, scope.user_id, scope.group_id), ("qq", "42", "100"))
        self.assertIsNone(policy.TrustedProfileScope.from_runtime(
            SimpleNamespace(chat_stream=SimpleNamespace(platform="qq", group_id=""))))

    def test_same_qq_different_groups(self):
        fact = {"person_id": "qq-123", "visibility": "group_private",
                "source_group_id": "100", "content": "群100内的事实"}
        self.assertTrue(policy.can_read_fact(fact, reader_group_id="100"))
        self.assertFalse(policy.can_read_fact(fact, reader_group_id="200"))

    def test_explicit_public_fact(self):
        fact = {"visibility": "public", "source_group_id": "100"}
        self.assertTrue(policy.can_read_fact(fact, reader_group_id="200"))
        self.assertFalse(policy.can_read_fact(fact, reader_group_id=""))

    def test_legacy_unscoped_is_not_public(self):
        self.assertFalse(policy.can_read_fact({"content": "旧数据"}, reader_group_id="100"))
        self.assertFalse(policy.can_read_fact(
            {"visibility": "group_private", "content": "来源不明"}, reader_group_id="100"))

    def test_unknown_visibility_fails_closed(self):
        self.assertFalse(policy.can_read_fact(
            {"visibility": "shared", "source_group_id": "100"}, reader_group_id="200"))

    def test_filter_does_not_change_person_identity(self):
        facts = [
            {"person_id": "qq-123", "visibility": "group_private", "source_group_id": "100"},
            {"person_id": "qq-123", "visibility": "group_private", "source_group_id": "200"},
            {"person_id": "qq-123", "visibility": "public", "source_group_id": "200"},
        ]
        visible = policy.filter_visible_facts(facts, reader_group_id="100")
        self.assertEqual(len(visible), 2)
        self.assertEqual({item["person_id"] for item in visible}, {"qq-123"})


if __name__ == "__main__":
    unittest.main()
