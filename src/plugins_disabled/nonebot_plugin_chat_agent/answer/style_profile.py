from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


_WS_RE = re.compile(r"\s+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_URL_RE = re.compile(r"^`?\s*https?://\S+\s*`?$", re.IGNORECASE)


def _import_storage():
    if __package__ in (None, ""):
        cur_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(cur_dir))
        import storage  # type: ignore

        return storage
    from . import storage

    return storage


def normalize_style_text(text: str) -> str:
    raw = str(text or "")
    raw = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    s = _WS_RE.sub(" ", raw.strip())
    if not s:
        return ""
    low_fragments = (
        "[image:",
        "[CQ:image",
        "[json:",
        "[CQ:json",
        "[forward:",
        "[CQ:forward",
        "[record:",
        "[CQ:record",
        "[video:",
        "[CQ:video",
        "[file:",
        "[CQ:file",
    )
    if any(f in s for f in low_fragments):
        return ""
    if s.startswith("/"):
        return ""
    if _URL_RE.fullmatch(s):
        return ""
    if len(s) > 300:
        return ""
    return s


def load_log_messages_for_style(
    db_path: Path,
    user_id: str | None = None,
    group_id: str | None = None,
    limit_rows: int | None = None,
) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        sql = """
        SELECT
            id,
            event_time,
            bot_id,
            group_id,
            user_id,
            nickname,
            group_card,
            plain_text
        FROM chat_agent_log_messages
        WHERE plain_text IS NOT NULL AND plain_text != ''
        """
        params: list[object] = []
        if group_id is not None:
            sql += " AND group_id = ?"
            params.append(str(group_id))
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(str(user_id))
        sql += " ORDER BY id ASC"
        if limit_rows is not None and int(limit_rows) > 0:
            sql += " LIMIT ?"
            params.append(int(limit_rows))
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall()
        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "event_time": r[1],
                    "bot_id": r[2],
                    "group_id": r[3] or "",
                    "user_id": r[4] or "",
                    "nickname": r[5] or "",
                    "group_card": r[6] or "",
                    "plain_text": r[7] or "",
                }
            )
        return out
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def group_user_messages(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        user_id = str(r.get("user_id", "") or "").strip()
        if not user_id:
            continue
        bot_id = str(r.get("bot_id", "") or "").strip()
        if bot_id and user_id == bot_id:
            continue
        group_id = str(r.get("group_id", "") or "").strip()
        text = normalize_style_text(str(r.get("plain_text", "") or ""))
        if not text:
            continue
        item = {
            "id": int(r.get("id") or 0),
            "event_time": int(r.get("event_time") or 0) if r.get("event_time") not in (None, "", 0, "0") else 0,
            "user_id": user_id,
            "group_id": group_id,
            "nickname": str(r.get("nickname", "") or ""),
            "group_card": str(r.get("group_card", "") or ""),
            "text": text,
        }
        key = (group_id, user_id)
        grouped.setdefault(key, []).append(item)
    return grouped


def collect_peer_replies(
    rows: list[dict],
    target_user_id: str,
    target_group_id: str,
    reply_window_seconds: int = 180,
    max_replies: int = 30,
) -> list[str]:
    if not rows or not target_user_id:
        return []
    if not str(target_group_id or "").strip():
        return []
    group_rows = [r for r in rows if str(r.get("group_id", "") or "") == str(target_group_id or "")]
    if not group_rows:
        return []
    if not any(r.get("event_time") not in (None, "", 0, "0") for r in group_rows):
        return []

    group_rows.sort(key=lambda r: (int(r.get("event_time") or 0), int(r.get("id") or 0)))
    out: list[str] = []
    last_target_time: int | None = None
    window = int(reply_window_seconds)

    for r in group_rows:
        event_time = int(r.get("event_time") or 0)
        if event_time <= 0:
            continue
        user_id = str(r.get("user_id", "") or "").strip()
        if not user_id:
            continue
        bot_id = str(r.get("bot_id", "") or "").strip()
        if bot_id and user_id == bot_id:
            continue

        if user_id == target_user_id:
            last_target_time = event_time
            continue

        if last_target_time is None:
            continue
        if event_time <= last_target_time:
            continue
        if event_time > last_target_time + window:
            continue

        text = normalize_style_text(str(r.get("plain_text", "") or ""))
        if not text:
            continue
        out.append(text)
        if len(out) >= int(max_replies):
            break
    return out


def _contains_emoji(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if 0x1F300 <= code <= 0x1FAFF:
            return True
    return False


def _is_mixed_lang(text: str) -> bool:
    has_cjk = bool(_CJK_RE.search(text))
    has_ascii = any("a" <= c.lower() <= "z" for c in text)
    return has_cjk and has_ascii


def _is_question_like(text: str) -> bool:
    return any(tok in text for tok in ["?", "？", "吗", "啥", "什么", "怎么", "多少", "有没有"])


def _is_keyword_like(text: str) -> bool:
    s = text.strip()
    if " " not in s:
        return False
    if len(s) > 30:
        return False
    parts = [p for p in s.split(" ") if p]
    if len(parts) < 2:
        return False
    return True


def _has_tech_terms(text: str) -> bool:
    low = text.lower()
    tokens = [
        "docker",
        "k8s",
        "argocd",
        "rtx",
        "git",
        "api",
        "db",
        "sql",
        "port",
        "模型",
        "显卡",
        "端口",
        "数据库",
        "接口",
    ]
    return any(t in low for t in tokens)


def _has_url_or_bv(text: str) -> bool:
    if "http://" in text.lower() or "https://" in text.lower():
        return True
    return "BV" in text or "bv" in text


def _pick_samples(texts: list[str], limit: int = 20) -> list[str]:
    seen: set[str] = set()
    preferred: list[str] = []
    others: list[str] = []
    for t in texts:
        s = normalize_style_text(t)
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        if 2 <= len(s) <= 80:
            preferred.append(s)
        else:
            others.append(s)
    picked = preferred + others
    if len(picked) <= limit:
        return picked
    head = picked[: limit // 2]
    tail = picked[-(limit - len(head)) :]
    return head + tail


def _stable_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def build_user_style_profile(group_key: tuple[str, str], messages: list[str], peer_replies: list[str]) -> dict:
    group_id, user_id = group_key
    msg_count = len(messages)
    peer_count = len(peer_replies)

    lens = [len(m) for m in messages if m]
    avg_len = sum(lens) / len(lens) if lens else 0.0
    short_ratio = sum(1 for m in messages if len(m) <= 12) / msg_count if msg_count else 0.0
    medium_ratio = sum(1 for m in messages if 13 <= len(m) <= 40) / msg_count if msg_count else 0.0
    long_ratio = sum(1 for m in messages if len(m) > 40) / msg_count if msg_count else 0.0
    question_ratio = sum(1 for m in messages if _is_question_like(m)) / msg_count if msg_count else 0.0
    keyword_like_ratio = sum(1 for m in messages if _is_keyword_like(m)) / msg_count if msg_count else 0.0
    emoji_ratio = sum(1 for m in messages if _contains_emoji(m)) / msg_count if msg_count else 0.0
    url_ratio = sum(1 for m in messages if _has_url_or_bv(m)) / msg_count if msg_count else 0.0
    mixed_lang_ratio = sum(1 for m in messages if _is_mixed_lang(m)) / msg_count if msg_count else 0.0
    tech_term_ratio = sum(1 for m in messages if _has_tech_terms(m)) / msg_count if msg_count else 0.0

    casual_markers = ["草", "艹", "笑死", "离谱", "牛", "绷", "啊", "哦", "嗯"]
    casual_ratio = sum(1 for m in messages if any(t in m for t in casual_markers)) / msg_count if msg_count else 0.0

    if short_ratio >= 0.55:
        length_tendency = "偏短"
    elif long_ratio >= 0.35:
        length_tendency = "偏长"
    else:
        length_tendency = "中等"

    user_style_lines = [
        f"基于历史文本消息的说话风格画像（group_id={group_id or ''}, user_id={user_id}）。",
        f"样本量：message_count={msg_count}，平均长度≈{avg_len:.1f}，长度倾向：{length_tendency}（短{short_ratio:.0%}/中{medium_ratio:.0%}/长{long_ratio:.0%}）。",
        f"提问倾向：question_ratio≈{question_ratio:.0%}；关键词式提问：keyword_like_ratio≈{keyword_like_ratio:.0%}。",
        f"表达元素：emoji_ratio≈{emoji_ratio:.0%}；中英混合：mixed_lang_ratio≈{mixed_lang_ratio:.0%}；链接/代号：url_ratio≈{url_ratio:.0%}；技术词：tech_term_ratio≈{tech_term_ratio:.0%}。",
        f"语气标记：casual_tone_ratio≈{casual_ratio:.0%}（如“草/离谱/笑死”等）。",
        "这是风格画像，不代表事实记忆；仅反映历史发言的统计特征。",
    ]
    user_style_text = "\n".join(user_style_lines)

    peer_style_text = ""
    if peer_count < 5:
        peer_style_text = f"同群他人回复风格：样本不足（peer_reply_count={peer_count}），暂时无法稳定判断。"
    else:
        peer_lens = [len(m) for m in peer_replies if m]
        peer_avg = sum(peer_lens) / len(peer_lens) if peer_lens else 0.0
        peer_short = sum(1 for m in peer_replies if len(m) <= 12) / peer_count
        peer_question = sum(1 for m in peer_replies if _is_question_like(m)) / peer_count
        peer_casual = sum(1 for m in peer_replies if any(t in m for t in casual_markers)) / peer_count
        peer_style_text = "\n".join(
            [
                f"同群他人回复风格画像（peer_reply_count={peer_count}）。",
                f"回复长度：平均≈{peer_avg:.1f}，短句占比≈{peer_short:.0%}。",
                f"回复形态：反问/追问占比≈{peer_question:.0%}；调侃/随意语气占比≈{peer_casual:.0%}。",
                "仅反映窗口内的后续消息统计，可能包含泛聊，不等同于严格“对他回复”。",
            ]
        )

    rec_lines = ["建议 bot 回复方式："]
    if length_tendency == "偏短":
        rec_lines.append("- 优先给结论，保持简短；必要时再补一两步。")
    elif length_tendency == "偏长":
        rec_lines.append("- 可以适度解释原因与步骤，但先给结论，避免长篇铺垫。")
    else:
        rec_lines.append("- 先给结论，再给简明补充。")
    if tech_term_ratio >= 0.20 or question_ratio >= 0.30:
        rec_lines.append("- 技术/配置类问题优先给可执行步骤或命令示例。")
    if keyword_like_ratio >= 0.20:
        rec_lines.append("- 看到关键词式提问时，按“他在问这个主题的结论/状态”理解并直接回答。")
    if casual_ratio >= 0.25:
        rec_lines.append("- 语气可以稍微轻松，但避免过度玩梗，避免武断推断。")
    rec_lines.append("- 不要主动引用历史内容，除非用户明确询问历史/以前/谁说过。")
    recommended_bot_style = "\n".join(rec_lines)

    sample_messages = _pick_samples(messages, limit=20)
    sample_peer = _pick_samples(peer_replies, limit=20)

    content_payload = _stable_json(
        {
            "profile_key": f"style:{group_id}:{user_id}",
            "message_count": msg_count,
            "peer_reply_count": peer_count,
            "sample_messages": sample_messages,
            "sample_peer_replies": sample_peer,
            "user_style_text": user_style_text,
            "peer_response_style_text": peer_style_text,
            "recommended_bot_style": recommended_bot_style,
        }
    ).encode("utf-8")
    content_hash = hashlib.sha256(content_payload).hexdigest()

    now = datetime.now(timezone.utc).isoformat()
    return {
        "profile_key": f"style:{group_id}:{user_id}",
        "user_id": user_id,
        "group_id": group_id,
        "message_count": msg_count,
        "peer_reply_count": peer_count,
        "sample_messages_json": _stable_json(sample_messages),
        "sample_peer_replies_json": _stable_json(sample_peer),
        "user_style_text": user_style_text,
        "peer_response_style_text": peer_style_text,
        "recommended_bot_style": recommended_bot_style,
        "content_hash": content_hash,
        "created_at": now,
        "updated_at": now,
    }


async def build_style_profiles(
    config,
    user_id: str | None = None,
    group_id: str | None = None,
    min_messages: int = 5,
    limit_users: int | None = None,
    limit_rows: int | None = None,
    reply_window_seconds: int = 180,
    dry_run: bool = True,
) -> dict:
    db_path = Path(getattr(config, "chat_agent_db_path"))

    read_user_id = None
    read_group_id = group_id
    if group_id is not None and user_id is None:
        read_user_id = None
    elif group_id is not None and user_id is not None:
        read_user_id = None
    else:
        read_user_id = None

    rows = load_log_messages_for_style(db_path, user_id=read_user_id, group_id=read_group_id, limit_rows=limit_rows)
    rows_count = len(rows)

    grouped = group_user_messages(rows)
    keys = sorted(grouped.keys(), key=lambda k: len(grouped.get(k) or []), reverse=True)
    if group_id is not None:
        keys = [k for k in keys if k[0] == str(group_id)]
    if user_id is not None:
        keys = [k for k in keys if k[1] == str(user_id)]
    if limit_users is not None and int(limit_users) > 0:
        keys = keys[: int(limit_users)]

    storage = _import_storage()
    if not dry_run:
        await storage.init_storage(config)

    profile_count = 0
    written_count = 0
    skipped_count = 0
    error_count = 0
    samples: list[dict] = []

    for key in keys:
        try:
            items = grouped.get(key) or []
            texts = [it.get("text", "") for it in items if it.get("text")]
            if len(texts) < int(min_messages):
                skipped_count += 1
                continue

            peer = collect_peer_replies(
                rows,
                target_user_id=key[1],
                target_group_id=key[0],
                reply_window_seconds=int(reply_window_seconds),
                max_replies=30,
            )
            profile = build_user_style_profile(key, texts, peer)
            profile_count += 1
            if dry_run:
                if len(samples) < 5:
                    samples.append(
                        {
                            "profile_key": profile.get("profile_key"),
                            "message_count": profile.get("message_count"),
                            "peer_reply_count": profile.get("peer_reply_count"),
                            "content_hash": profile.get("content_hash"),
                            "user_style_text_head": str(profile.get("user_style_text", ""))[:300],
                            "recommended_bot_style_head": str(profile.get("recommended_bot_style", ""))[:300],
                        }
                    )
            else:
                await storage.upsert_user_style_profile(config, profile)
                written_count += 1
        except Exception:
            error_count += 1

    return {
        "dry_run": bool(dry_run),
        "rows_count": rows_count,
        "profile_count": profile_count,
        "written_count": written_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "samples": samples,
    }
