"""Production-style plugin import smoke test. Run in a fresh Python process."""
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

class PluginImportTests(unittest.TestCase):
    def test_plugin_import_and_model_identity(self):
        try:
            import nonebot
            from nonebot.adapters.onebot.v11 import Adapter
            from sqlmodel import SQLModel
        except ImportError as exc:
            self.skipTest("runtime dependency unavailable: " + str(exc))
        try:
            nonebot.get_driver()
        except ValueError:
            nonebot.init(driver="~fastapi", command_start={"/"})
        nonebot.get_driver().register_adapter(Adapter)
        plugin_name = "src.plugins.nonebot_plugin_codex_chat"
        importlib.import_module(plugin_name)
        from src.common.database.database_model import HimariBotAffinity
        model_name = "src.common.database.database_model"
        self.assertIs(sys.modules[model_name].HimariBotAffinity, HimariBotAffinity)
        self.assertIs(SQLModel.metadata.tables["himaribot_affinity"], HimariBotAffinity.__table__)
        alternate = plugin_name + ".maibot_core.common.database.database_model"
        self.assertNotIn(alternate, sys.modules, "database model loaded twice under distinct names")
        self.assertIn(plugin_name, sys.modules)

if __name__ == "__main__":
    unittest.main()
