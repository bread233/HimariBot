"""Planner 提交后台生图任务。"""
from __future__ import annotations

from typing import Optional

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.plugins.nonebot_plugin_codex_chat.image_generation import submit_image_job

from .context import BuiltinToolRuntimeContext


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="generate_image",
        description="当用户明确要求创作或绘制新图片时调用。指定作品角色先核实身份，优先 web_search 的 images 模式找可信官方角色立绘，确认人物匹配后以 reference_image_url 传公开 HTTPS 图片直链；无可信图片时才按已核实文字特征绘制，禁止编造官方外观。后台自动引用原消息发图；同一 msg_id 只能提交一次，成功提交后不得额外 reply 或重复提交。",
        parameters_schema={
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "description": "请求画图的原始消息编号"},
                "prompt": {"type": "string", "description": "详细生图提示词：准确角色名、作品、经可靠资料核实的关键外观及用户要求的场景；禁止把未核实的发型、发色、瞳色等写成官方特征"},
                "caption": {"type": "string", "description": "随图片一起发送的简短文字，可为空", "default": ""},
                "reference_image_url": {"type": "string", "description": "可选：已核实角色身份的公开 HTTPS 图片直链；优先官方角色立绘，不能使用未经核实的搜索缩略图"},
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
    reference_url = str(args.get("reference_image_url") or "").strip()
    if len(reference_url) > 2048:
        return tool_ctx.build_failure_result(invocation.tool_name, "参考图 URL 过长。")
    if not prompt or len(prompt) > 6000:
        return tool_ctx.build_failure_result(invocation.tool_name, "生图提示词不能为空或超过 6000 字符。")
    target = tool_ctx.runtime.find_source_message_by_id(message_id)
    if target is None:
        return tool_ctx.build_failure_result(invocation.tool_name, "找不到生图请求的原始消息。")
    if tool_ctx.runtime.chat_stream.platform != "onebot.v11":
        return tool_ctx.build_failure_result(invocation.tool_name, "当前仅支持 QQ 生图。")
    try:
        job_id, created = submit_image_job(prompt, caption[:500], tool_ctx.runtime.session_id, target, True, reference_url)
    except RuntimeError as exc:
        return tool_ctx.build_failure_result(invocation.tool_name, str(exc))
    return tool_ctx.build_success_result(
        invocation.tool_name,
        (f"已提交后台生图任务 {job_id}，无需等待。" if created else
         f"该原消息已有生图任务 {job_id}，不再重复生成或发送。"),
        structured_content={"job_id": job_id, "status": "queued" if created else "already_submitted", "msg_id": message_id},
    )
