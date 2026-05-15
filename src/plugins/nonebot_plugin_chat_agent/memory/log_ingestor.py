from __future__ import annotations

import hashlib
import json
import re
import ast
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from ..stores.storage import get_log_import_file, insert_log_message, upsert_log_import_file
except ImportError:
    from storage import get_log_import_file, insert_log_message, upsert_log_import_file


def iter_info_log_files(log_dir: str, target_date: date | None = None) -> list[Path]:
    base = Path(str(log_dir or "")).expanduser()
    if not base.exists() or not base.is_dir():
        return []
    files = [p for p in base.glob("*INFO*.log") if p.is_file()]
    files.sort(key=lambda p: p.name)
    return files


def _extract_int(text: str, key: str) -> int | None:
    m = re.search(rf"{re.escape(key)}=(\d+)", text)
    return int(m.group(1)) if m else None


def _extract_text(text: str, key: str) -> str:
    m = re.search(rf"{re.escape(key)}='([^']*)'", text)
    return m.group(1) if m else ""


def _extract_sender_field(text: str, key: str) -> str:
    m_sender = re.search(r"sender=Sender\((.*?)\)", text)
    if not m_sender:
        return ""
    sender = m_sender.group(1)
    m = re.search(rf"{re.escape(key)}='([^']*)'", sender)
    return m.group(1) if m else ""


def _extract_reply_id(text: str) -> str:
    if "reply=None" in text:
        return ""
    m = re.search(r"reply=.*?(?:message_id|id)=(\d+)", text)
    return m.group(1) if m else ""


def _clean_plain_text(raw: str) -> str:
    text = str(raw or "")
    text = re.sub(r"\[(?:at:qq=\d+|CQ:at,qq=\d+)\]", "", text)
    text = re.sub(r"\[(?:reply:id=\d+|CQ:reply,id=\d+)\]", "", text)
    return text.strip()


def _extract_text_segments(text: str) -> list[str]:
    segs = []
    for m in re.finditer(r"MessageSegment\(type='text', data=(\{.*?\})\)", text):
        raw = m.group(1)
        try:
            data = ast.literal_eval(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            seg_text = str(data.get("text", ""))
            if seg_text:
                segs.append(seg_text)
    return segs


def _extract_at_qqs(text: str) -> list[str]:
    qqs = []
    for m in re.finditer(r"MessageSegment\(type='at', data=(\{.*?\})\)", text):
        raw = m.group(1)
        try:
            data = ast.literal_eval(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            qq = str(data.get("qq", "")).strip()
            if qq:
                qqs.append(qq)
    qqs.extend(re.findall(r"\[CQ:at,qq=(\d+)\]", text))
    uniq = []
    seen = set()
    for q in qqs:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq


def _parse_event_repr_line(text: str, source_file: str, source_line: int) -> tuple[dict | None, str | None]:
    if "GroupMessageEvent(" not in text and "PrivateMessageEvent(" not in text:
        return None, "not_event_repr"
    if "MessageSegment(type='text'" not in text:
        return None, "no_text_segment"

    msg_type = "group" if "GroupMessageEvent(" in text else "private"
    log_time_text = ""
    m_time = re.search(r"^\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", text)
    if m_time:
        log_time_text = m_time.group(0)

    text_segments = _extract_text_segments(text)
    plain_text = _clean_plain_text("".join(text_segments))
    if not plain_text:
        return None, "plain_text_empty"

    at_qqs = _extract_at_qqs(text)
    has_at = 1 if at_qqs else 0
    has_reply = 1 if ("reply=" in text and "reply=None" not in text) else 0
    reply_id = _extract_reply_id(text)
    source_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    row = {
        "source_file": source_file,
        "source_line": int(source_line),
        "source_hash": source_hash,
        "log_time_text": log_time_text,
        "event_time": _extract_int(text, "time"),
        "bot_id": str(_extract_int(text, "self_id") or ""),
        "adapter": "OneBot V11",
        "message_id": _extract_int(text, "message_id"),
        "message_type": _extract_text(text, "message_type") or msg_type,
        "sub_type": _extract_text(text, "sub_type"),
        "group_id": str(_extract_int(text, "group_id") or "") if msg_type == "group" else "",
        "group_name": _extract_text(text, "group_name"),
        "user_id": str(_extract_int(text, "user_id") or ""),
        "nickname": _extract_sender_field(text, "nickname"),
        "group_card": _extract_sender_field(text, "card"),
        "role": _extract_sender_field(text, "role"),
        "plain_text": plain_text,
        "raw_message": _extract_text(text, "raw_message"),
        "at_qqs_json": json.dumps(at_qqs, ensure_ascii=False),
        "reply_id": reply_id,
        "has_at": has_at,
        "has_reply": has_reply,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "parse_source": "event_repr",
    }
    return row, None


def _parse_success_message_line(text: str, source_file: str, source_line: int) -> tuple[dict | None, str | None]:
    m = re.search(
        r"^\s*(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}).*?\[SUCCESS\]\s+nonebot\s+\|\s+OneBot V11\s+(\d+)\s+\|\s+\[message\.(group|private)\.([a-z_]+)\]:\s+Message\s+(\d+)\s+from\s+(\d+)(?:@\[[^\]]*:(\d+)\])?\s+'(.*)'\s*$",
        text,
    )
    if not m:
        return None, "not_success_line"

    log_time_text = m.group(1) or ""
    bot_id = m.group(2) or ""
    message_type = m.group(3) or ""
    sub_type = m.group(4) or ""
    message_id = int(m.group(5)) if m.group(5) else None
    user_id = m.group(6) or ""
    group_id = m.group(7) or ""
    raw_message = m.group(8) or ""

    plain_text = _clean_plain_text(raw_message)
    if not plain_text:
        return None, "plain_text_empty"

    at_qqs = re.findall(r"\[(?:at:qq=|CQ:at,qq=)(\d+)\]", raw_message)
    uniq_at = []
    seen = set()
    for q in at_qqs:
        if q not in seen:
            seen.add(q)
            uniq_at.append(q)

    has_reply = 1 if re.search(r"\[(?:reply:id=\d+|CQ:reply,id=\d+)\]", raw_message) else 0
    reply_id_match = re.search(r"\[(?:reply:id=|CQ:reply,id=)(\d+)\]", raw_message)
    reply_id = reply_id_match.group(1) if reply_id_match else ""
    source_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    row = {
        "source_file": source_file,
        "source_line": int(source_line),
        "source_hash": source_hash,
        "log_time_text": log_time_text,
        "event_time": None,
        "bot_id": str(bot_id),
        "adapter": "OneBot V11",
        "message_id": message_id,
        "message_type": message_type,
        "sub_type": sub_type,
        "group_id": str(group_id) if message_type == "group" else "",
        "group_name": "",
        "user_id": str(user_id),
        "nickname": "",
        "group_card": "",
        "role": "",
        "plain_text": plain_text,
        "raw_message": raw_message,
        "at_qqs_json": json.dumps(uniq_at, ensure_ascii=False),
        "reply_id": reply_id,
        "has_at": 1 if uniq_at else 0,
        "has_reply": has_reply,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "parse_source": "success_line",
    }
    return row, None


def parse_log_line(line: str, source_file: str, source_line: int) -> tuple[dict | None, str | None]:
    text = str(line or "").rstrip("\n")
    if not text:
        return None, "empty"

    skip_tokens = [
        "MessageSegment(type='image'",
        "MessageSegment(type='json'",
        "MessageSegment(type='record'",
        "MessageSegment(type='video'",
        "MessageSegment(type='file'",
        "MessageSegment(type='face'",
        "[image:",
        "[CQ:image",
        "type='image'",
        "type='json'",
    ]
    if any(t in text for t in skip_tokens):
        return None, "non_text_message"

    row, reason = _parse_event_repr_line(text, source_file, source_line)
    if row is not None:
        return row, None

    row, reason = _parse_success_message_line(text, source_file, source_line)
    if row is not None:
        return row, None
    return None, reason


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def import_log_file(config, path: Path) -> dict:
    scanned_count = 0
    inserted_count = 0
    duplicate_count = 0
    skipped_count = 0
    error_count = 0
    status = "ok"
    error = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                scanned_count += 1
                try:
                    row, reason = parse_log_line(line, str(path), i)
                except Exception:
                    error_count += 1
                    continue
                if not row:
                    skipped_count += 1
                    continue
                inserted = await insert_log_message(config, row)
                if inserted:
                    inserted_count += 1
                else:
                    duplicate_count += 1
    except Exception as e:
        status = "error"
        error = str(e)
        error_count += 1

    file_row = {
        "file_path": str(path),
        "file_size": int(path.stat().st_size) if path.exists() else 0,
        "mtime": float(path.stat().st_mtime) if path.exists() else 0.0,
        "sha256": _sha256_file(path) if path.exists() else "",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "message_count": inserted_count,
        "skipped_count": skipped_count,
        "status": status,
        "error": error,
    }
    await upsert_log_import_file(config, file_row)

    return {
        "file_path": str(path),
        "scanned_count": scanned_count,
        "inserted_count": inserted_count,
        "duplicate_count": duplicate_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "status": status,
        "error": error,
    }


async def should_import_log_file(config, path: Path, changed_only: bool = True) -> bool:
    if not changed_only:
        return True
    info = await get_log_import_file(config, str(path))
    if not info:
        return True
    try:
        stat = path.stat()
    except Exception:
        return False
    old_size = info.get("file_size")
    old_mtime = info.get("mtime")
    if old_size is None or int(old_size) != int(stat.st_size):
        return True
    if old_mtime is None or float(old_mtime) != float(stat.st_mtime):
        return True
    return False


async def backfill_logs(
    config,
    target_date: date | None = None,
    changed_only: bool = True,
    limit_files: int | None = None,
) -> dict:
    files = iter_info_log_files(str(getattr(config, "chat_agent_log_dir", "/app/log")), target_date=target_date)
    candidate_files: list[Path] = []
    skipped_files_count = 0
    for path in files:
        if await should_import_log_file(config, path, changed_only=changed_only):
            candidate_files.append(path)
        else:
            skipped_files_count += 1
    if limit_files is not None and int(limit_files) >= 0:
        candidate_files = candidate_files[: int(limit_files)]

    totals = {
        "files_count": len(files),
        "candidate_files_count": len(candidate_files),
        "skipped_files_count": skipped_files_count,
        "imported_files_count": 0,
        "scanned_count": 0,
        "inserted_count": 0,
        "duplicate_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "files": [],
    }
    for path in candidate_files:
        result = await import_log_file(config, path)
        totals["files"].append(result)
        totals["imported_files_count"] += 1
        totals["scanned_count"] += int(result.get("scanned_count", 0))
        totals["inserted_count"] += int(result.get("inserted_count", 0))
        totals["duplicate_count"] += int(result.get("duplicate_count", 0))
        totals["skipped_count"] += int(result.get("skipped_count", 0))
        totals["error_count"] += int(result.get("error_count", 0))
    return totals
