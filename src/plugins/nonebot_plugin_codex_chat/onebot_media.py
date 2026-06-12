from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import asyncio
import hashlib
import importlib.util
import logging
import re
import sys
from urllib.parse import urlparse

import httpx

MEDIA_ROOT = Path("data/nonebot_chat_agent/maibot_media")
DEFAULT_MAX_MEDIA_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadedMedia:
    source_url: str | None
    local_path: str | None
    sha256: str | None
    mime_type: str | None
    size_bytes: int
    kind: str
    original_segment: dict[str, Any]
    ok: bool
    error: str | None = None


_SAFE_MESSAGE_ID_RE = re.compile(r"[^0-9A-Za-z_-]+")


def normalize_onebot_segment(segment: Any) -> dict[str, Any]:
    try:
        if segment is None:
            return {"type": "unknown", "data": {"raw": "None"}}

        if isinstance(segment, dict):
            segment_type = str(segment.get("type") or "unknown").strip() or "unknown"
            data = segment.get("data")
            if isinstance(data, dict):
                return {"type": segment_type, "data": dict(data)}
            if data is None:
                return {"type": segment_type, "data": {}}
            return {"type": segment_type, "data": {"raw": data}}

        segment_type = str(getattr(segment, "type", "unknown") or "unknown").strip() or "unknown"
        data = getattr(segment, "data", None)
        if isinstance(data, dict):
            return {"type": segment_type, "data": dict(data)}
        if data is None:
            return {"type": segment_type, "data": {}}
        return {"type": segment_type, "data": {"raw": data}}
    except Exception:
        return {"type": "unknown", "data": {"raw": repr(segment)}}


def normalize_onebot_segments(message: Any) -> list[dict[str, Any]]:
    try:
        if message is None:
            return []
        if isinstance(message, (str, bytes, bytearray)):
            return [normalize_onebot_segment(message)]
        try:
            iterator = iter(message)
        except TypeError:
            return [normalize_onebot_segment(message)]
        return [normalize_onebot_segment(segment) for segment in iterator]
    except Exception:
        return []


def build_media_scope(group_id: str | None, user_id: str | None) -> str:
    if group_id:
        return f"group_{group_id}"
    if user_id:
        return f"private_{user_id}"
    return "unknown"


def infer_extension_from_mime(mime_type: str | None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/png":
        return ".png"
    if normalized == "image/gif":
        return ".gif"
    if normalized == "image/webp":
        return ".webp"
    return ".bin"


def build_incoming_media_path(
    *,
    group_id: str | None,
    user_id: str | None,
    message_id: str,
    index: int,
    mime_type: str | None,
) -> Path:
    scope = build_media_scope(group_id, user_id)
    date_part = datetime.now().strftime("%Y%m%d")
    safe_message_id = _SAFE_MESSAGE_ID_RE.sub("_", str(message_id or "")).strip("_") or "message"
    ext = infer_extension_from_mime(mime_type)
    return MEDIA_ROOT / "incoming" / scope / date_part / f"{safe_message_id}_{index}{ext}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_mime_from_bytes(data: bytes, fallback: str | None = None) -> str | None:
    if not data:
        return fallback
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return fallback


def extract_media_url(segment: dict[str, Any]) -> str | None:
    data = segment.get("data") if isinstance(segment, dict) else None
    if not isinstance(data, dict):
        return None
    for key in ("url", "file", "file_id"):
        value = data.get(key)
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate
    return None


def is_media_segment_type(segment_type: str) -> bool:
    return str(segment_type or "").strip().lower() in {"image", "mface", "emoji"}


def _classify_onebot_media_kind(seg_type: str, data: dict[str, Any]) -> str:
    """Classify OneBot media segment kind, treating animated QQ emojis as ``"emoji"``.

    In OneBot V11, QQ animated emojis (黄脸/动画表情) arrive as ``type=image``
    with ``summary`` containing ``"[动画表情]"`` or ``sub_type`` equal to ``1``.
    This helper reclassifies them so they enter the emoji pipeline.
    """
    if seg_type in {"mface", "emoji"}:
        return "emoji"
    if seg_type != "image":
        return seg_type
    if not isinstance(data, dict):
        return "image"
    summary = str(data.get("summary") or "").strip()
    if "动画表情" in summary:
        return "emoji"
    sub_type = str(data.get("sub_type") or "").strip()
    if sub_type == "1":
        return "emoji"
    return "image"


def _coerce_content_type(response: httpx.Response) -> str | None:
    content_type = str(response.headers.get("content-type") or "").strip().lower()
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip() or None


def _media_url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None


def _log_media_event(event: str, *, kind: str, index: int, mime: str | None = None, size: int | None = None, path_exists: bool | None = None, error: str | None = None, url_present: bool | None = None, url_host: str | None = None) -> None:
    LOGGER.info(
        "%s kind=%s index=%s mime=%s size=%s path_exists=%s error=%s url_host=%s source_url_present=%s",
        event,
        kind,
        index,
        mime,
        size,
        path_exists,
        error,
        url_host,
        url_present,
    )


async def download_onebot_media(
    segment: dict[str, Any],
    *,
    group_id: str | None,
    user_id: str | None,
    message_id: str,
    index: int,
    kind: str | None = None,
    max_bytes: int = DEFAULT_MAX_MEDIA_BYTES,
    timeout_seconds: float = 8.0,
) -> DownloadedMedia:
    normalized_segment = normalize_onebot_segment(segment)
    segment_kind = str(kind or normalized_segment.get("type") or "unknown").strip() or "unknown"
    try:
        url = extract_media_url(normalized_segment)
        if not url:
            return DownloadedMedia(
                source_url=None,
                local_path=None,
                sha256=None,
                mime_type=None,
                size_bytes=0,
                kind=segment_kind,
                original_segment=normalized_segment,
                ok=False,
                error="missing_media_url",
            )

        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout_seconds) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return DownloadedMedia(
                        source_url=url,
                        local_path=None,
                        sha256=None,
                        mime_type=None,
                        size_bytes=0,
                        kind=segment_kind,
                        original_segment=normalized_segment,
                        ok=False,
                        error=f"http_status_{response.status_code}",
                    )

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            return DownloadedMedia(
                                source_url=url,
                                local_path=None,
                                sha256=None,
                                mime_type=None,
                                size_bytes=0,
                                kind=segment_kind,
                                original_segment=normalized_segment,
                                ok=False,
                                error="max_media_size_exceeded",
                            )
                    except ValueError:
                        pass

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        return DownloadedMedia(
                            source_url=url,
                            local_path=None,
                            sha256=None,
                            mime_type=None,
                            size_bytes=len(body),
                            kind=segment_kind,
                            original_segment=normalized_segment,
                            ok=False,
                            error="max_media_size_exceeded",
                        )

                raw_bytes = bytes(body)
                header_mime = _coerce_content_type(response)
                final_mime = guess_mime_from_bytes(raw_bytes, fallback=header_mime)
                if final_mime not in ALLOWED_IMAGE_MIME_TYPES:
                    return DownloadedMedia(
                        source_url=url,
                        local_path=None,
                        sha256=None,
                        mime_type=final_mime,
                        size_bytes=len(raw_bytes),
                        kind=segment_kind,
                        original_segment=normalized_segment,
                        ok=False,
                        error=f"unsupported_mime_type:{final_mime}",
                    )

                digest = sha256_bytes(raw_bytes)
                final_path = build_incoming_media_path(
                    group_id=group_id,
                    user_id=user_id,
                    message_id=message_id,
                    index=index,
                    mime_type=final_mime,
                )
                final_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = final_path.with_name(final_path.name + ".tmp")
                temp_path.write_bytes(raw_bytes)
                temp_path.replace(final_path)

                return DownloadedMedia(
                    source_url=url,
                    local_path=str(final_path),
                    sha256=digest,
                    mime_type=final_mime,
                    size_bytes=len(raw_bytes),
                    kind=segment_kind,
                    original_segment=normalized_segment,
                    ok=True,
                )
    except Exception as exc:
        return DownloadedMedia(
            source_url=extract_media_url(normalized_segment),
            local_path=None,
            sha256=None,
            mime_type=None,
            size_bytes=0,
            kind=segment_kind,
            original_segment=normalized_segment,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )


@dataclass(slots=True)
class ConvertedMessage:
    components: list[Any]
    plain_text: str
    raw_segments: list[dict[str, Any]]
    media: list[DownloadedMedia]


async def _load_maibot_component_types():
    bootstrap_path = Path(__file__).resolve().parent / "maibot_core" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("onebot_media_maibot_bootstrap", bootstrap_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 bootstrap: {bootstrap_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    bootstrap_src_alias = getattr(module, "bootstrap_src_alias", None)
    if callable(bootstrap_src_alias):
        bootstrap_src_alias()

    from src.common.data_models.message_component_data_model import (
        AtComponent,
        DictComponent,
        EmojiComponent,
        ImageComponent,
        ReplyComponent,
        TextComponent,
    )

    return {
        "AtComponent": AtComponent,
        "DictComponent": DictComponent,
        "EmojiComponent": EmojiComponent,
        "ImageComponent": ImageComponent,
        "ReplyComponent": ReplyComponent,
        "TextComponent": TextComponent,
    }


def _build_dict_component(segment: dict[str, Any], reason: str | None = None):
    payload = dict(segment)
    if reason:
        payload.setdefault("meta", {})
        if isinstance(payload["meta"], dict):
            payload["meta"]["reason"] = reason
        else:
            payload["meta"] = {"reason": reason}
    return {"type": "dict", "data": payload}


def _expand_forward_node_text(node_message: Any) -> str:
    """将 forward node 的 message 字段展开为纯文本（扁平化，不递归识别）。"""
    if isinstance(node_message, str):
        return node_message.strip()
    if not isinstance(node_message, (list, tuple)):
        return ""

    parts: list[str] = []
    for seg in node_message:
        seg = normalize_onebot_segment(seg)
        seg_type = str(seg.get("type") or "").strip().lower()
        seg_data = seg.get("data") if isinstance(seg.get("data"), dict) else {}

        if seg_type == "text":
            text = str(seg_data.get("text") or "").strip()
            if text:
                parts.append(text)
        elif seg_type in ("image", "mface"):
            parts.append("[图片]")
        elif seg_type in ("emoji", "face"):
            parts.append("[表情]")
        elif seg_type == "forward":
            parts.append("[嵌套合并转发]")
        else:
            summary = str(seg_data.get("summary") or seg_data.get("text") or "").strip()
            if summary:
                parts.append(summary)

    return "".join(parts).strip()


async def convert_onebot_segments_to_maibot_components(
    message: Any,
    *,
    group_id: str | None,
    user_id: str | None,
    message_id: str,
    self_id: str | None = None,
    bot: Any | None = None,
    download_media: bool = True,
) -> ConvertedMessage:
    comps = await _load_maibot_component_types()
    AtComponent = comps["AtComponent"]
    DictComponent = comps["DictComponent"]
    EmojiComponent = comps["EmojiComponent"]
    ImageComponent = comps["ImageComponent"]
    ReplyComponent = comps["ReplyComponent"]
    TextComponent = comps["TextComponent"]

    raw_segments = normalize_onebot_segments(message)
    components: list[Any] = []
    media: list[DownloadedMedia] = []
    plain_parts: list[str] = []

    for index, segment in enumerate(raw_segments):
        seg_type = str(segment.get("type") or "unknown").strip().lower()
        data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
        if not isinstance(data, dict):
            data = {}

        def append_plain(text: str) -> None:
            text = str(text or "").strip()
            if text:
                plain_parts.append(text)

        if seg_type == "text":
            text = str(data.get("text") or data.get("content") or data.get("message") or "").strip()
            if text:
                components.append(TextComponent(text=text))
                append_plain(text)
            continue

        if seg_type == "at":
            target_user_id = str(
                data.get("qq") or data.get("user_id") or data.get("target_user_id") or data.get("id") or ""
            ).strip()
            if target_user_id:
                nickname = str(data.get("nickname") or data.get("target_user_nickname") or data.get("name") or "").strip() or None
                cardname = str(data.get("card") or data.get("target_user_cardname") or "").strip() or None
                target_user_is_bot = bool(self_id and target_user_id == self_id)
                components.append(AtComponent(
                    target_user_id=target_user_id,
                    target_user_nickname=nickname,
                    target_user_cardname=cardname,
                    target_user_is_bot=target_user_is_bot,
                ))
                if target_user_id == "all":
                    append_plain("[@全体成员]")
                elif target_user_is_bot:
                    append_plain(f"[@{target_user_id}(当前bot)]")
                else:
                    append_plain(f"[@{target_user_id}(不是当前bot)]")
                if target_user_is_bot:
                    LOGGER.info(f"onebot_media_at_segment kind=bot qq={target_user_id} self_id={self_id} source=event.self_id")
                else:
                    LOGGER.info(f"onebot_media_at_segment kind=user qq={target_user_id} self_id={self_id or ''} source=event.self_id")
            else:
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason="missing_at_target")["data"])))
            continue

        if seg_type == "reply":
            target_message_id = str(
                data.get("id") or data.get("message_id") or data.get("target_message_id") or ""
            ).strip()
            if target_message_id:
                components.append(ReplyComponent(target_message_id=target_message_id))
                append_plain(f"[回复:{target_message_id}]")
            else:
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason="missing_reply_target")["data"])))
            continue

        if seg_type in {"image", "mface", "emoji"}:
            if download_media and seg_type in {"image", "mface", "emoji"}:
                media_item = await download_onebot_media(
                    segment,
                    group_id=group_id,
                    user_id=user_id,
                    message_id=message_id,
                    index=index,
                    kind=seg_type,
                )
                media.append(media_item)
                url_host = _media_url_host(media_item.source_url)
                if media_item.ok and media_item.local_path:
                    binary_data = Path(media_item.local_path).read_bytes()
                    binary_exists = bool(binary_data)
                    effective_kind = _classify_onebot_media_kind(seg_type, data)
                    _log_media_event(
                        "onebot_media_download_ok",
                        kind=effective_kind,
                        index=index,
                        mime=media_item.mime_type,
                        size=media_item.size_bytes,
                        path_exists=Path(media_item.local_path).exists(),
                        error=None,
                        url_present=bool(media_item.source_url),
                        url_host=url_host,
                    )
                    if effective_kind == "image":
                        components.append(ImageComponent(binary_hash=media_item.sha256 or sha256_bytes(binary_data), binary_data=binary_data))
                        append_plain("[图片]")
                    else:
                        components.append(EmojiComponent(binary_hash=media_item.sha256 or sha256_bytes(binary_data), binary_data=binary_data))
                        append_plain("[表情]")
                    continue
                _log_media_event(
                    "onebot_media_download_failed",
                    kind=seg_type,
                    index=index,
                    mime=media_item.mime_type,
                    size=media_item.size_bytes,
                    path_exists=bool(media_item.local_path and Path(media_item.local_path).exists()),
                    error=media_item.error,
                    url_present=bool(media_item.source_url),
                    url_host=url_host,
                )
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason=media_item.error or "download_failed")["data"])))
                append_plain("[图片:下载失败]" if seg_type == "image" else "[表情:下载失败]")
                continue
            _log_media_event(
                "onebot_media_download_skipped",
                kind=seg_type,
                index=index,
                mime=None,
                size=None,
                path_exists=False,
                error="download_disabled",
                url_present=bool(extract_media_url(segment)),
                url_host=_media_url_host(extract_media_url(segment)),
            )
            components.append(DictComponent(data=dict(_build_dict_component(segment, reason="download_disabled")["data"])))
            append_plain("[图片]" if seg_type == "image" else "[表情]")
            continue

        if seg_type == "face":
            components.append(DictComponent(data=dict(_build_dict_component(segment, reason="face_not_mapped")["data"])))
            append_plain("[表情]")
            continue

        if seg_type == "forward":
            forward_id = str(data.get("id") or data.get("forward_id") or "").strip()
            if not forward_id:
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason="forward_missing_id")["data"])))
                append_plain("[合并转发消息: 缺少 id]")
                continue

            if bot is None:
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason="forward_no_bot")["data"])))
                append_plain(f"[合并转发消息: 未展开 id={forward_id}]")
                continue

            try:
                forward_data = await bot.call_api("get_forward_msg", id=forward_id)
            except Exception as exc:
                LOGGER.warning(
                    "onebot_media_forward_expand_failed id=%s error=%r",
                    forward_id, exc,
                )
                components.append(DictComponent(data=dict(_build_dict_component(segment, reason=f"forward_expand_error:{exc}")["data"])))
                append_plain(f"[合并转发消息: 展开失败 id={forward_id}]")
                continue

            messages = (
                forward_data.get("messages")
                or forward_data.get("nodes")
                or (forward_data.get("data") or {}).get("messages")
                or (forward_data.get("data") or {}).get("nodes")
                or []
            )
            if not isinstance(messages, (list, tuple)):
                messages = []

            lines: list[str] = []
            for node in messages:
                if not isinstance(node, dict):
                    continue
                sender = node.get("sender") or {}
                sender_name = (
                    str(sender.get("nickname") or sender.get("card") or sender.get("user_id") or "未知用户")
                    if isinstance(sender, dict)
                    else "未知用户"
                )
                node_msg = node.get("message") or node.get("content") or node.get("messages") or ""
                node_text = _expand_forward_node_text(node_msg)
                if node_text:
                    lines.append(f"【{sender_name}】: {node_text}")

            if lines:
                forward_text = "【合并转发消息:\n" + "\n".join(lines) + "\n】"
            else:
                forward_text = f"[合并转发消息: 空 id={forward_id}]"

            components.append(DictComponent(data=dict(_build_dict_component(segment, reason="forward_expanded")["data"])))
            append_plain(forward_text)
            LOGGER.info(
                "onebot_media_forward_expand_done id=%s nodes=%s text_len=%s",
                forward_id, len(messages), len(forward_text),
            )
            continue

        components.append(DictComponent(data=dict(_build_dict_component(segment, reason="unknown_segment")["data"])))
        summary = str(data.get("summary") or data.get("text") or "").strip()
        if summary:
            append_plain(summary)
        else:
            append_plain("[未知消息]")

    converted = ConvertedMessage(
        components=components,
        plain_text="".join(plain_parts).strip(),
        raw_segments=raw_segments,
        media=media,
    )
    media_ok = sum(1 for item in media if item.ok)
    media_failed = sum(1 for item in media if not item.ok)
    LOGGER.info(
        "onebot_media_convert_done segments=%s components=%s media=%s ok=%s failed=%s plain_text_len=%s",
        len(raw_segments),
        len(components),
        len(media),
        media_ok,
        media_failed,
        len(converted.plain_text),
    )
    return converted


async def download_onebot_media_stub(*_args: Any, **_kwargs: Any) -> DownloadedMedia:
    await asyncio.sleep(0)
    return DownloadedMedia(
        source_url=None,
        local_path=None,
        sha256=None,
        mime_type=None,
        size_bytes=0,
        kind=str(_kwargs.get("kind") or "unknown"),
        original_segment=dict(_kwargs.get("original_segment") or {}),
        ok=False,
        error="download_not_implemented",
    )
