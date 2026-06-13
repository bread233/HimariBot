"""ocr_image 内置工具 — 识别图片中的文字。"""

import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec
from src.maisaka.context_messages import SessionBackedMessage

from .context import BuiltinToolRuntimeContext
from .send_image import _collect_images_from_sequence, _find_context_message_by_id


logger = __import__("nonebot").logger


def get_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="ocr_image",
        description="识别上下文中图片里的文字。当用户要求读图、识别图片文字、OCR、图里写了什么、截图文字、帮我看这张图上的字时使用。只能提取文字，不能可靠判断人物、场景、情绪、梗图含义。",
        parameters_schema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "指定图片消息 ID，可选",
                    "default": "",
                },
                "media_index": {
                    "type": "integer",
                    "description": "候选图片中的序号，从 0 开始，可选",
                    "default": 0,
                },
                "image_url": {
                    "type": "string",
                    "description": "图片 URL，调试用，可选",
                    "default": "",
                },
                "image_path": {
                    "type": "string",
                    "description": "本地图片路径，仅允许 /app/data/nonebot_chat_agent/ 下，可选",
                    "default": "",
                },
            },
            "required": [],
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

    logger.info(f"codex_chat_ocr_image_start args={json.dumps(arguments, ensure_ascii=False)}")

    from src.plugins.nonebot_plugin_codex_chat.config import get_config as _get_plugin_config
    config = _get_plugin_config()

    ocr_url = (config.codex_chat_ocr_url or "").strip()
    if not ocr_url:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "OCR 服务未配置（codex_chat_ocr_url 为空）。",
        )

    timeout = max(1, int(config.codex_chat_ocr_timeout) if config.codex_chat_ocr_timeout else 30)

    image_url = str(arguments.get("image_url") or "").strip()
    image_path = str(arguments.get("image_path") or "").strip()
    message_id = str(arguments.get("message_id") or "").strip()
    media_index = 0
    try:
        media_index = max(0, int(arguments.get("media_index") or 0))
    except (TypeError, ValueError):
        media_index = 0

    image_data: Optional[bytes] = None
    source_label = ""

    if image_url:
        source_label = "image_url"
        result = await _ocr_by_url(ocr_url, image_url, timeout)
        return _build_ocr_result(invocation.tool_name, result, tool_ctx)

    if image_path:
        allowed_prefix = Path("/app/data/nonebot_chat_agent").resolve()
        target_path = Path(image_path).resolve()
        try:
            target_path.relative_to(allowed_prefix)
        except ValueError:
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                "image_path 不在允许的目录 /app/data/nonebot_chat_agent/ 下。",
            )
        if not target_path.is_file():
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                f"image_path 文件不存在：{image_path}",
            )
        source_label = f"file:{image_path}"
        try:
            image_data = await _async_read_file(target_path)
        except Exception as exc:
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                f"读取本地图片失败：{exc}",
            )
        result = await _ocr_by_file(ocr_url, image_data, timeout)
        return _build_ocr_result(invocation.tool_name, result, tool_ctx)

    target_message = None
    if message_id:
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
        source_label = f"msg_id={message_id}"

    if target_message is not None:
        images = _collect_images_from_sequence(getattr(target_message, "raw_message", None))
        if not images:
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                f"目标消息中没有找到图片：{source_label}",
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
        image_data = image.binary_data
        source_label = f"{source_label}[{media_index}]"
    else:
        image_data, source_label = await _find_latest_image(tool_ctx, media_index)
        if image_data is None:
            return tool_ctx.build_failure_result(
                invocation.tool_name,
                "未找到可 OCR 的图片。",
            )

    result = await _ocr_by_file(ocr_url, image_data, timeout)
    return _build_ocr_result(invocation.tool_name, result, tool_ctx)


async def _find_latest_image(
    tool_ctx: BuiltinToolRuntimeContext,
    media_index: int = 0,
) -> tuple[Optional[bytes], str]:
    for history_message in reversed(tool_ctx.runtime._chat_history):
        if not isinstance(history_message, SessionBackedMessage):
            continue
        images = _collect_images_from_sequence(getattr(history_message, "raw_message", None))
        if not images:
            continue
        if media_index < 0 or media_index >= len(images):
            continue
        image = images[media_index]
        if not image.binary_data:
            try:
                await image.load_image_binary()
            except Exception:
                continue
        if image.binary_data:
            msg_id = str(getattr(history_message, "message_id", "") or "").strip()
            return image.binary_data, f"msg_id={msg_id}[{media_index}]"
    return None, ""


async def _async_read_file(path: Path) -> bytes:
    loop = __import__("asyncio").get_running_loop()
    return await loop.run_in_executor(None, path.read_bytes)


async def _ocr_by_url(base_url: str, image_url: str, timeout: int) -> dict[str, Any]:
    base = base_url.rstrip("/")
    endpoint = f"{base}/OCR/"
    params = {"url": image_url}

    logger.info(f"codex_chat_ocr_image_request mode=url endpoint={endpoint}")
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(endpoint, data=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=timeout elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求超时（{timeout}s）。"}
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=request_failed detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求失败：{exc}"}
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=unexpected detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求异常：{exc}"}

    elapsed = time.perf_counter() - started
    return _parse_ocr_response(data, elapsed)


async def _ocr_by_file(base_url: str, image_data: bytes, timeout: int) -> dict[str, Any]:
    base = base_url.rstrip("/")
    endpoint = f"{base}/OCR/"

    logger.info(f"codex_chat_ocr_image_request mode=file endpoint={endpoint}")
    started = time.perf_counter()

    try:
        async with httpx.AsyncClient() as client:
            files = {"file": ("image.png", image_data, "image/png")}
            resp = await client.post(endpoint, files=files, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=timeout elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求超时（{timeout}s）。"}
    except httpx.RequestError as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=request_failed detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求失败：{exc}"}
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.warning(f"codex_chat_ocr_image_failed error=unexpected detail={exc} elapsed={elapsed:.3f}")
        return {"error": f"OCR 请求异常：{exc}"}

    elapsed = time.perf_counter() - started
    return _parse_ocr_response(data, elapsed)


def _parse_ocr_response(data: Any, elapsed: float) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"error": f"OCR 返回格式异常：非 JSON 对象"}

    code = data.get("code")
    text = ""

    if isinstance(data.get("data"), dict):
        inner = data["data"]
        text = str(inner.get("msg") or inner.get("text") or inner.get("result") or "").strip()
    if not text:
        text = str(data.get("text") or data.get("result") or "").strip()
    if not text and isinstance(data.get("data"), str):
        text = data["data"].strip()

    if code != 200:
        message = str(data.get("message") or data.get("msg") or text or f"code={code}").strip()
        logger.warning(f"codex_chat_ocr_image_failed error=service_error code={code} message={message}")
        return {"error": f"OCR 服务返回错误：{message}"}

    if not text:
        logger.info(f"codex_chat_ocr_image_empty elapsed={elapsed:.3f}")
        return {"text": ""}

    logger.info(f"codex_chat_ocr_image_success chars={len(text)} elapsed={elapsed:.3f}")
    return {"text": text}


def _build_ocr_result(tool_name: str, result: dict[str, Any], tool_ctx: BuiltinToolRuntimeContext) -> ToolExecutionResult:
    error = result.get("error")
    if error:
        return tool_ctx.build_failure_result(tool_name, error)

    text = result.get("text", "")
    if not text:
        return tool_ctx.build_success_result(tool_name, "OCR 未识别到文字。", structured_content={"text": ""})

    return tool_ctx.build_success_result(tool_name, text, structured_content={"text": text})
