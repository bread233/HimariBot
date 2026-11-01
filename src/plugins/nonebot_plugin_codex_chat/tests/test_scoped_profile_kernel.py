"""隔离画像读取：不允许从其他群、旧数据或全局快照生成摘要。"""
import ast
import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1] / "maibot_core/A_memorix/core/runtime"
spec = importlib.util.spec_from_file_location("profile_scope_policy", ROOT / "profile_scope_policy.py")
policy = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


class ScopedProfileKernelTest(unittest.TestCase):
    def test_cross_group_and_legacy_data_not_returned(self):
        tree = ast.parse((ROOT / "sdk_memory_kernel.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SDKMemoryKernel")
        method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                      and node.name == "get_scoped_person_profile")
        # 只提取方法体，替换相对导入为测试内策略。
        method.body = method.body[1:]
        namespace = {"TrustedProfileScope": policy.TrustedProfileScope,
                     "can_read_fact": policy.can_read_fact}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     "<scoped-profile>", "exec"), namespace)
        rows = [
            {"hash": "a", "content": "群100", "metadata": {"person_ids": ["qq1"],
             "visibility": "group_private", "source_group_id": "100"}},
            {"hash": "b", "content": "群200秘密", "metadata": {"person_ids": ["qq1"],
             "visibility": "group_private", "source_group_id": "200"}},
            {"hash": "c", "content": "旧版秘密", "metadata": {"person_ids": ["qq1"]}},
            {"hash": "d", "content": "公开事实", "metadata": {"person_ids": ["qq1"],
             "visibility": "public", "source_group_id": "200"}},
        ]
        class Kernel:
            metadata_store = SimpleNamespace(get_paragraphs_by_entity=lambda pid: rows)
            async def initialize(self):
                pass
        scope = policy.TrustedProfileScope("qq", "user", "100", "session")
        result = asyncio.run(namespace["get_scoped_person_profile"](Kernel(), person_id="qq1", scope=scope))
        self.assertTrue(result["success"])
        self.assertEqual([e["hash"] for e in result["evidence"]], ["a", "d"])
        self.assertNotIn("秘密", result["summary"])
        self.assertFalse(result["has_manual_override"])


if __name__ == "__main__":
    unittest.main()
