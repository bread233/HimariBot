from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


_DATE_RE = re.compile(r"^(\d{8})")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")


def _import_storage():
    try:
        from . import storage  # type: ignore
    except ImportError:
        import storage  # type: ignore

    return storage


def infer_message_date(row: dict) -> str:
    event_time = row.get("event_time")
    try:
        if event_time not in (None, 0, "0", ""):
            ts = int(event_time)
            return datetime.fromtimestamp(ts).date().isoformat()
    except Exception:
        pass

    source_file = str(row.get("source_file", "") or "")
    filename = Path(source_file).name
    m = _DATE_RE.match(filename)
    if not m:
        return "unknown"
    s = m.group(1)
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except Exception:
        return "unknown"


def normalize_message_text(text: str) -> str:
    raw = str(text or "")
    raw = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    s = _WS_RE.sub(" ", raw.strip())
    if not s:
        return ""
    if s.startswith("@") and " " not in s and len(s) <= 24:
        return ""
    return s


def is_low_value_text(text: str) -> bool:
    s = normalize_message_text(text)
    if not s:
        return True
    if len(s) > 300:
        return True
    if len(s) < 2:
        return True
    if s.startswith("/"):
        return True
    low_fragments = (
        "[json:",
        "[CQ:json",
        "[forward:",
        "[CQ:forward",
        "[image:",
        "[CQ:image",
        "[record:",
        "[CQ:record",
        "[video:",
        "[CQ:video",
        "[file:",
        "[CQ:file",
    )
    if any(f in s for f in low_fragments):
        return True
    if s in {"嗯", "啊", "哦", "草", "艹", "？", "?", "。"}:
        return True
    return False


def _stable_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _pick_representation_texts(messages: list[dict], limit: int = 20) -> list[str]:
    seen: set[str] = set()
    preferred: list[str] = []
    others: list[str] = []

    for m in messages:
        t = normalize_message_text(m.get("plain_text", ""))
        if is_low_value_text(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        if 2 <= len(t) <= 80:
            preferred.append(t)
        else:
            others.append(t)

    picked = preferred + others
    if len(picked) <= limit:
        return picked
    head = picked[: limit // 2]
    tail = picked[-(limit - len(head)) :]
    return head + tail


def _extract_keywords(texts: list[str], limit: int = 30) -> list[str]:
    c: Counter[str] = Counter()
    for t in texts:
        for tok in _TOKEN_RE.findall(t):
            k = tok.lower()
            if len(k) < 2:
                continue
            c[k] += 1
    if not c:
        return []
    items = sorted(c.items(), key=lambda x: (-x[1], x[0]))
    return [k for k, _ in items[:limit]]


def _safe_group_id(group_id) -> str:
    s = str(group_id or "").strip()
    return s if s else "private"


def build_daily_summary_row(messages: list[dict]) -> dict | None:
    if not messages:
        return None

    messages_sorted = sorted(
        messages,
        key=lambda r: (
            int(r.get("event_time") or 0),
            int(r.get("id") or 0),
        ),
    )

    first = messages_sorted[0]

    user_id = str(first.get("user_id", "") or "").strip()
    if not user_id:
        return None

    group_id_norm = _safe_group_id(first.get("group_id"))
    summary_date = infer_message_date(first)
    if not summary_date:
        summary_date = "unknown"

    def pick_last_non_empty(key: str) -> str | None:
        for r in reversed(messages_sorted):
            v = str(r.get(key, "") or "").strip()
            if v:
                return v
        return None

    group_name = pick_last_non_empty("group_name")
    nickname = pick_last_non_empty("nickname")
    group_card = pick_last_non_empty("group_card")

    event_times = [int(r.get("event_time")) for r in messages_sorted if r.get("event_time") not in (None, 0, "0", "")]
    first_event_time = min(event_times) if event_times else None
    last_event_time = max(event_times) if event_times else None

    first_log_time_text = None
    last_log_time_text = None
    for r in messages_sorted:
        v = str(r.get("log_time_text", "") or "").strip()
        if v:
            first_log_time_text = v
            break
    for r in reversed(messages_sorted):
        v = str(r.get("log_time_text", "") or "").strip()
        if v:
            last_log_time_text = v
            break

    sample_texts = _pick_representation_texts(messages_sorted, limit=20)
    keywords = _extract_keywords(sample_texts, limit=30)

    message_count = len(messages_sorted)

    lines: list[str] = []
    lines.append(f"User {user_id} daily chat summary on {summary_date}.")
    lines.append(f"Group: {group_id_norm} {group_name or ''}".rstrip())
    lines.append(f"Nickname: {nickname or ''}".rstrip())
    lines.append(f"Group card: {group_card or ''}".rstrip())
    lines.append(f"Message count: {message_count}")
    lines.append("Representative messages:")
    max_len = 4000
    summary_text = "\n".join(lines) + "\n"
    for t in sample_texts:
        bullet = f"- {t}\n"
        if len(summary_text) + len(bullet) > max_len:
            break
        summary_text += bullet
    if not summary_text.endswith("\n"):
        summary_text += "\n"

    sample_messages_json = _stable_json(sample_texts)
    keywords_json = _stable_json(keywords) if keywords else "[]"

    content_key = "\n".join(
        [
            user_id,
            group_id_norm,
            summary_date,
            str(message_count),
            sample_messages_json,
            summary_text,
        ]
    ).encode("utf-8")
    content_hash = hashlib.sha256(content_key).hexdigest()

    now = datetime.now(timezone.utc).isoformat()
    summary_key = f"{summary_date}:{group_id_norm}:{user_id}"

    return {
        "summary_key": summary_key,
        "summary_date": summary_date,
        "user_id": user_id,
        "group_id": None if group_id_norm == "private" else group_id_norm,
        "group_name": group_name,
        "nickname": nickname,
        "group_card": group_card,
        "message_count": message_count,
        "first_event_time": first_event_time,
        "last_event_time": last_event_time,
        "first_log_time_text": first_log_time_text,
        "last_log_time_text": last_log_time_text,
        "sample_messages_json": sample_messages_json,
        "keywords_json": keywords_json,
        "summary_text": summary_text,
        "content_hash": content_hash,
        "source_message_count": message_count,
        "created_at": now,
        "updated_at": now,
    }


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def load_log_messages_for_summary(config, date_from: str | None, date_to: str | None, limit_rows: int | None = None) -> list[dict]:
    db_path = Path(config.chat_agent_db_path)
    if not db_path.exists():
        return []
    try:
        conn = _connect_readonly(db_path)
    except Exception:
        return []

    try:
        sql = """
            SELECT
                id,
                source_file,
                log_time_text,
                event_time,
                message_id,
                message_type,
                group_id,
                group_name,
                user_id,
                nickname,
                group_card,
                plain_text
            FROM chat_agent_log_messages
            ORDER BY id ASC
        """
        params: tuple = ()
        if limit_rows is not None and int(limit_rows) > 0:
            sql += " LIMIT ?"
            params = (int(limit_rows),)
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "source_file": r[1],
                    "log_time_text": r[2],
                    "event_time": r[3],
                    "message_id": r[4],
                    "message_type": r[5],
                    "group_id": r[6],
                    "group_name": r[7],
                    "user_id": r[8],
                    "nickname": r[9],
                    "group_card": r[10],
                    "plain_text": r[11],
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


async def build_daily_summaries(
    config,
    date_from: str | None = None,
    date_to: str | None = None,
    limit_rows: int | None = None,
    limit_groups: int | None = None,
    dry_run: bool = True,
) -> dict:
    storage = _import_storage()
    raw = load_log_messages_for_summary(config, date_from, date_to, limit_rows=limit_rows)

    grouped: dict[tuple[str, str, str], list[dict]] = {}
    skipped_count = 0
    error_count = 0

    for r in raw:
        try:
            user_id = str(r.get("user_id", "") or "").strip()
            if not user_id:
                skipped_count += 1
                continue
            group_id_norm = _safe_group_id(r.get("group_id"))
            d = infer_message_date(r)
            if date_from and d != "unknown" and d < date_from:
                skipped_count += 1
                continue
            if date_to and d != "unknown" and d > date_to:
                skipped_count += 1
                continue
            key = (d, group_id_norm, user_id)
            grouped.setdefault(key, []).append(r)
        except Exception:
            error_count += 1

    summary_rows: list[dict] = []
    for _, msgs in grouped.items():
        try:
            row = build_daily_summary_row(msgs)
            if row is None:
                skipped_count += 1
                continue
            summary_rows.append(row)
        except Exception:
            error_count += 1

    if limit_groups is not None and int(limit_groups) > 0:
        summary_rows = summary_rows[: int(limit_groups)]

    written_count = 0
    if not dry_run:
        for row in summary_rows:
            try:
                await storage.upsert_user_daily_summary(config, row)
                written_count += 1
            except Exception:
                error_count += 1

    samples: list[dict] = []
    for row in summary_rows[:5]:
        s = str(row.get("summary_text", ""))
        samples.append(
            {
                "summary_key": row.get("summary_key"),
                "summary_date": row.get("summary_date"),
                "user_id": row.get("user_id"),
                "group_id": row.get("group_id"),
                "message_count": row.get("message_count"),
                "content_hash": row.get("content_hash"),
                "sample_messages_json": row.get("sample_messages_json"),
                "summary_text": s[:1200],
            }
        )

    return {
        "raw_messages_count": len(raw),
        "grouped_count": len(grouped),
        "summary_count": len(summary_rows),
        "written_count": written_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "samples": samples,
    }
