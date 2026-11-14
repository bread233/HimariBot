import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp
from typing import Any, Dict, Optional
from pyquery import PyQuery as pq

def extract_og_url(msg: Any) -> Optional[str]:
    # OneBot 媒体段含内部下载 URL，不能作为用户分享的网页链接。
    if isinstance(msg, str):
        text = msg
    else:
        text = " ".join(
            str(segment.data.get("text", ""))
            for segment in msg
            if getattr(segment, "type", None) == "text"
        )
    # 仅白名单网站触发 OG；媒体平台交由专用解析插件处理。
    allowed_hosts = {
        "store.steampowered.com", "steamcommunity.com", "github.com",
        "gist.github.com", "reuters.com", "bbc.com", "nhk.or.jp",
        "www3.nhk.or.jp", "nikkei.com", "news.google.com", "medium.com",
        "note.com", "wordpress.com", "blogspot.com", "dev.to",
        "qiita.com", "zenn.dev",
    }
    for match in re.finditer(r'https?://\S+', text, re.IGNORECASE):
        target_url = match.group()
        try:
            parsed = urlsplit(target_url)
            host = (parsed.hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if (parsed.username is None and parsed.password is None
                and (host in allowed_hosts or host.removeprefix("www.") in allowed_hosts
                     or host.endswith((".wordpress.com", ".blogspot.com")))):
            return target_url
    return None


async def validate_public_url(url: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Resolve once, reject non-public answers, and return the IP to pin."""
    parsed = urlsplit(url)
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError as exc:
        raise ValueError("OG 目标 URL 无效") from exc
    if (parsed.scheme not in {"http", "https"} or not host or len(url) > 2048
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 80 if parsed.scheme == "http" else 443)
            or "%" in host):
        raise ValueError("OG 目标 URL 不安全")
    host = host.encode("idna").decode("ascii").lower()
    if host.rstrip(".") == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("OG 禁止访问本机域名")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not addresses or not all(address.is_global for address in addresses):
        raise ValueError("OG 禁止访问本机、内网或保留地址")
    return addresses[0]


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    """The connector can only dial the IP vetted for this request hop."""

    def __init__(self, host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address):
        self.host = host.encode("idna").decode("ascii").lower().rstrip(".")
        self.address = address

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host.encode("idna").decode("ascii").lower().rstrip(".") != self.host:
            raise ValueError("OG 连接目标与已校验域名不一致")
        return [{
            "hostname": host, "host": str(self.address), "port": port,
            "family": socket.AF_INET6 if self.address.version == 6 else socket.AF_INET,
            "proto": 0, "flags": socket.AI_NUMERICHOST,
        }]

    async def close(self) -> None:
        pass


async def _fetch_public(url: str, max_bytes: int) -> tuple[bytes, str, str]:
    """No automatic redirects, proxies, or second DNS lookup at connection time."""
    for _ in range(4):
        address = await validate_public_url(url)
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(urlsplit(url).hostname, address),
            use_dns_cache=False, force_close=True,
        )
        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=15), trust_env=False,
        ) as session:
            # Keep the original URL: aiohttp uses its hostname for Host, TLS SNI and cert checks.
            async with session.get(url, allow_redirects=False) as res:
                if res.status in (301, 302, 303, 307, 308):
                    location = res.headers.get("Location")
                    if not location:
                        raise ValueError("OG 重定向缺少目标地址")
                    url = urljoin(url, location)
                    continue
                res.raise_for_status()
                if int(res.headers.get("Content-Length") or 0) > max_bytes:
                    raise ValueError("OG 响应体过大")
                data = bytearray()
                async for chunk in res.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("OG 响应体过大")
                return bytes(data), url, res.headers.get("Content-Type", "")
    raise ValueError("OG 重定向次数过多")


async def fetch_og_image(url: str) -> bytes:
    content, _, content_type = await _fetch_public(url, 5 * 1024 * 1024)
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        raise ValueError("OG 图片类型不受支持")
    if not (content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a"))
            or content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        raise ValueError("OG 图片文件内容无效")
    return content


async def get_og_info(msg: Any) -> Optional[Dict[str, Any]]:
    target_url = extract_og_url(msg)
    if not target_url:
        return None

    content, final_url, _ = await _fetch_public(target_url, 1024 * 1024)
    doc = pq(content)

    meta_tags = doc('meta')
    og_keys = ['type', 'url', 'title', 'description', 'image']

    info = {}
    for tag in meta_tags.items():
        property_name = tag.attr('property')
        if property_name and property_name.startswith('og:'):
            key = property_name[3:]
            value = tag.attr('content')
            if key in og_keys:
                info[key] = value
    if info.get("image"):
        info["image"] = urljoin(final_url, info["image"])
    return info