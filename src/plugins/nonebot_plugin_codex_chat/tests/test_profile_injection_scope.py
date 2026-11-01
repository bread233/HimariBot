"""画像自动注入的群上下文与调用链回归（无外部服务）。"""
import ast
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).parents[1] / "maibot_core"
POLICY = ROOT / "A_memorix/core/runtime/profile_scope_policy.py"
spec = importlib.util.spec_from_file_location("profile_scope_policy_injection_test", POLICY)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


def message(group_id, user_id="qq1"):
    return SimpleNamespace(
        platform="qq", session_id="session",
        message_info=SimpleNamespace(
            group_info=SimpleNamespace(group_id=group_id) if group_id else None,
            user_info=SimpleNamespace(user_id=user_id)),
    )


class ProfileInjectionScopeTests(unittest.TestCase):
    def test_message_scope_requires_group(self):
        self.assertIsNone(policy.TrustedProfileScope.from_message(message(None)))
        self.assertEqual(policy.TrustedProfileScope.from_message(message("100")).group_id, "100")

    def test_injection_uses_scoped_service_not_admin(self):
        source = (ROOT / "maisaka/person_profile_injector.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "build_person_profile_injection_messages")
        config = SimpleNamespace(a_memorix=SimpleNamespace(integration=SimpleNamespace(
            enable_person_profile_injection=True, person_profile_injection_max_profiles=2)))
        memory = SimpleNamespace(get_scoped_person_profile=AsyncMock(return_value={
            "success": True, "summary": "本群画像", "person_id": "qq1"}))
        candidate = SimpleNamespace(person_id="qq1", person_name="甲", user_id="qq1", source="recent_speaker")
        namespace = {
            "TrustedProfileScope": policy.TrustedProfileScope, "global_config": config,
            "collect_person_profile_candidates": lambda *a, **kw: [candidate],
            "memory_service": memory, "PROFILE_QUERY_LIMIT": 4,
            "build_profile_injection_text": lambda value: value,
            "_extract_profile_text": lambda value: value.get("summary", ""),
            "_profile_display_name": lambda c, p: c.person_name,
            "_truncate_profile_text": lambda s: s,
            "_format_profile_reference_block": lambda blocks: "\n".join(blocks),
            "logger": SimpleNamespace(debug=lambda *args: None),
        }
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, fn], type_ignores=[])),
                     "<injector>", "exec"), namespace)
        result = asyncio.run(namespace[fn.name](anchor_message=message("100"),
                           pending_messages=[message("200")]))
        self.assertIn("本群画像", result[0])
        args, kwargs = memory.get_scoped_person_profile.await_args
        self.assertEqual(args, ("qq1",))
        self.assertEqual(kwargs["scope"].group_id, "100")
        self.assertEqual(asyncio.run(namespace[fn.name](
            anchor_message=message(None))), [])
        self.assertEqual(memory.get_scoped_person_profile.await_count, 1)


if __name__ == "__main__":
    unittest.main()
