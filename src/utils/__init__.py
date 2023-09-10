# 引入工具
from PIL import Image
from io import BytesIO
import base64
import requests
from nonebot.adapters.onebot.v11 import MessageSegment
from sql import *


def pic2b64(pic: Image) -> str:
    buf = BytesIO()
    pic.save(buf, format="PNG")
    base64_str = base64.b64encode(buf.getvalue()).decode()
    return "base64://" + base64_str


def concat_pic(pics, border=5):
    num = len(pics)
    w, h = pics[0].size
    des = Image.new("RGBA", (w, num * h + (num - 1) * border), (255, 255, 255, 255))
    for i, pic in enumerate(pics):
        des.paste(pic, (0, i * (h + border)), pic)
    return des


def path_to_64img(path):
    try:
        img = Image.open(path)
    except:
        r = requests.get(path)
        img = Image.open(BytesIO(r.read()))
    res = pic2b64(img)
    res = MessageSegment.image(res)
    return res
