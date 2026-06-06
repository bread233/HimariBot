"""
MaiBot模块系统
包含聊天、情绪、记忆、日程等功能模块
"""

# 包级别不再 eager import 重模块，避免 bridge smoke 触发数据库/配置初始化。
# 需要时请直接从具体模块导入：
#   from .message_receive.chat_manager import chat_manager
#   from ..emoji_system.emoji_manager import emoji_manager

__all__ = ["chat_manager", "emoji_manager"]
