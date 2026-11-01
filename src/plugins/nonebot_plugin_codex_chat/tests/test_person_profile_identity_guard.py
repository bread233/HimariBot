"""人物别名解析歧义的轻量回归测试，不依赖数据库启动。"""
import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SOURCE = Path(__file__).parents[1] / "maibot_core/A_memorix/core/utils/person_profile_service.py"


class PersonProfileIdentityGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PersonProfileService")
        method = next(n for n in service.body if isinstance(n, ast.FunctionDef) and n.name == "resolve_person_id")
        cls.method = ast.FunctionDef(
            name=method.name, args=method.args, body=method.body,
            decorator_list=[], returns=method.returns, type_comment=None,
        )

    def resolve(self, identifier, results):
        session = MagicMock()
        session.exec.side_effect = [MagicMock(first=lambda: None)] + [
            MagicMock(all=lambda values=values: values) for values in results
        ]
        context = MagicMock()
        context.__enter__.return_value = session
        scope = {
            "get_db_session": lambda **kwargs: context,
            "select": lambda *args: MagicMock(),
            "PersonInfo": MagicMock(),
            "or_": lambda *args: MagicMock(),
            "logger": MagicMock(),
        }
        exec(compile(ast.Module(body=[self.method], type_ignores=[]), str(SOURCE), "exec"), scope)
        return scope["resolve_person_id"](identifier)

    def test_duplicate_nicknames_fail_closed(self):
        self.assertEqual(self.resolve("同名", [["person-a", "person-b"]]), "")

    def test_unique_nickname_resolves(self):
        self.assertEqual(self.resolve("唯一", [["person-a"]]), "person-a")

    def test_duplicate_group_cards_fail_closed(self):
        self.assertEqual(self.resolve("群名片", [[], ["person-a", "person-b"]]), "")

    def test_unique_group_card_resolves(self):
        self.assertEqual(self.resolve("群名片", [[], ["person-b"]]), "person-b")


if __name__ == "__main__":
    unittest.main()
