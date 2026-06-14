"""vision_caption 内置工具 — 描述图片的视觉内容。"""

import json
import time
from typing import Any, Optional

import httpx

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext
from .send_image import _collect_images_from_sequence, _find_context_message_by_id


logger = __import__("nonebot").logger


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="vision_caption",
        description='用于描述图片、表情、截图、梗图的大致视觉内容。适合回答"这是什么图""这图啥意思""什么梗""图里发生了什么""这个动态是什么"等问题。不适合精确 OCR；读文字时优先使用 ocr_image。',
        parameters_schema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "图片消息 ID（必填）",
                },
                "media_index": {
                    "type": "integer",
                    "description": "候选图片中的序号，从 0 开始，可选",
                    "default": 0,
                },
            },
            "required": ["message_id"],
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
    arguments = dict(invocation.arguments or {})

    logger.info(f"codex_chat_vision_caption_start args={json.dumps(arguments, ensure_ascii=False)}")

    from src.plugins.nonebot_plugin_codex_chat.config import get_config as _get_plugin_config
    config = _get_plugin_config()

    caption_url = (config.codex_chat_vision_caption_url or "").strip()
    if not caption_url:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "Vision Caption 服务未配置（codex_chat_vision_caption_url 为空）。",
        )

    timeout = max(1, int(config.codex_chat_vision_caption_timeout) if config.codex_chat_vision_caption_timeout else 60)

    message_id = str(arguments.get("message_id") or "").strip()
    if not message_id:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "缺少参数 message_id。",
        )

    media_index = 0
    try:
        media_index = max(0, int(arguments.get("media_index") or 0))
    except (TypeError, ValueError):
        media_index = 0

    target_message = _find_context_message_by_id(tool_ctx, message_id)
    if target_message is None:
        try:
            raw_msg = tool_ctx.runtime.find_source_message_by_id(message_id)
            if raw_msg is not None and hasattr(raw_msg, "raw_message"):
                target_message = raw_msg
        except Exception:
            pass
    if target_message is None:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"未找到指定消息：message_id={message_id}",
        )

    images = _collect_images_from_sequence(getattr(target_message, "raw_message", None))
    if not images:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"目标消息中没有找到图片：message_id={message_id}",
        )

    if media_index >= len(images):
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"图片序号超出范围：index={media_index}，该消息共有 {len(images)} 张图片。",
        )

    image = images[media_index]
    if not image.binary_data:
        try:
            await image.load_image_binary()
        except Exception as exc:
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                f"加载图片二进制数据失败：{exc}",
            )
    if not image.binary_data:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "图片数据不可读取。",
        )

    result = await _caption_by_file(caption_url, image.binary_data, timeout)
    return _build_caption_result(invocation.tool_name, result, tool_ctx, message_id, media_index)


async def _caption_by_file(base_url: str, image_data: bytes, timeout: int) -> dict[str, Any]:
    endpoint = base_url.rstrip("/")

    logger.info(f"codex_chat_vision_caption_request mode=file endpoint={endpoint}")
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            files = {"file": ("image.png", image_data, "image/png")}
            resp = await client.post(endpoint, files=files, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_vision_caption_failed error=timeout elapsed={elapsed:.3f}")
        return {"error": f"Vision Caption 请求超时（{timeout}s）。"}
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_vision_caption_failed error=request_failed detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"Vision Caption 请求失败：{exc}"}
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_vision_caption_failed error=unexpected detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"Vision Caption 请求异常：{exc}"}

    elapsed = time.perf_counter() - started
    return _parse_caption_response(data, elapsed)


def _parse_caption_response(data: Any, elapsed: float) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"error": "Vision Caption 返回格式异常：非 JSON 对象"}

    code = data.get("code")
    description = ""

    description = str(data.get("description") or "").strip()
    if not description and isinstance(data.get("data"), dict):
        inner = data["data"]
        description = str(inner.get("description") or inner.get("msg") or "").strip()
    if not description:
        description = str(data.get("text") or data.get("result") or "").strip()

    if code != 200:
        message = str(data.get("message") or data.get("msg") or description or f"code={code}").strip()
        logger.warning(f"codex_chat_vision_caption_failed error=service_error code={code} message={message}")
        return {"error": f"Vision Caption 服务返回错误：{message}"}

    if not description:
        logger.info(f"codex_chat_vision_caption_empty elapsed={elapsed:.3f}")
        return {"description": ""}

    logger.info(f"codex_chat_vision_caption_success chars={len(description)} elapsed={elapsed:.3f}")
    return {"description": description}


def _build_caption_result(
    tool_name: str, result: dict[str, Any], tool_ctx: BuiltinToolRuntimeContext,
    message_id: str, media_index: int,
) -> ToolExecutionResult:
    error = result.get("error")
    if error:
        return tool_ctx.build_failure_result(tool_name, error)

    description = result.get("description", "")
    if not description:
        logger.info(f"codex_chat_vision_caption_empty message_id={message_id} media_index={media_index}")
        return tool_ctx.build_success_result(tool_name, "视觉描述为空。", structured_content={"description": ""})

    return tool_ctx.build_success_result(tool_name, description, structured_content={"description": description})
