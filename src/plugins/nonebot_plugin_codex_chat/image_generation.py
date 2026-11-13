"""后台 Codex 生图任务；不阻塞 Planner/Replyer 的普通文字消息。"""
from __future__ import annotations

import asyncio
import hashlib
import struct
import json
import os
import tempfile
import re
import time
import uuid
from pathlib import Path

from src.common.data_models.message_component_data_model import ImageComponent, MessageSequence, TextComponent
from src.common.logger import get_logger
from src.plugins.nonebot_plugin_codex_chat.image_reference import download_reference_image
from src.services import send_service

logger = get_logger("maisaka_image_generation")
_TASKS: set[asyncio.Task] = set()
_LIMIT = asyncio.Semaphore(1)
_MAX_PENDING = 8
_ROOT = Path("/app/data/nonebot_chat_agent/generated_images")
_IMAGE_PATH = re.compile(r"(?<![\w])(/(?:[\w.\-]+/)+[\w.\-]+\.png)\b", re.IGNORECASE)
_HIMARI_NAME = re.compile(r"上原绯玛丽|上原緋まり|上原ひまり|绯玛丽|肥玛丽|himari|hmr", re.IGNORECASE)
_HIMARI_NEGATED = re.compile(
    r"(?:不要|别|避免|禁止|不是|并非|而非|not|without).{0,20}"
    r"(?:上原绯玛丽|上原緋まり|上原ひまり|绯玛丽|肥玛丽|himari|hmr)", re.IGNORECASE
)
_HIMARI_SELF = re.compile(r"自画像|画(?:一[张幅个])?(?:我|自己)|画画(?:我|自己)|(?:我|自己)的(?:画像|肖像|照片)")
_HIMARI_VISUAL = (
    "Character identity constraint: depict Himari Uehara (上原ひまり) from BanG Dream!, "
    "Afterglow's bassist, with pink hair and distinctly GREEN eyes (not pink/red/purple eyes). "
    "The nickname 肥玛丽 is only a homophonic nickname for 绯玛丽 and does NOT imply a heavier body type. "
    "Preserve the user's requested scene, pose, outfit, and art style. "
    "Use official Himari Uehara character design as the visual identity reference."
)


def _image_request_prompt(prompt: str) -> str:
    """Only enrich requests about Himari herself; do not change unrelated image requests."""
    if _HIMARI_NEGATED.search(prompt):
        return prompt
    if _HIMARI_NAME.search(prompt) or _HIMARI_SELF.search(prompt):
        return f"{prompt}\n\n{_HIMARI_VISUAL}"
    return prompt


async def _run(*args: str, timeout: float = 300, input_text: str | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if input_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input_text.encode("utf-8") if input_text is not None else None), timeout=timeout
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
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
    if any("安全审核拦截" in text or "moderation_blocked" in text for text in texts):
        raise ValueError("moderation_blocked: 图像生成被安全审核拦截")
    raise ValueError("Codex 未返回可验证的 PNG 路径")


async def _prepare_reference(container: str, url: str, job_id: str) -> str:
    image_bytes, suffix = await download_reference_image(url)
    container_path = f"/tmp/himaribot-reference-{job_id}{suffix}"
    # 清理上次进程异常退出留下的宿主临时文件（仅匹配本功能专用前缀）。
    for stale in Path(tempfile.gettempdir()).glob("himaribot-reference-*"):
        try:
            if stale.is_file() and not stale.is_symlink() and time.time() - stale.stat().st_mtime > 7200:
                stale.unlink()
        except OSError:
            logger.warning("无法清理过期参考图临时文件")
    fd, local_path = tempfile.mkstemp(prefix="himaribot-reference-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(image_bytes)
        code, _, stderr = await _run("docker", "cp", local_path, f"{container}:{container_path}", timeout=45)
        if code:
            await _run("docker", "exec", container, "rm", "-f", "--", container_path, timeout=15)
            raise RuntimeError(f"参考图传入 Codex 失败; stderr_chars={len(stderr)}")
    finally:
        os.unlink(local_path)
    return container_path


async def _generate_and_send(
    job_id: str, prompt: str, caption: str, session_id: str, target_message: object, quote: bool,
    reference_image_url: str = "",
) -> None:
    job_dir = _ROOT / job_id
    container = os.getenv("CODEX_CHAT_DOCKER_CONTAINER", "codexcli")
    reference_path = ""
    try:
        async with _LIMIT:
            await asyncio.to_thread(job_dir.mkdir, parents=True, exist_ok=False)
            # 下次任务顺便清理强制退出遗留的旧参考图；当前任务最多运行约 5 分钟。
            await _run("docker", "exec", container, "find", "/tmp", "-maxdepth", "1",
                       "-type", "f", "-name", "himaribot-reference-*", "-mmin", "+120", "-delete", timeout=15)
            if reference_image_url:
                reference_path = await _prepare_reference(container, reference_image_url, job_id)
            instruction = (
                "Use your built-in image generation capability to create exactly one PNG image. "
                "Report the generated PNG absolute path under /root/.codex/generated_images/ in the final response. "
                "Do not merely describe an image. Keep the explicitly requested character identity; "
                "do not substitute another character or invent missing official appearance traits. " +
                ("Use the attached image as the visual identity reference; preserve its recognizable "
                 "character design while changing only the requested scene. " if reference_path else "")
                + "Image request: " + _image_request_prompt(prompt)
            )
            cmd = ["docker", "exec", "-i", container, "codex", "exec", "--json",
                "-s", "read-only", "-C", "/opt/codex", "--skip-git-repo-check"]
            if reference_path:
                cmd.extend(["--image", reference_path])
            cmd.append("-")
            code, output, stderr = await _run(*cmd,
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
            # 先持久化发送占位，防止重启或重复 Planner 调用再次发送。
            await asyncio.to_thread(
                (job_dir / "send_started.json").write_text,
                json.dumps({"job_id": job_id, "started_at": time.time()}), "utf-8",
            )
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
                "reference_used": bool(reference_path),
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
                json.dumps({"job_id": job_id, "error_type": type(exc).__name__,
                            "reason": "moderation_blocked" if "moderation_blocked" in str(exc) else "generation_failed",
                            "created_at": time.time()}), "utf-8",
            )
        except Exception:
            logger.exception(f"generate_image job={job_id} failed to persist error")
        try:
            # 发送阶段可能已经成功但回执/元数据失败，不再补发失败消息。
            if (job_dir / "send_started.json").exists():
                return
            notice = ("这次画图被图像生成服务的安全审核拦截了。" if "moderation_blocked" in str(exc)
                      else "这次画图没成功，稍后再试试吧。")
            await send_service._send_to_target_with_message(
                message_sequence=MessageSequence([TextComponent(notice)]),
                stream_id=session_id,
                processed_plain_text=notice,
                set_reply=quote,
                reply_message=target_message if quote else None,
                typing=False,
                sync_to_maisaka_history=True,
                maisaka_source_kind="generated_image_error",
            )
        except Exception:
            logger.exception(f"generate_image job={job_id} failed to notify user")

    finally:
        if reference_path:
            try:
                code, _, stderr = await _run("docker", "exec", container, "rm", "-f", "--", reference_path, timeout=15)
                if code:
                    logger.warning(f"generate_image job={job_id} reference cleanup failed: stderr_chars={len(stderr)}")
            except Exception:
                logger.exception(f"generate_image job={job_id} failed to clean temporary reference")


def image_request_claimed(session_id: str, source_id: str) -> bool:
    """已占位的画图请求不允许再额外 reply，包含任务进行中和完成后。"""
    if not session_id or not source_id:
        return False
    key = hashlib.sha256(
        json.dumps(["onebot.v11", session_id, source_id], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return (_ROOT / "requests" / key).is_dir()


def submit_image_job(prompt: str, caption: str, session_id: str, target_message: object, quote: bool, reference_image_url: str = "") -> tuple[str, bool]:
    """按会话与原消息永久去重；原子目录创建防止并发 Planner 重复提交。

    以持久化标记为准，重启后也不会自动重试同一原消息。
    用户发送新的 QQ 消息才会创建新的生成任务。
    """
    source_id = str(getattr(target_message, "message_id", "") or "").strip()
    if not session_id or not source_id:
        raise RuntimeError("无法确认原始消息 ID，拒绝提交生图任务")
    key = hashlib.sha256(
        json.dumps(["onebot.v11", session_id, source_id], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    claims = _ROOT / "requests"
    claims.mkdir(parents=True, exist_ok=True)
    claim = claims / key
    try:
        claim.mkdir()
    except FileExistsError:
        record = claim / "job.json"
        try:
            existing = json.loads(record.read_text(encoding="utf-8"))
            return str(existing["job_id"]), False
        except (OSError, ValueError, KeyError):
            # 创建目录后进程崩溃：仍拒绝二次生成，避免重复扣额度和重复发图。
            return key, False
    job_id = uuid.uuid4().hex
    try:
        (claim / "job.json").write_text(
            json.dumps({
                "job_id": job_id, "session_id": session_id,
                "source_message_id": source_id, "created_at": time.time(),
            }, ensure_ascii=False), encoding="utf-8",
        )
        if len(_TASKS) >= _MAX_PENDING:
            # 排队已满时释放本次新占位，允许用户稍后重试。
            (claim / "job.json").unlink()
            claim.rmdir()
            raise RuntimeError("生图队列已满，请稍后再试")
        task = asyncio.create_task(
            _generate_and_send(job_id, prompt, caption, session_id, target_message, quote, reference_image_url),
            name=f"generate_image_{job_id}",
        )
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        logger.info(f"generate_image submitted job={job_id} source={source_id} key={key[:12]}")
        return job_id, True
    except Exception:
        # 已经创建任务时不能释放占位；这里只处理提交之前的失败。
        if not (claim / "job.json").exists():
            try:
                claim.rmdir()
            except OSError:
                pass
        raise
