"""P0-4: 普通工具及伪造参数不能调用全局画像管理。"""
import ast
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).parents[1] / "maibot_core"
ACCESS = ROOT / "A_memorix/admin_access.py"
spec = importlib.util.spec_from_file_location("profile_admin_access_test", ACCESS)
access = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = access
spec.loader.exec_module(access)


class ProfileAdminAuthorizationTests(unittest.TestCase):
    def test_capability_not_forgeable_from_payload(self):
        self.assertFalse(access.is_profile_admin_capability(None))
        self.assertFalse(access.is_profile_admin_capability(True))
        self.assertFalse(access.is_profile_admin_capability("admin"))
        self.assertFalse(access.is_profile_admin_capability({"is_admin": True}))
        with self.assertRaises(PermissionError):
            access.issue_webui_profile_admin_capability("")
        cap = access.issue_webui_profile_admin_capability("verified-session")
        self.assertTrue(access.is_profile_admin_capability(cap))

    def test_host_requires_capability_before_kernel_access(self):
        source = (ROOT / "A_memorix/host_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AMemorixHostService")
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == "invoke_authorized_profile_admin")
        method.body = method.body[1:]
        namespace = {"is_profile_admin_capability": access.is_profile_admin_capability}
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[])),
                     "<profile-admin>", "exec"), namespace)
        kernel = SimpleNamespace(memory_profile_admin=AsyncMock(return_value={"success": True}))
        class Host:
            def is_enabled(self):
                return True
            async def _ensure_kernel(self):
                return kernel
        invoke = namespace[method.name]
        denied = asyncio.run(invoke(Host(), action="query", capability={"is_admin": True}))
        self.assertEqual(denied["error"], "profile_admin_forbidden")
        self.assertEqual(kernel.memory_profile_admin.await_count, 0)
        cap = access.issue_webui_profile_admin_capability("verified-session")
        allowed = asyncio.run(invoke(Host(), action="query", capability=cap, person_id="qq1"))
        self.assertTrue(allowed["success"])
        kernel.memory_profile_admin.assert_awaited_once_with(action="query", person_id="qq1")

    def test_public_tool_and_generic_host_are_blocked(self):
        plugin = (ROOT / "A_memorix/plugin.py").read_text(encoding="utf-8")
        host = (ROOT / "A_memorix/host_service.py").read_text(encoding="utf-8")
        self.assertIn('"error": "profile_admin_forbidden"', plugin)
        self.assertIn('if component_name == "memory_profile_admin":', host)
        self.assertIn('"error": "profile_admin_forbidden"', host)


if __name__ == "__main__":
    unittest.main()
