"""
message_receive 包入口

避免包级别 eager import 触发 emoji/database 等重初始化。
需要时请直接从具体模块导入。
"""

__all__ = ["chat_manager", "emoji_manager"]
