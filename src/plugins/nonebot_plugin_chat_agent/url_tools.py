from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

import httpx


_URL_RE = re.compile(r"https?://[^\s]+", re.I)
_TRAILING_PUNCT = "：:，,。.;；、)）]】}>》\"'“”‘’"


def extract_urls(text: str) -> list[str]:
    raw = text or ""
    found = _URL_RE.findall(raw)
    out: list[str] = []
    seen = set()
    for item in found:
        cleaned = item.rstrip(_TRAILING_PUNCT)
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def classify_url(url: str) -> str:
    u = (url or "").lower()
    if "b23.tv" in u or "bilibili.com/video/" in u:
        return "bilibili_video"
    if "huggingface.co/models" in u:
        return "huggingface_models"
    if "huggingface.co" in u:
        return "huggingface"
    return "web_page"


def parse_huggingface_models_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "huggingface.co" or parsed.path.rstrip("/") != "/models":
        return ""
    qs = parse_qs(parsed.query, keep_blank_values=True)
    parts = ["这是 Hugging Face 的模型搜索/筛选页面。"]
    filters = []
    if "num_parameters" in qs:
        filters.append(f"参数量 num_parameters={qs['num_parameters'][0]}")
    if "sort" in qs:
        filters.append(f"排序 sort={qs['sort'][0]}")
    if "search" in qs:
        filters.append(f"搜索关键词 search={qs['search'][0]}")
    if filters:
        parts.append("筛选条件：" + "，".join(filters) + "。")
    else:
        parts.append("URL 中没有明确筛选条件。")
    return "\n".join(parts)


def _pick_meta(html_text: str, key: str, is_property: bool = False) -> str:
    attr = "property" if is_property else "name"
    m = re.search(
        rf'<meta[^>]*{attr}\s*=\s*["\']{re.escape(key)}["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
        html_text,
        flags=re.I,
    )
    return html.unescape(m.group(1).strip()) if m else ""


def _extract_page_bits(html_text: str) -> tuple[str, str, str]:
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_m.group(1)).strip()) if title_m else ""
    desc = _pick_meta(html_text, "description") or _pick_meta(html_text, "og:description", is_property=True)
    og_title = _pick_meta(html_text, "og:title", is_property=True)
    if not title and og_title:
        title = og_title

    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.I | re.S)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    preview = cleaned[:1000]
    return title, desc, preview


async def build_direct_url_context(config, prompt: str, urls: list[str]) -> str:
    if not urls:
        return ""
    selected = urls[:2]
    timeout = int(getattr(config, "chat_agent_web_timeout", 20) or 20)
    ua = str(getattr(config, "chat_agent_web_user_agent", "Mozilla/5.0") or "Mozilla/5.0")
    headers = {"User-Agent": ua}
    lines: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, headers=headers, follow_redirects=True) as client:
        for i, url in enumerate(selected, start=1):
            kind = classify_url(url)
            lines.append(f"[URL {i}] {url}")
            lines.append(f"- 类型：{kind}")
            if kind == "huggingface_models":
                parsed = parse_huggingface_models_url(url)
                if parsed:
                    lines.append(parsed)
            if kind == "bilibili_video":
                lines.append("- 限制说明：这是视频页；当前只读取到页面元信息/简介，未下载或观看视频内容，也未做字幕/音频分析。")
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                html_text = resp.text or ""
                title, desc, preview = _extract_page_bits(html_text)
                if title:
                    lines.append(f"- 标题：{title}")
                if desc:
                    lines.append(f"- 描述：{desc}")
                if preview:
                    lines.append(f"- 页面预览：{preview}")
            except Exception as e:
                lines.append(f"- 读取失败：{type(e).__name__}")
            lines.append("")
    return "\n".join(lines).strip()
