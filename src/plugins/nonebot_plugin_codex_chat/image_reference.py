"""安全获取临时生图参考图片；不接受 NAS 内网或本机地址。"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp

_MAX_BYTES = 8 * 1024 * 1024


def _validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("参考图 URL 无效") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or port not in (None, 443) or len(url) > 2048):
        raise ValueError("参考图仅支持公开 HTTPS 图片直链")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("禁止使用本机或内网图片地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("禁止使用内网或本机图片地址")


class _PublicResolver(aiohttp.resolver.DefaultResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        records = await super().resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(item["host"]).is_global for item in records):
            raise ValueError("参考图域名解析到非公网地址")
        return records


async def download_reference_image(url: str) -> tuple[bytes, str]:
    """限制跳转、DNS、体积和文件类型；返回图片字节及扩展名。"""
    timeout = aiohttp.ClientTimeout(total=20)
    connector = aiohttp.TCPConnector(resolver=_PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False) as session:
        for _ in range(4):
            _validate_url(url)
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("参考图跳转缺少目标地址")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                if int(response.headers.get("Content-Length") or 0) > _MAX_BYTES:
                    raise ValueError("参考图超过 8 MB")
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > _MAX_BYTES:
                        raise ValueError("参考图超过 8 MB")
                content = bytes(data)
                if len(content) < 32:
                    raise ValueError("参考图文件过小")
                if content.startswith(b"\x89PNG\r\n\x1a\n"):
                    return content, ".png"
                if content.startswith(b"\xff\xd8\xff"):
                    return content, ".jpg"
                if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
                    return content, ".webp"
                raise ValueError("参考图不是受支持的 PNG/JPEG/WebP 图片")
    raise ValueError("参考图重定向次数过多")
