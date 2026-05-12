from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RocoCrawlerConfig:
    base_url: str
    output_dir: Path
    assets_dir: Path
    request_delay: float = 0.5
    timeout: float = 20.0
    max_pages: int = 200
    download_images: bool = True
    user_agent: str = "HimariBot-RocoCrawler/1.0"


def fetch_url(url: str, timeout: float, user_agent: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": str(user_agent or "HimariBot-RocoCrawler/1.0")})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 20.0))) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def fetch_json_with_retry(url: str, params: dict, retries: int = 3, timeout: float = 10.0, user_agent: str = "Mozilla/5.0 HimariBot/knowledge-pack-crawler") -> dict:
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}"
    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 10.0))) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                raw = resp.read().decode("utf-8", errors="replace")
            if code == 567:
                time.sleep(3 * attempt)
                continue
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            last_err = e
            if int(getattr(e, "code", 0) or 0) == 567 and attempt < retries:
                time.sleep(3 * attempt)
                continue
            if attempt < retries:
                time.sleep(1.0 * attempt)
                continue
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * attempt)
                continue
    raise RuntimeError(f"fetch_json_failed:{type(last_err).__name__}:{str(last_err)[:200]}")


def parse_index_links(html: str, base_url: str) -> list[str]:
    text = str(html or "")
    base = str(base_url or "").strip()
    if not base:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', text, flags=re.IGNORECASE):
        h = str(href or "").strip()
        if not h or h.startswith("#") or h.lower().startswith("javascript:"):
            continue
        low = h.lower()
        if any(x in low for x in ["/edit", "/history", "/comment", "action=edit", "login", "signin"]):
            continue
        full = urllib.parse.urljoin(base, h)
        u = urllib.parse.urlparse(full)
        b = urllib.parse.urlparse(base)
        if u.scheme not in {"http", "https"}:
            continue
        if b.netloc and u.netloc and u.netloc != b.netloc:
            continue
        clean = urllib.parse.urlunparse((u.scheme, u.netloc, u.path, "", "", ""))
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def parse_roco_page(html: str, url: str) -> dict:
    text = str(html or "")
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
    if not title:
        m2 = re.search(r"<h1[^>]*>(.*?)</h1>", text, flags=re.IGNORECASE | re.DOTALL)
        if m2:
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m2.group(1))).strip()
    body = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    image_url = ""
    mi = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
    if mi:
        image_url = urllib.parse.urljoin(url, mi.group(1).strip())
    blob = (title + " " + url).lower()
    category = "other"
    if any(x in blob for x in ["宠物", "pet"]):
        category = "pet"
    elif any(x in blob for x in ["技能", "skill"]):
        category = "skill"
    elif any(x in blob for x in ["道具", "item", "咕噜球", "果实", "技能石"]):
        category = "item"
    elif any(x in blob for x in ["家具", "furniture"]):
        category = "furniture"
    elif any(x in blob for x in ["蛋", "egg"]):
        category = "egg"
    return {
        "category": category,
        "name": title,
        "title": title,
        "content": body[:8000],
        "source_url": url,
        "image_url": image_url,
        "metadata": {"parsed_from": "html"},
    }


def _extract_first_image_from_html(html: str, page_url: str) -> str:
    for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', str(html or ""), flags=re.IGNORECASE):
        s = str(src or "").strip()
        if not s:
            continue
        if s.startswith("//"):
            return "https:" + s
        return urllib.parse.urljoin(page_url, s)
    return ""


def _classify_roco_category(title: str, source_url: str, categories: list[str] | None = None) -> str:
    blob = f"{title} {source_url} {' '.join(categories or [])}".lower()
    if any(x in blob for x in ["宠物", "pet"]):
        return "pet"
    if any(x in blob for x in ["技能", "skill"]):
        return "skill"
    if any(x in blob for x in ["道具", "item", "咕噜球", "果实", "技能石"]):
        return "item"
    if any(x in blob for x in ["家具", "furniture"]):
        return "furniture"
    if any(x in blob for x in ["蛋", "egg"]):
        return "egg"
    return "other"


def download_image(url: str, target_path: Path, timeout: float = 20.0, user_agent: str = "HimariBot-RocoCrawler/1.0") -> bool:
    if target_path.exists() and target_path.stat().st_size > 0:
        return True
    target_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": str(user_agent or "HimariBot-RocoCrawler/1.0")})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 20.0))) as resp:
        raw = resp.read()
    if not raw:
        return False
    target_path.write_bytes(raw)
    return target_path.exists() and target_path.stat().st_size > 0


def crawl_roco_world_source(config: RocoCrawlerConfig, fetcher=None) -> dict:
    base_url = str(config.base_url or "").strip()
    api_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api.php")
    out_dir = Path(config.output_dir)
    source_dir = out_dir / "source"
    assets_root = Path(config.assets_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    skipped = 0
    assets_count = 0
    records: list[dict] = []
    fetch_json = fetcher or fetch_json_with_retry
    pages: list[dict] = []
    cont = ""
    while len(pages) < int(max(1, config.max_pages)):
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": 0,
            "aplimit": 50,
            "format": "json",
        }
        if cont:
            params["apcontinue"] = cont
        try:
            data = fetch_json(api_url, params, retries=3, timeout=config.timeout, user_agent="Mozilla/5.0 HimariBot/knowledge-pack-crawler")
            batch = list(((data.get("query") or {}).get("allpages") or []))
            pages.extend(batch)
            cont = str(((data.get("continue") or {}).get("apcontinue") or "")).strip()
            if not cont:
                break
        except Exception as e:
            errors.append(f"allpages_failed:{type(e).__name__}:{str(e)[:200]}")
            break

    pages = pages[: int(max(1, config.max_pages))]
    for p in pages:
        pageid = int(p.get("pageid", 0) or 0)
        title = str(p.get("title", "") or "").strip()
        if pageid <= 0 or not title:
            skipped += 1
            continue
        params = {
            "action": "parse",
            "pageid": pageid,
            "prop": "text|displaytitle|images|categories|links",
            "format": "json",
        }
        try:
            data = fetch_json(api_url, params, retries=3, timeout=config.timeout, user_agent="Mozilla/5.0 HimariBot/knowledge-pack-crawler")
            parsed = data.get("parse") or {}
            html = str(((parsed.get("text") or {}).get("*") or ""))
            displaytitle = str(parsed.get("displaytitle") or title).strip()
            plain = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
            plain = re.sub(r"<[^>]+>", " ", plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            cats = [str(x.get("*", "")).strip() for x in (parsed.get("categories") or []) if isinstance(x, dict)]
            page_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", urllib.parse.quote(title))
            image_url = _extract_first_image_from_html(html, page_url)
            category = _classify_roco_category(displaytitle or title, page_url, cats)
            rec = {
                "category": category,
                "name": title,
                "title": displaytitle or title,
                "content": plain[:8000],
                "source_url": page_url,
                "image_url": image_url,
                "image_path": "",
                "metadata": {
                    "source_type": "mediawiki_api",
                    "pageid": pageid,
                    "displaytitle": displaytitle,
                    "categories": cats[:50],
                },
            }
            if image_url and config.download_images:
                try:
                    u = urllib.parse.urlparse(str(image_url))
                    ext = Path(u.path).suffix or ".jpg"
                    local = assets_root / "images" / category / f"{pageid}{ext}"
                    if download_image(str(image_url), local, timeout=config.timeout, user_agent=config.user_agent):
                        rec["image_path"] = str(local).replace("\\", "/")
                        assets_count += 1
                except Exception as ie:
                    errors.append(f"image_download_failed:{type(ie).__name__}:{str(ie)[:120]}")
            records.append(rec)
            time.sleep(max(0.0, float(config.request_delay or 0.0)))
        except Exception as e:
            errors.append(f"parse_failed:{type(e).__name__}:{str(e)[:200]}")
            skipped += 1

    records_path = source_dir / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as wf:
        for r in records:
            wf.write(json.dumps(r, ensure_ascii=False) + "\n")
    (source_dir / "crawl_state.json").write_text(
        json.dumps(
            {
                "ok": True,
                "base_url": base_url,
                "visited_count": len(pages),
                "records_count": len(records),
                "assets_count": assets_count,
                "skipped_count": skipped,
                "errors": errors[:200],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "records_count": len(records),
        "assets_count": assets_count,
        "skipped_count": skipped,
        "errors": errors[:50],
        "records_path": str(records_path),
        "assets_dir": str(assets_root),
    }
