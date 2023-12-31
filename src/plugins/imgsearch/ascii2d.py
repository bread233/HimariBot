# -*- coding:utf-8 -*-
import httpx
from bs4 import BeautifulSoup
from .response import *

class SingleRes():
    def __init__(self, title=None, title_url=None, author=None, author_url=None,thumb_url=None):
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.163 Safari/537.36",
}

class Ascii2D:
    """ # Ascii2D search moudle #"""
    __instance = None

    def __init__(self,proxy=None):
        self.proxy = proxy

    def __new__(cls, *a, **k):
        if not cls.__instance:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    def parse_html(self, data: httpx.Response) -> "list":
        soup = BeautifulSoup(data.text, 'html.parser')
        results = []
        for img in soup.find_all('div', attrs={'class': 'row item-box'}):
            img_url = "https://ascii2d.net" + str(img.img['src'])
            the_list = img.find_all('a')
            title = str(the_list[0].get_text())
            if title == "色合検索":
                results.append(SingleRes())
                continue
            title_url = str(the_list[0]["href"])
            author = str(the_list[1].get_text())
            author_url = str(the_list[1]["href"])
            results.append(SingleRes(title, title_url, author, author_url,img_url))
        return results

    async def search(self, url: str) -> "BaseResponse":
        try:
            client = httpx.AsyncClient(proxies=self.proxy, headers=headers,follow_redirects=True)
            # color_res = await client.post("https://ascii2d.net/search/multi", files=files)
            
            # 既然ascii2d能传图片url, 那就直接丢给它好了！
            color_response = await client.get("https://ascii2d.net/search/url/"+url,follow_redirects=True)
            #print(color_response.url)
            bovw_url = color_response.url.__str__().replace("/color/", "/bovw/")
            bovw_response = await client.get(bovw_url)
            color_results = self.parse_html(color_response)
            bovw_results = self.parse_html(bovw_response)
            print(color_response)
            print(bovw_response)
            if not len(color_results)==0:
                color_results[1].thumbnail = (await client.get(color_results[1].thumbnail_url)).content
            if not len(bovw_results)==0:
                bovw_results[1].thumbnail = (await client.get(bovw_results[1].thumbnail_url)).content
        #res = requests.post(ASCII2DURL, headers=headers, data=m, verify=False, **self.requests_kwargs)
            await client.aclose()
        except httpx.ReadTimeout:
            return BaseResponse(ACTION_FAILED,message="链接超时, 请检查网络是否通畅")
        except httpx.ProxyError:
            return BaseResponse(ACTION_FAILED,message="连接代理服务器出现错误, 请检查代理设置")

        if color_results[0].title:
            single = color_results[0]
            # 处理逻辑： 先看第一个返回结果是否带上title，如果有说明这张图已经被搜索过了，有直接结果
            # 如果第一个结果的title为空，那么直接返回第二个结果，带上缩略图让用户自行比对是否一致
            return BaseResponse(ACTION_SUCCESS, "get direct result from ascii2d color", {'index': "ascii2d颜色检索", 'title': single.title, 'url': single.title_url})
        elif bovw_results[0].title:
            single = bovw_results[0]
            return BaseResponse(ACTION_SUCCESS, "get direct result from ascii2d bovw", {'index': "ascii2d特征检索", 'title': single.title, 'url': single.title_url})
        else:

            return BaseResponse(ACTION_WARNING, "get possible results from ascii2d", [
                {'[ ascii2d': " 颜色检索 ]",  'title': color_results[1].title, 'title_url': color_results[1].title_url,
                "author":color_results[1].author,"author_url":color_results[1].author_url}, color_results[1].thumbnail,
                
                {'[ ascii2d': " 特征检索 ]",  'title': bovw_results[1].title, 'url': bovw_results[1].title_url,
                "author":bovw_results[1].author,"author_url":bovw_results[1].author_url}, bovw_results[1].thumbnail])
