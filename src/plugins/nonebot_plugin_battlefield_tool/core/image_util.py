import base64
import os
import mimetypes
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from nonebot.log import logger  # ✅ Replace AstrBot logger

from .request_util import fetch_image

# ======================================
# 目录管理：替代 StarTools.get_data_dir
# ======================================
# 插件根目录下生成 data/images
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
image_dir = DATA_DIR / "images"
image_dir.mkdir(parents=True, exist_ok=True)


def _get_mime_type(file_path: str) -> str:
    """根据文件路径获取MIME类型"""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type if mime_type else "application/octet-stream"


def get_local_image_path(image_url: str) -> str:
    """根据图片URL生成本地存储路径"""
    parsed_url = urlparse(image_url)
    file_name = os.path.basename(parsed_url.path)
    return os.path.join(image_dir, file_name)


def image_to_base64(image_path: str) -> Optional[str]:
    """读取本地图片转base64"""
    if not os.path.exists(image_path):
        logger.debug(f"图片文件未找到: {image_path}")
        return None

    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        mime_type = _get_mime_type(image_path)
        return f"data:{mime_type};base64,{encoded_string}"
    except Exception as e:
        logger.error(f"读取或编码图片文件失败: {e}")
        return None


def svg_to_base64(svg_path: str) -> Optional[str]:
    """读取 SVG 文件转 base64"""
    if not os.path.exists(svg_path):
        logger.debug(f"SVG文件未找到: {svg_path}")
        return None

    try:
        with open(svg_path, "r", encoding="utf-8") as svg_file:
            svg_content = svg_file.read()
            encoded_string = base64.b64encode(svg_content.encode("utf-8")).decode(
                "utf-8"
            )
        return f"data:image/svg+xml;base64,{encoded_string}"
    except Exception as e:
        logger.error(f"读取或编码SVG文件失败: {e}")
        return None


def save_image_to_local(image_path: str, image_data: bytes):
    """二进制保存图片"""
    try:
        with open(image_path, "wb") as f:
            f.write(image_data)
        logger.debug(f"图片已保存到本地: {image_path}")
    except Exception as e:
        logger.error(f"保存图片到本地失败: {e}")


async def get_image_base64(image_url: str, timeout: int = 15) -> Optional[str]:
    """
    优先从本地获取，不存在则远程下载
    """
    local_path = get_local_image_path(image_url)

    # 尝试本地读取
    if local_path.lower().endswith(".svg"):
        base64_data = svg_to_base64(local_path)
    else:
        base64_data = image_to_base64(local_path)

    if base64_data:
        logger.debug(f"图片已从本地获取并转换: {local_path}")
        return base64_data

    logger.debug(f"尝试远程获取图片: {image_url}")
    image_data = await fetch_image(image_url, timeout)
    if image_data:
        save_image_to_local(local_path, image_data)

        # 再转换一次
        if local_path.lower().endswith(".svg"):
            return svg_to_base64(local_path)
        else:
            return image_to_base64(local_path)

    logger.error(f"无法获取图片并转换为Base64: {image_url}")
    return None
