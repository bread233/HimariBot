from __future__ import annotations

"""maibot_core 的导入 bootstrap。

将顶层 `src` 兼容别名指向当前插件内的 `maibot_core` 根目录，
以便复用原 Maibot 源码中大量 `from src...` 导入，而不必批量重写。
"""

from pathlib import Path
import sys
import types


def bootstrap_src_alias() -> None:
    """注册 `src` 兼容包别名。"""

    package_name = "src"
    package_root = Path(__file__).resolve().parent

    module = sys.modules.get(package_name)
    if module is None:
        module = types.ModuleType(package_name)
        module.__file__ = str(package_root / "__init__.py")
        module.__package__ = package_name
        module.__path__ = [str(package_root)]
        sys.modules[package_name] = module
        return

    existing_path = list(getattr(module, "__path__", []))
    root_str = str(package_root)
    if root_str not in existing_path:
        existing_path.insert(0, root_str)
        module.__path__ = existing_path


bootstrap_src_alias()
