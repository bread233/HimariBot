"""后台 Codex 生图任务；不阻塞 Planner/Replyer 的普通文字消息。"""
from __future__ import annotations

import asyncio
import hashlib
import struct
import json
import os
import re
import time
import uuid
from pathlib import Path

from src.common.data_models.message_component_data_model import ImageComponent, MessageSequence, TextComponent
from src.common.logger import get_logger
from src.services import send_service

logger = get_logger("maisaka_image_generation")
_TASKS: set[asyncio.Task] = set()
_LIMIT = asyncio.Semaphore(1)
_MAX_PENDING = 8
_ROOT = Path("/app/data/nonebot_chat_agent/generated_images")
_IMAGE_PATH = re.compile(r"(?<![\w])(/(?:[\w.\-]+/)+[\w.\-]+\.png)\b", re.IGNORECASE)


async def _run(*args: str, timeout: float = 300, input_text: str | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input_text.encode("utf-8") if input_text is not None else None), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


def _extract_image_path(output: str) -> str:
    """仅接受 Codex JSONL 中的图片路径，不从任意提示词中提取路径。"""
    texts = []
    thread_id = None
    completed = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            if event.get("type") == "thread.started":
                thread_id = str(event.get("thread_id") or "")
            if event.get("type") == "turn.completed":
                completed = True
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") in {"agent_message", "tool_output"}:
                texts.append(str(item.get("text") or item.get("output") or ""))
    if not completed or not thread_id or not re.fullmatch(r"[a-f0-9-]{36}", thread_id):
        raise ValueError("Codex 生图任务未正常完成或缺少 thread_id")
    expected_prefix = f"/root/.codex/generated_images/{thread_id}/"
    for text in reversed(texts):
        for candidate in reversed(_IMAGE_PATH.findall(text)):
            if candidate.startswith(expected_prefix) and ".." not in Path(candidate).parts:
                return candidate
    raise ValueError("Codex 未返回可验证的 PNG 路径")


async def _generate_and_send(
    job_id: str, prompt: str, caption: str, session_id: str, target_message: object, quote: bool,
) -> None:
    job_dir = _ROOT / job_id
    try:
        async with _LIMIT:
            await asyncio.to_thread(job_dir.mkdir, parents=True, exist_ok=False)
            container = os.getenv("CODEX_CHAT_DOCKER_CONTAINER", "codexcli")
            instruction = (
                "Use your built-in image generation capability to create exactly one PNG image. "
                "Report the generated PNG absolute path under /root/.codex/generated_images/ in the final response. "
                "Do not merely describe an image. Image request: " + prompt
            )
            code, output, stderr = await _run(
                "docker", "exec", "-i", container, "codex", "exec", "--json",
                "-s", "read-only", "-C", "/opt/codex", "--skip-git-repo-check", "-",
                timeout=300, input_text=instruction,
            )
            if code:
                raise RuntimeError(f"Codex exited {code}; stderr_chars={len(stderr)}")
            image_path = _extract_image_path(output)
            local_path = job_dir / "original.png"
            code, _, stderr = await _run(
                "docker", "cp", f"{container}:{image_path}", str(local_path), timeout=45,
            )
            if code:
                raise RuntimeError(f"PNG copy failed; stderr_chars={len(stderr)}")
            await asyncio.to_thread(local_path.chmod, 0o600)
            image_bytes = await asyncio.to_thread(local_path.read_bytes)
            if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or not 45 <= len(image_bytes) <= 25 * 1024 * 1024:
                raise ValueError("生成文件不是有效大小的 PNG")
            width, height = struct.unpack(">II", image_bytes[16:24])
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise ValueError("PNG 尺寸不合法")
            components = ([TextComponent(caption)] if caption else []) + [
                ImageComponent(binary_hash=hashlib.sha256(image_bytes).hexdigest(), binary_data=image_bytes)
            ]
            sent = await send_service._send_to_target_with_message(
                message_sequence=MessageSequence(components),
                stream_id=session_id,
                processed_plain_text=caption,
                set_reply=quote,
                reply_message=target_message if quote else None,
                typing=False,
                sync_to_maisaka_history=True,
                maisaka_source_kind="generated_image",
            )
            metadata = {
                "job_id": job_id, "prompt": prompt, "caption": caption,
                "source_message_id": str(getattr(target_message, "message_id", "")),
                "sent_message_id": str(getattr(sent, "message_id", "")) if sent else "",
                "status": "sent" if sent else "send_failed", "created_at": time.time(),
            }
            await asyncio.to_thread(
                (job_dir / "metadata.json").write_text,
                json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8",
            )
    except Exception as exc:
        logger.exception(f"generate_image job={job_id} failed: {type(exc).__name__}: {exc}")
        try:
            await asyncio.to_thread(job_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(
                (job_dir / "error.json").write_text,
                json.dumps({"job_id": job_id, "error_type": type(exc).__name__, "created_at": time.time()}), "utf-8",
            )
        except Exception:
            logger.exception(f"generate_image job={job_id} failed to persist error")
        try:
            await send_service._send_to_target_with_message(
                message_sequence=MessageSequence([TextComponent("这次画图没成功，稍后再试试吧。")]),
                stream_id=session_id,
                processed_plain_text="这次画图没成功，稍后再试试吧。",
                set_reply=quote,
                reply_message=target_message if quote else None,
                typing=False,
                sync_to_maisaka_history=True,
                maisaka_source_kind="generated_image_error",
            )
        except Exception:
            logger.exception(f"generate_image job={job_id} failed to notify user")


def submit_image_job(prompt: str, caption: str, session_id: str, target_message: object, quote: bool) -> str:
    if len(_TASKS) >= _MAX_PENDING:
        raise RuntimeError("生图队列已满，请稍后再试")
    job_id = uuid.uuid4().hex
    task = asyncio.create_task(
        _generate_and_send(job_id, prompt, caption, session_id, target_message, quote),
        name=f"generate_image_{job_id}",
    )
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return job_id
