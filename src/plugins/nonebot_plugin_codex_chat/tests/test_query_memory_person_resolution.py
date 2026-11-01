"""Static regression checks for query_memory person resolution."""

import ast
import unittest
from unittest.mock import Mock
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "maibot_core/maisaka/builtin_tool/query_memory.py"


class QueryMemoryPersonResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.func = next(
            node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_resolve_person_id"
        )
        cls.source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), cls.func)

    def test_resolver_is_imported(self):
        self.assertTrue(any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == "resolve_person_id_for_memory" for alias in node.names)
            for node in self.tree.body
        ))

    def test_named_person_resolution(self):
        self.assertIn("if clean_person_name:", self.source)
        self.assertIn("person_name=clean_person_name", self.source)

    def test_private_sender_fallback(self):
        self.assertIn("if not group_id and platform and user_id:", self.source)
        self.assertIn("user_id=user_id", self.source)



    def resolve(self, *, name="", group="", resolved_id="person-123"):
        resolver = Mock(return_value=resolved_id)
        scope = {"resolve_person_id_for_memory": resolver, "Tuple": tuple}
        exec(compile(ast.Module(body=[self.func], type_ignores=[]), str(SOURCE), "exec"), scope)
        result = scope["_resolve_person_id"](
            person_name=name, platform="qq", user_id="123", group_id=group
        )
        return result, resolver

    def test_named_person_behavior(self):
        result, resolver = self.resolve(name="琉璃", group="456")
        self.assertEqual(result, ("person-123", "琉璃"))
        resolver.assert_called_once_with(person_name="琉璃", platform="qq", user_id="123")

    def test_private_sender_behavior(self):
        result, resolver = self.resolve()
        self.assertEqual(result, ("person-123", ""))
        resolver.assert_called_once_with(platform="qq", user_id="123")

    def test_group_without_name_behavior(self):
        result, resolver = self.resolve(group="456")
        self.assertEqual(result, ("", ""))
        resolver.assert_not_called()

    def test_unknown_name_behavior(self):
        result, resolver = self.resolve(name="未知", group="456", resolved_id="")
        self.assertEqual(result, ("", "未知"))
        resolver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
