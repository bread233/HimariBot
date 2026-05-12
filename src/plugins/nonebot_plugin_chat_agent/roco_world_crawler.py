from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
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
    f = fetcher or fetch_url
    base_url = str(config.base_url or "").strip()
    out_dir = Path(config.output_dir)
    source_dir = out_dir / "source"
    assets_root = Path(config.assets_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    skipped = 0
    assets_count = 0
    records: list[dict] = []
    visited: set[str] = set()
    queue: list[str] = [base_url]

    try:
        index_html = f(base_url, config.timeout, config.user_agent)
        queue.extend(parse_index_links(index_html, base_url))
    except Exception as e:
        return {
            "ok": False,
            "errors": [f"index_fetch_failed:{type(e).__name__}:{str(e)[:200]}"],
            "records_count": 0,
            "assets_count": 0,
            "skipped_count": 0,
            "records_path": "",
            "assets_dir": str(assets_root),
        }

    while queue and len(visited) < int(max(1, config.max_pages)):
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            html = f(url, config.timeout, config.user_agent)
            rec = parse_roco_page(html, url)
            if rec.get("title") and rec.get("content"):
                if rec.get("image_url"):
                    if config.download_images:
                        try:
                            u = urllib.parse.urlparse(str(rec["image_url"]))
                            ext = Path(u.path).suffix or ".jpg"
                            local = assets_root / "images" / rec.get("category", "other") / f"{len(records)+1}{ext}"
                            if download_image(str(rec["image_url"]), local, timeout=config.timeout, user_agent=config.user_agent):
                                rec["image_path"] = str(local).replace("\\", "/")
                                assets_count += 1
                        except Exception as ie:
                            errors.append(f"image_download_failed:{type(ie).__name__}:{str(ie)[:120]}")
                    else:
                        rec["image_path"] = ""
                records.append(rec)
            else:
                skipped += 1
            for link in parse_index_links(html, base_url):
                if link not in visited and link not in queue and len(queue) < int(config.max_pages * 3):
                    queue.append(link)
            time.sleep(max(0.0, float(config.request_delay or 0.0)))
        except Exception as e:
            errors.append(f"page_failed:{type(e).__name__}:{str(e)[:200]}")
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
                "visited_count": len(visited),
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

