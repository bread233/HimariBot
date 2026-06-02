"""
日志脱敏工具 - 仅用于日志展示，不用于业务配置。

说明：
- 只用于日志展示，不改变真实配置值。
- 不用于业务逻辑判断、数据库存储等场景。
- 对敏感字段进行递归脱敏，防止启动日志打印敏感配置。
"""

import re

SENSITIVE_KEYWORDS = [
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "session",
]

_REDACTED_MARKER = "***REDACTED***"
_ERROR_MARKER = "***REDACTED_ERROR***"

_SENSITIVE_PATTERN = re.compile(
    r"(sk-|sk-proj-|Bearer\s)",
    re.IGNORECASE,
)


def _is_sensitive_key(key: object) -> bool:
    """判断 key 是否命中敏感关键词。"""
    lower = str(key).lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in lower:
            return True
    return False


def _sanitize_string(value: str) -> str:
    """对字符串值进行脱敏：替换 sk-/sk-proj-/Bearer token 等模式。"""
    if _SENSITIVE_PATTERN.search(value):
        return _REDACTED_MARKER
    return value


def sanitize_for_log(value) -> object:
    """
    递归脱敏日志值。

    - dict：key 命中敏感关键词时，value 替换为 ***REDACTED***
    - list/tuple/set：递归处理每个元素
    - str：检测 sk-/sk-proj-/Bearer token 模式并完全替换
    - 其他类型：直接返回原值
    """
    try:
        if isinstance(value, dict):
            sanitized = {}
            for k, v in value.items():
                if _is_sensitive_key(k):
                    sanitized[k] = _REDACTED_MARKER
                elif isinstance(v, (dict, list, tuple, set)):
                    sanitized[k] = sanitize_for_log(v)
                elif isinstance(v, str):
                    sanitized[k] = _sanitize_string(v)
                else:
                    sanitized[k] = v
            return sanitized

        if isinstance(value, list):
            return [sanitize_for_log(item) for item in value]

        if isinstance(value, tuple):
            return tuple(sanitize_for_log(item) for item in value)

        if isinstance(value, set):
            return {sanitize_for_log(item) for item in value}

        if isinstance(value, str):
            return _sanitize_string(value)

        return value
    except Exception:
        return _ERROR_MARKER
