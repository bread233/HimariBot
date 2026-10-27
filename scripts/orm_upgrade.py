"""Run project Alembic migrations without loading business plugins."""

import nonebot

nonebot.init()
if nonebot.load_plugin("nonebot_plugin_orm") is None:
    raise RuntimeError("Required plugin failed to load: nonebot_plugin_orm")

from nonebot_plugin_orm.__main__ import main

main(args=["upgrade"], standalone_mode=False)
