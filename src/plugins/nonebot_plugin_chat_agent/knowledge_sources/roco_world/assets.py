from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import RocoWorldPaths


def _sanitize_name(name: str) -> str:
    x = re.sub(r"[^\w\-.]+", "_", str(name or "").strip(), flags=re.UNICODE).strip("._")
    return (x[:96] or "image")


def _is_http_url(url: str) -> bool:
    x = str(url or "").strip()
    if not x:
        return False
    return x.startswith("http://") or x.startswith("https://") or x.startswith("//")


class RocoWorldAssetManager:
    def __init__(self, paths: RocoWorldPaths, timeout: float = 12.0) -> None:
        self.paths = paths
        self.timeout = max(1.0, float(timeout or 12.0))
        self.paths.assets_dir.mkdir(parents=True, exist_ok=True)
        self.paths.images_dir.mkdir(parents=True, exist_ok=True)

    def normalize_asset_path(self, entry_type: str, title: str, image_url: str = "", image_path: str = "") -> str:
        raw_path = str(image_path or "").strip().replace("\\", "/")
        if raw_path.startswith("assets/"):
            safe = raw_path.replace("..", "").strip("/")
            return safe
        et = str(entry_type or "other").strip().lower() or "other"
        filename_base = _sanitize_name(str(title or "image"))
        ext = ".png"
        if image_url:
            parsed = urllib.parse.urlparse("https:" + image_url if image_url.startswith("//") else image_url)
            pext = Path(parsed.path or "").suffix.lower()
            if pext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                ext = pext
        return f"assets/images/{et}/{filename_base}{ext}"

    def _resolve_local(self, rel_path: str) -> Path:
        clean = str(rel_path or "").replace("\\", "/").strip("/")
        if clean.startswith("../") or "/../" in clean:
            clean = clean.replace("..", "")
        return self.paths.root / clean

    def ensure_asset(self, image_url: str, target_relative_path: str, dry_run: bool = True) -> dict:
        out = {
            "ok": False,
            "dry_run": bool(dry_run),
            "target_path": str(target_relative_path or ""),
            "downloaded": False,
            "skipped_existing": False,
            "invalid_url": False,
            "error": "",
            "url": str(image_url or ""),
            "http_status": 0,
            "content_type": "",
            "redirected": False,
            "final_url": "",
            "exception_type": "",
        }
        target = self._resolve_local(target_relative_path)
        if target.exists() and target.is_file() and target.stat().st_size > 0:
            out["ok"] = True
            out["skipped_existing"] = True
            return out
        if not _is_http_url(image_url):
            out["invalid_url"] = True
            out["error"] = "invalid_url"
            return out
        if dry_run:
            out["ok"] = True
            return out
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            safe_url = "https:" + image_url if image_url.startswith("//") else image_url
            out["final_url"] = safe_url
            req = urllib.request.Request(
                safe_url,
                headers={
                    "User-Agent": "Mozilla/5.0 HimariBot/knowledge-source",
                    "Referer": "https://wiki.biligame.com/rocom",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                out["http_status"] = code
                out["final_url"] = str(getattr(resp, "url", safe_url) or safe_url)
                out["redirected"] = out["final_url"] != safe_url
                out["content_type"] = str(getattr(resp, "headers", {}).get("Content-Type", "") or "")
                if code != 200:
                    out["error"] = f"http_{code}"
                    return out
                raw = resp.read()
            ctype = out["content_type"].lower()
            is_image = ctype.startswith("image/")
            if not is_image and not any((out["final_url"] or safe_url).lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                out["error"] = "invalid_content_type"
                return out
            if not raw:
                out["error"] = "empty_body"
                return out
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(raw)
            tmp.replace(target)
            out["ok"] = True
            out["downloaded"] = True
            return out
        except Exception as e:
            out["exception_type"] = type(e).__name__
            out["error"] = f"{type(e).__name__}:{str(e)[:120]}"
            return out

    def fix_missing_assets(self, records: list[dict], dry_run: bool = True) -> dict:
        existing_count = 0
        missing_count = 0
        would_download_count = 0
        invalid_url_count = 0
        failed: list[dict] = []
        targets: list[str] = []
        updated_records: list[dict] = []

        for row in records:
            rec = dict(row)
            meta = dict(rec.get("metadata") or {})
            assets = list(meta.get("assets") or [])
            image_path = str(rec.get("image_path") or meta.get("image_path") or "").strip()
            image_url = str(rec.get("image_url") or meta.get("image_url") or "").strip()
            if not assets and (image_path or image_url):
                assets = [{"kind": "image", "path": image_path, "url": image_url, "role": "primary"}]
            fixed_assets = []
            for a in assets:
                if str(a.get("kind", "")).strip().lower() != "image":
                    fixed_assets.append(a)
                    continue
                target_rel = self.normalize_asset_path(
                    str(rec.get("category") or meta.get("entry_type") or "other"),
                    str(rec.get("title") or rec.get("name") or ""),
                    image_url=str(a.get("url") or image_url or ""),
                    image_path=str(a.get("path") or image_path or ""),
                )
                targets.append(target_rel)
                candidates = list(meta.get("image_url_candidates") or [])
                if not candidates:
                    candidates = [{"url": str(a.get("url") or image_url or ""), "source": "single"}]
                res = {"ok": False, "error": "no_candidate"}
                used_url = ""
                for c in candidates:
                    used_url = str(c.get("url") or "").strip()
                    if not used_url:
                        continue
                    res = self.ensure_asset(used_url, target_rel, dry_run=dry_run)
                    if res.get("ok") or res.get("skipped_existing"):
                        break
                if res["skipped_existing"]:
                    existing_count += 1
                elif res["invalid_url"]:
                    invalid_url_count += 1
                elif res["ok"] and res["dry_run"]:
                    missing_count += 1
                    would_download_count += 1
                elif res["ok"] and res["downloaded"]:
                    missing_count += 1
                else:
                    missing_count += 1
                    failed.append(
                        {
                            "target": target_rel,
                            "error": res.get("error", ""),
                            "url": res.get("url", used_url),
                            "http_status": res.get("http_status", 0),
                            "content_type": res.get("content_type", ""),
                            "redirected": res.get("redirected", False),
                            "final_url": res.get("final_url", ""),
                            "exception_type": res.get("exception_type", ""),
                        }
                    )
                fixed_assets.append(
                    {
                        "kind": "image",
                        "path": target_rel if (res["ok"] or res["skipped_existing"]) else "",
                        "url": str(res.get("url") or used_url or a.get("url") or image_url or ""),
                        "role": str(a.get("role") or "primary"),
                    }
                )
            meta["assets"] = fixed_assets
            if fixed_assets:
                rec["image_path"] = str(fixed_assets[0].get("path") or "")
                rec["image_url"] = str(fixed_assets[0].get("url") or "")
                meta["image_path"] = rec["image_path"]
                if rec["image_url"]:
                    meta["image_url"] = rec["image_url"]
            rec["metadata"] = meta
            rec["metadata_json"] = json.dumps(meta, ensure_ascii=False)
            updated_records.append(rec)

        return {
            "ok": True,
            "dry_run": bool(dry_run),
            "total_assets": len(targets),
            "existing_count": existing_count,
            "missing_count": missing_count,
            "would_download_count": would_download_count if dry_run else 0,
            "invalid_url_count": invalid_url_count,
            "failed": failed,
            "target_paths": targets,
            "records": updated_records,
        }
