from __future__ import annotations

from ...extension import Extension  # 从当前插件里的 extension.py 引用基类


class ReplyMergeExtension(Extension):
    """兼容用的 ReplyMergeExtension，最简实现版本

    只为了满足 nonebot_plugin_memes_api 对它的依赖，
    不做任何实际处理。
    """

    @property
    def id(self) -> str:
        # 全局唯一 id，随便起名，不和别的 Extension 冲突就行
        return "reply.merge"

    @property
    def priority(self) -> int:
        # 扩展执行优先级，数字越小优先级越高
        return 10
