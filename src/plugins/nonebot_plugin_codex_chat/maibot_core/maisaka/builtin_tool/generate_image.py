"""Planner 提交后台生图任务。"""
from __future__ import annotations

from io import BytesIO
import time
from typing import Optional

from PIL import Image
from src.common.data_models.message_component_data_model import ImageComponent, ReplyComponent
from src.config.config import global_config
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.plugins.nonebot_plugin_codex_chat.image_generation import get_image_job_status, submit_image_job

from ..reply_target_guard import evaluate_runtime_target
from ..image_clarification import load_image_clarification, _user_id as clarification_user_id
from .context import BuiltinToolRuntimeContext


async def _resolve_reference_image_bytes(runtime: object, target: object, reference_msg_id: str) -> bytes:
    """只读取同会话、当前请求明确关联的原始消息图片；不混用引用展开内容。"""
    session_id = str(getattr(runtime, "session_id", "") or "")
    if not session_id or str(getattr(target, "session_id", "") or "") != session_id:
        raise ValueError("无法确认生图请求所属会话。")
    source = runtime.find_source_message_by_id(reference_msg_id)
    if source is None or str(getattr(source, "session_id", "") or "") != session_id:
        raise ValueError("找不到同会话的参考图消息。")
    request_parts = getattr(getattr(target, "raw_message", None), "components", ()) or ()
    if reference_msg_id != str(getattr(target, "message_id", "") or "") and not any(
        isinstance(part, ReplyComponent) and str(part.target_message_id or "").strip() == reference_msg_id
        for part in request_parts
    ):
        raise ValueError("参考图必须来自当前消息，或当前请求明确引用的消息。")
    source_parts = getattr(getattr(source, "raw_message", None), "components", ()) or ()
    images = [part for part in source_parts if isinstance(part, ImageComponent)]
    if any(isinstance(part, ReplyComponent) for part in source_parts):
        if source is target:
            images = [part for part in images if getattr(part, "_onebot_direct_attachment", False)]
        elif not any(
            getattr(entry, "original_message", None) is source and getattr(entry, "source_kind", "") == "generated_image"
            for entry in getattr(runtime, "_chat_history", ())
        ):
            raise ValueError("参考消息含引用展开内容，无法确认图片归属。")
    if len(images) != 1:
        raise ValueError("参考消息必须恰好包含一张原始图片。")
    image = images[0]
    if not image.binary_data:
        try:
            await image.load_image_binary()
        except Exception as exc:
            raise ValueError("参考图片数据不可读取。") from exc
    data = image.binary_data
    if not isinstance(data, bytes) or not 32 <= len(data) <= 8 * 1024 * 1024:
        raise ValueError("参考图为空、过小或超过 8 MB。")
    try:
        with Image.open(BytesIO(data)) as opened:
            if opened.format not in {"PNG", "JPEG", "WEBP"} or not (1 <= opened.width <= 8192 and 1 <= opened.height <= 8192):
                raise ValueError("参考图格式或尺寸不受支持。")
            opened.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("参考图不是有效的 PNG/JPEG/WebP 图片。") from exc
    return data


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="generate_image",
        description=(
            "仅在用户明确要求画新图或修改、重画已有图片时调用。"
            "单独发送图片、仅说“这是参考图”或补充旧任务资料，不代表要求立即生图；不得把后续图片自动关联到已提交任务。"
            "修改旧图时，若用户在新消息中明确提出修改要求，必须使用该新消息的 msg_id 提交新任务，不能复用旧请求 msg_id；可参考引用消息理解需求。"
            "QQ 参考图使用 reference_msg_id（当前消息或明确引用的同会话消息）；验证后作为本次新任务的参考图传入 Codex。"
            "参考图校验失败时必须解释原因或请用户重新提供图片，不得移除参考图参数改为纯文字生图。"
            "reference_image_url 仅接受已核实的公开 HTTPS 图片直链；未实际传入参考图不得声称已使用。"
            "指定作品角色先核实身份，优先 web_search 的 images 模式找可信官方角色立绘；身份已确认后不要反复搜索，无可信图片时按已核实文字特征绘制，禁止编造官方外观。若同一用户普通发言经 Planner 判断是旧绘图澄清的补充，合并原请求并使用当前消息有效 msg_id 提交，new_image_request=false；独立新绘图设 true。"
            "后台自动引用请求消息发图；同一 msg_id 只能提交一次，成功提交后不得额外 reply 或重复提交。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "msg_id": {"type": "string", "description": "本轮有效用户消息 ID；旧图澄清补充也使用当前消息 ID，不得复用原请求 ID"},
                "prompt": {"type": "string", "description": "详细生图提示词：准确角色名、作品、经可靠资料核实的关键外观及用户要求的场景；禁止把未核实的发型、发色、瞳色等写成官方特征"},
                "caption": {"type": "string", "description": "随图片一起发送的简短文字，可为空", "default": ""},
                "reference_image_url": {"type": "string", "description": "可选：已核实角色身份的公开 HTTPS 图片直链；优先官方角色立绘，不能使用未经核实的搜索缩略图"},
                "reference_msg_id": {"type": "string", "description": "可选：当前消息或当前请求明确引用的同会话 QQ 图片消息 ID；验证后将图片传给 Codex"},
                "new_image_request": {"type": "boolean", "description": "仅当 LLM 确认本轮是独立的新绘图请求、而非此前澄清的补充时设为 true", "default": False},
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
    reference_msg_id = str(args.get("reference_msg_id") or "").strip()
    new_image_request = args.get("new_image_request") is True
    if "reference_msg_id" in args and not reference_msg_id:
        return tool_ctx.build_failure_result(invocation.tool_name, "参考图消息 ID 不能为空。")
    if reference_msg_id and (len(reference_msg_id) > 128 or reference_url):
        return tool_ctx.build_failure_result(invocation.tool_name, "参考图消息 ID 过长，或同时指定了两种参考图来源。")
    if len(reference_url) > 2048:
        return tool_ctx.build_failure_result(invocation.tool_name, "参考图 URL 过长。")
    if not prompt or len(prompt) > 6000:
        return tool_ctx.build_failure_result(invocation.tool_name, "生图提示词不能为空或超过 6000 字符。")
    target = tool_ctx.runtime.find_source_message_by_id(message_id)
    if target is None:
        return tool_ctx.build_failure_result(invocation.tool_name, "找不到生图请求的原始消息。")
    if tool_ctx.runtime.chat_stream.platform != "onebot.v11":
        return tool_ctx.build_failure_result(invocation.tool_name, "当前仅支持 QQ 生图。")
    if message_id not in getattr(tool_ctx.runtime, "_active_reply_request_ids", set()):
        return tool_ctx.build_failure_result(invocation.tool_name, "生图请求不属于当前有效消息批次。")
    guard = evaluate_runtime_target(
        tool_ctx.runtime, target, float(global_config.chat.reply_target_max_age_seconds), time.time(),
    )
    if not guard.allowed:
        return tool_ctx.build_failure_result(invocation.tool_name, f"生图请求目标已失效：{guard.reason}")
    clarification = load_image_clarification(tool_ctx.runtime.session_id, clarification_user_id(target))
    if (clarification and not new_image_request and clarification.get("reference_required")
            and str(clarification.get("original_msg_id")) != message_id
            and not reference_msg_id and not reference_url):
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "之前的绘图请求包含参考图。请用户在新消息里重新附图或明确引用原图，并传入 reference_msg_id；不得忽略参考图直接生图。",
        )
    if not reference_msg_id and not reference_url:
        parts = getattr(target.raw_message, "components", ()) or ()
        sources = [target]
        for part in parts:
            if isinstance(part, ReplyComponent):
                source = tool_ctx.runtime.find_source_message_by_id(str(part.target_message_id or ""))
                if source is not None and str(getattr(source, "session_id", "")) == tool_ctx.runtime.session_id:
                    sources.append(source)
        if any(isinstance(part, ImageComponent) for source in sources for part in source.raw_message.components):
            return tool_ctx.build_failure_result(
                invocation.tool_name, "请求包含图片参考，请指定 reference_msg_id 或 reference_image_url，避免误作纯文字生图。",
            )
    reference_bytes = None
    if reference_msg_id:
        try:
            reference_bytes = await _resolve_reference_image_bytes(tool_ctx.runtime, target, reference_msg_id)
        except ValueError as exc:
            return tool_ctx.build_failure_result(invocation.tool_name, str(exc))
    try:
        job_id, created = submit_image_job(
            prompt, caption[:500], tool_ctx.runtime.session_id, target, True, reference_url,
            reference_image_bytes=reference_bytes,
        )
    except RuntimeError as exc:
        return tool_ctx.build_failure_result(invocation.tool_name, str(exc))
    status = "pending" if created else (get_image_job_status(tool_ctx.runtime.session_id, message_id) or {}).get("status", "unknown")
    return tool_ctx.build_success_result(
        invocation.tool_name,
        (f"已提交后台生图任务 {job_id}，无需等待。" if created else
         f"该原消息已有生图任务 {job_id}，当前状态：{status}，不再重复生成或发送。"),
        structured_content={"job_id": job_id, "status": status, "msg_id": message_id},
        metadata={"pause_execution": True},
    )
