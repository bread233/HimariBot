import inspect
from pathlib import Path
from typing import Callable, Optional, Dict, Any, TypeVar
from nonebot import get_plugin_config
from nonebot.plugin import Plugin, PluginMetadata, get_plugin_by_module_name
from nonestorage import user_cache_dir, user_config_dir, user_data_dir
from typing_extensions import ParamSpec
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="本地数据存储",
    description="存储插件数据至本地文件",
    usage=(
        '声明依赖: `require("nonebot_plugin_localstore")`\n'
        "导入所需文件夹:\n"
        "  `cache_dir = store.get_plugin_cache_dir()`\n"
        '  `cache_file = store.get_plugin_cache_file("file_name")`\n'
        "  `data_dir = store.get_plugin_data_dir()`\n"
        '  `data_file = store.get_plugin_data_file("file_name")`\n'
        "  `config_dir = store.get_plugin_config_dir()`\n"
        '  `config_file = store.get_plugin_config_file("file_name")`'
    ),
    type="library",
    homepage="https://github.com/nonebot/plugin-localstore",
    config=Config,
    supported_adapters=None,
)

plugin_config = get_plugin_config(Config)

P = ParamSpec("P")
T = TypeVar("T")

APP_NAME = "nonebot2"

BASE_CACHE_DIR = (
    Path.cwd() / "cache"
    if plugin_config.localstore_use_cwd
    else user_cache_dir(APP_NAME).resolve()
)
if plugin_config.localstore_cache_dir is not None:
    BASE_CACHE_DIR = plugin_config.localstore_cache_dir.resolve()

BASE_CONFIG_DIR = (
    Path.cwd() / "config"
    if plugin_config.localstore_use_cwd
    else user_config_dir(APP_NAME).resolve()
)
if plugin_config.localstore_config_dir is not None:
    BASE_CONFIG_DIR = plugin_config.localstore_config_dir.resolve()

BASE_DATA_DIR = (
    Path.cwd() / "data"
    if plugin_config.localstore_use_cwd
    else user_data_dir(APP_NAME).resolve()
)
if plugin_config.localstore_data_dir is not None:
    BASE_DATA_DIR = plugin_config.localstore_data_dir.resolve()


def _ensure_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    elif not path.is_dir():
        raise RuntimeError(f"{path} is not a directory")


def _auto_create_dir(func: Callable[..., Path]) -> Callable[..., Path]:
    def wrapper(*args, **kwargs) -> Path:
        path = func(*args, **kwargs)
        _ensure_dir(path)
        return path
    return wrapper


def _get_caller_plugin_safe() -> Plugin:
    """
    自动获取调用模块对应的 NoneBot 插件对象。
    如果无法获取，则抛出明确错误。
    """
    current_frame = inspect.currentframe()
    if current_frame is None:
        raise RuntimeError("无法获取调用栈")

    frame = current_frame
    while True:
        frame = frame.f_back
        if frame is None:
            break
        module = inspect.getmodule(frame)
        if module is None or not hasattr(module, "__name__"):
            continue
        module_name = module.__name__

        # 跳过 localstore 自己
        if module_name.split(".", 1)[0] == "nonebot_plugin_localstore":
            continue

        plugin = get_plugin_by_module_name(module_name)
        if plugin:
            return plugin

    raise RuntimeError("Cannot detect caller plugin")


def _get_plugin_path(base_dir: Path, plugin_dir: Dict[str, Path], plugin: Plugin) -> Path:
    """
    获取插件存储目录
    兼容 Nonebot 2 Plugin 对象，使用 module_name 作为唯一标识
    """
    parts = []

    # Nonebot 2 Plugin 没有 id_，使用 module_name
    plugin_id = getattr(plugin, "module_name", None)
    if plugin_id is None:
        raise ValueError(f"无法获取插件标识: {plugin}")

    while True:
        if plugin_id in plugin_dir:
            return plugin_dir[plugin_id].joinpath(*reversed(parts))
        if ":" not in plugin_id:
            break
        plugin_id, part = plugin_id.rsplit(":", 1)
        parts.append(part)
    return base_dir.joinpath(plugin_id, *reversed(parts))


# -----------------------------
# Cache
# -----------------------------
@_auto_create_dir
def get_plugin_cache_dir(plugin: Optional[Plugin] = None) -> Path:
    if plugin is None:
        plugin = _get_caller_plugin_safe()
    return _get_plugin_path(BASE_CACHE_DIR, plugin_config.localstore_plugin_cache_dir, plugin)

def get_plugin_cache_file(filename: str, plugin: Optional[Plugin] = None) -> Path:
    return get_plugin_cache_dir(plugin) / filename


# -----------------------------
# Config
# -----------------------------
@_auto_create_dir
def get_plugin_config_dir(plugin: Optional[Plugin] = None) -> Path:
    if plugin is None:
        plugin = _get_caller_plugin_safe()
    return _get_plugin_path(BASE_CONFIG_DIR, plugin_config.localstore_plugin_config_dir, plugin)

def get_plugin_config_file(filename: str, plugin: Optional[Plugin] = None) -> Path:
    return get_plugin_config_dir(plugin) / filename


# -----------------------------
# Data
# -----------------------------
@_auto_create_dir
def get_plugin_data_dir(plugin: Optional[Plugin] = None) -> Path:
    if plugin is None:
        plugin = _get_caller_plugin_safe()
    return _get_plugin_path(BASE_DATA_DIR, plugin_config.localstore_plugin_data_dir, plugin)

def get_plugin_data_file(filename: str, plugin: Optional[Plugin] = None) -> Path:
    return get_plugin_data_dir(plugin) / filename


# -----------------------------
# 通用基础目录函数
# -----------------------------
@_auto_create_dir
def get_cache_dir(plugin_name: Optional[str] = None) -> Path:
    return BASE_CACHE_DIR / plugin_name if plugin_name else BASE_CACHE_DIR

def get_cache_file(plugin_name: Optional[str], filename: str) -> Path:
    return get_cache_dir(plugin_name) / filename

@_auto_create_dir
def get_config_dir(plugin_name: Optional[str] = None) -> Path:
    return BASE_CONFIG_DIR / plugin_name if plugin_name else BASE_CONFIG_DIR

def get_config_file(plugin_name: Optional[str], filename: str) -> Path:
    return get_config_dir(plugin_name) / filename

@_auto_create_dir
def get_data_dir(plugin_name: Optional[str] = None) -> Path:
    return BASE_DATA_DIR / plugin_name if plugin_name else BASE_DATA_DIR

def get_data_file(plugin_name: Optional[str], filename: str) -> Path:
    return get_data_dir(plugin_name) / filename
