from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .paths import RocoWorldPaths

try:
    from ...roco_world_crawler import RocoCrawlerConfig, crawl_roco_world_source
except Exception:  # pragma: no cover
    from roco_world_crawler import RocoCrawlerConfig, crawl_roco_world_source


_ALLOWED_TYPES = {"pet", "skill", "item", "egg", "furniture", "region", "dungeon", "update_log"}
_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_ENTITY_TYPES = {"pet", "skill", "item", "egg", "furniture"}
_SITE_OG_ALLOWED = {"region", "dungeon", "update_log"}


def _route_other_type(row: dict) -> str:
    title = str(row.get("title") or row.get("name") or "").lower()
    content = str(row.get("content") or "").lower()
    text = f"{title}\n{content}"
    if any(k in text for k in ["region", "area", "\u5730\u56fe", "\u533a\u57df"]):
        return "region"
    if any(k in text for k in ["dungeon", "\u526f\u672c", "\u6311\u6218"]):
        return "dungeon"
    if any(k in text for k in ["update", "patch", "\u66f4\u65b0", "\u7ef4\u62a4", "\u516c\u544a"]):
        return "update_log"
    return "item"


def _normalize_records(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in records:
        row = dict(r)
        cat = str(row.get("category") or "").strip().lower()
        if cat not in _ALLOWED_TYPES:
            cat = _route_other_type(row)
        row["category"] = cat
        row.setdefault("name", str(row.get("title") or ""))
        row.setdefault("title", str(row.get("name") or ""))
        row.setdefault("aliases", [])
        row.setdefault("source_url", "")
        row.setdefault("image_url", "")
        row.setdefault("image_path", "")
        row.setdefault("metadata", {})
        out.append(row)
    return out


def _looks_image_ref(x: str) -> bool:
    s = str(x or "").strip().lower()
    return bool(s) and any(s.endswith(ext) for ext in _IMG_EXT)


def _normalize_url(raw: str, source_url: str, base_url: str) -> str:
    x = str(raw or "").strip()
    if not x:
        return ""
    if x.startswith("//"):
        return "https:" + x
    if x.startswith("http://") or x.startswith("https://"):
        return x
    if x.startswith("/"):
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", x)
    if _looks_image_ref(x) and source_url:
        return urllib.parse.urljoin(source_url.rstrip("/") + "/", x)
    return ""


def _pick_from_fields(row: dict) -> tuple[str, str]:
    fields = ["image_url", "icon_image", "sprite_image", "image", "thumbnail", "cover"]
    for k in fields:
        v = str(row.get(k) or "").strip()
        if v:
            return v, "existing_field"
    meta = dict(row.get("metadata") or {})
    for k in fields:
        v = str(meta.get(k) or "").strip()
        if v:
            return v, "existing_field"
    return "", ""


def _pick_from_wikitext(text: str) -> tuple[str, str]:
    raw = str(text or "")
    pats = [
        r"\[\[(?:文件|File)\s*:\s*([^|\]]+)\]\]",
        r"\|\s*(?:图片|精灵图片|icon)\s*=\s*([^\s|]+)",
    ]
    for pat in pats:
        m = re.search(pat, raw, flags=re.IGNORECASE)
        if not m:
            continue
        ref = str(m.group(1) or "").strip()
        if _looks_image_ref(ref):
            return ref, "wikitext"
    return "", ""


def _pick_from_html(html: str) -> tuple[str, str]:
    src = str(html or "")
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', src, flags=re.IGNORECASE)
    if m:
        return str(m.group(1) or "").strip(), "html_og"
    for key in ("src", "data-src", "data-original"):
        for m2 in re.finditer(rf'<img[^>]+{key}=["\']([^"\']+)["\']', src, flags=re.IGNORECASE):
            u = str(m2.group(1) or "").strip()
            low = u.lower()
            if any(bad in low for bad in ["logo", "blank", "placeholder", "icon"]):
                continue
            return u, "html_img"
    return "", ""


class _ImgCandidateParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if str(tag).lower() != "img":
            return
        data = {str(k).lower(): str(v or "").strip() for k, v in attrs}
        srcset = data.get("srcset", "")
        srcset_first = ""
        if srcset:
            srcset_first = str(srcset.split(",")[0].strip().split(" ")[0]).strip()
        src = data.get("src") or data.get("data-src") or data.get("data-original") or srcset_first
        if not src:
            return
        self.items.append(
            {
                "src": src,
                "alt": data.get("alt", ""),
                "title": data.get("title", ""),
                "class": data.get("class", ""),
                "width": data.get("width", ""),
                "height": data.get("height", ""),
            }
        )


def _is_bad_candidate(url: str) -> bool:
    low = str(url or "").strip().lower()
    if not low:
        return True
    return any(
        x in low
        for x in [
            "wiki.png",
            "logo",
            "icon",
            "favicon",
            "blank",
            "placeholder",
            "avatar",
            "default",
            "sprite_sheet",
            "/common/logo",
        ]
    )


def _small_img(meta: dict) -> bool:
    try:
        w = int(str(meta.get("width", "") or "0"))
    except Exception:
        w = 0
    try:
        h = int(str(meta.get("height", "") or "0"))
    except Exception:
        h = 0
    if w > 0 and h > 0 and (w < 64 or h < 64):
        return True
    return False


def _tokens_for_entity(record: dict) -> list[str]:
    t = str(record.get("title") or record.get("name") or "").strip()
    aliases = record.get("aliases") or []
    out = [x for x in [t] if x]
    for a in aliases:
        s = str(a or "").strip()
        if s:
            out.append(s)
    uniq: list[str] = []
    seen = set()
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _html_entity_candidates(record: dict, html: str, source_url: str, base_url: str, unresolved: str = "") -> tuple[list[dict], list[dict], dict]:
    parser = _ImgCandidateParser()
    parser.feed(str(html or ""))
    tokens = _tokens_for_entity(record)
    token_l = [x.lower() for x in tokens]
    unresolved_l = str(unresolved or "").strip().lower()
    accepted: list[dict] = []
    rejected: list[dict] = []
    checked = 0
    for it in parser.items:
        checked += 1
        src = str(it.get("src") or "").strip()
        url = _normalize_url(src, source_url, base_url)
        if not url:
            rejected.append({"url": src, "source": "html_img", "reason": "unresolved_url"})
            continue
        low = url.lower()
        if _is_bad_candidate(low):
            rejected.append({"url": url, "source": "html_img", "reason": "generic_url"})
            continue
        if _small_img(it):
            rejected.append({"url": url, "source": "html_img", "reason": "too_small"})
            continue
        alt = str(it.get("alt") or "")
        title = str(it.get("title") or "")
        hay = f"{alt}\n{title}\n{src}\n{url}".lower()
        src_kind = ""
        if token_l and any(tok in hay for tok in token_l):
            if any(tok in alt.lower() for tok in token_l):
                src_kind = "html_img_entity_alt"
            elif any(tok in title.lower() for tok in token_l):
                src_kind = "html_img_entity_title"
            else:
                src_kind = "html_img_entity_src"
        elif unresolved_l and unresolved_l in hay:
            src_kind = "html_img_unresolved_ref"
        if src_kind:
            accepted.append({"url": url, "source": src_kind})
        else:
            rejected.append({"url": url, "source": "html_img", "reason": "entity_mismatch"})
    # page-level raw counters
    raw_checked = checked
    raw_accepted = len(accepted)
    raw_rejected = len(rejected)
    # page-level unique counters (by url)
    accepted_unique = len({str(x.get("url") or "") for x in accepted if str(x.get("url") or "")})
    rejected_unique = len({str(x.get("url") or "") for x in rejected if str(x.get("url") or "")})
    candidate_unique = len(
        {
            str(x.get("url") or "")
            for x in (accepted + rejected)
            if str(x.get("url") or "")
        }
    )
    diag = {
        "raw_checked": raw_checked,
        "raw_accepted": raw_accepted,
        "raw_rejected": raw_rejected,
        "candidate_count": candidate_unique,
        "accepted_count": accepted_unique,
        "rejected_count": rejected_unique,
    }
    return accepted, rejected, diag


def _build_image_candidates(record: dict, *, timeout: float = 20.0, base_url: str = "") -> tuple[list[dict], str]:
    source_url = str(record.get("source_url") or "").strip()
    candidates: list[dict] = []
    direct, src = _pick_from_fields(record)
    if direct:
        url = _normalize_url(direct, source_url, base_url)
        if url and not _is_bad_candidate(url):
            candidates.append({"url": url, "source": src})
    wiki_ref, src2 = _pick_from_wikitext(str(record.get("content") or ""))
    unresolved = ""
    if wiki_ref:
        url = _normalize_url(wiki_ref, source_url, base_url)
        if url and not _is_bad_candidate(url):
            candidates.append({"url": url, "source": src2})
        else:
            unresolved = wiki_ref
    html = ""
    entity_rejected: list[dict] = []
    entity_diag = {}
    if source_url.startswith("http"):
        try:
            html = _fetch_page_html(source_url, timeout)
        except Exception:
            html = ""
    if html:
        cat = str(record.get("category") or "").strip().lower()
        if cat in _ENTITY_TYPES:
            html_accept, html_reject, html_diag = _html_entity_candidates(record, html, source_url, base_url, unresolved=unresolved)
            candidates.extend(html_accept)
            entity_rejected.extend(html_reject)
            entity_diag = html_diag
        else:
            html_ref, src3 = _pick_from_html(html)
            if html_ref:
                url = _normalize_url(html_ref, source_url, base_url)
                if url and not _is_bad_candidate(url):
                    candidates.append({"url": url, "source": src3})
    dedup: list[dict] = []
    seen = set()
    order = {"wikitext": 0, "html_img": 1, "existing_field": 2, "html_og": 3}
    for c in sorted(candidates, key=lambda x: order.get(str(x.get("source") or ""), 99)):
        u = str(c.get("url") or "")
        if u and u not in seen:
            seen.add(u)
            dedup.append(c)
    return dedup, unresolved, {"rejected": entity_rejected, "diag": entity_diag}


def _fetch_page_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(str(url), headers={"User-Agent": "Mozilla/5.0 HimariBot/knowledge-source"})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 20.0))) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_site_og_candidate(base_url: str, timeout: float) -> dict | None:
    try:
        html = _fetch_page_html(base_url, timeout)
    except Exception:
        return None
    ref, src = _pick_from_html(html)
    if not ref:
        return None
    url = _normalize_url(ref, base_url, base_url)
    if not url:
        return None
    return {"url": url, "source": f"{src}_site"}


def extract_image_url(record: dict, raw_text: str | None = None, html: str | None = None, *, timeout: float = 20.0, base_url: str = "") -> tuple[str, str, str]:
    source_url = str(record.get("source_url") or "").strip()
    direct, src = _pick_from_fields(record)
    if direct:
        url = _normalize_url(direct, source_url, base_url)
        if url:
            return url, src, ""
    wiki_ref, src2 = _pick_from_wikitext(raw_text or record.get("content") or "")
    if wiki_ref:
        url = _normalize_url(wiki_ref, source_url, base_url)
        if url:
            return url, src2, ""
        return "", "", wiki_ref
    if html is None and source_url.startswith("http"):
        try:
            html = _fetch_page_html(source_url, timeout)
        except Exception:
            html = ""
    html_ref, src3 = _pick_from_html(html or "")
    if html_ref:
        url = _normalize_url(html_ref, source_url, base_url)
        if url:
            return url, src3, ""
        return "", "", html_ref
    return "", "", ""


async def sync_roco_source_to_records(
    *,
    paths: RocoWorldPaths,
    base_url: str,
    timeout: float = 20.0,
    limit: int | None = None,
    types: list[str] | None = None,
    download_images: bool = False,
) -> dict:
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    paths.assets_dir.mkdir(parents=True, exist_ok=True)
    crawler_limits = {"pet": 1000, "skill": 1000, "item": 1000, "egg": 500, "furniture": 500}
    if isinstance(limit, int) and limit > 0:
        crawler_limits = {k: int(limit) for k in crawler_limits.keys()}
    cfg = RocoCrawlerConfig(
        base_url=str(base_url or "").strip(),
        output_dir=paths.root,
        assets_dir=paths.assets_dir,
        timeout=float(timeout or 20.0),
        download_images=bool(download_images),
        crawler_limits=crawler_limits,
    )
    crawl_res = await asyncio.to_thread(crawl_roco_world_source, cfg)
    if not crawl_res.get("ok"):
        return {"ok": False, "status": "crawl_failed", "crawl_result": crawl_res}
    records_path = Path(str(crawl_res.get("records_path") or paths.records_file))
    if not records_path.exists():
        return {"ok": False, "status": "records_missing", "records_path": str(records_path)}
    rows: list[dict] = []
    with records_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    norm = _normalize_records(rows)
    site_og = _fetch_site_og_candidate(base_url, timeout)
    stats = {"valid_entity_assets": 0, "rejected_generic_assets": 0, "unresolved_image_refs": 0}
    for row in norm:
        cat = str(row.get("category") or "").strip().lower()
        meta = dict(row.get("metadata") or {})
        candidates, unresolved, ext = _build_image_candidates(row, timeout=timeout, base_url=base_url)
        entity_diag = dict(ext.get("diag") or {})
        if entity_diag:
            meta["entity_img_diag"] = entity_diag
            stats["entity_img_candidates_checked"] = int(stats.get("entity_img_candidates_checked", 0) or 0) + int(entity_diag.get("raw_checked", 0) or 0)
            stats["entity_img_candidates_accepted"] = int(stats.get("entity_img_candidates_accepted", 0) or 0) + int(entity_diag.get("raw_accepted", 0) or 0)
            stats["entity_img_candidates_rejected"] = int(stats.get("entity_img_candidates_rejected", 0) or 0) + int(entity_diag.get("raw_rejected", 0) or 0)
        if ext.get("rejected"):
            meta["rejected_image_candidates"] = list(ext.get("rejected") or [])
        if not candidates and site_og and cat in _SITE_OG_ALLOWED:
            candidates = [site_og]
        accepted: list[dict] = []
        rejected: list[dict] = []
        for c in candidates:
            u = str(c.get("url") or "")
            if _is_bad_candidate(u):
                rejected.append(c)
            else:
                accepted.append(c)
        if cat in _ENTITY_TYPES:
            accepted2 = [c for c in accepted if str(c.get("source") or "") != "html_og_site"]
            if len(accepted2) != len(accepted):
                rejected.extend([c for c in accepted if str(c.get("source") or "") == "html_og_site"])
            accepted = accepted2
        candidates = accepted
        if rejected:
            meta["rejected_image_candidates"] = list(meta.get("rejected_image_candidates") or []) + rejected
            stats["rejected_generic_assets"] += len(rejected)
        if candidates:
            row["image_url"] = str(candidates[0].get("url") or "")
            meta["image_url_source"] = str(candidates[0].get("source") or "")
            meta["image_url_candidates"] = candidates
            if cat in _ENTITY_TYPES:
                stats["valid_entity_assets"] += 1
        elif unresolved:
            meta["unresolved_image_ref"] = unresolved
            stats["unresolved_image_refs"] += 1
        row["metadata"] = meta
    if types:
        wanted = {str(x).strip().lower() for x in types if str(x).strip()}
        norm = [r for r in norm if str(r.get("category") or "").lower() in wanted]
    if isinstance(limit, int) and limit > 0:
        norm = norm[: int(limit)]
    with paths.records_file.open("w", encoding="utf-8") as wf:
        for r in norm:
            wf.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "records_path": str(paths.records_file),
        "records_count": len(norm),
        "category_counts": crawl_res.get("category_counts", {}),
        "crawl_errors_count": int(len(crawl_res.get("errors", []) or [])),
        "valid_entity_assets": int(stats["valid_entity_assets"]),
        "rejected_generic_assets": int(stats["rejected_generic_assets"]),
        "unresolved_image_refs": int(stats["unresolved_image_refs"]),
        "entity_img_candidates_checked": int(stats.get("entity_img_candidates_checked", 0) or 0),
        "entity_img_candidates_accepted": int(stats.get("entity_img_candidates_accepted", 0) or 0),
        "entity_img_candidates_rejected": int(stats.get("entity_img_candidates_rejected", 0) or 0),
    }
