from __future__ import annotations

import asyncio
import re
import urllib.parse
import urllib.request
from pathlib import Path


def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^\w\-.]+", "_", str(name or "").strip(), flags=re.UNICODE)
    base = base.strip("._")
    return base[:96] or "image"


def _to_assets_relative(path_value: str | None, assets_root: Path) -> str | None:
    if not path_value:
        return None
    p = Path(path_value)
    try:
        rel = p.relative_to(assets_root.parent)
        return str(rel).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def normalize_image_url(url: str, base_url: str) -> str:
    x = str(url or "").strip()
    if x.startswith("//"):
        return "https:" + x
    if x.startswith("http://") or x.startswith("https://"):
        return x
    if x.startswith("/"):
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", x)
    return ""


def is_valid_image_url(url: str) -> bool:
    x = str(url or "").strip()
    if not x:
        return False
    bad_terms = ("{{{", "{{", "}}", "图标_宠物_属性_", "图标_技能_属性_")
    if any(t in x for t in bad_terms):
        return False
    if not (x.startswith("http://") or x.startswith("https://") or x.startswith("//")):
        return False
    parsed = urllib.parse.urlparse("https:" + x if x.startswith("//") else x)
    if not parsed.netloc:
        return False
    path = (parsed.path or "").lower()
    ok_ext = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    return any(path.endswith(ext) for ext in ok_ext)


def _extract_first_image_url(text: str, base_url: str) -> str | None:
    html = str(text or "")
    patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r"\|\s*(?:icon|image|img)\s*=\s*(https?://[^\s|]+)",
        r"\|\s*(?:icon|image|img)\s*=\s*(//[^\s|]+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, flags=re.IGNORECASE):
            raw = str(m.group(1) or "").strip()
            url = normalize_image_url(raw, base_url)
            if is_valid_image_url(url):
                return url
    return None


def extract_pet_sprite_url(html_or_raw: str, pet_name: str, base_url: str) -> str | None:
    return _extract_first_image_url(html_or_raw, base_url)


def extract_skill_icon_url(html_or_raw: str, skill_name: str, base_url: str) -> str | None:
    return _extract_first_image_url(html_or_raw, base_url)


def extract_item_image_url(html_or_raw: str, item_name: str, base_url: str) -> str | None:
    return _extract_first_image_url(html_or_raw, base_url)


def extract_egg_image_url(html_or_raw: str, item_name: str, base_url: str) -> str | None:
    return _extract_first_image_url(html_or_raw, base_url)


def extract_furniture_image_url(html_or_raw: str, item_name: str, base_url: str) -> str | None:
    return _extract_first_image_url(html_or_raw, base_url)


def _download_image_sync(url: str, dest_dir: Path, filename: str | None = None, timeout: float = 20.0) -> str | None:
    safe_url = str(url or "").strip()
    if not is_valid_image_url(safe_url):
        return None
    parsed = urllib.parse.urlparse("https:" + safe_url if safe_url.startswith("//") else safe_url)
    ext = Path(parsed.path or "").suffix.lower() or ".png"
    name = sanitize_filename(filename or Path(parsed.path or "").stem or "image")
    out = dest_dir / f"{name}{ext}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return str(out).replace("\\", "/")
    req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0 HimariBot/knowledge-pack-crawler"})
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 20.0))) as resp:
        raw = resp.read()
    if not raw:
        return None
    out.write_bytes(raw)
    return str(out).replace("\\", "/") if out.exists() and out.stat().st_size > 0 else None


async def download_image(url: str, dest_dir: Path, filename: str | None = None, timeout: float = 20.0) -> str | None:
    return await asyncio.to_thread(_download_image_sync, url, dest_dir, filename, timeout)


async def download_pet_sprite(url: str, assets_root: Path, pet_name: str, timeout: float = 20.0) -> str | None:
    raw = await download_image(url, assets_root / "images" / "pet", pet_name, timeout)
    return _to_assets_relative(raw, assets_root)


async def download_skill_icon(url: str, assets_root: Path, skill_name: str, timeout: float = 20.0) -> str | None:
    raw = await download_image(url, assets_root / "images" / "skill", skill_name, timeout)
    return _to_assets_relative(raw, assets_root)


async def download_item_image(url: str, assets_root: Path, item_name: str, timeout: float = 20.0) -> str | None:
    raw = await download_image(url, assets_root / "images" / "item", item_name, timeout)
    return _to_assets_relative(raw, assets_root)


def download_pet_sprite_sync(url: str, assets_root: Path, pet_name: str, timeout: float = 20.0) -> str | None:
    raw = _download_image_sync(url, assets_root / "images" / "pet", pet_name, timeout)
    return _to_assets_relative(raw, assets_root)


def download_skill_icon_sync(url: str, assets_root: Path, skill_name: str, timeout: float = 20.0) -> str | None:
    raw = _download_image_sync(url, assets_root / "images" / "skill", skill_name, timeout)
    return _to_assets_relative(raw, assets_root)


def download_item_image_sync(url: str, assets_root: Path, item_name: str, timeout: float = 20.0) -> str | None:
    raw = _download_image_sync(url, assets_root / "images" / "item", item_name, timeout)
    return _to_assets_relative(raw, assets_root)
