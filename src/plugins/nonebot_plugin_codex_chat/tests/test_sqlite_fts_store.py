"""SQLite-only memory backend regression tests."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "maibot_core/A_memorix/core/storage/sqlite_fts_store.py"
spec = importlib.util.spec_from_file_location("sqlite_fts_store", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SQLiteFTSMemoryStore = module.SQLiteFTSMemoryStore


class SQLiteFTSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteFTSMemoryStore(Path(self.tmp.name) / "memory.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_profile_identity_and_alias_merge(self):
        self.store.upsert_profile(
            qq_id="123", group_id="456", group_name="测试群",
            group_nickname="免费鸡蛋", original_nickname="面包",
            aliases=["小面包"], notes={"speaking_style": "喜欢用颜文字"},
        )
        self.store.upsert_profile(qq_id="123", group_id="456", aliases=["小包"])
        profile = self.store.get_profile(qq_id="123", group_id="456")
        self.assertEqual(profile["group_nickname"], "免费鸡蛋")
        self.assertEqual(profile["original_nickname"], "面包")
        self.assertEqual(profile["aliases"], ["小面包", "小包"])
        self.assertEqual(profile["notes"]["speaking_style"], "喜欢用颜文字")

    def test_group_scoping(self):
        self.store.upsert_profile(qq_id="123", group_id="1", group_nickname="甲")
        self.store.upsert_profile(qq_id="123", group_id="2", group_nickname="乙")
        self.assertEqual(self.store.get_profile(qq_id="123", group_id="2")["group_nickname"], "乙")

    def test_fts_chinese_and_group_filter(self):
        self.store.add_memory("小面包喜欢玩鸣潮", qq_id="123", group_id="1")
        self.store.add_memory("小面包喜欢喝茶", qq_id="123", group_id="2")
        found = self.store.search("喜欢鸣潮", group_id="1")
        self.assertEqual(len(found), 1)
        self.assertIn("鸣潮", found[0]["content"])
        self.assertEqual(len(self.store.search("鸣潮", group_id="2")), 0)

    def test_no_match(self):
        self.assertEqual(self.store.search("完全不存在的关键词"), [])


if __name__ == "__main__":
    unittest.main()
