from __future__ import annotations

import json
import re
import time
import urllib.error
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
    user_agent: str = "Mozilla/5.0 HimariBot/knowledge-pack-crawler"
    crawler_limits: dict[str, int] | None = None


def _pick_ua(attempt: int) -> str:
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15",
        "Mozilla/5.0 HimariBot/knowledge-pack-crawler",
    ]
    return uas[(attempt - 1) % len(uas)]


def fetch_json_with_retry(url: str, params: dict, retries: int = 3, timeout: float = 10.0, user_agent: str = "") -> dict:
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}"
    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        ua = user_agent or _pick_ua(attempt)
        headers = {
            "User-Agent": ua,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": urllib.parse.urljoin(url, "/"),
        }
        try:
            req = urllib.request.Request(full, headers=headers)
            with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 10.0))) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            last_err = e
            if int(getattr(e, "code", 0) or 0) == 567 and attempt < retries:
                time.sleep(3 * attempt)
                continue
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
    raise RuntimeError(f"fetch_json_failed:{type(last_err).__name__}:{str(last_err)[:200]}")


def fetch_text_with_retry(url: str, retries: int = 3, timeout: float = 10.0) -> str:
    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        headers = {
            "User-Agent": _pick_ua(attempt),
            "Accept": "text/html,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": urllib.parse.urljoin(url, "/"),
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 10.0))) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if int(getattr(e, "code", 0) or 0) == 567 and attempt < retries:
                time.sleep(3 * attempt)
                continue
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
    raise RuntimeError(f"fetch_text_failed:{type(last_err).__name__}:{str(last_err)[:200]}")


def _call_with_retry(fn, *, retries: int = 3, delay_base: float = 3.0, errors: list[str] | None = None, label: str = ""):
    last_err = None
    for attempt in range(1, max(1, int(retries)) + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            last_err = e
            code = int(getattr(e, "code", 0) or 0)
            if attempt < retries and code == 567:
                time.sleep(max(0.0, float(delay_base)) * attempt)
                continue
            if attempt < retries:
                time.sleep(max(0.0, float(delay_base)) * 0.5 * attempt)
                continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(max(0.0, float(delay_base)) * 0.5 * attempt)
                continue
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(max(0.0, float(delay_base)) * 0.5 * attempt)
                continue
    if errors is not None:
        errors.append(f"{label}failed:{type(last_err).__name__}:{str(last_err)[:200]}")
    raise last_err


def _normalize_category_name(name: str) -> str:
    x = str(name or "").strip()
    if x.startswith("Category:"):
        x = x.split(":", 1)[1]
    return x


def fetch_category_members(api_url: str, category: str, timeout: float, limit: int, fetch_json=None) -> list[dict]:
    f = fetch_json or fetch_json_with_retry
    out: list[dict] = []
    cont = ""
    while len(out) < max(1, int(limit or 1)):
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": 50,
            "format": "json",
        }
        if cont:
            params["cmcontinue"] = cont
        data = f(api_url, params, retries=3, timeout=timeout)
        out.extend(((data.get("query") or {}).get("categorymembers") or []))
        cont = str(((data.get("continue") or {}).get("cmcontinue") or "")).strip()
        if not cont:
            break
    return out[: max(1, int(limit or 1))]


def _extract_image_url(text: str, page_url: str) -> str:
    html = str(text or "")
    for pat in [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r"\[\[(?:File|文件):([^|\]]+)",
    ]:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if not m:
            continue
        src = str(m.group(1) or "").strip()
        if not src:
            continue
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("http://") or src.startswith("https://"):
            return src
        return urllib.parse.urljoin(page_url, src)
    return ""


def _strip_markup(raw: str) -> str:
    text = str(raw or "")
    text = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[\[|\]\]|\{\{|\}\}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_page_content(base_url: str, title: str, timeout: float, fetch_text=None) -> tuple[str, str]:
    page_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", urllib.parse.quote(title))
    raw_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", f"index.php?title={urllib.parse.quote(title)}&action=raw")
    f = fetch_text or fetch_text_with_retry
    try:
        raw = f(raw_url, retries=3, timeout=timeout)
        return raw, page_url
    except Exception:
        html = f(page_url, retries=3, timeout=timeout)
        return html, page_url


def download_image(url: str, target_path: Path, timeout: float = 20.0) -> bool:
    if target_path.exists() and target_path.stat().st_size > 0:
        return True
    target_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _pick_ua(1)})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 20.0))) as resp:
        raw = resp.read()
    if not raw:
        return False
    target_path.write_bytes(raw)
    return target_path.exists() and target_path.stat().st_size > 0


def crawl_roco_world_source(config: RocoCrawlerConfig, fetch_json=None, fetch_text=None) -> dict:
    base_url = str(config.base_url or "").strip()
    api_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api.php")
    out_dir = Path(config.output_dir)
    source_dir = out_dir / "source"
    assets_root = Path(config.assets_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    limits = dict(config.crawler_limits or {})
    cat_defs = [
        ("Category:精灵", "pet", int(limits.get("pet", 50) or 50)),
        ("Category:技能", "skill", int(limits.get("skill", 50) or 50)),
        ("Category:道具", "item", int(limits.get("item", 50) or 50)),
        ("Category:精灵蛋", "egg", int(limits.get("egg", 50) or 50)),
        ("Category:家具", "furniture", int(limits.get("furniture", 50) or 50)),
    ]

    cat_defs = [
        ("\u0043\u0061\u0074\u0065\u0067\u006f\u0072\u0079\u003a\u7cbe\u7075", "pet", int(limits.get("pet", 1000) or 1000)),
        ("\u0043\u0061\u0074\u0065\u0067\u006f\u0072\u0079\u003a\u6280\u80fd", "skill", int(limits.get("skill", 1000) or 1000)),
        ("\u0043\u0061\u0074\u0065\u0067\u006f\u0072\u0079\u003a\u9053\u5177", "item", int(limits.get("item", 1000) or 1000)),
        ("\u0043\u0061\u0074\u0065\u0067\u006f\u0072\u0079\u003a\u7cbe\u7075\u86cb", "egg", int(limits.get("egg", 500) or 500)),
        ("\u0043\u0061\u0074\u0065\u0067\u006f\u0072\u0079\u003a\u5bb6\u5177", "furniture", int(limits.get("furniture", 500) or 500)),
    ]

    errors: list[str] = []
    skipped = 0
    assets_count = 0
    records: list[dict] = []
    visited_titles: set[str] = set()
    category_counts = {"pet": 0, "skill": 0, "item": 0, "egg": 0, "furniture": 0}

    for cmtitle, category, per_limit in cat_defs:
        if len(records) >= int(max(1, config.max_pages)):
            break
        try:
            members = _call_with_retry(
                lambda: fetch_category_members(api_url, cmtitle, config.timeout, per_limit, fetch_json=fetch_json),
                retries=3,
                delay_base=3.0,
                errors=errors,
                label=f"category:{cmtitle}:",
            )
        except Exception as e:
            errors.append(f"category_failed:{cmtitle}:{type(e).__name__}:{str(e)[:200]}")
            continue
        for m in members:
            if len(records) >= int(max(1, config.max_pages)):
                break
            title = str(m.get("title", "") or "").strip()
            if not title or title in visited_titles:
                continue
            visited_titles.add(title)
            try:
                raw_or_html, page_url = _call_with_retry(
                    lambda: _fetch_page_content(base_url, title, config.timeout, fetch_text=fetch_text),
                    retries=3,
                    delay_base=3.0,
                    errors=errors,
                    label=f"page:{title}:",
                )
                plain = _strip_markup(raw_or_html)[:8000]
                image_url = _extract_image_url(raw_or_html, page_url)
                rec = {
                    "category": category,
                    "name": title,
                    "title": title,
                    "content": plain,
                    "source_url": page_url,
                    "image_url": image_url,
                    "image_path": "",
                    "metadata": {
                        "source_type": "mediawiki_categorymembers",
                        "category": _normalize_category_name(cmtitle),
                    },
                }
                if image_url and config.download_images:
                    try:
                        u = urllib.parse.urlparse(image_url)
                        ext = Path(u.path).suffix or ".png"
                        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", title)[:80] or f"p{len(records)+1}"
                        local = assets_root / "images" / category / f"{safe_name}{ext}"
                        if download_image(image_url, local, timeout=config.timeout):
                            rec["image_path"] = str(local).replace("\\", "/")
                            assets_count += 1
                    except Exception as ie:
                        errors.append(f"image_failed:{title}:{type(ie).__name__}:{str(ie)[:120]}")
                records.append(rec)
                if category in category_counts:
                    category_counts[category] = int(category_counts.get(category, 0) or 0) + 1
                time.sleep(max(0.0, float(config.request_delay or 0.0)))
            except Exception as e:
                errors.append(f"page_failed:{title}:{type(e).__name__}:{str(e)[:200]}")
                skipped += 1

    records_path = source_dir / "records.jsonl"
    with records_path.open("w", encoding="utf-8") as wf:
        for r in records:
            wf.write(json.dumps(r, ensure_ascii=False) + "\n")

    state = {
        "ok": True,
        "base_url": base_url,
        "records_count": len(records),
        "assets_count": assets_count,
        "category_counts": category_counts,
        "skipped_count": skipped,
        "errors": errors[:200],
    }
    (source_dir / "crawl_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "records_count": len(records),
        "assets_count": assets_count,
        "skipped_count": skipped,
        "errors": errors[:50],
        "records_path": str(records_path),
        "assets_dir": str(assets_root),
        "category_counts": category_counts,
    }
