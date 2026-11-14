"""Durable, per-user image request state; Planner cycles are not task boundaries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_ROOT = Path("/app/data/nonebot_chat_agent/generated_images/image_tasks")
_TERMINAL = {"sent", "cancelled"}
_ACTIVE = {"planning", "searching", "awaiting_clarification", "generating", "sending", "failed", "send_failed", "delivery_uncertain"}


def user_id(message: Any) -> str:
    return str(getattr(getattr(getattr(message, "message_info", None), "user_info", None), "user_id", "") or "").strip()


def _path(session_id: str, uid: str) -> Path:
    key = hashlib.sha256(json.dumps([session_id, uid], ensure_ascii=False).encode("utf-8")).hexdigest()
    return _ROOT / f"{key}.json"


def load_image_task(session_id: str, uid: str) -> dict[str, Any] | None:
    if not session_id or not uid:
        return None
    try:
        data = json.loads(_path(session_id, uid).read_text(encoding="utf-8"))
        return data if data.get("session_id") == session_id and data.get("user_id") == uid else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _resume_claim_path(session_id: str, uid: str, original_msg_id: str) -> Path:
    key = hashlib.sha256(json.dumps([session_id, uid, original_msg_id], ensure_ascii=False).encode("utf-8")).hexdigest()
    return _ROOT / "resume_claims" / key


def image_resume_claimed(session_id: str, uid: str, original_msg_id: str) -> bool:
    return _resume_claim_path(session_id, uid, original_msg_id).exists()


def claim_image_resume(session_id: str, uid: str, original_msg_id: str) -> bool:
    """One durable, at-most-once Planner recovery; never replay an already submitted job."""
    task = load_image_task(session_id, uid)
    if (not task or task.get("original_msg_id") != original_msg_id
            or task.get("status") not in {"planning", "searching"} or task.get("job_id")
            or task.get("reference_required") or time.time() - float(task.get("created_at", 0)) > 600):
        return False
    path = _resume_claim_path(session_id, uid, original_msg_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
        return True
    except FileExistsError:
        return False


def _save(data: dict[str, Any]) -> None:
    _ROOT.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=_ROOT, prefix=".task-", delete=False) as file:
            tmp = file.name
            json.dump(data, file, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, _path(data["session_id"], data["user_id"]))
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def start_image_task(session_id: str, message: Any, *, new_request: bool = False) -> dict[str, Any] | None:
    uid = user_id(message)
    msg_id = str(getattr(message, "message_id", "") or "").strip()
    if not session_id or not uid or not msg_id:
        return None
    previous = load_image_task(session_id, uid)
    if (previous and new_request and previous.get("status") not in _TERMINAL
            and previous.get("original_msg_id") != msg_id):
        raise RuntimeError("上一张图尚未结束；请等待完成，或先明确取消旧任务。")
    if previous and previous.get("status") not in _TERMINAL and not new_request:
        return previous
    if previous and previous.get("original_msg_id") == msg_id:
        return previous
    content = " ".join(
        str(getattr(part, "text", "") or "")
        for part in (getattr(getattr(message, "raw_message", None), "components", ()) or ())
        if isinstance(getattr(part, "text", None), str)
    ).strip()
    data = {
        "session_id": session_id, "user_id": uid, "original_msg_id": msg_id,
        "original_request": content[:2000], "status": "planning",
        "reference_required": any(type(p).__name__ in {"ImageComponent", "ReplyComponent"} for p in (getattr(getattr(message, "raw_message", None), "components", ()) or ())),
        "search_queries": [], "search_evidence": "", "job_id": "", "submitted_msg_id": "",
        "created_at": time.time(), "updated_at": time.time(),
    }
    _save(data)
    return data


def update_image_task(session_id: str, uid: str, status: str | None = None, *,
                      job_id: str | None = None, submitted_msg_id: str | None = None,
                      expected_job_id: str | None = None,
                      query: str | None = None, evidence: str | None = None) -> dict[str, Any] | None:
    data = load_image_task(session_id, uid)
    if not data or data.get("status") in _TERMINAL:
        return None
    if expected_job_id is not None and data.get("job_id") != expected_job_id:
        return None
    if status is not None:
        if status not in _ACTIVE | _TERMINAL:
            raise ValueError(f"Unknown image task status: {status}")
        data["status"] = status
    if job_id is not None:
        data["job_id"] = job_id
    if submitted_msg_id is not None:
        data["submitted_msg_id"] = submitted_msg_id
    if query:
        queries = list(data.get("search_queries", []))
        if query not in queries:
            queries.append(query)
        data["search_queries"] = queries[-8:]
    if evidence is not None:
        data["search_evidence"] = evidence[:1800]
    data["updated_at"] = time.time()
    _save(data)
    return data


def _cancel_path(job_id: str) -> Path | None:
    return _ROOT / "cancelled_jobs" / job_id if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", job_id) else None


def cancel_image_task(session_id: str, uid: str) -> bool:
    data = load_image_task(session_id, uid)
    if not data or data.get("status") in _TERMINAL or data.get("status") == "sending":
        return False  # Once transport starts, delivery cannot be reliably recalled.
    marker = _cancel_path(str(data.get("job_id") or ""))
    if marker is not None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
    return update_image_task(session_id, uid, "cancelled") is not None


def image_task_cancelled(session_id: str, uid: str, job_id: str) -> bool:
    data = load_image_task(session_id, uid)
    marker = _cancel_path(job_id)
    return bool((marker and marker.is_file()) or (data and data.get("job_id") == job_id and data.get("status") == "cancelled"))
