# src/plugins/qq_test/__init__.py

from nonebot import on_message
from nonebot.adapters.qq import MessageEvent

# 优先级高一点，block=False 不影响别的插件
test_msg = on_message(priority=1, block=False)


@test_msg.handle()
async def _(event: MessageEvent):
    # 取纯文本
    text = event.get_plaintext().strip()

    # 只要消息里包含 /test 就回复
    if "/test" in text:
        await test_msg.finish("✅ 收到 /test 了，说明 QQ WebHook + 插件 都正常！")
