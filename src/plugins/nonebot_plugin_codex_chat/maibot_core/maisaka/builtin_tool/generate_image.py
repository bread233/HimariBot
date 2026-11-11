"""Planner 提交后台生图任务。"""
from __future__ import annotations

from typing import Optional

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.plugins.nonebot_plugin_codex_chat.image_generation import submit_image_job

from .context import BuiltinToolRuntimeContext


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="generate_image",
        description="当用户明确要求创作或绘制新图片时调用。根据自然语言理解意图，不依赖关键词。提交后后台生成并自动引用原消息发送图片，普通聊天不等待；成功提交后不要再用 reply 承诺图片已完成，也不要重复调用。",
        parameters_schema={
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "description": "请求画图的原始消息编号"},
                "prompt": {"type": "string", "description": "详细的图片生成提示词"},
                "caption": {"type": "string", "description": "随图片一起发送的简短文字，可为空", "default": ""},
            },
            "required": ["msg_id", "prompt"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    del context
    args = invocation.arguments or {}
    message_id = str(args.get("msg_id") or "").strip()
    prompt = str(args.get("prompt") or "").strip()
    caption = str(args.get("caption") or "").strip()
    if not prompt or len(prompt) > 6000:
        return tool_ctx.build_failure_result(invocation.tool_name, "生图提示词不能为空或超过 6000 字符。")
    target = tool_ctx.runtime.find_source_message_by_id(message_id)
    if target is None:
        return tool_ctx.build_failure_result(invocation.tool_name, "找不到生图请求的原始消息。")
    if tool_ctx.runtime.chat_stream.platform != "onebot.v11":
        return tool_ctx.build_failure_result(invocation.tool_name, "当前仅支持 QQ 生图。")
    try:
        job_id, created = submit_image_job(prompt, caption[:500], tool_ctx.runtime.session_id, target, True)
    except RuntimeError as exc:
        return tool_ctx.build_failure_result(invocation.tool_name, str(exc))
    return tool_ctx.build_success_result(
        invocation.tool_name,
        (f"已提交后台生图任务 {job_id}，无需等待。" if created else
         f"该原消息已有生图任务 {job_id}，不再重复生成或发送。"),
        structured_content={"job_id": job_id, "status": "queued" if created else "already_submitted", "msg_id": message_id},
    )
