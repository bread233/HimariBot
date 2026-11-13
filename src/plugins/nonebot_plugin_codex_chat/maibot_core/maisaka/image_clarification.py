"""Persist an explicit, user-scoped image clarification until the user answers.

Only a confirmed clarification reply may create a record. Later messages are
candidates for the Planner to classify, not automatic permission to draw.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from src.plugins.nonebot_plugin_codex_chat.maibot_core.maisaka.image_task_state import load_image_task

_ROOT = Path("/app/data/nonebot_chat_agent/generated_images/image_clarifications")
TTL_SECONDS = 15 * 60
_DRAW = re.compile(r"(?:画(?:一[张幅个]|个|张|幅|一下)?|绘制|生图|生成.{0,8}(?:图|图片|插画)|重画|改图)")
_CANCEL = re.compile(r"(?:取消(?:绘图|画图|生图)|算了.{0,6}(?:不画|别画)|^\s*(?:(?:先)?(?:别|不要|不用|不想|不)画(?:了)?|算了|不用了|取消|别弄了)\s*[。！!]*$)")
_QUESTION = re.compile(r"[?？]|哪个|哪部|哪张|哪位|什么|请(?:提供|补充|告诉)|告诉我|能否|是否")


def _user_id(message: Any) -> str:
    return str(getattr(getattr(getattr(message, "message_info", None), "user_info", None), "user_id", "") or "").strip()


def _text(message: Any) -> str:
    parts = getattr(getattr(message, "raw_message", None), "components", ()) or ()
    return " ".join(str(getattr(p, "text", "") or "") for p in parts if isinstance(getattr(p, "text", None), str)).strip()


def _record_path(session_id: str, user_id: str) -> Path:
    digest = hashlib.sha256(json.dumps([session_id, user_id], ensure_ascii=False).encode("utf-8")).hexdigest()
    return _ROOT / f"{digest}.json"


def clear_image_clarification(session_id: str, user_id: str) -> None:
    if not session_id or not user_id:
        return
    try:
        _record_path(session_id, user_id).unlink(missing_ok=True)
    except OSError:
        pass


def load_image_clarification(session_id: str, user_id: str, now: float | None = None) -> dict[str, Any] | None:
    if not session_id or not user_id:
        return None
    now = time.time() if now is None else now
    path = _record_path(session_id, user_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("session_id") != session_id
                or data.get("user_id") != user_id or not data.get("original_request")
                or not data.get("original_msg_id")
                or not data.get("question")
                or not 0 <= now - float(data.get("updated_at", 0)) <= TTL_SECONDS):
            clear_image_clarification(session_id, user_id)
            return None
        return data
    except (OSError, ValueError, TypeError):
        return None


def save_image_clarification(
    session_id: str, message: Any, question: str, *, new_request: bool = False, now: float | None = None
) -> bool:
    user_id = _user_id(message)
    msg_id = str(getattr(message, "message_id", "") or "").strip()
    original_text = _text(message)
    question = question.strip()
    if not session_id or not user_id or not msg_id or not question or len(question) > 1000 or not _QUESTION.search(question):
        return False
    if _CANCEL.search(original_text):
        return False
    previous = None if new_request else load_image_clarification(session_id, user_id, now=now)
    task = load_image_task(session_id, user_id)
    supplements = list(previous.get("supplements", []))[-5:] if previous else []
    if previous:
        supplements.append(original_text[:500])
        original_text = str(previous["original_request"])
        msg_id = str(previous["original_msg_id"])
    elif not _DRAW.search(original_text):
        if not task or task.get("status") in {"sent", "cancelled"}:
            return False
        original_text = str(task["original_request"])
        msg_id = str(task["original_msg_id"])
    now = time.time() if now is None else now
    data = {
        "session_id": session_id,
        "user_id": user_id,
        "original_msg_id": msg_id,
        "original_request": original_text[:2000],
        "question": question,
        "supplements": supplements[-6:],
        "reference_required": bool(previous.get("reference_required")) if previous else bool(
            task and task.get("reference_required")
        ) or any(
            type(part).__name__ in {"ImageComponent", "ReplyComponent"}
            for part in (getattr(getattr(message, "raw_message", None), "components", ()) or ())
        ),
        "updated_at": now,
    }
    _ROOT.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=_ROOT, prefix=".pending-", delete=False) as file:
            temp_name = file.name
            json.dump(data, file, ensure_ascii=False)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, _record_path(session_id, user_id))
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return True


def pending_clarification_for_message(runtime: Any, message: Any, now: float | None = None) -> dict[str, Any] | None:
    """Return context only for a fresh message from the same QQ user in the same session."""
    if getattr(getattr(runtime, "chat_stream", None), "platform", "") != "onebot.v11":
        return None
    session_id = str(getattr(runtime, "session_id", "") or "")
    user_id = _user_id(message)
    record = load_image_clarification(session_id, user_id, now=now)
    if not record:
        return None
    msg_id = str(getattr(message, "message_id", "") or "")
    if not msg_id or msg_id == record["original_msg_id"]:
        return None
    if msg_id not in getattr(runtime, "_active_reply_request_ids", set()):
        return None
    try:
        message_epoch = float(message.timestamp.timestamp())
    except (AttributeError, ValueError, TypeError):
        return None
    if message_epoch < float(record["updated_at"]) - 2:
        return None
    content = _text(message)
    if _CANCEL.search(content):
        clear_image_clarification(session_id, user_id)
        return None
    return record
