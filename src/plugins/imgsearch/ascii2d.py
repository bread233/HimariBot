# -*- coding:utf-8 -*-
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from nonebot.log import logger

from .response import *


class SingleRes:
    def __init__(
        self,
        title=None,
        title_url=None,
        author=None,
        author_url=None,
        thumb_url=None,
    ):
        self.title = title
        self.title_url = title_url
        self.author = author
        self.author_url = author_url
        self.thumbnail_url = thumb_url
        self.thumbnail = None


headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Origin": "https://ascii2d.net",
    "Referer": "https://ascii2d.net/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/80.0.3987.163 Safari/537.36"
    ),
}


class Ascii2D:
    """Ascii2D search module"""

    __instance = None

    def __init__(self, proxy=None):
        self.proxy = proxy

    def __new__(cls, *a, **k):
        if not cls.__instance:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def parse_html(self, data: httpx.Response) -> list:
        soup = BeautifulSoup(data.text, "html.parser")
        results = []

        for item in soup.find_all("div", attrs={"class": "row item-box"}):
            img_tag = item.find("img")
            thumb_url = None
            if img_tag and img_tag.get("src"):
                src = str(img_tag["src"])
                if src.startswith("http://") or src.startswith("https://"):
                    thumb_url = src
                else:
                    thumb_url = "https://ascii2d.net" + src

            links = item.find_all("a")
            if not links:
                continue

            title = str(links[0].get_text()).strip()

            # ascii2d 页面里的分类/提示块，不是真正结果
            if title == "色合検索":
                results.append(SingleRes())
                continue

            title_url = str(links[0].get("href", "")).strip() or None

            author = None
            author_url = None
            if len(links) > 1:
                author = str(links[1].get_text()).strip() or None
                author_url = str(links[1].get("href", "")).strip() or None

            results.append(
                SingleRes(
                    title=title or None,
                    title_url=title_url,
                    author=author,
                    author_url=author_url,
                    thumb_url=thumb_url,
                )
            )

        return results

    async def _fetch_thumbnail(self, client: httpx.AsyncClient, result: SingleRes) -> None:
        if not result or not result.thumbnail_url:
            return

        try:
            resp = await client.get(result.thumbnail_url)
            if resp.status_code == 200:
                result.thumbnail = resp.content
            else:
                logger.warning(
                    "Ascii2D thumbnail request failed: HTTP {} url={}",
                    resp.status_code,
                    result.thumbnail_url,
                )
        except httpx.HTTPError as e:
            logger.warning("Ascii2D thumbnail request failed: {}", e)

    async def search(self, url: str) -> "BaseResponse":
        color_results = []
        bovw_results = []

        try:
            encoded_url = quote(url, safe="")

            async with httpx.AsyncClient(
                proxies=self.proxy,
                headers=headers,
                follow_redirects=True,
                timeout=30,
            ) as client:
                # ascii2d 支持用图片 URL 搜索，但 URL 必须先编码，否则 QQ 图片 URL 里的 ? & 会破坏路径
                color_response = await client.get(
                    f"https://ascii2d.net/search/url/{encoded_url}",
                    follow_redirects=True,
                )

                logger.info(
                    "Ascii2D color response: HTTP {} url={}",
                    color_response.status_code,
                    color_response.url,
                )

                if color_response.status_code != 200:
                    return BaseResponse(
                        ACTION_WARNING,
                        message=f"Ascii2D颜色检索请求失败: HTTP {color_response.status_code}",
                    )

                bovw_url = str(color_response.url).replace("/color/", "/bovw/")
                bovw_response = await client.get(bovw_url, follow_redirects=True)

                logger.info(
                    "Ascii2D bovw response: HTTP {} url={}",
                    bovw_response.status_code,
                    bovw_response.url,
                )

                if bovw_response.status_code != 200:
                    return BaseResponse(
                        ACTION_WARNING,
                        message=f"Ascii2D特征检索请求失败: HTTP {bovw_response.status_code}",
                    )

                color_results = self.parse_html(color_response)
                bovw_results = self.parse_html(bovw_response)

                logger.info(
                    "Ascii2D parsed results: color={} bovw={}",
                    len(color_results),
                    len(bovw_results),
                )

                # 原逻辑用 [1] 作为可能结果。这里必须 len > 1 才能访问。
                if len(color_results) > 1:
                    await self._fetch_thumbnail(client, color_results[1])

                if len(bovw_results) > 1:
                    await self._fetch_thumbnail(client, bovw_results[1])

        except httpx.ReadTimeout:
            return BaseResponse(ACTION_FAILED, message="链接超时, 请检查网络是否通畅")
        except httpx.ProxyError:
            return BaseResponse(ACTION_FAILED, message="连接代理服务器出现错误, 请检查代理设置")
        except httpx.HTTPError as e:
            logger.warning("Ascii2D request failed: {}", e)
            return BaseResponse(ACTION_FAILED, message="Ascii2D请求失败, 请检查网络或代理")
        except Exception:
            logger.exception("Ascii2D unexpected error")
            return BaseResponse(ACTION_FAILED, message="Ascii2D解析失败")

        first_color = color_results[0] if color_results else None
        first_bovw = bovw_results[0] if bovw_results else None

        # 直接结果：第一个结果有 title
        if first_color and first_color.title:
            return BaseResponse(
                ACTION_SUCCESS,
                "get direct result from ascii2d color",
                {
                    "index": "ascii2d颜色检索",
                    "title": first_color.title,
                    "url": first_color.title_url,
                },
            )

        if first_bovw and first_bovw.title:
            return BaseResponse(
                ACTION_SUCCESS,
                "get direct result from ascii2d bovw",
                {
                    "index": "ascii2d特征检索",
                    "title": first_bovw.title,
                    "url": first_bovw.title_url,
                },
            )

        # 可能结果：第二个结果存在才返回，避免 IndexError
        possible_results = []

        if len(color_results) > 1:
            possible_results.extend(
                [
                    {
                        "[ ascii2d": " 颜色检索 ]",
                        "title": color_results[1].title,
                        "title_url": color_results[1].title_url,
                        "author": color_results[1].author,
                        "author_url": color_results[1].author_url,
                    },
                    color_results[1].thumbnail,
                ]
            )

        if len(bovw_results) > 1:
            possible_results.extend(
                [
                    {
                        "[ ascii2d": " 特征检索 ]",
                        "title": bovw_results[1].title,
                        "url": bovw_results[1].title_url,
                        "author": bovw_results[1].author,
                        "author_url": bovw_results[1].author_url,
                    },
                    bovw_results[1].thumbnail,
                ]
            )

        if possible_results:
            return BaseResponse(
                ACTION_WARNING,
                "get possible results from ascii2d",
                possible_results,
            )

        logger.warning(
            "Ascii2D returned no usable results: color={} bovw={}",
            len(color_results),
            len(bovw_results),
        )
        return BaseResponse(
            ACTION_WARNING,
            message="Ascii2D没有找到可用结果",
        )