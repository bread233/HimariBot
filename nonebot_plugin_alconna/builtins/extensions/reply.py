"""
兼容用的 ReplyMergeExtension 空实现

原版 nonebot_plugin_alconna 提供了:
    nonebot_plugin_alconna.builtins.extensions.reply.ReplyMergeExtension

你现在用的是自带的 service/nonebot_plugin_alconna，
里面没有这个模块，所以这里补一个“占位实现”，
让依赖它的插件(比如 nonebot_plugin_memes_api)能正常 import。
"""

from src.service.nonebot_plugin_alconna.extension import Extension


class ReplyMergeExtension(Extension):
    """空实现，只用于兼容，真正功能可以以后再补"""

    # 一般 Extension 会被当作“扩展标记类”使用
    # 如果以后需要真正的“合并回复”功能，可以参考原项目实现再完善
    ...
    

__all__ = ["ReplyMergeExtension"]
