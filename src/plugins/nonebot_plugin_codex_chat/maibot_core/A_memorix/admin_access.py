"""进程内画像管理授权凭据。仅由已认证的 WebUI 依赖签发。

普通工具参数中的 admin/is_admin/token 字段不能构造此凭据。
"""
from __future__ import annotations

from typing import Any

_PROFILE_ADMIN_CAPABILITY = object()


def issue_webui_profile_admin_capability(verified_session: str) -> object:
    if not isinstance(verified_session, str) or not verified_session:
        raise PermissionError("需要已认证的 WebUI 会话")
    return _PROFILE_ADMIN_CAPABILITY


def is_profile_admin_capability(value: Any) -> bool:
    return value is _PROFILE_ADMIN_CAPABILITY
