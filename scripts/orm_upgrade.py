"""Run project Alembic migrations without loading business plugins."""

import nonebot

nonebot.init()
for name in ("nonebot_plugin_orm", "nonebot_plugin_user", "nonebot_plugin_skland"):
    if nonebot.load_plugin(name) is None:
        raise RuntimeError(f"Required plugin failed to load: {name}")

from nonebot_plugin_orm import _init_orm
from nonebot_plugin_orm.__main__ import main

_init_orm()
main(args=["upgrade"], standalone_mode=False)
